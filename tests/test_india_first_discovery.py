"""India-first discovery: classification, scoring, filtering, guards (offline).

Deterministic fixtures only — no network, no credentials, no DB writes.
Covers task §17: aliases, registry config, source priority, India vs
foreign vs ambiguous, India-only filtering, multi-location India jobs,
source selection, Firecrawl guards, dedup, provenance, incremental
calculations, and India coverage scoring.
"""

from __future__ import annotations

from app.crawlers.crawl_registry import CrawlTarget, all_targets
from app.crawlers.source_quality import canonicalize_url, classify_source
from app.models.job import NormalizedJob
from app.services.jobs.company_coverage import (
    CLASSIFICATIONS,
    PROVIDER_COVERAGE_LEVELS,
    classify_provider_coverage,
)
from app.services.jobs.india_coverage_score import SourceSignals, rank_sources, score_source
from app.services.jobs.india_geography import (
    classify_india_relevance,
    filter_india_only,
    geography_report,
    india_first_rank,
)
from app.services.jobs.ingestion_validation import (
    FIRECRAWL_MAX_PAGES,
    geography_breakdown,
    incremental_report,
    provider_geography_report,
    summarize_jobs,
    validate_firecrawl_candidate,
)
from app.services.jobs.job_relevance_service import _india_first_score as relevance_score
from app.services.jobs.source_priority import select_preferred_source
from app.services.recommendations.recommendation_engine import (
    _india_first_score as rec_score,
)


def _job(location=None, **kw) -> NormalizedJob:
    base = dict(
        title="Data Analyst", company="Acme", location=location,
        description="SQL dashboards " * 30, source_platform="adzuna",
        apply_url="https://acme.com/jobs/1", canonical_url="https://acme.com/jobs/1",
        external_job_id="a1",
    )
    base.update(kw)
    return NormalizedJob(**base)


# --- §6: clearly India ----------------------------------------------------

def test_clearly_india_locations():
    for loc in (
        "Bengaluru, India", "Bangalore, India", "Hyderabad, India",
        "Mumbai, India", "Remote - India", "India - Remote", "India",
        "Pune, India", "Noida, India", "Coimbatore, India", "Mohali, India",
        "Dehradun, India", "Ajmer, India", "Udaipur, India", "Kochi, India",
    ):
        assert classify_india_relevance(loc) == "INDIA", loc


# --- §6: clearly foreign ---------------------------------------------------

def test_clearly_foreign_locations():
    for loc in (
        "London, UK", "New York, USA", "Toronto, Canada", "Singapore",
        "Berlin, Germany", "Sydney, Australia",
    ):
        assert classify_india_relevance(loc) == "FOREIGN", loc


# --- §6: ambiguous never Indian -------------------------------------------

def test_ambiguous_locations_never_indian():
    for loc in ("Remote", "Worldwide", "Global", "Multiple Locations", "EMEA", "APAC"):
        assert classify_india_relevance(loc) == "AMBIGUOUS", loc
        assert classify_india_relevance(loc) != "INDIA"


def test_indiana_usa_is_not_india():
    assert classify_india_relevance("Indiana, USA") != "INDIA"


# --- §6: multi-location including India -----------------------------------

def test_multi_location_including_india_stays_india():
    job = _job("United States / India")
    assert classify_india_relevance(job.location) == "INDIA"
    assert len(filter_india_only([job])) == 1
    # Original location preserved (no rewrite by the classifier).
    assert job.location == "United States / India"


# --- §7: India-only filtering ---------------------------------------------

def test_india_only_filtering():
    jobs = [_job("Bengaluru, India"), _job("Remote"), _job("London, UK"), _job("India")]
    kept = filter_india_only(jobs)
    assert [j.location for j in kept] == ["Bengaluru, India", "India"]


# --- §7: India-first ranking order ----------------------------------------

