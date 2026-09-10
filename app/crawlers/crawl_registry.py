"""Crawl target registry: the single configuration point for ingestion targets.

Each target describes ONE crawlable source endpoint. Adding a company means
adding a registry entry — never a new crawler implementation. The registry is
consumed by :mod:`app.services.jobs.scheduled_crawl_runner` (scheduling) and
``app.workers.jobs.crawl_jobs`` (execution).

Priority policy (drives enqueue ordering only; ranking is handled by
``app.services.jobs.source_priority``):

    1. YC startup board            (provider: ycombinator)
    2. Firecrawl official careers  (provider: firecrawl)
    3. Direct official ATS boards  (provider: ashby/greenhouse/lever/smartrecruiters)
    4. Aggregators                 (provider: adzuna)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class CrawlTarget:
    """One crawlable source endpoint.

    India-first registry fields (task §14): adding a company is
    configuration — set ``company``/``url``/``india_only``/``india_filter``
    plus coverage metadata. All new fields are optional so existing
    positional construction keeps working.
    """

    source: str  # adapter key: ycombinator|firecrawl|ashby|greenhouse|lever|smartrecruiters|adzuna|jobspy
    slug: str  # adapter payload (adzuna/jobspy: search query; firecrawl: "<company>|<careers_url>")
    provider: str  # provider family: yc|firecrawl|ats|aggregator
    priority: int = 50  # lower = higher priority (enqueue order)
    enabled: bool = True
    notes: str = ""
    # Company source registry metadata (all optional; defaults keep existing
    # positional construction working). ATS/API sources are preferred over
    # Firecrawl; aggregators (Adzuna/JobSpy) cover the long tail.
    country: str = "IN"
    region: str = ""
    source_type: str = ""  # ats|api|india_career_page|career_page|global_with_india_filter|aggregator|firecrawl
    crawl_frequency_hours: Optional[float] = None
    firecrawl_enabled: bool = False
    enrichment_enabled: bool = False
    metadata: Optional[dict] = field(default=None)
    # India-first discovery fields (§14): company identity, aliases, official
    # URL, India scoping, and audit coverage. Defaults preserve behaviour.
    company: str = ""
    aliases: tuple[str, ...] = ()
    url: str = ""
    india_only: bool = False
    india_filter: str = ""
    coverage_status: str = ""
    coverage_score: Optional[float] = None

    @property
    def key(self) -> str:
        return f"{self.source}:{self.slug}"

    @property
    def company_name(self) -> str:
        """Best-known company label (explicit field, else Firecrawl slug head)."""
        if self.company:
            return self.company
        if self.source == "firecrawl" and "|" in self.slug:
            return self.slug.split("|", 1)[0].strip()
        return ""

    @property
    def careers_url(self) -> str:
        """Best-known official careers URL (explicit field, else slug tail)."""
        if self.url:
            return self.url
        if self.source == "firecrawl" and "|" in self.slug:
            return self.slug.split("|", 1)[1].strip()
        return ""


# ---------------------------------------------------------------------------
# Priority 1: YC Work at a Startup (recurring, high priority)
# ---------------------------------------------------------------------------
YC_TARGET = CrawlTarget(
    source="ycombinator",
    slug="",
    provider="yc",
    priority=1,
    notes="YC Work at a Startup board; single recurring target.",
)

# ---------------------------------------------------------------------------
# Priority 2: Firecrawl official company career pages.
# Slug format: "<company>|<careers_url>". Add new companies here — no new
# crawler code is required; the FirecrawlAdapter handles any careers URL.
# ---------------------------------------------------------------------------
FIRECRAWL_TARGETS: list[CrawlTarget] = [
    CrawlTarget("firecrawl", "PostHog|https://posthog.com/careers", "firecrawl", 2, source_type="firecrawl", firecrawl_enabled=True,
                company="PostHog", url="https://posthog.com/careers", india_filter="India"),
    CrawlTarget("firecrawl", "Linear|https://linear.app/careers", "firecrawl", 2, source_type="firecrawl", firecrawl_enabled=True,
                company="Linear", url="https://linear.app/careers", india_filter="India"),
    CrawlTarget("firecrawl", "Razorpay|https://razorpay.com/jobs/", "firecrawl", 2, source_type="firecrawl", firecrawl_enabled=True,
                company="Razorpay", url="https://razorpay.com/jobs/", country="IN", india_only=True, india_filter="India"),
    CrawlTarget("firecrawl", "PhonePe|https://www.phonepe.com/careers/job-openings/", "firecrawl", 2, source_type="firecrawl", firecrawl_enabled=True,
                company="PhonePe", url="https://www.phonepe.com/careers/job-openings/", country="IN", india_only=True, india_filter="India"),
    CrawlTarget("firecrawl", "CRED|https://careers.cred.club/", "firecrawl", 2, source_type="firecrawl", firecrawl_enabled=True,
                company="CRED", url="https://careers.cred.club/", country="IN", india_only=True, india_filter="India"),
    CrawlTarget("firecrawl", "Zerodha|https://zerodha.com/careers", "firecrawl", 2, source_type="firecrawl", firecrawl_enabled=True,
                company="Zerodha", url="https://zerodha.com/careers", country="IN", india_only=True, india_filter="India"),
]

# ---------------------------------------------------------------------------
# Priority 3: Direct official ATS boards.
# ---------------------------------------------------------------------------
ATS_TARGETS: list[CrawlTarget] = [
    CrawlTarget("ashby", "notion", "ats", 3, source_type="ats", company="Notion", india_filter="India"),
    CrawlTarget("greenhouse", "stripe", "ats", 3, source_type="ats", company="Stripe", india_filter="India"),
    CrawlTarget("smartrecruiters", "servicenow", "ats", 3, source_type="ats", company="ServiceNow", india_filter="India"),
    CrawlTarget("lever", "coupa", "ats", 3, source_type="ats", company="Coupa", india_filter="India"),
    CrawlTarget("smartrecruiters", "visa", "ats", 3, source_type="ats", company="Visa", india_filter="India"),
]

# ---------------------------------------------------------------------------
# Priority 4: Aggregator (least frequent).
# ---------------------------------------------------------------------------
AGGREGATOR_TARGETS: list[CrawlTarget] = [
    CrawlTarget("adzuna", "software engineer", "aggregator", 4,
                notes="Slug is the primary search query; adapter rotates India-first queries.",
                source_type="aggregator"),
    # JobSpy (Naukri/LinkedIn coverage) shares the aggregator cadence so the
    # provider set stays {yc, firecrawl, ats, aggregator}. Bounded single
    # query; broader coverage comes from the Adzuna rotation + ATS boards.
    CrawlTarget("jobspy", "data analyst India", "aggregator", 4,
                notes="JobSpy Naukri/LinkedIn discovery; optional dep (python-jobspy).",
                source_type="aggregator"),
]


def all_targets() -> list[CrawlTarget]:
    """All registered targets, ordered by priority."""
    targets = [YC_TARGET, *FIRECRAWL_TARGETS, *ATS_TARGETS, *AGGREGATOR_TARGETS]
    return sorted([t for t in targets if t.enabled], key=lambda t: t.priority)


def targets_for_provider(provider: str) -> list[CrawlTarget]:
    """All enabled targets for one provider family, priority-ordered."""
    return [t for t in all_targets() if t.provider == provider]


# Backwards-compatible view used by earlier code/tests: list of (source, slug).
CRAWL_TARGETS: list[tuple[str, str]] = [(t.source, t.slug) for t in all_targets()]
