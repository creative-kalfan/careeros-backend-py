"""Ingestion validation metrics (mocked providers; no live API)."""

from __future__ import annotations

import pytest

from app.crawlers.models import CrawledJob
from app.models.job import NormalizedJob
from app.services.jobs.ingestion_validation import (
    MAX_FIRECRAWL_CALLS,
    MAX_PAGES_PER_QUERY,
    MAX_QUERIES,
    ValidationLimits,
    company_coverage,
    dedup_report,
    dry_run_provider,
    firecrawl_report,
    role_coverage,
    source_report,
    summarize_jobs,
)
from app.services.jobs.job_service import merge_enrichment


def _norm(**kw) -> NormalizedJob:
    base = dict(title="Data Analyst", company="Acme", location="Bengaluru, India",
                description="SQL dashboards " * 30, source_platform="adzuna",
                apply_url="https://acme.com/jobs/1", canonical_url="https://acme.com/jobs/1",
                external_job_id="a1")
    base.update(kw)
    return NormalizedJob(**base)


def test_limits_clamped_to_hard_maxima():
    lim = ValidationLimits(max_queries=99, max_pages_per_query=99,
                           results_per_query=9999, max_firecrawl_calls=9999)
    assert lim.max_queries == MAX_QUERIES
    assert lim.max_pages_per_query == MAX_PAGES_PER_QUERY
    assert lim.results_per_query <= 50
    assert lim.max_firecrawl_calls == MAX_FIRECRAWL_CALLS


def test_summarize_counts_and_india_relevance():
    jobs = [_norm(), _norm(title="   "), _norm(location="Berlin", canonical_url="https://acme.com/jobs/2",
              apply_url="https://acme.com/jobs/2", external_job_id="a2")]
    s = summarize_jobs(jobs)
    assert s["raw"] == 3 and s["invalid"] == 1 and s["india_relevant"] == 2
    assert s["unique_canonical"] == 2


def test_dedup_conservative_no_fuzzy_merge():
    jobs = [_norm(), _norm(source_platform="jobspy", external_job_id="j9"),  # same URL, 2 sources
            _norm(canonical_url=None, apply_url=None, url=None, external_job_id="x1", source_platform="adzuna")]
    d = dedup_report(jobs)
    assert d == {"raw_discoveries": 3, "canonical_jobs": 2, "duplicate_discoveries": 1,
                 "duplicate_pct": 33.3, "multi_source_jobs": 1, "single_source_jobs": 1}


def test_firecrawl_selective_and_gain():
    thin = _norm(description="short")
    rich = _norm(description="x" * 500, skills=["SQL"], requirements=["SQL"],
                 canonical_url="https://acme.com/jobs/9", apply_url="https://acme.com/jobs/9")
    r = firecrawl_report([thin, rich])
    assert r["requiring_enrichment"] == 1 and r["skipped_sufficient"] == 1
    from app.services.jobs.ingestion_validation import enrichment_gain
    thin_empty = _norm(description="short", location=None)
    enriched = _norm(description="x" * 500, location="Chennai, India", title="WRONG")
    assert enrichment_gain(thin_empty, merge_enrichment(thin_empty, enriched)) >= 1
    assert merge_enrichment(thin, enriched).title == "Data Analyst"  # protected


def test_role_and_company_coverage():
    jobs = [_norm(title="Data Analyst"), _norm(title="SAP ABAP Developer"), _norm(title="Janitor")]
    roles = role_coverage(jobs)
    assert roles["analytics"] == 1 and roles["sap"] == 1 and roles["other"] == 1
    cov = company_coverage(["Acme", "Infosys"], jobs)
    assert cov["Acme"]["coverage"] == "PARTIAL_COVERAGE" and cov["Infosys"]["coverage"] == "NO_COVERAGE"


def test_source_report_reuses_confidence():
    jobs = [_norm(source_confidence=0.9), _norm(source_confidence=0.7)]
    rep = source_report({"adzuna": jobs})
    assert rep["adzuna"]["raw"] == 2 and rep["adzuna"]["confidence"] == 0.8


async def test_dry_run_bounded_never_persists():
    async def fake_fetch(query, page, per_page):
        return [CrawledJob(title="Data Analyst", company="Acme", description="SQL " * 60,
                           location="Bangalore", apply_url=f"https://acme.com/{query}/{page}/{i}",
                           external_job_id=f"{page}-{i}", source_platform="adzuna")
                for i in range(per_page + 50)]  # oversupply must be clamped

    lim = ValidationLimits(max_queries=1, results_per_query=5)
    out = await dry_run_provider("adzuna", ["q1", "q2", "q3"], lim, fetch_fn=fake_fetch)
    assert out["dry_run"] is True and out["persisted"] is False
    assert out["queries_executed"] == 1 and len(out["jobs"]) == 5


async def test_dry_run_isolates_fetch_errors():
    async def boom(query, page, per_page):
        raise RuntimeError("provider down")

    out = await dry_run_provider("adzuna", ["q1"], ValidationLimits(), fetch_fn=boom)
    assert out["raw"] == 0 and out["errors"] == ["RuntimeError"]
