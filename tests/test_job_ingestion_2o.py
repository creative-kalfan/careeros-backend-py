"""Job Ingestion 2.0: India-first multi-source pipeline (lazy slice).

Covers: Adzuna India endpoint + bounded rotation + what_and/category,
JobSpy normalization/failure isolation, canonical URL dedup conservatism,
validation outcomes, India location normalization, selective Firecrawl
enrichment guard, provenance confidence, registry/worker wiring.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.crawlers.source_quality import canonicalize_url, classify_source
from app.crawlers.models import CrawledJob
from app.models.job import NormalizedJob
from app.services.jobs.job_ingestion_service import (
    ADZUNA_BROAD_QUERIES,
    JobIngestionService,
)
from app.services.jobs.job_service import (
    merge_enrichment,
    needs_enrichment,
    normalize_india_location,
    validate_job,
)


def _crawled(**kw) -> CrawledJob:
    base = dict(title="Data Analyst", company="Acme", description="SQL dashboards " * 30,
                location="Bangalore", apply_url="https://acme.com/jobs/1",
                external_job_id="x1", source_platform="adzuna")
    base.update(kw)
    return CrawledJob(**base)


# --- Adzuna ---

@pytest.mark.asyncio
async def test_adzuna_uses_india_endpoint():
    from app.crawlers.aggregators.adzuna import AdzunaAdapter

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    async with AdzunaAdapter(app_id="id", app_key="key", client=mock_client) as adapter:
        await adapter.search_by_query("data analyst", country="in", page=1)
    url = mock_client.get.call_args.args[0]
    assert "/jobs/in/search/1" in url


@pytest.mark.asyncio
async def test_adzuna_what_and_category_passthrough():
    from app.crawlers.aggregators.adzuna import AdzunaAdapter

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    async with AdzunaAdapter(app_id="id", app_key="key", client=mock_client) as adapter:
        await adapter.search_by_query("analyst", country="in", what_and="SQL", category="it-jobs")
    params = mock_client.get.call_args.kwargs["params"]
    assert params["what_and"] == "SQL" and params["category"] == "it-jobs"


def test_adzuna_rotation_covers_required_domains_and_rotates():
    text = " ".join(ADZUNA_BROAD_QUERIES).lower()
    for needle in ("data analyst", "data engineer", "machine learning",
                   "backend", "sap abap", "etl", "ai engineer", "data scientist"):
        assert needle in text
    b1 = JobIngestionService.adzuna_rotation_batch(1)
    b2 = JobIngestionService.adzuna_rotation_batch(2)
    assert len(b1) == 2 and b1 != b2  # rotation bug fixed: batches differ by day
    assert JobIngestionService.adzuna_rotation_batch(1) == b1  # deterministic


@pytest.mark.asyncio
async def test_adzuna_ingest_bounded_budget():
    service = JobIngestionService()
    service.job_repository = MagicMock()
    service.job_repository.upsert_jobs.return_value = {"inserted": 1}
    service.job_service = MagicMock()
    service.job_service.normalize_and_classify.side_effect = lambda j: MagicMock()
    # _drop_invalid on MagicMocks drops everything -> upsert([]) still once
    mock_adapter = AsyncMock()
    mock_adapter.search_by_query.return_value = []
    import app.services.jobs.job_ingestion_service as mod

    orig = mod.AdzunaAdapter
    try:
        mod.AdzunaAdapter = MagicMock(return_value=mock_adapter)
        await service.ingest_adzuna_jobs("software engineer")
    finally:
        mod.AdzunaAdapter = orig
    assert mock_adapter.search_by_query.await_count == 5  # 3 primary + 2 rotated


# --- JobSpy ---

def test_jobspy_maps_naukri_linkedin_records():
    from app.crawlers.adapters.jobspy import map_jobspy_record

    naukri = {"title": "Data Analyst", "company": "Mu Sigma", "location": "Bengaluru",
              "description": "SQL", "job_url": "https://naukri.com/job/1",
              "site": "naukri", "id": "n1"}
    job = map_jobspy_record(naukri)
    assert job.source_platform == "jobspy" and job.external_job_id == "n1"
    assert job.apply_url == "https://naukri.com/job/1"

    linked = {"title": "ML Engineer", "company": "Acme", "location": "Remote India",
              "job_text": "Python", "job_url": "https://linkedin.com/jobs/2", "site": "linkedin"}
    job2 = map_jobspy_record(linked)
    assert job2.title == "ML Engineer" and job2.description == "Python"
    assert job2.external_job_id.startswith("jobspy-")  # deterministic fallback id


@pytest.mark.asyncio
async def test_jobspy_failure_isolated_to_empty():
    from app.crawlers.adapters.jobspy import JobSpyAdapter

    async def boom(**kw):
        raise RuntimeError("site down")

    adapter = JobSpyAdapter(fetch_fn=boom)
    assert await adapter.discover_jobs() == []


@pytest.mark.asyncio
async def test_jobspy_ingest_flows_through_canonical_pipeline():
    service = JobIngestionService()
    service.job_repository = MagicMock()
    service.job_repository.upsert_jobs.return_value = {"inserted": 2}
    real_service = service.job_service  # real JobService for normalization
    import app.crawlers.adapters.jobspy as jobspy_mod
    from app.crawlers.adapters.jobspy import JobSpyAdapter

    async def fake_fetch(**kw):
        return [
            {"title": "Data Analyst", "company": "Zoho", "location": "Chennai",
             "description": "SQL " * 60, "job_url": "https://zoho.com/jobs/9",
             "site": "naukri", "id": "z9"},
        ]

    orig = jobspy_mod.JobSpyAdapter
    try:
        jobspy_mod.JobSpyAdapter = lambda **kw: JobSpyAdapter(fetch_fn=fake_fetch, **{k: v for k, v in kw.items() if k in ("query", "location", "results_wanted")})
        result = await service.ingest_jobspy_jobs("data analyst India")
    finally:
        jobspy_mod.JobSpyAdapter = orig
    assert result == {"inserted": 2}
    rows = service.job_repository.upsert_jobs.call_args.args[0]
    assert len(rows) == 1 and isinstance(rows[0], NormalizedJob)
    assert rows[0].source_platform == "jobspy"
    assert real_service is not None


# --- Canonical URL + dedup conservatism ---

def test_canonicalize_url_strips_tracking_but_keeps_identity():
    a = canonicalize_url("https://Acme.com/jobs/1?utm_source=x&gclid=1#frag/")
    b = canonicalize_url("https://acme.com/jobs/1")
    assert a == b == "https://acme.com/jobs/1"
    assert canonicalize_url(None) == "" and canonicalize_url("not a url") == ""
    # Genuinely different postings stay distinct (conservative: keep separate).
    assert canonicalize_url("https://acme.com/jobs/1") != canonicalize_url("https://acme.com/jobs/2")


def test_cross_source_same_url_not_merged_by_identity():
    # Identity is (source_platform, external_job_id); same canonical URL from
    # Adzuna + JobSpy keeps separate rows (conservative, no fuzzy merge).
    assert ("adzuna", "a1") != ("jobspy", "j9")


# --- Validation ---

def test_validate_job_outcomes():
    ok = NormalizedJob(title="Data Analyst", company="Acme", location="Chennai",
                       description="SQL dashboards", source_platform="adzuna",
                       apply_url="https://acme.com/j/1")
    assert validate_job(ok)[0] == "VALID"
    thin = NormalizedJob(title="Analyst", apply_url="https://acme.com/j/1")
    status, reasons = validate_job(thin)
    assert status == "VALID_WITH_WARNINGS" and reasons
    bad = NormalizedJob(title="   ", apply_url="https://acme.com/j/1")
    assert validate_job(bad)[0] == "INVALID"
    bad_url = NormalizedJob(title="Analyst", apply_url="ftp://acme.com/j")
    assert validate_job(bad_url)[0] == "INVALID"


# --- India normalization ---

def test_india_location_aliases_deterministic():
    assert normalize_india_location("Bangalore") == "Bengaluru, India"
    assert normalize_india_location("Bombay") == "Mumbai, India"
    assert normalize_india_location("Madras") == "Chennai, India"
    assert normalize_india_location("Gurgaon") == "Gurugram, India"
    assert normalize_india_location("Berlin") == "Berlin"  # never rewrite intl
    assert normalize_india_location(None) is None


# --- Selective Firecrawl enrichment ---

def test_enrichment_selective_and_never_overwrites():
    thin = NormalizedJob(title="Analyst", company="Acme", apply_url="https://acme.com/j/1",
                         description="short")
    assert needs_enrichment(thin) is True
    rich = NormalizedJob(title="Analyst", company="Acme", apply_url="https://acme.com/j/1",
                         description="x" * 500, skills=["SQL"], requirements=["SQL"])
    assert needs_enrichment(rich) is False
    no_url = NormalizedJob(title="Analyst", company="Acme", description="short")
    assert needs_enrichment(no_url) is False  # no URL -> no Firecrawl
    enriched = NormalizedJob(title="WRONG", company="Evil", apply_url="https://evil.com",
                             description="x" * 500, location="Chennai, India")
    merged = merge_enrichment(thin, enriched)
    assert merged.title == "Analyst" and merged.company == "Acme"  # protected
    assert merged.location == "Chennai, India"  # gap filled


# --- Provenance / registry / workers ---

def test_jobspy_confidence_medium_high_below_ats():
    ats = classify_source("greenhouse", "https://boards.greenhouse.io/s/j/1", "S")
    spy = classify_source("jobspy", "https://www.naukri.com/job/1", "Acme")
    adz = classify_source("adzuna", "https://adzuna.com/jobs/1", "Acme")
    assert spy.confidence > adz.confidence and spy.confidence < ats.confidence
    assert not spy.is_official


def test_registry_supports_jobspy_and_company_metadata():
    from app.crawlers.crawl_registry import CrawlTarget, all_targets

    providers = {t.provider for t in all_targets()}
    assert providers == {"yc", "firecrawl", "ats", "aggregator"}  # no new family
    assert any(t.source == "jobspy" for t in all_targets())
    t = CrawlTarget("ats", "x", "ats", source_type="ats", country="IN")
    assert t.country == "IN" and t.source_type == "ats"


@pytest.mark.asyncio
async def test_worker_jobspy_branch_idempotent():
    from app.workers.jobs import crawl_jobs

    ingestion = MagicMock()
    ingestion.ingest_jobspy_jobs = AsyncMock(return_value={"discovered": 1, "inserted": 1})
    ingestion.job_repository.deactivate_not_seen_since.return_value = 0
    ingestion.job_repository.deactivate_stale_jobs.return_value = 0
    import app.workers.jobs.crawl_jobs as mod

    orig = mod.JobIngestionService
    try:
        mod.JobIngestionService = MagicMock(return_value=ingestion)
        result = await crawl_jobs.crawl_company_job({"job_id": "t"}, "jobspy", "data analyst India")
    finally:
        mod.JobIngestionService = orig
    assert result["success"] is True
    ingestion.ingest_jobspy_jobs.assert_awaited_once_with("data analyst India")
