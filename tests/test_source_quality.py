"""Tests for source quality: tiers, official-domain verification, ATS detection."""

from __future__ import annotations

from app.crawlers.source_quality import (
    SOURCE_TIER_AGGREGATOR,
    SOURCE_TIER_OFFICIAL_ATS,
    SOURCE_TIER_OFFICIAL_COMPANY_CAREER,
    SOURCE_TIER_OTHER_VERIFIED_SOURCE,
    SOURCE_TIER_VERIFIED_YC_STARTUP,
    classify_source,
    company_domain_token,
    detect_ats_provider,
    is_aggregator_url,
    is_official_career_url,
    stable_hash,
)


def test_stable_hash_is_deterministic():
    assert stable_hash("https://x/jobs/1") == stable_hash("https://x/jobs/1")
    assert stable_hash("a") != stable_hash("b")


def test_detect_ats_provider_known_boards():
    assert detect_ats_provider("https://boards.greenhouse.io/stripe/jobs/1") == "greenhouse"
    assert detect_ats_provider("https://job-boards.greenhouse.io/acme/jobs/9") == "greenhouse"
    assert detect_ats_provider("https://jobs.lever.co/coupa/abc") == "lever"
    assert detect_ats_provider("https://jobs.ashbyhq.com/notion/role") == "ashby"
    assert detect_ats_provider("https://jobs.smartrecruiters.com/visa/1") == "smartrecruiters"
    assert detect_ats_provider("https://acme.wd3.myworkdayjobs.com/careers") == "workday"


def test_detect_ats_provider_unknown():
    assert detect_ats_provider("https://company.com/careers/x") is None
    assert detect_ats_provider(None) is None


def test_aggregators_never_official():
    for url in (
        "https://www.linkedin.com/jobs/view/123",
        "https://www.indeed.com/viewjob?jk=1",
        "https://www.glassdoor.com/job-listing/1",
        "https://www.naukri.com/job-listing-1",
        "https://www.ycombinator.com/jobs/abc",
    ):
        assert is_aggregator_url(url), url
        assert not is_official_career_url(url, "Stripe")


def test_official_career_url_detection():
    assert is_official_career_url("https://stripe.com/jobs/backend-engineer", "Stripe")
    assert is_official_career_url("https://jobs.stripe.com/backend-engineer", "Stripe Inc")
    # careers_url host match also verifies
    assert is_official_career_url(
        "https://acme.com/jobs/1", "Totally Different Name", careers_url="https://acme.com/careers"
    )
    # Unrelated domain is NOT official
    assert not is_official_career_url("https://randomsite.net/jobs/1", "Stripe")


def test_company_domain_token():
    assert company_domain_token("Stripe Inc") == "stripe"
    assert company_domain_token("Beta Labs") == "beta"


def test_classify_ycombinator_tiers():
    # Plain YC board listing -> tier 3
    p = classify_source("ycombinator", "https://www.ycombinator.com/jobs/abc", "Acme")
    assert p.tier == SOURCE_TIER_VERIFIED_YC_STARTUP
    # YC job pointing at the company ATS -> tier 2
    p = classify_source("ycombinator", "https://jobs.lever.co/acme/1", "Acme")
    assert p.tier == SOURCE_TIER_OFFICIAL_ATS
    # YC job pointing at the company's own domain -> tier 1
    p = classify_source("ycombinator", "https://acme.com/jobs/1", "Acme Corp")
    assert p.tier == SOURCE_TIER_OFFICIAL_COMPANY_CAREER


def test_classify_firecrawl_requires_domain_verification():
    # Official company domain -> tier 1
    p = classify_source("firecrawl", "https://stripe.com/jobs/1", "Stripe", careers_url="https://stripe.com/careers")
    assert p.tier == SOURCE_TIER_OFFICIAL_COMPANY_CAREER
    assert p.is_official and p.verified

    # Unverifiable third-party domain -> NOT official, low confidence
    p = classify_source("firecrawl", "https://randomjobs.net/jobs/1", "Stripe")
    assert p.tier == SOURCE_TIER_OTHER_VERIFIED_SOURCE
    assert not p.is_official and not p.verified and p.confidence < 0.5

    # Aggregator retrieved via Firecrawl -> aggregator tier
    p = classify_source("firecrawl", "https://www.indeed.com/viewjob?jk=1", "Stripe")
    assert p.tier == SOURCE_TIER_AGGREGATOR


def test_classify_ats_adapters_official():
    p = classify_source("greenhouse", "https://boards.greenhouse.io/stripe/jobs/1", "Stripe")
    assert p.tier == SOURCE_TIER_OFFICIAL_ATS
    assert p.provider == "greenhouse"
    p = classify_source("adzuna", "https://adzuna.com/jobs/1", "Acme")
    assert p.tier == SOURCE_TIER_AGGREGATOR


def test_classify_unknown_degrades_safely():
    p = classify_source("mystery", None, None)
    assert p.tier == SOURCE_TIER_OTHER_VERIFIED_SOURCE
    assert not p.is_official
