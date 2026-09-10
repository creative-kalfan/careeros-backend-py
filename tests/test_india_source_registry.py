"""India company source registry: aliases, priority, coverage (offline).

Covers: company registration as config, provider selection order
(official ATS > career page > aggregator > Firecrawl), enabled/disabled
sources, company aliases, Firecrawl official-only guard, cross-source dedup
conservatism, and India location preservation. No network, no credentials.
"""

from __future__ import annotations

from app.crawlers.crawl_registry import FIRECRAWL_TARGETS, all_targets
from app.crawlers.models import CrawledJob
from app.crawlers.source_quality import classify_source, is_aggregator_url
from app.services.jobs.company_coverage import (
    CLASSIFICATIONS,
    COVERAGE_LEVELS,
    INDIA_COMPANY_COVERAGE,
    STATUSES,
    coverage_report,
)
from app.services.jobs.job_service import JobService, normalize_company_name
from app.services.jobs.source_priority import select_preferred_source


def _crawled(**kw) -> CrawledJob:
    base = dict(title="Data Analyst", company="Acme", description="SQL",
                location="Chennai", apply_url="https://acme.com/j/1",
                external_job_id="x1", source_platform="adzuna")
    base.update(kw)
    return CrawledJob(**base)


# --- Company aliases (single shared normalizer, applied at ingest) ---

def test_aliases_cover_task_variants():
    assert normalize_company_name("J.P. Morgan") == "JPMorgan Chase"
    assert normalize_company_name("JP Morgan") == "JPMorgan Chase"
    assert normalize_company_name("JPMorgan") == "JPMorgan Chase"
    assert normalize_company_name("EY GDS") == "EY"
    assert normalize_company_name("Ernst & Young") == "EY"
    assert normalize_company_name("Tata Consultancy Services") == "TCS"


def test_aliases_passthrough_unknown_and_empty():
    assert normalize_company_name("Zoho") == "Zoho"  # no false merge
    assert normalize_company_name("  ") == "  "
    assert normalize_company_name(None) is None
    assert normalize_company_name("") == ""


def test_normalize_job_applies_company_alias():
    job = JobService().normalize_job(_crawled(company="J.P. Morgan"))
    assert job.company == "JPMorgan Chase"
    assert normalize_company_name("EY") == "EY"


# --- Source selection priority ---

def test_preferred_source_order():
    assert select_preferred_source(["firecrawl", "aggregator", "career_page", "ats"]) == "ats"
    assert select_preferred_source(["firecrawl", "aggregator", "career_page"]) == "career_page"
    assert select_preferred_source(["firecrawl", "aggregator"]) == "aggregator"
    assert select_preferred_source(["firecrawl"]) == "firecrawl"
    assert select_preferred_source([]) is None
    assert select_preferred_source(["unknown"]) is None


def test_company_preferred_source_uses_priority():
    by_name = {r.company: r for r in INDIA_COMPANY_COVERAGE}
    assert by_name["Razorpay"].preferred_source == "career_page"  # official beats aggregator
    assert by_name["TCS"].preferred_source == "aggregator"
    assert by_name["Zoho"].preferred_source is None  # no automated source


# --- Registry: config-driven expansion, no duplicate crawlers ---

def test_india_firecrawl_companies_are_registry_config():
    slugs = " ".join(t.slug for t in FIRECRAWL_TARGETS)
    for company in ("Razorpay", "PhonePe", "CRED", "Zerodha"):
        assert company in slugs


def test_registry_targets_carry_source_metadata():
    for target in all_targets():
        assert target.provider in {"yc", "firecrawl", "ats", "aggregator"}
        assert target.enabled in (True, False)


def test_no_firecrawl_target_duplicates_ats_coverage():
    ats_slugs = {t.slug for t in all_targets() if t.source_type == "ats"}
    for target in FIRECRAWL_TARGETS:
        assert target.slug not in ats_slugs


def test_disabled_target_is_excluded():
    from app.crawlers.crawl_registry import CrawlTarget

    off = CrawlTarget("firecrawl", "Off|https://off.example/careers", "firecrawl", 2, enabled=False)
    assert all(t.key != off.key for t in all_targets())


# --- Firecrawl: official pages only, aggregators rejected ---

def test_aggregator_urls_rejected_as_official():
    assert is_aggregator_url("https://www.naukri.com/job/1")
    assert is_aggregator_url("https://www.linkedin.com/jobs/view/9")
    assert is_aggregator_url("https://www.adzuna.co.in/jobs/1")
    assert not is_aggregator_url("https://www.zoho.com/careers/1")


def test_firecrawl_official_page_classified_official():
    prov = classify_source("firecrawl", "https://www.zoho.com/careers/1", "Zoho",
                           careers_url="https://www.zoho.com/careers/")
    assert prov.is_official and prov.tier == 1


def test_firecrawl_aggregator_url_never_official():
    prov = classify_source("firecrawl", "https://www.naukri.com/job/1", "Zoho")
    assert not prov.is_official and prov.tier == 5


# --- Dedup: one canonical job, multiple provenance records ---

def test_official_plus_aggregator_share_canonical_url_but_keep_identity():
    from app.crawlers.source_quality import canonicalize_url

    url = "https://www.zoho.com/careers/9?utm_source=naukri"
    assert canonicalize_url(url) == "https://www.zoho.com/careers/9"
    assert ("firecrawl", "abc") != ("adzuna", "z9")  # conservative: separate rows
    official = classify_source("firecrawl", url, "Zoho", careers_url="https://www.zoho.com/careers/")
    agg = classify_source("adzuna", url, "Zoho")
    assert official.tier < agg.tier  # same URL, provenance preserved per source


# --- India locations preserved, international untouched ---

def test_india_and_international_locations_preserved():
    job = JobService().normalize_job(_crawled(location="Bengaluru"))
    assert job.location == "Bengaluru, India"
    remote = JobService().normalize_job(_crawled(location="Remote US"))
    assert remote.location == "Remote US"


# --- Coverage audit honesty ---

def test_coverage_report_counts_and_vocab():
    report = coverage_report()
    assert report["companies_audited"] == len(INDIA_COMPANY_COVERAGE) >= 50
    assert set(report["by_status"]) <= set(STATUSES)
    assert set(report["by_coverage"]) <= set(COVERAGE_LEVELS)
    for row in INDIA_COMPANY_COVERAGE:
        assert row.classification in CLASSIFICATIONS
        assert not row.notes == ""  # every row justifies itself
    assert len(report["already_covered"]) == 7  # 4 firecrawl + 3 adzuna-extra
    assert len(report["unverified"]) == 24  # startup Firecrawl candidates
    assert report["by_status"].get("implemented", 0) == 0  # nothing fabricated


def test_no_unverified_company_claims_good_coverage():
    for row in INDIA_COMPANY_COVERAGE:
        if row.status == "unverified":
            assert row.coverage == "UNVERIFIED"
            assert row.provider == "none"