def test_india_first_ranking_order():
    india = _job("Bengaluru, India")
    india_remote = _job("Remote - India")
    multi = _job("United States / India")
    generic_remote = _job("Remote")
    foreign = _job("London, UK")
    assert india_first_rank(india.location) == 3  # Bangalore hub
    assert india_first_rank(india_remote.location) == 2
    assert india_first_rank(multi.location) == 2  # explicit India inclusion
    assert india_first_rank(generic_remote.location) == 1
    assert india_first_rank(foreign.location) == 0
    # Both ranking surfaces agree on the order.
    assert relevance_score(india) >= relevance_score(generic_remote) >= relevance_score(foreign)
    assert rec_score(india) >= rec_score(generic_remote) >= rec_score(foreign)
    # Foreign never outranks explicit India at equal match.
    assert relevance_score(india) > relevance_score(foreign)


# --- §3: source classification vocabulary ---------------------------------

def test_source_classification_vocabulary():
    for required in (
        "OFFICIAL_ATS", "OFFICIAL_INDIA_CAREER_PAGE",
        "OFFICIAL_GLOBAL_CAREER_PAGE_WITH_INDIA_FILTER",
        "AGGREGATOR_COVERED", "MULTI_SOURCE",
        "NO_RELIABLE_AUTOMATION", "UNVERIFIED",
    ):
        assert required in CLASSIFICATIONS


def test_source_selection_prefers_india_career_page():
    assert select_preferred_source(["aggregator", "firecrawl", "india_career_page", "ats"]) == "ats"
    assert select_preferred_source(["aggregator", "firecrawl", "india_career_page"]) == "india_career_page"
    assert select_preferred_source(["aggregator", "global_with_india_filter"]) == "global_with_india_filter"
    assert select_preferred_source(["aggregator", "firecrawl"]) == "aggregator"


# --- §8: provider coverage audit ------------------------------------------

def test_provider_coverage_audit_levels():
    assert set(PROVIDER_COVERAGE_LEVELS) == {
        "ALREADY_WELL_COVERED", "PARTIALLY_COVERED", "POORLY_COVERED",
        "NOT_COVERED", "UNVERIFIED",
    }
    assert classify_provider_coverage(12) == "ALREADY_WELL_COVERED"
    assert classify_provider_coverage(5) == "PARTIALLY_COVERED"
    assert classify_provider_coverage(1) == "POORLY_COVERED"
    assert classify_provider_coverage(0) == "NOT_COVERED"
    assert classify_provider_coverage(None) == "UNVERIFIED"
    assert classify_provider_coverage(7, verified=False) == "UNVERIFIED"


# --- §4: India coverage scoring -------------------------------------------

def test_india_relevance_dominates_volume():
    global_heavy = SourceSignals(
        india_relevance=0.002, india_job_volume=20, target_role_relevance=0.5,
        coverage_gap=0.5, reliability=0.5, incremental_potential=0.5, crawl_requests=5,
    )
    india_focused = SourceSignals(
        india_relevance=1.0, india_job_volume=300, target_role_relevance=0.8,
        coverage_gap=0.8, reliability=0.8, incremental_potential=0.8, crawl_requests=5,
    )
    assert score_source(india_focused) > score_source(global_heavy)
    ranked = rank_sources({"global": global_heavy, "india": india_focused})
    assert ranked[0][0] == "india"


def test_coverage_score_bounded_and_cost_aware():
    cheap = SourceSignals(india_relevance=0.8, india_job_volume=100, crawl_requests=2)
    pricey = SourceSignals(india_relevance=0.8, india_job_volume=100, crawl_requests=200)
    assert 0.0 <= score_source(cheap) <= 100.0
    assert score_source(cheap) > score_source(pricey)


# --- §5/§11: geography + incremental reports ------------------------------

