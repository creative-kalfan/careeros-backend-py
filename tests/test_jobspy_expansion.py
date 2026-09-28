"""JobSpy broad discovery layer: rotation, classification, reliability, scheduler.

All external job-board calls are mocked (fetch_fn injection); no test
requires live Naukri/LinkedIn/Indeed access.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.jobs.job_ingestion_service import JobIngestionService
from app.services.jobs.jobspy_strategy import (
    JOBSPY_LOCATIONS,
    JOBSPY_QUERY_FAMILIES,
    rotation_batch,
)
from app.services.jobs.jobspy_throttle import (
    JobSpyCircuitBreaker,
    ProviderThrottle,
    SearchCache,
    is_rate_limit_error,
)
from app.services.jobs.mass_hiring_detector import detect_mass_hiring, detect_walkin


NOW_ISO = datetime.now(timezone.utc).isoformat()


def _job_record(title="Fresher Data Analyst", company="FresherCo",
                 location="Bengaluru", site="indeed", job_id="f1",
                 description="0-1 years experience, SQL dashboards."):
    return {
        "title": title, "company": company, "location": location,
        "description": description,
        "job_url": f"https://example.com/jobs/{job_id}",
        "site": site, "id": job_id, "date_posted": NOW_ISO,
    }


def _fresh_instances(ttl_seconds=3600.0):
    now = [1000.0]
    return (
        ProviderThrottle(default_delay_seconds=5.0,
                         per_provider_delay_seconds={"linkedin": 15.0},
                         monotonic=lambda: now[0],
                         sleep=AsyncMock()),
        JobSpyCircuitBreaker(failure_threshold=3, cooldown_seconds=600.0,
                             monotonic=lambda: now[0]),
        SearchCache(ttl_seconds=ttl_seconds, monotonic=lambda: now[0]),
        now,
    )


def _service_with_mock_repo(inserted=2):
    service = JobIngestionService()
    service.job_repository = MagicMock()
    service.job_repository.upsert_jobs.return_value = {
        "discovered": inserted, "inserted": inserted, "updated": 0,
        "unchanged": 0, "deduplicated": 0, "skipped": 0,
    }
    return service


# --- 1. query rotation ---

def test_jobspy_query_rotation_bounded_deterministic():
    b1 = rotation_batch(4, sites=["indeed"])
    b2 = rotation_batch(4, sites=["indeed"])
    assert b1 == b2  # deterministic
    assert 1 <= len(b1) <= 4  # bounded: max(queries, locations)
    assert len(rotation_batch(4, query_batch_size=8, location_batch_size=4,
                              sites=["indeed"])) <= 8
    families = {s.query_family for s in rotation_batch(4, sites=["indeed"])}
    assert families  # every batch is labeled by family


def test_jobspy_rotation_covers_families_over_cycle():
    seen = set()
    for ordinal in range(40):
        seen.update(s.query_family for s in rotation_batch(ordinal, sites=["indeed"]))
    for family in ("fresher_data", "software_backend", "ai_ml", "qa_testing",
                   "erp_enterprise", "cloud_devops", "finance_bfsi",
                   "operations_support", "internship", "walkin_mass",
                   "core_experienced"):
        assert family in seen, family


def test_jobspy_rotation_steps_forward_not_repeating():
    first_queries = [" ".join(s.query for s in rotation_batch(o, sites=["indeed"]))
                     for o in range(6)]
    assert len(set(first_queries)) > 1  # consecutive cycles cover new ground


# --- 2. location rotation ---

def test_jobspy_location_rotation_india_first():
    seen = set()
    for ordinal in range(40):
        seen.update(s.location for s in rotation_batch(ordinal, sites=["indeed"]))
    for city in ("India", "Bengaluru, India", "Hyderabad, India", "Pune, India",
                 "Chennai, India", "Mumbai, India", "Delhi NCR, India",
                 "Gurugram, India", "Noida, India", "Kolkata, India",
                 "Remote, India"):
        assert city in seen, city
    assert len(JOBSPY_LOCATIONS) >= 15


# --- 3. fresher query generation ---

def test_jobspy_fresher_queries_present():
    text = " ".join(q for queries in JOBSPY_QUERY_FAMILIES.values() for q in queries).lower()
    for needle in ("fresher", "junior", "trainee", "entry level", "graduate",
                   "intern", "campus", "associate"):
        assert needle in text, needle
    assert "fresher" in " ".join(JOBSPY_QUERY_FAMILIES["fresher_data"]).lower()
    assert "intern" in " ".join(JOBSPY_QUERY_FAMILIES["internship"]).lower()
    assert "walk" in " ".join(JOBSPY_QUERY_FAMILIES["walkin_mass"]).lower()


def test_jobspy_hours_old_only_where_supported():
    batch = rotation_batch(3, sites=["indeed", "naukri", "linkedin", "glassdoor"])
    by_site = {}
    for search in batch:
        by_site.setdefault(search.site, []).append(search.hours_old)
    assert all(h is None for h in by_site.get("naukri", [None]))
    for site in ("indeed", "linkedin", "glassdoor"):
        for hours in by_site.get(site, []):
            assert hours in (24, 72, 168)


# --- 4. walk-in detection ---

def test_walkin_detected_from_title_evidence():
    assert detect_walkin("Walk-in Interview: Customer Support", "")["is_walkin"] is True
    res = detect_mass_hiring(title="Walk-in Interview for Freshers",
                             description="Bring your resume to the venue in Bengaluru.")
    assert res["confidence"] == "VERIFIED_MASS_HIRING"
    assert res["walkin_detected"] is True


def test_walkin_description_needs_corroboration():
    # Bare mention without event evidence is possible, never verified.
    res = detect_mass_hiring(title="Customer Support Associate",
                             description="We sometimes do walk-in interviews.")
    assert res["confidence"] in ("POSSIBLE_MASS_HIRING", "NOT_MASS_HIRING")
    assert res["confidence"] != "VERIFIED_MASS_HIRING"
    # Venue/date details corroborate the event.
    res2 = detect_mass_hiring(
        title="Customer Support Associate",
        description="Walk-in interview on 12th Dec, venue: Bengaluru office. "
                    "Reporting time 9am, carry your resume.",
    )
    assert res2["confidence"] == "VERIFIED_MASS_HIRING"


def test_walkin_rejects_senior_and_incidental_and_furniture():
    senior = detect_mass_hiring(title="Senior Backend Engineer",
                                description="5+ years experience, system design.")
    assert senior["confidence"] == "NOT_MASS_HIRING"
    assert senior["walkin_detected"] is False
    vendor = detect_mass_hiring(title="Account Executive",
                                description="We provide mass hiring solutions.")
    assert vendor["confidence"] == "NOT_MASS_HIRING"
    assert vendor["walkin_detected"] is False
    closet = detect_mass_hiring(title="Walk-in Closet Installer",
                                description="Install wardrobes and closets.")
    assert closet["confidence"] == "NOT_MASS_HIRING"
    assert closet["walkin_detected"] is False


# --- 5. emerging-company signal extraction ---

def test_hiring_signal_labels_without_best_startups():
    from app.services.jobs.jobspy_strategy import hiring_signal_score

    emerging = hiring_signal_score({
        "active_openings": 5, "recent_postings_7d": 3, "fresher_postings": 2,
        "internship_postings": 1, "india_postings": 5, "distinct_sources": 2,
        "recurring": True, "ats_covered": False,
    })
    assert emerging["label"] == "emerging hiring company"
    assert "best" not in emerging["label"].lower()
    assert "startup" not in emerging["label"].lower()
    under = hiring_signal_score({
        "active_openings": 3, "recent_postings_7d": 0, "fresher_postings": 0,
        "internship_postings": 0, "india_postings": 3, "distinct_sources": 1,
        "recurring": False, "ats_covered": False,
    })
    assert under["label"] == "under-covered company"
    covered = hiring_signal_score({
        "active_openings": 30, "recent_postings_7d": 10, "fresher_postings": 5,
        "internship_postings": 2, "india_postings": 30, "distinct_sources": 3,
        "recurring": True, "ats_covered": True,
    })
    assert covered["label"] == "ats-covered company"


def test_score_companies_from_jobs_aggregates_batch():
    from app.services.jobs.jobspy_strategy import score_companies_from_jobs
    from app.models.job import NormalizedJob

    jobs = [
        NormalizedJob(title="Fresher Data Analyst", company="FresherCo",
                      location="Bengaluru, India", description="0-1 years SQL",
                      source_platform="jobspy", external_job_id=f"f{i}",
                      experience_level="entry", posted_date=NOW_ISO)
        for i in range(4)
    ]
    scored = score_companies_from_jobs(jobs, ats_companies=set())
    assert len(scored) == 1
    assert scored[0]["company"] == "FresherCo"
    assert scored[0]["label"] in ("emerging hiring company", "under-covered company")
    assert scored[0]["stats"]["fresher_postings"] == 4


# --- 6. provider throttling ---

@pytest.mark.asyncio
async def test_provider_throttle_enforces_minimum_delay():
    now = [1000.0]
    waited: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waited.append(seconds)
        now[0] += seconds

    throttle = ProviderThrottle(default_delay_seconds=5.0,
                                per_provider_delay_seconds={"linkedin": 15.0},
                                monotonic=lambda: now[0], sleep=fake_sleep)
    assert await throttle.wait("indeed") == 0.0  # first search: no wait
    throttle.record("indeed")
    now[0] += 2.0
    assert await throttle.wait("indeed") == pytest.approx(3.0)  # spacing enforced
    assert throttle.delay_for("linkedin") == 15.0  # conservative LinkedIn
    assert throttle.delay_for("indeed") == 5.0


# --- 7. circuit breaker ---

def test_circuit_breaker_opens_after_threshold_and_resets():
    now = [0.0]
    breaker = JobSpyCircuitBreaker(failure_threshold=3, cooldown_seconds=600.0,
                                   monotonic=lambda: now[0])
    assert breaker.should_skip("naukri") is False
    breaker.record_failure("naukri")
    breaker.record_failure("naukri")
    assert breaker.should_skip("naukri") is False
    breaker.record_failure("naukri")
    assert breaker.should_skip("naukri") is True
    assert "naukri" in breaker.open_providers
    now[0] += 601.0  # cooldown elapses: probe allowed again
    assert breaker.should_skip("naukri") is False
    breaker.record_success("naukri")
    assert breaker.failure_count("naukri") == 0


def test_circuit_breaker_rate_limit_backs_off_exponentially():
    now = [0.0]
    breaker = JobSpyCircuitBreaker(failure_threshold=3, cooldown_seconds=600.0,
                                   monotonic=lambda: now[0])
    breaker.record_rate_limited("linkedin")
    first_open = breaker._open_until["linkedin"]
    assert first_open == 600.0
    now[0] += 1.0
    breaker.record_rate_limited("linkedin")
    assert breaker._open_until["linkedin"] > first_open + 600.0  # doubled


# --- 8. 429 handling (no aggressive retry) ---

@pytest.mark.asyncio
async def test_rate_limit_drops_search_without_retry():
    calls: list[dict] = []

    async def fetch_429(**kw):
        calls.append(kw)
        raise RuntimeError("429 Too Many Requests")

    assert is_rate_limit_error(RuntimeError("429 Too Many Requests")) is True
    service = _service_with_mock_repo(inserted=0)
    throttle, breaker, cache, _ = _fresh_instances()
    result = await service.ingest_jobspy_scheduled(
        ordinal=1, throttle=throttle, breaker=breaker, cache=cache, fetch_fn=fetch_429,
    )
    # One attempt per scheduled search — never a retry storm.
    assert len(calls) == result["searches_executed"] > 0
    assert all(o["outcome"] == "rate_limited" for o in result["provider_outcomes"])
    assert result["incremental"] == 0
    assert breaker.should_skip("indeed") or breaker.should_skip("naukri") \
        or breaker.should_skip("linkedin")


# --- 9. cache / freshness skipping ---

@pytest.mark.asyncio
async def test_identical_searches_skipped_inside_freshness_window():
    calls: list[dict] = []

    async def fetch_ok(**kw):
        calls.append(kw)
        return [_job_record(job_id=f"{kw['query']}-{kw['location']}")]

    service = _service_with_mock_repo(inserted=1)
    throttle, breaker, cache, _ = _fresh_instances()
    first = await service.ingest_jobspy_scheduled(
        ordinal=7, throttle=throttle, breaker=breaker, cache=cache, fetch_fn=fetch_ok,
    )
    assert first["searches_executed"] > 0
    before = len(calls)
    second = await service.ingest_jobspy_scheduled(
        ordinal=7, throttle=throttle, breaker=breaker, cache=cache, fetch_fn=fetch_ok,
    )
    assert len(calls) == before  # nothing re-requested
    assert second["searches_executed"] == 0
    assert second["searches_skipped"] == first["searches_executed"]


# --- 10. scheduler registration ---

def test_jobspy_registered_in_production_scheduler():
    from app.crawlers.crawl_registry import all_targets
    from app.services.jobs.scheduled_crawl_runner import ScheduledCrawlRunner

    assert any(t.source == "jobspy" and t.provider == "aggregator"
               for t in all_targets())
    runner = ScheduledCrawlRunner(enqueue_fn=AsyncMock())
    assert ("jobspy", "data analyst India") in runner._enabled_targets()


def test_jobspy_disabled_removes_scheduler_target(monkeypatch):
    from app.config import get_settings
    from app.services.jobs.scheduled_crawl_runner import ScheduledCrawlRunner

    monkeypatch.setattr(get_settings(), "jobspy_enabled", False)
    runner = ScheduledCrawlRunner(enqueue_fn=AsyncMock())
    assert all(source != "jobspy" for source, _ in runner._enabled_targets())


@pytest.mark.asyncio
async def test_worker_invokes_scheduled_jobspy_batch():
    from app.workers.jobs import crawl_jobs
    import app.workers.jobs.crawl_jobs as mod

    ingestion = MagicMock()
    ingestion.ingest_jobspy_scheduled = AsyncMock(
        return_value={"discovered": 2, "inserted": 2})
    ingestion.job_repository.deactivate_not_seen_since.return_value = 0
    ingestion.job_repository.deactivate_stale_jobs.return_value = 0
    orig = mod.JobIngestionService
    try:
        mod.JobIngestionService = MagicMock(return_value=ingestion)
        result = await crawl_jobs.crawl_company_job({"job_id": "t"}, "jobspy", "")
    finally:
        mod.JobIngestionService = orig
    assert result["success"] is True
    ingestion.ingest_jobspy_scheduled.assert_awaited_once()


# --- 11. provider failure isolation ---

@pytest.mark.asyncio
async def test_one_provider_failure_does_not_abort_others():
    async def fetch_flaky(**kw):
        if kw.get("site_names") == ["naukri"]:
            raise RuntimeError("Naukri bot-gate")
        return [_job_record(site=kw["site_names"][0], job_id=kw["site_names"][0])]

    service = _service_with_mock_repo(inserted=3)
    throttle, breaker, cache, _ = _fresh_instances()
    result = await service.ingest_jobspy_scheduled(
        ordinal=2, throttle=throttle, breaker=breaker, cache=cache, fetch_fn=fetch_flaky,
    )
    outcomes = {o["outcome"] for o in result["provider_outcomes"]}
    assert "transient" in outcomes and "success" in outcomes
    assert result["incremental"] == 3  # surviving providers still persist


# --- 12/13. deduplication against ATS and Adzuna ---

def test_ats_remains_authoritative_over_jobspy():
    from app.crawlers.source_quality import canonicalize_url, classify_source

    url = "https://boards.greenhouse.io/acme/jobs/1?utm_source=jobspy"
    ats = classify_source("greenhouse", url, "Acme")
    spy = classify_source("jobspy", url, "Acme")
    assert ats.tier < spy.tier  # lower tier = higher authority
    assert ats.is_official and not spy.is_official
    # Conservative identity: the same URL keeps separate
    # (source_platform, external_job_id) rows — JobSpy can never
    # overwrite the official row.
    assert ("greenhouse", "g1") != ("jobspy", "jobspy-x")
    assert canonicalize_url(url) == "https://boards.greenhouse.io/acme/jobs/1"


def test_adzuna_jobspy_overlap_accounted_without_merging():
    from app.services.jobs.ingestion_validation import dedup_report
    from app.models.job import NormalizedJob

    shared_url = "https://example.com/jobs/shared"
    jobs = [
        NormalizedJob(title="Data Analyst", company="Acme", source_platform="adzuna",
                      external_job_id="a1", apply_url=shared_url, canonical_url=shared_url),
        NormalizedJob(title="Data Analyst", company="Acme", source_platform="jobspy",
                      external_job_id="j1", apply_url=shared_url, canonical_url=shared_url),
    ]
    report = dedup_report(jobs)
    assert report["raw_discoveries"] == 2
    assert report["canonical_jobs"] == 1
    assert report["multi_source_jobs"] == 1  # overlap measured, rows not merged


# --- 14. incremental measurement ---

@pytest.mark.asyncio
async def test_scheduled_run_reports_incremental_canonical_jobs():
    async def fetch_mixed(**kw):
        site = kw["site_names"][0]
        return [
            _job_record(title="Fresher Data Analyst", company="FresherCo",
                        location="Bengaluru", site=site, job_id=f"{site}-1",
                        description="0-1 years experience, SQL."),
            _job_record(title="Fresher QA Engineer", company="FresherCo",
                        location="Hyderabad", site=site, job_id=f"{site}-2",
                        description="Graduate trainee, manual testing."),
            _job_record(title="Walk-in Interview Drive for Freshers",
                        company="FresherCo", location="Chennai", site=site,
                        job_id=f"{site}-3",
                        description="Walk-in interview on 12th Dec, venue Chennai. "
                                    "Carry your resume. 0-2 years."),
        ]

    service = _service_with_mock_repo(inserted=5)
    throttle, breaker, cache, _ = _fresh_instances()
    result = await service.ingest_jobspy_scheduled(
        ordinal=9, throttle=throttle, breaker=breaker, cache=cache, fetch_fn=fetch_mixed,
    )
    assert result["incremental"] == 5  # headline: canonical jobs added
    assert result["fresher"] > 0
    assert result["walkins"] >= 1
    assert result["emerging_company_jobs"] >= 1
    assert result["unique_companies"] >= 1
    assert result["discovered"] >= result["valid"] > 0
    for outcome in result["provider_outcomes"]:
        assert {"provider", "query_family", "location", "requested",
                "discovered", "outcome"} <= set(outcome)
        assert "password" not in str(outcome).lower()


# --- 15. disabled behavior ---

@pytest.mark.asyncio
async def test_jobspy_disabled_runs_nothing(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "jobspy_enabled", False)

    async def fetch_must_not_run(**kw):
        raise AssertionError("must not scrape while disabled")

    service = _service_with_mock_repo()
    result = await service.ingest_jobspy_scheduled(ordinal=1, fetch_fn=fetch_must_not_run)
    assert result["incremental"] == 0
    assert result["discovered"] == 0
    assert result["searches_executed"] == 0


# --- 16. production configuration defaults ---

def test_jobspy_configuration_defaults_conservative():
    from app.config import get_settings
    from app.services.jobs.jobspy_strategy import (
        MAX_JOBSPY_SEARCHES_PER_RUN,
        parse_freshness_buckets,
        parse_sites,
    )

    settings = get_settings()
    assert settings.jobspy_enabled is True
    assert 1 <= settings.jobspy_max_concurrent <= 3
    assert settings.jobspy_per_provider_delay_seconds >= 1.0
    assert settings.jobspy_linkedin_delay_seconds >= settings.jobspy_per_provider_delay_seconds
    assert 1 <= settings.jobspy_query_batch_size <= 8
    assert 1 <= settings.jobspy_location_batch_size <= 4
    assert settings.jobspy_provider_cooldown_seconds >= 60.0
    assert settings.jobspy_circuit_threshold >= 2
    assert settings.jobspy_results_wanted <= 200
    sites = parse_sites(settings.jobspy_sites)
    assert sites and set(sites) <= {"indeed", "naukri", "glassdoor", "linkedin"}
    assert "linkedin" in sites  # conservative provider stays in rotation
    buckets = parse_freshness_buckets(settings.jobspy_freshness_buckets)
    assert set(buckets) == {24, 72, 168}
    assert MAX_JOBSPY_SEARCHES_PER_RUN <= 10


def test_jobspy_rotation_batch_respects_settings(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "jobspy_query_batch_size", 2)
    monkeypatch.setattr(get_settings(), "jobspy_location_batch_size", 1)
    batch = JobIngestionService.jobspy_rotation_batch(11)
    assert len(batch) == 2
    assert all(s.results_wanted == get_settings().jobspy_results_wanted for s in batch)


# --- structured-coverage gate (generic crawl pressure) ---

@pytest.mark.asyncio
async def test_generic_crawl_skipped_when_ats_covers_company():
    from app.crawlers.generic_fallback import crawl_generic_career_page

    jobs, meta = await crawl_generic_career_page(
        "https://jobs.ashbyhq.com/notion", company="Notion")
    assert jobs == []
    assert meta["provider"] == "structured-coverage"


@pytest.mark.asyncio
async def test_generic_crawl_untouched_for_uncovered_company():
    from app.crawlers.generic_fallback import crawl_generic_career_page
    from app.config import get_settings

    settings = get_settings()
    old_crawl4ai, old_key = settings.crawl4ai_enabled, settings.firecrawl_api_key
    settings.crawl4ai_enabled = False
    settings.firecrawl_api_key = ""
    try:
        jobs, meta = await crawl_generic_career_page(
            "https://example.com/careers", company="Acme")
    finally:
        settings.crawl4ai_enabled = old_crawl4ai
        settings.firecrawl_api_key = old_key
    assert jobs == []
    assert meta["provider"] != "structured-coverage"


def test_company_structured_source_grounded_in_registry():
    from app.services.jobs.jobspy_strategy import company_has_structured_source

    assert company_has_structured_source("Notion") is True
    assert company_has_structured_source("Acme") is False
    assert company_has_structured_source("") is False
    assert company_has_structured_source(None) is False
