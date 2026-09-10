"""India company source audit: classification without fabrication.

Internal report data for the India company list. Every row states what is
actually configured in :mod:`app.crawlers.crawl_registry` or covered by the
shared Adzuna/JobSpy queries — never a guessed ATS slug or an unfetched
career page. Rows that could not be verified in this environment are marked
``unverified`` rather than assumed.

Source policy (see ``select_preferred_source``): official ATS/API first,
then the official career page, then existing aggregator coverage, then
Firecrawl retrieval, then no automated source. A company is never Firecrawled
when a better structured source already covers it.

Naukri through JobSpy is blocked (HTTP 406/reCAPTCHA) and stays unscheduled;
LinkedIn through JobSpy provides the long-tail. No per-company Naukri
scheduling exists, so no company row claims it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.jobs.source_priority import select_preferred_source

# Classification axis: best available automated source for the company.
# Task §3 vocabulary. OFFICIAL_CAREER_PAGE is the legacy alias for
# OFFICIAL_INDIA_CAREER_PAGE (kept so existing rows/tests keep working).
CLASSIFICATIONS = (
    "OFFICIAL_ATS",
    "OFFICIAL_INDIA_CAREER_PAGE",
    "OFFICIAL_GLOBAL_CAREER_PAGE_WITH_INDIA_FILTER",
    "OFFICIAL_CAREER_PAGE",
    "AGGREGATOR_COVERED",
    "MULTI_SOURCE",
    "NO_RELIABLE_AUTOMATION",
    "UNVERIFIED",
)

# Coverage axis: observed or strongly supported inventory level.
COVERAGE_LEVELS = ("GOOD", "PARTIAL", "POOR", "NONE", "UNVERIFIED")

# Provider audit axis (task §8): is the company already captured by an
# existing provider (Adzuna/JobSpy/ATS/Firecrawl) without a new source?
PROVIDER_COVERAGE_LEVELS = (
    "ALREADY_WELL_COVERED",
    "PARTIALLY_COVERED",
    "POORLY_COVERED",
    "NOT_COVERED",
    "UNVERIFIED",
)

# Status axis: the §18 decision per company.
STATUSES = ("already_covered", "implemented", "deferred", "blocked", "unverified")

# Classification -> source types available, for preferred-source derivation.
# New India-specific classifications sort above the legacy generic page
# (see source_priority order); MULTI_SOURCE keeps its legacy mapping so
# existing Firecrawl+aggregator rows still resolve to "career_page".
_CLASSIFICATION_SOURCE_TYPES: dict[str, tuple[str, ...]] = {
    "OFFICIAL_ATS": ("ats",),
    "OFFICIAL_INDIA_CAREER_PAGE": ("india_career_page",),
    "OFFICIAL_GLOBAL_CAREER_PAGE_WITH_INDIA_FILTER": ("global_with_india_filter",),
    "OFFICIAL_CAREER_PAGE": ("career_page",),
    "AGGREGATOR_COVERED": ("aggregator",),
    "MULTI_SOURCE": ("career_page", "aggregator"),
    "NO_RELIABLE_AUTOMATION": (),
    "UNVERIFIED": (),
}


def classify_provider_coverage(jobs_discovered: int | None, verified: bool = True) -> str:
    """Map an observed per-company job count to the §8 provider audit level.

    Thresholds mirror the validation company_coverage buckets: >=10 well
    covered, >=3 partial, >=1 poor, 0 not covered. Unverifiable counts
    (None or explicitly unverified) map to UNVERIFIED rather than a guess.
    """
    if jobs_discovered is None or not verified:
        return "UNVERIFIED"
    try:
        count = int(jobs_discovered)
    except (TypeError, ValueError):
        return "UNVERIFIED"
    if count >= 10:
        return "ALREADY_WELL_COVERED"
    if count >= 3:
        return "PARTIALLY_COVERED"
    if count >= 1:
        return "POORLY_COVERED"
    return "NOT_COVERED"


@dataclass(frozen=True)
class CompanyCoverage:
    """One audited company: classification, coverage, and the decision."""

    company: str
    classification: str
    coverage: str
    status: str
    provider: str  # firecrawl|ats|aggregator|none
    firecrawl_required: bool
    notes: str = ""

    @property
    def preferred_source(self) -> str | None:
        """Highest-priority automated source type, or None (no source)."""
        return select_preferred_source(
            _CLASSIFICATION_SOURCE_TYPES.get(self.classification, ())
        )


_ADZUNA_EXTRA = "Adzuna company-inclusive extra queries + broad rotation + JobSpy long-tail."
_BROAD_ONLY = (
    "Broad-query rotation + JobSpy long-tail only; "
    "official portal is unsupported (Workday/SuccessFactors-class) — no dedicated source."
)
_FIRECRAWL_CANDIDATE = (
    "Official career page is the only structured path; "
    "URL/inventory UNVERIFIED here — verify page + sample crawl before scheduling."
)
_FIRECRAWL_CONFIGURED = (
    "Firecrawl target configured in crawl_registry; live inventory UNVERIFIED in this environment."
)

INDIA_COMPANY_COVERAGE: list[CompanyCoverage] = [
    # -- Already covered: Firecrawl official pages in the registry --
    CompanyCoverage("Razorpay", "MULTI_SOURCE", "UNVERIFIED", "already_covered", "firecrawl", False, _FIRECRAWL_CONFIGURED),
    CompanyCoverage("PhonePe", "MULTI_SOURCE", "UNVERIFIED", "already_covered", "firecrawl", False, _FIRECRAWL_CONFIGURED),
    CompanyCoverage("CRED", "MULTI_SOURCE", "UNVERIFIED", "already_covered", "firecrawl", False, _FIRECRAWL_CONFIGURED),
    CompanyCoverage("Zerodha", "MULTI_SOURCE", "UNVERIFIED", "already_covered", "firecrawl", False, _FIRECRAWL_CONFIGURED),
    # -- Already covered: named Adzuna company-inclusive extras (aggregator-only by design) --
    CompanyCoverage("Accenture", "AGGREGATOR_COVERED", "PARTIAL", "already_covered", "aggregator", False, _ADZUNA_EXTRA),
    CompanyCoverage("JPMorgan Chase", "AGGREGATOR_COVERED", "PARTIAL", "already_covered", "aggregator", False, _ADZUNA_EXTRA),
    CompanyCoverage("IBM", "AGGREGATOR_COVERED", "PARTIAL", "already_covered", "aggregator", False, _ADZUNA_EXTRA),
    # -- Deferred: MNCs on unsupported portals, aggregator long-tail only --
    CompanyCoverage("TCS", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Infosys", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Wipro", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Cognizant", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Capgemini", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Deloitte", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("EY", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("PwC", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("KPMG", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Deutsche Bank", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Goldman Sachs", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("BlackRock", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("American Express", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Swiss Re", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Amazon", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Google", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Microsoft", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("SAP Labs India", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Oracle", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Salesforce", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Dell Technologies", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("HCLTech", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Tech Mahindra", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("LTIMindtree", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("Mu Sigma", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    CompanyCoverage("ZS Associates", "AGGREGATOR_COVERED", "POOR", "deferred", "aggregator", False, _BROAD_ONLY),
    # -- Unverified: startup/product official pages, Firecrawl candidates --
    CompanyCoverage("Zoho", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Freshworks", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Groww", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Upstox", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Swiggy", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Zomato", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Meesho", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Postman", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("BrowserStack", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Chargebee", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Innovaccer", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Hasura", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Sarvam AI", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Onyx", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Kipplo", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Qualifacts", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("V4c.ai", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Fractal Analytics", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Tredence", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("LatentView Analytics", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Gramener", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Sigmoid", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Affine Analytics", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
    CompanyCoverage("Course5 Intelligence", "UNVERIFIED", "UNVERIFIED", "unverified", "none", True, _FIRECRAWL_CANDIDATE),
]


def coverage_report() -> dict:
    """Aggregate the audit into counts + company lists (internal use, no API)."""
    by_status: dict[str, list[str]] = {}
    by_coverage: dict[str, list[str]] = {}
    firecrawl_candidates: list[str] = []
    for row in INDIA_COMPANY_COVERAGE:
        by_status.setdefault(row.status, []).append(row.company)
        by_coverage.setdefault(row.coverage, []).append(row.company)
        if row.firecrawl_required:
            firecrawl_candidates.append(row.company)
    return {
        "companies_audited": len(INDIA_COMPANY_COVERAGE),
        "by_status": {k: len(v) for k, v in by_status.items()},
        "by_coverage": {k: len(v) for k, v in by_coverage.items()},
        "firecrawl_candidates": firecrawl_candidates,
        "already_covered": sorted(by_status.get("already_covered", [])),
        "deferred": sorted(by_status.get("deferred", [])),
        "unverified": sorted(by_status.get("unverified", [])),
    }
