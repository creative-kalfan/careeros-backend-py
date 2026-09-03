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
    """One crawlable source endpoint."""

    source: str  # adapter key: ycombinator|firecrawl|ashby|greenhouse|lever|smartrecruiters|adzuna
    slug: str  # adapter payload (adzuna: search query; firecrawl: "<company>|<careers_url>")
    provider: str  # provider family: yc|firecrawl|ats|aggregator
    priority: int = 50  # lower = higher priority (enqueue order)
    enabled: bool = True
    notes: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.slug}"


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
    CrawlTarget("firecrawl", "PostHog|https://posthog.com/careers", "firecrawl", 2),
    CrawlTarget("firecrawl", "Linear|https://linear.app/careers", "firecrawl", 2),
    CrawlTarget("firecrawl", "Razorpay|https://razorpay.com/jobs/", "firecrawl", 2),
    CrawlTarget("firecrawl", "PhonePe|https://www.phonepe.com/careers/job-openings/", "firecrawl", 2),
    CrawlTarget("firecrawl", "CRED|https://careers.cred.club/", "firecrawl", 2),
    CrawlTarget("firecrawl", "Zerodha|https://zerodha.com/careers", "firecrawl", 2),
]

# ---------------------------------------------------------------------------
# Priority 3: Direct official ATS boards.
# ---------------------------------------------------------------------------
ATS_TARGETS: list[CrawlTarget] = [
    CrawlTarget("ashby", "notion", "ats", 3),
    CrawlTarget("greenhouse", "stripe", "ats", 3),
    CrawlTarget("smartrecruiters", "servicenow", "ats", 3),
    CrawlTarget("lever", "coupa", "ats", 3),
    CrawlTarget("smartrecruiters", "visa", "ats", 3),
]

# ---------------------------------------------------------------------------
# Priority 4: Aggregator (least frequent).
# ---------------------------------------------------------------------------
AGGREGATOR_TARGETS: list[CrawlTarget] = [
    CrawlTarget("adzuna", "software engineer", "aggregator", 4,
                notes="Slug is the primary search query; adapter rotates India-first queries."),
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
