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
from app.crawlers.source_quality import canonicalize_url, classify_source
from app.models.job import NormalizedJob
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
    text = f"{job.location or ''} {job.title or ''} {(job.raw or {}).get('location', '')}".lower()
    return any(tok in text for tok in _INDIA_TOKENS)


def summarize_jobs(jobs: list[NormalizedJob]) -> dict[str, Any]:
    """Per-provider counts reusing validate_job + canonicalize_url."""
    valid = warnings = invalid = stale = india = 0
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
        if _india_relevant(job):
            india += 1
    return {
        "raw": len(jobs), "valid": valid, "warnings": warnings,
        "invalid": invalid, "stale": stale,
        "unique_canonical": len(canonicals), "india_relevant": india,
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
