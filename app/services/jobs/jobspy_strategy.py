"""JobSpy broad discovery strategy: deterministic query/location/freshness rotation.

Transforms the JobSpy integration from a single hard-coded query
(``data analyst India``) into a bounded, India-first discovery layer that
sits between the direct ATS adapters and Adzuna in the acquisition
hierarchy:

    1. Direct ATS adapters (authoritative)
    2. JobSpy (broad job-board discovery, this module)
    3. Adzuna (broad search / additional coverage)
    4. Crawl4AI (generic career pages)
    5. Firecrawl (exceptional fallback only)

All functions here are pure and deterministic (no network, no DB) so the
rotation is restart-safe and fully unit-testable. Live scraping stays in
``app.crawlers.adapters.jobspy.JobSpyAdapter``; orchestration (throttling,
circuit breaking, caching) lives in ``app.services.jobs.jobspy_throttle``;
persistence flows through the canonical
``JobIngestionService -> JobRepository.upsert_jobs`` pipeline.

Pinned provider library: ``python-jobspy==1.1.82`` (see requirements.txt).
Per-site parameter support (conservative — only pass what each source
demonstrably accepts):

    - indeed / glassdoor: search_term, location, results_wanted, hours_old,
      country_indeed (required for India scoping, e.g. ``"India"``).
      Indeed limitation: only one of hours_old / (job_type & is_remote) /
      easy_apply per search — we use hours_old only.
    - linkedin: search_term, location, results_wanted, hours_old (xor
      easy_apply — we use hours_old only). ``linkedin_fetch_description``
      stays False (it multiplies requests O(n)); rate-limit sensitive, so
      LinkedIn is scheduled conservatively (longer per-provider delay).
    - naukri: search_term, location, results_wanted only. hours_old /
      country support on the Naukri scraper is unverified, so freshness
      filtering is never requested there (freshness is enforced by the
      CareerOS lifecycle instead).

Naukri through JobSpy has historically been flaky (HTTP 406 / reCAPTCHA);
one provider failure must never abort the other providers — see
``ingest_jobspy_scheduled``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Query families (bounded; rotated, never executed simultaneously)
# ---------------------------------------------------------------------------

# Each family is a small set of role queries. Fresher / entry-level intent
# is expressed per family (fresher, graduate, junior, trainee, associate,
# entry level, 0-1 / 0-2 years, campus) so every crawl cycle covers both
# experienced and entry-level demand without concatenating every keyword.
JOBSPY_QUERY_FAMILIES: dict[str, tuple[str, ...]] = {
    "fresher_data": (
        "fresher data analyst",
        "junior data analyst",
        "graduate data engineer",
        "trainee MIS analyst",
        "campus hire analyst",
    ),
    "software_backend": (
        "software engineer fresher",
        "junior backend developer",
        "Python developer entry level",
        "full stack developer junior",
    ),
    "ai_ml": (
        "fresher AI engineer",
        "junior machine learning engineer",
        "graduate data scientist",
        "generative AI trainee",
    ),
    "qa_testing": (
        "QA engineer fresher",
        "junior test engineer",
        "automation tester entry level",
        "software tester trainee",
    ),
    "erp_enterprise": (
        "SAP fresher",
        "junior SAP consultant",
        "ERP trainee",
        "Salesforce developer entry level",
    ),
    "cloud_devops": (
        "cloud engineer fresher",
        "junior DevOps engineer",
        "cloud support associate",
        "infrastructure engineer entry level",
    ),
    "finance_bfsi": (
        "financial analyst fresher",
        "junior risk analyst",
        "credit analyst entry level",
        "operations analyst fresher",
    ),
    "operations_support": (
        "product analyst fresher",
        "customer success associate",
        "technical support engineer fresher",
        "implementation analyst entry level",
    ),
    "core_experienced": (
        "data analyst",
        "software engineer",
        "backend developer",
        "business analyst",
    ),
    "internship": (
        "data analyst intern",
        "software developer intern",
        "machine learning intern",
        "business analyst intern",
    ),
    "walkin_mass": (
        "walk-in interview fresher",
        "hiring drive freshers",
        "immediate joiner analyst",
        "recruitment drive graduate",
    ),
}

# ---------------------------------------------------------------------------
# India-first locations (bounded rotation; never role x city cross-product)
# ---------------------------------------------------------------------------

JOBSPY_LOCATIONS: tuple[str, ...] = (
    "India",
    "Bengaluru, India",
    "Hyderabad, India",
    "Pune, India",
    "Chennai, India",
    "Mumbai, India",
    "Delhi NCR, India",
    "Gurugram, India",
    "Noida, India",
    "Ahmedabad, India",
    "Kolkata, India",
    "Jaipur, India",
    "Kochi, India",
    "Coimbatore, India",
    "Chandigarh, India",
    "Remote, India",
)

# ---------------------------------------------------------------------------
# Freshness buckets (hours_old values supported by indeed/linkedin)
# ---------------------------------------------------------------------------

# Very recent (0-24h), recent (24-72h), rolling (3-7 days). One bucket per
# scheduled run, rotated deterministically; the CareerOS age-based lifecycle
# (JOB_STALE_AFTER_DAYS) remains the deactivation authority.
JOBSPY_FRESHNESS_BUCKETS: tuple[int, ...] = (24, 72, 168)

# ---------------------------------------------------------------------------
# Provider matrix
# ---------------------------------------------------------------------------

SUPPORTED_JOBSPY_SITES: tuple[str, ...] = ("indeed", "naukri", "glassdoor", "linkedin")

# Default rotation order: Indeed-heavy (broad recurring searches where
# production testing confirms reliability), Naukri for India-specific
# coverage, LinkedIn conservatively (rate-limit sensitive). Glassdoor is
# opt-in via JOBSPY_SITES.
DEFAULT_JOBSPY_SITE_ROTATION: tuple[str, ...] = ("indeed", "naukri", "indeed", "linkedin")

# Sites that accept the hours_old freshness parameter.
HOURS_OLD_SUPPORTED_SITES = frozenset({"indeed", "glassdoor", "linkedin"})

# Sites that accept country_indeed for India scoping.
COUNTRY_SUPPORTED_SITES = frozenset({"indeed", "glassdoor"})

# Conservative bounds (never exceeded regardless of caller input).
MAX_JOBSPY_QUERIES_PER_RUN = 8
MAX_JOBSPY_LOCATIONS_PER_RUN = 4
MAX_JOBSPY_SEARCHES_PER_RUN = 10


@dataclass(frozen=True)
class JobSpySearch:
    """One bounded JobSpy search within a scheduled rotation batch."""

    query: str
    location: str
    site: str
    hours_old: Optional[int]
    results_wanted: int
    query_family: str


def parse_sites(raw: Optional[str]) -> list[str]:
    """Parse the JOBSPY_SITES allowlist; unknown sites are dropped.

    Empty / fully-unknown input yields [] (the scheduled run then returns
    zeros and logs — never a fake success).
    """
    if not raw or not isinstance(raw, str):
        return list(DEFAULT_JOBSPY_SITE_ROTATION[:3])
    wanted = [part.strip().lower() for part in raw.split(",")]
    known = [site for site in wanted if site in SUPPORTED_JOBSPY_SITES]
    # Preserve configured order but deduplicate; fall back to the default
    # rotation order filtered to the configured set.
    seen: list[str] = []
    for site in known:
        if site not in seen:
            seen.append(site)
    return seen


def parse_freshness_buckets(raw: Optional[str]) -> tuple[int, ...]:
    """Parse JOBSPY_FRESHNESS_BUCKETS (hours_old list); clamped to 1..720."""
    if not raw or not isinstance(raw, str):
        return JOBSPY_FRESHNESS_BUCKETS
    parsed: list[int] = []
    for part in raw.split(","):
        try:
            value = int(part.strip())
        except (TypeError, ValueError):
            continue
        parsed.append(max(1, min(value, 720)))
    return tuple(parsed) if parsed else JOBSPY_FRESHNESS_BUCKETS


def _ordered_queries() -> list[tuple[str, str]]:
    """Flatten families to (family, query) pairs in fixed declaration order."""
    pairs: list[tuple[str, str]] = []
    for family in JOBSPY_QUERY_FAMILIES:
        for query in JOBSPY_QUERY_FAMILIES[family]:
            pairs.append((family, query))
    return pairs


def rotation_batch(
    ordinal: int,
    query_batch_size: int = 4,
    location_batch_size: int = 2,
    sites: Optional[list[str]] = None,
    results_wanted: int = 50,
    freshness_buckets: Optional[tuple[int, ...]] = None,
) -> list[JobSpySearch]:
    """Deterministic bounded batch of JobSpy searches for one crawl cycle.

    - ``ordinal`` is typically the day-of-year; the windows step by batch
      size (``ordinal * size % total``) so consecutive cycles cover NEW
      ground instead of re-requesting the same combinations inside the
      freshness window.
    - Queries and locations rotate independently (no role x city
      cross-product); the batch pairs them round-robin, so batch size is
      ``max(queries, locations)`` — always bounded.
    - One freshness bucket per run (rotated); hours_old is attached only
      for sites that support it (naukri relies on the DB lifecycle).
    - Sites cycle deterministically across the batch.
    """
    queries = _ordered_queries()
    total_queries = len(queries)
    num_queries = max(1, min(int(query_batch_size or 1), MAX_JOBSPY_QUERIES_PER_RUN))
    num_locations = max(
        1, min(int(location_batch_size or 1), MAX_JOBSPY_LOCATIONS_PER_RUN)
    )
    site_list = [s for s in (sites or list(DEFAULT_JOBSPY_SITE_ROTATION[:3])) if s]
    if not site_list or total_queries == 0:
        return []
    buckets = freshness_buckets or JOBSPY_FRESHNESS_BUCKETS
    bucket = buckets[int(ordinal) % len(buckets)]

    query_start = (int(ordinal) * num_queries) % total_queries
    picked_queries = [
        queries[(query_start + i) % total_queries] for i in range(num_queries)
    ]
    # Coprime stride (7) over 16 locations spreads successive cycles across
    # cities instead of pinning each query to one city.
    location_start = (int(ordinal) * num_locations * 7) % len(JOBSPY_LOCATIONS)
    picked_locations = [
        JOBSPY_LOCATIONS[(location_start + i) % len(JOBSPY_LOCATIONS)]
        for i in range(num_locations)
    ]

    searches: list[JobSpySearch] = []
    count = min(max(num_queries, num_locations), MAX_JOBSPY_SEARCHES_PER_RUN)
    for i in range(count):
        family, query = picked_queries[i % len(picked_queries)]
        location = picked_locations[i % len(picked_locations)]
        site = site_list[(int(ordinal) + i) % len(site_list)]
        hours_old = bucket if site in HOURS_OLD_SUPPORTED_SITES else None
        searches.append(
            JobSpySearch(
                query=query,
                location=location,
                site=site,
                hours_old=hours_old,
                results_wanted=max(1, min(int(results_wanted or 1), 200)),
                query_family=family,
            )
        )
    return searches


# ---------------------------------------------------------------------------
# Fresher / entry-level assessment (reuses the canonical seniority taxonomy)
# ---------------------------------------------------------------------------

def fresher_assessment(title: Optional[str], description: Optional[str]) -> dict[str, Any]:
    """Evidence-based fresher assessment reusing ``classify_seniority``.

    No second taxonomy: the canonical classifier's title precedence already
    excludes senior/lead/principal/manager roles (a senior title wins even
    when "freshers" appears in the body). Returns the level, confidence,
    and boolean so callers never reimplement the rules.
    """
    from app.services.jobs.extraction_utils import classify_seniority

    level, confidence = classify_seniority(description or "", title or "")
    return {
        "is_fresher": level in ("entry", "intern"),
        "is_internship": level == "intern",
        "level": level,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Emerging / under-covered company discovery (observable signals only)
# ---------------------------------------------------------------------------

# Score weights for the deterministic hiring-signal score. Positive signals
# reward recent India fresher/internship demand; ATS coverage strongly
# deprioritizes (those companies are already authoritative elsewhere).
_HIRING_SIGNAL_WEIGHTS = {
    "recent_posting": 3,  # >=1 posting in the last 7 days
    "fresher_signal": 2,  # >=1 fresher/entry-level posting
    "internship_signal": 2,  # >=1 internship posting
    "openings_volume": 2,  # >=3 distinct active openings (>=10 scores +1)
    "india_location": 2,  # >=1 India-located posting
    "recurring_signal": 2,  # seen across >=2 recent runs / sources
    "source_diversity": 1,  # >=2 distinct discovery sources
    "ats_covered_penalty": -4,  # already covered by a direct ATS board
}


def hiring_signal_score(stats: dict[str, Any]) -> dict[str, Any]:
    """Score one company's hiring signal from observable posting facts.

    ``stats`` keys (all optional, missing = no signal): active_openings,
    recent_postings_7d, fresher_postings, internship_postings,
    india_postings, distinct_sources, recurring (bool), ats_covered (bool).

    Terminology is deliberate: "emerging hiring company", "active hiring
    company", "fresher hiring signal", "under-covered company" — never a
    subjective "best startups" list.
    """
    score = 0
    reasons: list[str] = []
    get = stats.get

    if int(get("recent_postings_7d") or 0) >= 1:
        score += _HIRING_SIGNAL_WEIGHTS["recent_posting"]
        reasons.append("recent posting signal")
    if int(get("fresher_postings") or 0) >= 1:
        score += _HIRING_SIGNAL_WEIGHTS["fresher_signal"]
        reasons.append("fresher hiring signal")
    if int(get("internship_postings") or 0) >= 1:
        score += _HIRING_SIGNAL_WEIGHTS["internship_signal"]
        reasons.append("internship signal")
    openings = int(get("active_openings") or 0)
    if openings >= 3:
        score += _HIRING_SIGNAL_WEIGHTS["openings_volume"]
        reasons.append(f"{openings} distinct active openings")
        if openings >= 10:
            score += 1
            reasons.append("high opening volume")
    if int(get("india_postings") or 0) >= 1:
        score += _HIRING_SIGNAL_WEIGHTS["india_location"]
        reasons.append("India-location signal")
    if bool(get("recurring")):
        score += _HIRING_SIGNAL_WEIGHTS["recurring_signal"]
        reasons.append("recurring posting signal")
    if int(get("distinct_sources") or 0) >= 2:
        score += _HIRING_SIGNAL_WEIGHTS["source_diversity"]
        reasons.append("source diversity")
    ats_covered = bool(get("ats_covered"))
    if ats_covered:
        score += _HIRING_SIGNAL_WEIGHTS["ats_covered_penalty"]
        reasons.append("already covered by direct ATS ingestion")

    if ats_covered:
        label = "ats-covered company"
    elif score >= 6:
        label = "emerging hiring company"
    elif score >= 4:
        label = "under-covered company"
    elif score >= 2:
        label = "active hiring company"
    else:
        label = "low hiring signal"
    return {"score": score, "label": label, "reasons": reasons}


def score_companies_from_jobs(
    jobs: list[Any],
    ats_companies: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """Aggregate one ingestion batch into per-company hiring-signal scores.

    Accepts NormalizedJob rows (or anything with company/location/
    experience_level/source_platform/posted_date attributes). Recency uses
    posted_date/posted_at best-effort; missing dates are never treated as
    recent. India signal uses the strict ``is_india_job`` classifier.
    """
    from datetime import datetime, timezone

    from app.services.jobs.india_geography import is_india_job

    covered = {str(c).strip().lower() for c in (ats_companies or set()) if c}
    buckets: dict[str, dict[str, Any]] = {}

    for job in jobs:
        company = str(getattr(job, "company", "") or "").strip()
        if not company:
            continue
        key = company.lower()
        entry = buckets.setdefault(
            key,
            {
                "company": company,
                "active_openings": 0,
                "recent_postings_7d": 0,
                "fresher_postings": 0,
                "internship_postings": 0,
                "india_postings": 0,
                "distinct_sources": set(),
                "recurring": False,
            },
        )
        entry["active_openings"] += 1
        level = (getattr(job, "experience_level", "") or "").lower()
        if level == "intern":
            entry["internship_postings"] += 1
            entry["fresher_postings"] += 1
        elif level == "entry":
            entry["fresher_postings"] += 1
        try:
            if is_india_job(getattr(job, "location", ""), getattr(job, "remote", None)):
                entry["india_postings"] += 1
        except Exception:
            pass
        source = getattr(job, "source_platform", "") or ""
        if source:
            entry["distinct_sources"].add(str(source).lower())
        raw = (getattr(job, "posted_date", None) or getattr(job, "posted_at", None))
        if raw:
            try:
                posted = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if posted.tzinfo is None:
                    posted = posted.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - posted).total_seconds() / 86400
                if 0 <= age_days <= 7:
                    entry["recent_postings_7d"] += 1
            except Exception:
                pass

    scored: list[dict[str, Any]] = []
    for key, entry in buckets.items():
        entry["recurring"] = (
            entry["recent_postings_7d"] >= 2 or len(entry["distinct_sources"]) >= 2
        )
        stats = {
            "active_openings": entry["active_openings"],
            "recent_postings_7d": entry["recent_postings_7d"],
            "fresher_postings": entry["fresher_postings"],
            "internship_postings": entry["internship_postings"],
            "india_postings": entry["india_postings"],
            "distinct_sources": len(entry["distinct_sources"]),
            "recurring": entry["recurring"],
            "ats_covered": key in covered,
        }
        result = hiring_signal_score(stats)
        scored.append({"company": entry["company"], "stats": stats, **result})
    scored.sort(key=lambda item: (-item["score"], item["company"].lower()))
    return scored


# ---------------------------------------------------------------------------
# Structured-source coverage gate (reduces redundant generic crawling)
# ---------------------------------------------------------------------------

def _normalize_company_token(company: Optional[str]) -> str:
    collapsed = " ".join(str(company or "").strip().split()).lower()
    return "".join(ch for ch in collapsed if ch.isalnum() or ch == " ").strip()


def ats_covered_companies() -> set[str]:
    """Company names with a direct ATS board in the crawl registry."""
    from app.crawlers.crawl_registry import ATS_TARGETS

    return {
        _normalize_company_token(target.company)
        for target in ATS_TARGETS
        if target.company
    }


def company_has_structured_source(company: Optional[str]) -> bool:
    """True when a direct ATS adapter already covers this company.

    Strong, registry-grounded evidence — the only condition under which
    generic (Crawl4AI/Firecrawl) crawling for the company is skipped.
    """
    token = _normalize_company_token(company)
    if not token:
        return False
    return token in ats_covered_companies()
