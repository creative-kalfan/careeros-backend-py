"""Ingestion validation: bounded dry-run + pure metric aggregation.

Reuses the canonical pipeline (normalize/validate/canonicalize/enrichment-guard/
provenance) — no second ingestion path. Dry-run never touches the DB; persist
delegates to JobIngestionService. Hard bounds prevent quota exhaustion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from app.crawlers.models import CrawledJob
from app.crawlers.source_quality import canonicalize_url, classify_source, is_aggregator_url
from app.models.job import NormalizedJob
from app.services.jobs.india_geography import (
    classify_india_relevance,
    geography_report as _geography_report,
    is_india_job,
)
from app.services.jobs.job_service import needs_enrichment, validate_job

logger = logging.getLogger(__name__)

# Hard upper bounds (never exceeded regardless of caller input).
MAX_QUERIES = 5
MAX_PAGES_PER_QUERY = 1
MAX_RESULTS_PER_QUERY = 50
MAX_TOTAL_JOBS = 250
MAX_FIRECRAWL_CALLS = 20

PROVIDER_DEFAULT_CONFIDENCE = {"adzuna": 0.5, "jobspy": 0.65}

# Minimal keyword buckets for the 5 CareerOS target domains (title substring).
TARGET_ROLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "analytics": ("data analyst", "analytics", "bi analyst", "business analyst", "reporting analyst"),
    "data_engineering": ("data engineer", "analytics engineer", "etl", "data warehouse"),
    "ai_ml": ("machine learning", "ai engineer", "data scientist", "generative ai", "ml engineer"),
    "backend": ("backend", "python", "java backend", "api developer"),
    "sap": ("sap", "abap", "hana", "sap bw"),
}

_INDIA_TOKENS = (
    "india", "bengaluru", "bangalore", "mumbai", "chennai", "hyderabad",
    "pune", "delhi", "noida", "gurugram", "gurgaon", "kolkata", "ahmedabad",
    "kochi", "jaipur", "chandigarh", "remote india",
)


@dataclass
class ValidationLimits:
    """Bounded crawl budget; constructor inputs are clamped to hard maxima."""

    max_queries: int = 2
    max_pages_per_query: int = 1
    results_per_query: int = 10
    max_firecrawl_calls: int = 10

    def __post_init__(self) -> None:
        self.max_queries = max(1, min(int(self.max_queries), MAX_QUERIES))
        self.max_pages_per_query = max(1, min(int(self.max_pages_per_query), MAX_PAGES_PER_QUERY))
        self.results_per_query = max(1, min(int(self.results_per_query), MAX_RESULTS_PER_QUERY))
        self.max_firecrawl_calls = max(0, min(int(self.max_firecrawl_calls), MAX_FIRECRAWL_CALLS))


def _india_relevant(job: NormalizedJob) -> bool:
    """Strict India check: explicit India only (never Remote/Global/APAC)."""
    try:
        return is_india_job(job.location, getattr(job, "remote", None))
    except Exception:
        text = f"{job.location or ''} {job.title or ''} {(job.raw or {}).get('location', '')}".lower()
        return any(tok in text for tok in _INDIA_TOKENS) and "indiana" not in text


def summarize_jobs(jobs: list[NormalizedJob]) -> dict[str, Any]:
    """Per-provider counts reusing validate_job + canonicalize_url.

    Geography uses the strict classifier: only explicit India counts as
    India; Remote/Worldwide/Global/APAC are ambiguous, never Indian.
    Extra keys (india/foreign/ambiguous/unknown) extend the legacy
    india_relevant count without breaking existing consumers.
    """
    valid = warnings = invalid = stale = india = foreign = ambiguous = unknown = 0
    canonicals: set[str] = set()
    for job in jobs:
        try:
            status, _ = validate_job(job)
        except Exception:
            invalid += 1
            continue
        if status == "INVALID":
            invalid += 1
        elif status == "STALE":
            stale += 1
        elif status == "VALID_WITH_WARNINGS":
            warnings += 1
        else:
            valid += 1
        canon = job.canonical_url or canonicalize_url(job.apply_url or job.url)
        if canon:
            canonicals.add(canon)
        try:
            label = classify_india_relevance(job.location, getattr(job, "remote", None))
        except Exception:
            label = "UNKNOWN"
        if label == "INDIA":
            india += 1
        elif label == "FOREIGN":
            foreign += 1
        elif label == "AMBIGUOUS":
            ambiguous += 1
        else:
            unknown += 1
    total = len(jobs)
    return {
        "raw": total, "valid": valid, "warnings": warnings,
        "invalid": invalid, "stale": stale,
        "unique_canonical": len(canonicals), "india_relevant": india,
        "india": india, "foreign": foreign, "ambiguous": ambiguous, "unknown": unknown,
        "india_pct": round(100.0 * india / total, 1) if total else 0.0,
    }


def dedup_report(jobs: list[NormalizedJob]) -> dict[str, Any]:
    """Cross-source duplicate accounting on canonical URL identity.

    Conservative: jobs without a usable canonical URL stay separate (never
    fuzzy-merged). Identity falls back to (source_platform, external_job_id).
    """
    buckets: dict[str, set[str]] = {}
    for job in jobs:
        canon = job.canonical_url or canonicalize_url(job.apply_url or job.url)
        key = canon if canon else f"{job.source_platform}:{job.external_job_id}"
        buckets.setdefault(key, set()).add(job.source_platform or "unknown")
    multi = sum(1 for v in buckets.values() if len(v) > 1)
    raw = len(jobs)
    canon_count = len(buckets)
    dupes = raw - canon_count
    return {
        "raw_discoveries": raw, "canonical_jobs": canon_count,
        "duplicate_discoveries": dupes,
        "duplicate_pct": round(100.0 * dupes / raw, 1) if raw else 0.0,
        "multi_source_jobs": multi, "single_source_jobs": canon_count - multi,
    }


def firecrawl_report(jobs: list[NormalizedJob], limits: Optional[ValidationLimits] = None) -> dict[str, Any]:
    """Selective-enrichment metrics reusing needs_enrichment (no network)."""
    lim = limits or ValidationLimits()
    evaluated = len(jobs)
    requiring = sum(1 for j in jobs[: MAX_TOTAL_JOBS] if needs_enrichment(j))
    requiring = min(requiring, lim.max_firecrawl_calls)
    skipped = evaluated - min(sum(1 for j in jobs if needs_enrichment(j)), evaluated)
    return {
        "evaluated": evaluated, "requiring_enrichment": requiring,
        "skipped_sufficient": skipped,
        "utilization_rate": round(requiring / evaluated, 3) if evaluated else 0.0,
    }


def enrichment_gain(base: NormalizedJob, merged: NormalizedJob) -> int:
    """Count of previously-empty fields filled by merge_enrichment."""
    before, after = base.model_dump(), merged.model_dump()
    return sum(
        1 for k, v in after.items()
        if k != "raw" and (before.get(k) in (None, "", [])) and v not in (None, "", [])
    )


def role_coverage(jobs: list[NormalizedJob]) -> dict[str, int]:
    """Bucket jobs into the 5 target domains by title substring (no LLM)."""
    out = {domain: 0 for domain in TARGET_ROLE_KEYWORDS}
    out["other"] = 0
    for job in jobs:
        title = (job.title or "").lower()
        hit = next((d for d, kws in TARGET_ROLE_KEYWORDS.items() if any(k in title for k in kws)), None)
        out[hit if hit else "other"] += 1
    return out


def company_coverage(companies: list[str], jobs: list[NormalizedJob]) -> dict[str, dict[str, Any]]:
    """Classify GOOD(>=10)/PARTIAL(>=3)/POOR(>=1)/NO(0) coverage per company."""
    counts: dict[str, int] = {c: 0 for c in companies}
    for job in jobs:
        company = (job.company or "").strip().lower()
        for target in companies:
            if target.lower() in company or company in target.lower():
                counts[target] += 1
                break
    report = {}
    for company in companies:
        n = counts[company]
        label = "NO_COVERAGE" if n == 0 else "POOR_COVERAGE" if n < 3 else "PARTIAL_COVERAGE" if n < 10 else "GOOD_COVERAGE"
        report[company] = {"jobs_discovered": n, "coverage": label}
    return report


def source_report(provider_jobs: dict[str, list[NormalizedJob]]) -> dict[str, dict[str, Any]]:
    """Per-provider quality reusing summarize + classify_source confidence."""
    out = {}
    for provider, jobs in provider_jobs.items():
        summary = summarize_jobs(jobs)
        confs = [j.source_confidence for j in jobs if isinstance(j.source_confidence, (int, float))]
        if not confs and jobs:
            probe = classify_source(provider, jobs[0].apply_url, jobs[0].company)
            confs = [probe.confidence]
        fr = firecrawl_report(jobs)
        out[provider] = {
            **summary,
            "duplicate_pct": dedup_report(jobs)["duplicate_pct"],
            "enrichment_need_pct": round(100.0 * fr["requiring_enrichment"] / fr["evaluated"], 1) if fr["evaluated"] else 0.0,
            "confidence": round(sum(confs) / len(confs), 3) if confs else PROVIDER_DEFAULT_CONFIDENCE.get(provider, 0.4),
        }
    return out


def geography_breakdown(jobs: list[NormalizedJob]) -> dict[str, Any]:
    """Strict India/foreign/ambiguous/unknown split (task §5, pure)."""
    return _geography_report(jobs)


def provider_geography_report(provider_jobs: dict[str, list[NormalizedJob]]) -> dict[str, dict[str, Any]]:
    """Per-provider geography: total/india/foreign/ambiguous/unknown + India %."""
    return {provider: _geography_report(jobs) for provider, jobs in provider_jobs.items()}


def incremental_report(
    new_jobs: list[NormalizedJob],
    existing_canonicals: set[str] | list[str],
) -> dict[str, Any]:
    """Incremental value of a source vs already-known inventory (task §11, pure).

    Identity is the canonical URL (fallback: source_platform:external_job_id),
    matching the conservative dedup policy — no fuzzy merging. The headline
    metric is incremental unique useful Indian jobs.
    """
    existing = set(existing_canonicals or [])

    def _identity(job: NormalizedJob) -> str:
        canon = job.canonical_url or canonicalize_url(job.apply_url or job.url or "")
        if canon:
            return canon
        return f"{job.source_platform}:{job.external_job_id}"

    seen: set[str] = set()
    unique = dupes = 0
    incremental_unique = incremental_india = 0
    india_total = foreign_total = 0
    target_roles = role_coverage(new_jobs)
    target_total = sum(v for k, v in target_roles.items() if k != "other")

    for job in new_jobs:
        key = _identity(job)
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        unique += 1
        if key not in existing:
            incremental_unique += 1
            try:
                if is_india_job(job.location, getattr(job, "remote", None)):
                    incremental_india += 1
            except Exception:
                pass
        try:
            label = classify_india_relevance(job.location, getattr(job, "remote", None))
        except Exception:
            label = "UNKNOWN"
        if label == "INDIA":
            india_total += 1
        elif label == "FOREIGN":
            foreign_total += 1

    # Validation split for the §11 raw/valid/stale/invalid row.
    summary = summarize_jobs(new_jobs)
    return {
        "raw": summary["raw"],
        "valid": summary["valid"] + summary["warnings"],
        "stale": summary["stale"],
        "invalid": summary["invalid"],
        "india": india_total,
        "foreign": foreign_total,
        "unique_canonical": unique,
        "duplicates": dupes,
        "incremental_unique": incremental_unique,
        "incremental_india": incremental_india,
        "target_role_jobs": target_total,
        "target_roles": target_roles,
    }


def india_kpis(
    new_jobs: list[NormalizedJob],
    existing_canonicals: set[str] | list[str],
    provider_calls: int = 0,
) -> dict[str, Any]:
    """Incremental India coverage KPIs (task §16, pure).

    Single internal metric family:

        incremental_unique_india_jobs            (headline)
        incremental_unique_india_target_role_jobs
        india_jobs_per_provider_call
        india_jobs_per_crawl
        india_job_percentage
        india_target_role_percentage

    ``existing_canonicals`` is the already-known canonical URL set for the
    SAME provider, so incrementality is measured against prior inventory, not
    against the other providers. Identity is canonical URL (conservative).
    """
    existing = set(existing_canonicals or [])
    calls = max(1, int(provider_calls or 0))

    def _identity(job: NormalizedJob) -> str:
        canon = job.canonical_url or canonicalize_url(job.apply_url or job.url or "")
        if canon:
            return canon
        return f"{job.source_platform}:{job.external_job_id}"

    seen: set[str] = set()
    india_total = 0
    india_target_total = 0
    incremental_india = 0
    incremental_india_target = 0
    target_roles = role_coverage(new_jobs)

    for job in new_jobs:
        key = _identity(job)
        if key in seen:
            continue
        seen.add(key)
        is_india = False
        try:
            is_india = is_india_job(job.location, getattr(job, "remote", None))
        except Exception:
            is_india = False
        if is_india:
            india_total += 1
        bucket = next(
            (d for d, kws in TARGET_ROLE_KEYWORDS.items() if any(k in (job.title or "").lower() for k in kws)),
            None,
        )
        is_target = bucket is not None
        if is_india and is_target:
            india_target_total += 1
        if is_india and key not in existing:
            incremental_india += 1
            if is_target:
                incremental_india_target += 1

    raw = len(new_jobs)
    return {
        "incremental_unique_india_jobs": incremental_india,
        "incremental_unique_india_target_role_jobs": incremental_india_target,
        "india_jobs_per_provider_call": round(incremental_india / calls, 2),
        "india_jobs_per_crawl": india_total,
        "india_job_percentage": round(100.0 * india_total / raw, 1) if raw else 0.0,
        "india_target_role_percentage": round(100.0 * india_target_total / raw, 1) if raw else 0.0,
        "target_roles": target_roles,
    }


def score_queries_by_yield(
    per_query_stats: dict[str, dict[str, Any]],
) -> list[tuple[str, float]]:
    """Rank Adzuna queries by incremental India yield per API call (§5).

    Optimization metric: > incremental India jobs / call. The score blends
    incremental unique India jobs (0.6) with India target-role jobs (0.4),
    penalized when a query spends calls for no new coverage (call count from
    the stats dict defaulting to 1).

    ``per_query_stats`` entries mirror the live-probe shape:
        {"raw": int, "india": int, "target_role": int,
         "incremental_unique_india": int (optional), "calls": int (optional)}
    Ranking is deterministic (descending score, then query name).
    """
    ranked: list[tuple[str, float]] = []
    for query, stats in (per_query_stats or {}).items():
        calls = max(1, int(stats.get("calls", 1) or 1))
        incremental = max(0, int(stats.get("incremental_unique_india", stats.get("india", 0) or 0)))
        india_target = max(0, int(stats.get("india_target_role", stats.get("target_role", 0) or 0)))
        if incremental == 0 and india_target == 0:
            score = 0.0
        else:
            score = round((0.6 * incremental + 0.4 * india_target) / calls, 3)
        ranked.append((query, score))
    ranked.sort(key=lambda kv: (-kv[1], kv[0]))
    return ranked


# Firecrawl remains official-page-only and bounded (task §10). This guard is
# the single checklist a candidate URL must pass before scheduling.
FIRECRAWL_MAX_PAGES = 15


def validate_firecrawl_candidate(
    url: Optional[str],
    company: Optional[str] = None,
    expected_india_volume: int = 0,
    expected_requests: int = FIRECRAWL_MAX_PAGES,
    aggregator_followup: bool = False,
) -> dict[str, Any]:
    """Decide whether a Firecrawl candidate may be scheduled (pure).

    Rejects aggregator URLs, unbounded page budgets, and aggregator
    redirect-chasing. Returns the decision plus the bounded crawl plan.
    """
    reasons: list[str] = []
    allowed = True
    if not url or not isinstance(url, str):
        allowed, reasons = False, ["missing official URL"]
    else:
        if is_aggregator_url(url):
            allowed = False
            reasons.append("aggregator URL: Firecrawl is official-page-only")
        if aggregator_followup:
            allowed = False
            reasons.append("aggregator redirect follow-up is prohibited")
        try:
            pages = int(expected_requests)
        except (TypeError, ValueError):
            pages = FIRECRAWL_MAX_PAGES + 1
        if pages > FIRECRAWL_MAX_PAGES:
            allowed = False
            reasons.append(f"unbounded pages: max_pages={FIRECRAWL_MAX_PAGES}")
        if expected_india_volume <= 0:
            # Not a hard reject — volume unknown means "verify with a probe
            # first", recorded explicitly so unverified pages never schedule.
            reasons.append("India volume unverified: probe before scheduling")
    return {
        "allowed": allowed and not is_aggregator_url(url or ""),
        "url": url,
        "company": company,
        "max_pages": min(int(expected_requests or 0), FIRECRAWL_MAX_PAGES)
        if isinstance(expected_requests, int) else FIRECRAWL_MAX_PAGES,
        "expected_india_volume": expected_india_volume,
        "india_filter": "India",
        "extraction": "map official careers page -> scrape bounded job URLs -> parse title/company/location/description/apply_url",
        "required_fields": ["title", "company", "location", "description", "apply_url"],
        "crawl_frequency": "24h",
        "failure_behavior": "per-page isolation; failures never destroy usable jobs; retry bounded",
        "reasons": reasons,
    }


async def dry_run_provider(
    provider: str,
    queries: list[str],
    limits: Optional[ValidationLimits] = None,
    fetch_fn: Optional[Callable[..., Awaitable[list[CrawledJob]]]] = None,
) -> dict[str, Any]:
    """Bounded dry-run: fetch -> normalize -> validate -> metrics. No DB writes.

    fetch_fn(query, page, per_page) injects mocked or real discovery. When
    omitted, the canonical Adzuna/JobSpy adapters run with clamped budgets.
    Set persist=True via persist_run() instead — this function never persists.
    """
    from app.services.jobs.job_service import JobService

    lim = limits or ValidationLimits()
    queries = queries[: lim.max_queries]
    service = JobService()
    crawled: list[CrawledJob] = []
    pages_fetched = 0
    errors: list[str] = []
    for query in queries:
        for page in range(1, lim.max_pages_per_query + 1):
            try:
                if fetch_fn is not None:
                    batch = await fetch_fn(query=query, page=page, per_page=lim.results_per_query)
                elif provider == "adzuna":
                    from app.crawlers.aggregators.adzuna import AdzunaAdapter

                    batch = await AdzunaAdapter().search_by_query(
                        query, country="in", page=page, results_per_page=lim.results_per_query
                    )
                elif provider == "jobspy":
                    from app.crawlers.adapters.jobspy import JobSpyAdapter

                    batch = await JobSpyAdapter(query=query, results_wanted=lim.results_per_query).discover_jobs()
                else:
                    raise ValueError(f"Unknown provider: {provider}")
                pages_fetched += 1
                crawled.extend(batch[: lim.results_per_query])
            except Exception as exc:
                errors.append(f"{exc.__class__.__name__}")
                logger.warning("dry-run fetch failed (isolated): %s", exc)
            if len(crawled) >= MAX_TOTAL_JOBS:
                break
        if len(crawled) >= MAX_TOTAL_JOBS:
            break
    normalized = [service.normalize_and_classify(j) for j in crawled[:MAX_TOTAL_JOBS]]
    summary = summarize_jobs(normalized)
    return {
        "provider": provider, "dry_run": True, "persisted": False,
        "queries_executed": len(queries), "pages_fetched": pages_fetched,
        "errors": errors, **summary,
        "deduplication": dedup_report(normalized),
        "firecrawl": firecrawl_report(normalized, lim),
        "roles": role_coverage(normalized),
        "jobs": normalized,  # caller decides whether to persist via canonical path
    }


async def persist_run(provider: str, queries: list[str], **kwargs: Any) -> dict[str, Any]:
    """Persist via the canonical JobIngestionService (no parallel pipeline)."""
    from app.services.jobs.job_ingestion_service import JobIngestionService

    service = JobIngestionService()
    if provider == "adzuna":
        return await service.ingest_adzuna_jobs(queries[0] if queries else "software engineer")
    if provider == "jobspy":
        return await service.ingest_jobspy_jobs(queries[0] if queries else "data analyst India")
    raise ValueError(f"Unknown provider: {provider}")


if __name__ == "__main__":  # ponytail: CLI over endpoint; no public API surface
    import argparse
    import asyncio
    import json

    parser = argparse.ArgumentParser(description="Bounded ingestion dry-run (no DB writes)")
    parser.add_argument("--provider", default="adzuna", choices=["adzuna", "jobspy"])
    parser.add_argument("--queries", nargs="*", default=["data analyst India"])
    parser.add_argument("--max-queries", type=int, default=2)
    parser.add_argument("--per-page", type=int, default=10)
    args = parser.parse_args()
    try:  # local runs read .env; deployed workers export env vars (AdzunaAdapter uses os.getenv)
        from dotenv import load_dotenv

        load_dotenv(".env")
    except Exception:
        pass
    lim = ValidationLimits(max_queries=args.max_queries, results_per_query=args.per_page)
    result = asyncio.run(dry_run_provider(args.provider, args.queries, lim))
    jobs = result.pop("jobs")
    print(json.dumps(result, indent=2, default=str))