def test_geography_breakdown_counts():
    jobs = [_job("Bengaluru, India"), _job("London, UK"), _job("Remote"), _job(None)]
    rep = geography_breakdown(jobs)
    assert (rep["india"], rep["foreign"], rep["ambiguous"], rep["unknown"]) == (1, 1, 1, 1)
    assert rep["india_pct"] == 25.0
    full = geography_report(jobs)
    assert full["by_provider"]["adzuna"]["india"] == 1


def test_provider_geography_split():
    providers = {
        "adzuna": [_job("Bengaluru, India"), _job("London, UK")],
        "greenhouse": [_job("Hyderabad, India")],
    }
    rep = provider_geography_report(providers)
    assert rep["adzuna"]["india"] == 1 and rep["adzuna"]["foreign"] == 1
    assert rep["greenhouse"]["india_pct"] == 100.0


def test_summarize_includes_foreign_split():
    jobs = [_job("Bengaluru, India"), _job("London, UK", canonical_url="https://acme.com/jobs/2",
            apply_url="https://acme.com/jobs/2", external_job_id="a2")]
    summary = summarize_jobs(jobs)
    assert summary["india"] == 1 and summary["foreign"] == 1
    assert summary["india_relevant"] == 1  # legacy key preserved


def test_incremental_report_headline_metric():
    old = {"https://acme.com/jobs/1"}
    jobs = [
        _job("Bengaluru, India"),  # already known canonical
        _job("Hyderabad, India", canonical_url="https://acme.com/jobs/2",
             apply_url="https://acme.com/jobs/2", external_job_id="a2"),
        _job("London, UK", canonical_url="https://acme.com/jobs/3",
             apply_url="https://acme.com/jobs/3", external_job_id="a3"),
    ]
    rep = incremental_report(jobs, old)
    assert rep["raw"] == 3 and rep["unique_canonical"] == 3
    assert rep["incremental_unique"] == 2
    assert rep["incremental_india"] == 1  # headline: new useful Indian jobs
    assert rep["india"] == 2 and rep["foreign"] == 1


# --- §10: Firecrawl guards -------------------------------------------------

def test_firecrawl_candidate_official_only_and_bounded():
    ok = validate_firecrawl_candidate("https://www.zoho.com/careers/", "Zoho", expected_india_volume=50)
    assert ok["allowed"] is True
    assert ok["max_pages"] <= FIRECRAWL_MAX_PAGES == 15
    assert ok["required_fields"] and ok["india_filter"] == "India"

    agg = validate_firecrawl_candidate("https://www.naukri.com/job/1", "Zoho", expected_india_volume=50)
    assert agg["allowed"] is False

    chained = validate_firecrawl_candidate(
        "https://www.zoho.com/careers/", "Zoho",
        expected_india_volume=50, aggregator_followup=True,
    )
    assert chained["allowed"] is False

    unbounded = validate_firecrawl_candidate(
        "https://www.zoho.com/careers/", "Zoho",
        expected_india_volume=50, expected_requests=500,
    )
    assert unbounded["allowed"] is False


# --- §14: registry stays configuration-driven ------------------------------

def test_registry_carries_india_fields():
    target = CrawlTarget("firecrawl", "Acme|https://acme.com/careers", "firecrawl", 2,
                         company="Acme", url="https://acme.com/careers",
                         india_only=True, india_filter="India")
    assert target.company_name == "Acme"
    assert target.careers_url == "https://acme.com/careers"
    assert target.india_only is True and target.india_filter == "India"
    # Existing registry targets expose the same surface.
    for existing in all_targets():
        assert hasattr(existing, "india_only") and hasattr(existing, "coverage_score")


# --- Dedup + provenance preserved ------------------------------------------

def test_canonical_dedup_conservative():
    url = "https://www.zoho.com/careers/9?utm_source=naukri"
    assert canonicalize_url(url) == "https://www.zoho.com/careers/9"
    official = classify_source("firecrawl", url, "Zoho", careers_url="https://www.zoho.com/careers/")
    agg = classify_source("adzuna", url, "Zoho")
    assert official.tier < agg.tier  # same URL, provenance preserved per source
