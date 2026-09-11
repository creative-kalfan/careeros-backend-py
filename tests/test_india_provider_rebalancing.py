"""India coverage expansion & provider rebalancing (offline).

Covers task §17:
- provider rebalancing: complete-inventory vs query-based not-seen policy
- Greenhouse geographic filtering (india_only, opt-in; global preserved)
- Adzuna query scoring (incremental India yield per call)
- city-query deduplication guard (measured incremental, not blind adds)
- UNKNOWN/AMBIGUOUS classification (US-only strings -> FOREIGN; conservative)
- multi-location India classification preserved
- incremental India-job KPI calculation (§16 family)
- India-first ranking consistency across retrieval & recommendation surfaces

Deterministic fixtures only — no network, no credentials, no DB writes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from app.crawlers.adapters.greenhouse import GreenhouseAdapter
from app.models.job import NormalizedJob
from app.services.jobs.india_geography import (
    AMBIGUOUS,
    FOREIGN,
    INDIA,
    UNKNOWN,
    classify_india_relevance,
    india_first_rank,
)
from app.services.jobs.ingestion_validation import (
    india_kpis,
    score_queries_by_yield,
)
from app.services.jobs.job_ingestion_service import ADZUNA_BROAD_QUERIES
from app.workers.jobs import crawl_jobs


def _job(location=None, **kw) -> NormalizedJob:
    base = dict(
        title="Data Analyst", company="Acme", location=location,
        description="SQL dashboards " * 30, source_platform="adzuna",
        apply_url="https://acme.com/jobs/1", canonical_url="https://acme.com/jobs/1",
        external_job_id="a1",
    )
    base.update(kw)
    return NormalizedJob(**base)


# --- Provider rebalancing: not-seen deactivation policy ----------------------

def test_uses_complete_inventory_split():
    # ATS boards / YC enumerate their whole inventory -> not-seen deactivation applies.
    for source in ("greenhouse", "ashby", "lever", "smartrecruiters", "ycombinator", "workday"):
        assert crawl_jobs._uses_complete_inventory(source) is True, source
    # Query-based providers (Adzuna/JobSpy) never enumerate the full source ->
    # "not seen today" must NOT deactivate (bounded rotation churn root cause).
    # Firecrawl IS complete-inventory, but scoped to the crawled careers URL.
    for source in ("adzuna", "jobspy"):
        assert crawl_jobs._uses_complete_inventory(source) is False, source


def test_query_based_sources_excluded_from_not_seen_deactivation():
    from app.workers.jobs.crawl_jobs import _QUERY_BASED_SOURCES

    assert "adzuna" in _QUERY_BASED_SOURCES and "jobspy" in _QUERY_BASED_SOURCES
    assert not _QUERY_BASED_SOURCES & {"greenhouse", "ashby", "lever", "smartrecruiters"}


# --- Greenhouse geographic filtering (opt-in; global preserved) --------------

class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


_GH_PAYLOAD = {
    "jobs": [
        {"title": "Data Analyst", "company_name": "Stripe", "location": "Bengaluru, India",
         "absolute_url": "https://boards.greenhouse.io/stripe/jobs/1", "id": 101},
        {"title": "Software Engineer", "company_name": "Stripe", "location": "London, UK",
         "absolute_url": "https://boards.greenhouse.io/stripe/jobs/2", "id": 102},
        {"title": "PM", "company_name": "Stripe", "location": "Remote",
         "absolute_url": "https://boards.greenhouse.io/stripe/jobs/3", "id": 103},
        {"title": "SRE", "company_name": "Stripe", "location": "US-Remote",
         "absolute_url": "https://boards.greenhouse.io/stripe/jobs/4", "id": 104},
        {"title": "Analyst", "company_name": "Stripe", "location": "Hyderabad, India",
         "absolute_url": "https://boards.greenhouse.io/stripe/jobs/5", "id": 105},
    ]
}


async def _gh_discover(india_only: bool):
    mock_client = AsyncMock()
    mock_client.get.side_effect = lambda *a, **k: _Resp(_GH_PAYLOAD)
    adapter = GreenhouseAdapter("stripe", client=mock_client, india_only=india_only)
    jobs = await adapter.discover_jobs()
    return jobs


async def test_greenhouse_default_preserves_global_inventory():
    jobs = await _gh_discover(india_only=False)
    assert len(jobs) == 5
    # Foreign + ambiguous + unknown canonical rows are NOT deleted by ingestion.
    locations = {j.location for j in jobs}
    assert "London, UK" in locations and "Remote" in locations and "US-Remote" in locations


async def test_greenhouse_india_only_filter():
    jobs = await _gh_discover(india_only=True)
    assert 1 <= len(jobs) <= 5
    for job in jobs:
        assert classify_india_relevance(job.location, job.remote) == INDIA, job.location
    assert {j.title for j in jobs} >= {"Data Analyst", "Analyst"}
# --- UNKNOWN / AMBIGUOUS conservative classification -------------------------

def test_us_only_remote_strings_are_foreign_not_unknown():
    for loc in ("US", "US-Remote", "US remote", "US - Remote", "US-SF, US-Seattle", "US-AMER"):
        assert classify_india_relevance(loc) == FOREIGN, loc


def test_bare_remote_forms_stay_ambiguous():
    for loc in ("Remote", "Remote US", "Remote in the US", "Remote - Worldwide"):
        assert classify_india_relevance(loc) == AMBIGUOUS, loc


def test_unresolved_strings_stay_unknown():
    for loc in ("N/A", "None", "Products", "LOCATION", "Skip to content", ""):
        assert classify_india_relevance(loc) == UNKNOWN, loc


def test_multi_location_explicit_india_stays_india():
    for loc in ("United States / India", "India / Singapore", "Remote - India", "IN-Bengaluru"):
        assert classify_india_relevance(loc) == INDIA, loc


def test_no_false_positive_us_substrings():
    # "us" inside words must never be read as the USA marker.
    assert classify_india_relevance("Mauritius") == UNKNOWN
    assert classify_india_relevance("Cyprus") == UNKNOWN
    assert classify_india_relevance("Luxembourg") == UNKNOWN
    assert classify_india_relevance("Austin") == FOREIGN  # real US city marker


# --- Adzuna query scoring (incremental India yield per call) -----------------

def test_score_queries_by_yield_ranks_incremental_india_first():
    stats = {
        "data analyst Hyderabad": {"raw": 10, "india": 10, "target_role": 8,
                                   "incremental_unique_india": 10, "india_target_role": 8},
        "data analyst Delhi": {"raw": 2, "india": 2, "target_role": 1,
                               "incremental_unique_india": 2, "india_target_role": 1},
        "dead query": {"raw": 10, "india": 0, "target_role": 0,
                       "incremental_unique_india": 0, "india_target_role": 0},
    }
    ranked = score_queries_by_yield(stats)
    assert ranked[0][0] == "data analyst Hyderabad"
    assert ranked[-1][0] == "dead query" and ranked[-1][1] == 0.0
    assert all(isinstance(score, float) for _, score in ranked)


def test_city_queries_are_part_of_rotation_but_bounded():
    text = " ".join(ADZUNA_BROAD_QUERIES).lower()
    # City queries exist only where measured incremental (dedup guard §7).
    for city in ("hyderabad", "pune", "mumbai", "chennai", "bengaluru", "gurugram"):
        assert f"data analyst {city}" in text
    # Not blindly every city / every role combination.
    assert "data analyst kolkata" not in text
    assert "machine learning hyderabad" not in text
    # Batch stays bounded (task §5: no API usage increase merely for volume).
    from app.services.jobs.job_ingestion_service import ADZUNA_BATCH_SIZE, ADZUNA_BROAD_COUNTRIES

    assert ADZUNA_BATCH_SIZE <= 3
    assert ADZUNA_BROAD_COUNTRIES == ("in",)


# --- Incremental India KPI family (§16) -------------------------------------

def test_india_kpis_headline_and_rates():
    existing = {"https://acme.com/jobs/1"}
    jobs = [
        _job("Hyderabad, India", canonical_url="https://acme.com/jobs/2",
             apply_url="https://acme.com/jobs/2"),  # incremental India target-role
        _job("London, UK", canonical_url="https://acme.com/jobs/3",
             apply_url="https://acme.com/jobs/3"),  # foreign, not counted
        _job("Bengaluru, India", title="Data Engineer", canonical_url="https://acme.com/jobs/4",
             apply_url="https://acme.com/jobs/4"),  # incremental India target-role
        _job("Bengaluru, India", canonical_url="https://acme.com/jobs/1",
             apply_url="https://acme.com/jobs/1"),  # already known -> not incremental
    ]
    kpis = india_kpis(jobs, existing, provider_calls=2)
    assert kpis["incremental_unique_india_jobs"] == 2
    assert kpis["incremental_unique_india_target_role_jobs"] == 2
    assert kpis["india_jobs_per_provider_call"] == 1.0  # 2 incremental / 2 calls
    assert kpis["india_jobs_per_crawl"] == 3  # 3 unique India in crawl
    assert kpis["india_job_percentage"] == 75.0
    assert kpis["india_target_role_percentage"] == 75.0  # 3 India target-role / 4 raw


def test_india_kpis_zero_calls_safe():
    kpis = india_kpis([_job("Pune, India")], [], provider_calls=0)
    assert kpis["india_jobs_per_provider_call"] == 1.0  # max(1,0) guard


# --- India-first ranking consistency (retrieval boundary §14) ----------------

def test_ranking_surfaces_agree():
    from app.services.jobs.job_relevance_service import _india_first_score as relevance_score
    from app.services.recommendations.recommendation_engine import _india_first_score as rec_score

    india = _job("Bengaluru, India")
    india_remote = _job("Remote - India")
    multi = _job("United States / India")
    generic_remote = _job("Remote")
    foreign = _job("London, UK")
    unknown = _job("N/A")

    assert india_first_rank(india.location) == 3
    assert india_first_rank(india_remote.location) == 2
    assert india_first_rank(multi.location) == 2
    assert india_first_rank(generic_remote.location) == 1
    assert india_first_rank(foreign.location) == 0
    assert india_first_rank(unknown.location) == 0

    # Both ranking surfaces agree on the order (India > remote > foreign).
    assert relevance_score(india) >= relevance_score(generic_remote) >= relevance_score(foreign)
    assert rec_score(india) >= rec_score(generic_remote) >= rec_score(foreign)
    # New US-only FOREIGN classification never ranks as India (never >= 2),
    # and ranks no higher than generic remote.
    us_remote = _job("US-Remote")
    assert relevance_score(us_remote) < 2
    assert rec_score(us_remote) < 2
    assert relevance_score(us_remote) <= relevance_score(generic_remote)
    assert rec_score(us_remote) <= rec_score(generic_remote)