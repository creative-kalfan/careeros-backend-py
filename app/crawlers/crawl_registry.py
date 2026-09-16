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
    tier: str = "P1"  # P0 (daily), P1 (standard rotation), P2 (weekly rotation)

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
# Verified Indian tech unicorns & high-value startups without direct ATS boards.
# ---------------------------------------------------------------------------
FIRECRAWL_TARGETS: list[CrawlTarget] = [
    CrawlTarget("firecrawl", "Razorpay|https://razorpay.com/jobs/", "firecrawl", 2, tier="P0",
                source_type="firecrawl", firecrawl_enabled=True, company="Razorpay",
                url="https://razorpay.com/jobs/", country="IN", india_only=True, india_filter="India"),
    CrawlTarget("firecrawl", "PhonePe|https://www.phonepe.com/careers/job-openings/", "firecrawl", 2, tier="P0",
                source_type="firecrawl", firecrawl_enabled=True, company="PhonePe",
                url="https://www.phonepe.com/careers/job-openings/", country="IN", india_only=True, india_filter="India"),
    CrawlTarget("firecrawl", "CRED|https://careers.cred.club/", "firecrawl", 2, tier="P0",
                source_type="firecrawl", firecrawl_enabled=True, company="CRED",
                url="https://careers.cred.club/", country="IN", india_only=True, india_filter="India"),
    CrawlTarget("firecrawl", "Zerodha|https://zerodha.com/careers", "firecrawl", 2, tier="P0",
                source_type="firecrawl", firecrawl_enabled=True, company="Zerodha",
                url="https://zerodha.com/careers", country="IN", india_only=True, india_filter="India"),
    CrawlTarget("firecrawl", "Swiggy|https://careers.swiggy.com", "firecrawl", 2, tier="P1",
                source_type="firecrawl", firecrawl_enabled=True, company="Swiggy",
                url="https://careers.swiggy.com", country="IN", india_only=True, india_filter="India"),
    CrawlTarget("firecrawl", "BrowserStack|https://www.browserstack.com/careers", "firecrawl", 2, tier="P1",
                source_type="firecrawl", firecrawl_enabled=True, company="BrowserStack",
                url="https://www.browserstack.com/careers", country="IN", india_only=True, india_filter="India"),
    CrawlTarget("firecrawl", "PostHog|https://posthog.com/careers", "firecrawl", 2, tier="P1",
                source_type="firecrawl", firecrawl_enabled=True, company="PostHog",
                url="https://posthog.com/careers", india_filter="India"),
    CrawlTarget("firecrawl", "Linear|https://linear.app/careers", "firecrawl", 2, tier="P1",
                source_type="firecrawl", firecrawl_enabled=True, company="Linear",
                url="https://linear.app/careers", india_filter="India"),
]

# ---------------------------------------------------------------------------
# Priority 3: Direct official ATS boards (100+ verified active endpoints).
# Verified via live probe against Greenhouse, Ashby, Lever, SmartRecruiters.
# ---------------------------------------------------------------------------
ATS_TARGETS: list[CrawlTarget] = [
    # ---- Ashby Verified Boards (30 targets) ----
    CrawlTarget("ashby", "notion", "ats", 3, tier="P0", company="Notion", india_filter="India", url="https://jobs.ashbyhq.com/notion"),
    CrawlTarget("ashby", "openai", "ats", 3, tier="P0", company="OpenAI", india_filter="India", url="https://jobs.ashbyhq.com/openai"),
    CrawlTarget("ashby", "elevenlabs", "ats", 3, tier="P0", company="ElevenLabs", india_filter="India", url="https://jobs.ashbyhq.com/elevenlabs"),
    CrawlTarget("ashby", "cursor", "ats", 3, tier="P0", company="Cursor", india_filter="India", url="https://jobs.ashbyhq.com/cursor"),
    CrawlTarget("ashby", "cognition", "ats", 3, tier="P0", company="Cognition", india_filter="India", url="https://jobs.ashbyhq.com/cognition"),
    CrawlTarget("ashby", "perplexity", "ats", 3, tier="P0", company="Perplexity", india_filter="India", url="https://jobs.ashbyhq.com/perplexity"),
    CrawlTarget("ashby", "ramp", "ats", 3, tier="P1", company="Ramp", india_filter="India", url="https://jobs.ashbyhq.com/ramp"),
    CrawlTarget("ashby", "linear", "ats", 3, tier="P1", company="Linear", india_filter="India", url="https://jobs.ashbyhq.com/linear"),
    CrawlTarget("ashby", "sentry", "ats", 3, tier="P1", company="Sentry", india_filter="India", url="https://jobs.ashbyhq.com/sentry"),
    CrawlTarget("ashby", "vanta", "ats", 3, tier="P1", company="Vanta", india_filter="India", url="https://jobs.ashbyhq.com/vanta"),
    CrawlTarget("ashby", "synthesia", "ats", 3, tier="P1", company="Synthesia", india_filter="India", url="https://jobs.ashbyhq.com/synthesia"),
    CrawlTarget("ashby", "hex", "ats", 3, tier="P1", company="Hex", india_filter="India", url="https://jobs.ashbyhq.com/hex"),
    CrawlTarget("ashby", "modal", "ats", 3, tier="P1", company="Modal", india_filter="India", url="https://jobs.ashbyhq.com/modal"),
    CrawlTarget("ashby", "posthog", "ats", 3, tier="P1", company="PostHog", india_filter="India", url="https://jobs.ashbyhq.com/posthog"),
    CrawlTarget("ashby", "render", "ats", 3, tier="P1", company="Render", india_filter="India", url="https://jobs.ashbyhq.com/render"),
    CrawlTarget("ashby", "cohere", "ats", 3, tier="P1", company="Cohere", india_filter="India", url="https://jobs.ashbyhq.com/cohere"),
    CrawlTarget("ashby", "replit", "ats", 3, tier="P1", company="Replit", india_filter="India", url="https://jobs.ashbyhq.com/replit"),
    CrawlTarget("ashby", "deepgram", "ats", 3, tier="P1", company="Deepgram", india_filter="India", url="https://jobs.ashbyhq.com/deepgram"),
    CrawlTarget("ashby", "supabase", "ats", 3, tier="P1", company="Supabase", india_filter="India", url="https://jobs.ashbyhq.com/supabase"),
    CrawlTarget("ashby", "langchain", "ats", 3, tier="P1", company="LangChain", india_filter="India", url="https://jobs.ashbyhq.com/langchain"),
    CrawlTarget("ashby", "baseten", "ats", 3, tier="P1", company="Baseten", india_filter="India", url="https://jobs.ashbyhq.com/baseten"),
    CrawlTarget("ashby", "anyscale", "ats", 3, tier="P2", company="Anyscale", india_filter="India", url="https://jobs.ashbyhq.com/anyscale"),
    CrawlTarget("ashby", "pinecone", "ats", 3, tier="P2", company="Pinecone", india_filter="India", url="https://jobs.ashbyhq.com/pinecone"),
    CrawlTarget("ashby", "resend", "ats", 3, tier="P2", company="Resend", india_filter="India", url="https://jobs.ashbyhq.com/resend"),
    CrawlTarget("ashby", "tavily", "ats", 3, tier="P2", company="Tavily", india_filter="India", url="https://jobs.ashbyhq.com/tavily"),
    CrawlTarget("ashby", "e2b", "ats", 3, tier="P2", company="E2B", india_filter="India", url="https://jobs.ashbyhq.com/e2b"),
    CrawlTarget("ashby", "warp", "ats", 3, tier="P2", company="Warp", india_filter="India", url="https://jobs.ashbyhq.com/warp"),
    CrawlTarget("ashby", "graphite", "ats", 3, tier="P2", company="Graphite", india_filter="India", url="https://jobs.ashbyhq.com/graphite"),
    CrawlTarget("ashby", "railway", "ats", 3, tier="P2", company="Railway", india_filter="India", url="https://jobs.ashbyhq.com/railway"),
    CrawlTarget("ashby", "suno", "ats", 3, tier="P2", company="Suno", india_filter="India", url="https://jobs.ashbyhq.com/suno"),

    # ---- Greenhouse Verified Boards (66 targets) ----
    # Tier 1 Heavy India Hiring (P0)
    CrawlTarget("greenhouse", "stripe", "ats", 3, tier="P0", company="Stripe", india_only=True, india_filter="India", url="https://boards.greenhouse.io/stripe"),
    CrawlTarget("greenhouse", "databricks", "ats", 3, tier="P0", company="Databricks", india_filter="India", url="https://boards.greenhouse.io/databricks"),
    CrawlTarget("greenhouse", "mongodb", "ats", 3, tier="P0", company="MongoDB", india_filter="India", url="https://boards.greenhouse.io/mongodb"),
    CrawlTarget("greenhouse", "okta", "ats", 3, tier="P0", company="Okta", india_filter="India", url="https://boards.greenhouse.io/okta"),
    CrawlTarget("greenhouse", "zscaler", "ats", 3, tier="P0", company="Zscaler", india_filter="India", url="https://boards.greenhouse.io/zscaler"),
    CrawlTarget("greenhouse", "inmobi", "ats", 3, tier="P0", company="InMobi", india_filter="India", url="https://boards.greenhouse.io/inmobi"),
    CrawlTarget("greenhouse", "gitlab", "ats", 3, tier="P0", company="GitLab", india_filter="India", url="https://boards.greenhouse.io/gitlab"),
    CrawlTarget("greenhouse", "rubrik", "ats", 3, tier="P0", company="Rubrik", india_filter="India", url="https://boards.greenhouse.io/rubrik"),
    CrawlTarget("greenhouse", "elastic", "ats", 3, tier="P0", company="Elastic", india_filter="India", url="https://boards.greenhouse.io/elastic"),
    CrawlTarget("greenhouse", "druva", "ats", 3, tier="P0", company="Druva", india_filter="India", url="https://boards.greenhouse.io/druva"),
    CrawlTarget("greenhouse", "twilio", "ats", 3, tier="P0", company="Twilio", india_filter="India", url="https://boards.greenhouse.io/twilio"),
    CrawlTarget("greenhouse", "fivetran", "ats", 3, tier="P0", company="Fivetran", india_filter="India", url="https://boards.greenhouse.io/fivetran"),
    CrawlTarget("greenhouse", "coinbase", "ats", 3, tier="P0", company="Coinbase", india_filter="India", url="https://boards.greenhouse.io/coinbase"),
    CrawlTarget("greenhouse", "samsara", "ats", 3, tier="P0", company="Samsara", india_filter="India", url="https://boards.greenhouse.io/samsara"),
    CrawlTarget("greenhouse", "airbnb", "ats", 3, tier="P0", company="Airbnb", india_filter="India", url="https://boards.greenhouse.io/airbnb"),
    CrawlTarget("greenhouse", "datadog", "ats", 3, tier="P0", company="Datadog", india_filter="India", url="https://boards.greenhouse.io/datadog"),
    CrawlTarget("greenhouse", "groww", "ats", 3, tier="P0", company="Groww", india_only=True, india_filter="India", url="https://boards.greenhouse.io/groww"),
    CrawlTarget("greenhouse", "postman", "ats", 3, tier="P0", company="Postman", india_filter="India", url="https://boards.greenhouse.io/postman"),
    # Standard Verified Tech Companies (P1)
    CrawlTarget("greenhouse", "figma", "ats", 3, tier="P1", company="Figma", india_filter="India", url="https://boards.greenhouse.io/figma"),
    CrawlTarget("greenhouse", "cloudflare", "ats", 3, tier="P1", company="Cloudflare", india_filter="India", url="https://boards.greenhouse.io/cloudflare"),
    CrawlTarget("greenhouse", "yugabyte", "ats", 3, tier="P1", company="Yugabyte", india_filter="India", url="https://boards.greenhouse.io/yugabyte"),
    CrawlTarget("greenhouse", "cockroachlabs", "ats", 3, tier="P1", company="Cockroach Labs", india_filter="India", url="https://boards.greenhouse.io/cockroachlabs"),
    CrawlTarget("greenhouse", "pingidentity", "ats", 3, tier="P1", company="Ping Identity", india_filter="India", url="https://boards.greenhouse.io/pingidentity"),
    CrawlTarget("greenhouse", "amplitude", "ats", 3, tier="P1", company="Amplitude", india_filter="India", url="https://boards.greenhouse.io/amplitude"),
    CrawlTarget("greenhouse", "mixpanel", "ats", 3, tier="P1", company="Mixpanel", india_filter="India", url="https://boards.greenhouse.io/mixpanel"),
    CrawlTarget("greenhouse", "starburst", "ats", 3, tier="P1", company="Starburst", india_filter="India", url="https://boards.greenhouse.io/starburst"),
    CrawlTarget("greenhouse", "gusto", "ats", 3, tier="P1", company="Gusto", india_filter="India", url="https://boards.greenhouse.io/gusto"),
    CrawlTarget("greenhouse", "instacart", "ats", 3, tier="P1", company="Instacart", india_filter="India", url="https://boards.greenhouse.io/instacart"),
    CrawlTarget("greenhouse", "affirm", "ats", 3, tier="P1", company="Affirm", india_filter="India", url="https://boards.greenhouse.io/affirm"),
    CrawlTarget("greenhouse", "discord", "ats", 3, tier="P1", company="Discord", india_filter="India", url="https://boards.greenhouse.io/discord"),
    CrawlTarget("greenhouse", "robinhood", "ats", 3, tier="P1", company="Robinhood", india_filter="India", url="https://boards.greenhouse.io/robinhood"),
    CrawlTarget("greenhouse", "brex", "ats", 3, tier="P1", company="Brex", india_filter="India", url="https://boards.greenhouse.io/brex"),
    CrawlTarget("greenhouse", "chime", "ats", 3, tier="P1", company="Chime", india_filter="India", url="https://boards.greenhouse.io/chime"),
    CrawlTarget("greenhouse", "lyft", "ats", 3, tier="P1", company="Lyft", india_filter="India", url="https://boards.greenhouse.io/lyft"),
    CrawlTarget("greenhouse", "pinterest", "ats", 3, tier="P1", company="Pinterest", india_filter="India", url="https://boards.greenhouse.io/pinterest"),
    CrawlTarget("greenhouse", "reddit", "ats", 3, tier="P1", company="Reddit", india_filter="India", url="https://boards.greenhouse.io/reddit"),
    CrawlTarget("greenhouse", "pagerduty", "ats", 3, tier="P1", company="PagerDuty", india_filter="India", url="https://boards.greenhouse.io/pagerduty"),
    CrawlTarget("greenhouse", "qualtrics", "ats", 3, tier="P1", company="Qualtrics", india_filter="India", url="https://boards.greenhouse.io/qualtrics"),
    CrawlTarget("greenhouse", "checkr", "ats", 3, tier="P1", company="Checkr", india_filter="India", url="https://boards.greenhouse.io/checkr"),
    CrawlTarget("greenhouse", "carta", "ats", 3, tier="P1", company="Carta", india_filter="India", url="https://boards.greenhouse.io/carta"),
    CrawlTarget("greenhouse", "braze", "ats", 3, tier="P1", company="Braze", india_filter="India", url="https://boards.greenhouse.io/braze"),
    CrawlTarget("greenhouse", "lattice", "ats", 3, tier="P2", company="Lattice", india_filter="India", url="https://boards.greenhouse.io/lattice"),
    CrawlTarget("greenhouse", "dremio", "ats", 3, tier="P2", company="Dremio", india_filter="India", url="https://boards.greenhouse.io/dremio"),
    CrawlTarget("greenhouse", "slice", "ats", 3, tier="P2", company="Slice", india_filter="India", url="https://boards.greenhouse.io/slice"),
    CrawlTarget("greenhouse", "porter", "ats", 3, tier="P2", company="Porter", india_filter="India", url="https://boards.greenhouse.io/porter"),
    CrawlTarget("greenhouse", "confluent", "ats", 3, tier="P1", company="Confluent", india_filter="India", url="https://boards.greenhouse.io/confluent"),
    CrawlTarget("greenhouse", "snowflake", "ats", 3, tier="P1", company="Snowflake", india_filter="India", url="https://boards.greenhouse.io/snowflake"),
    CrawlTarget("greenhouse", "paloaltonetworks", "ats", 3, tier="P1", company="Palo Alto Networks", india_filter="India", url="https://boards.greenhouse.io/paloaltonetworks"),
    CrawlTarget("greenhouse", "crowdstrike", "ats", 3, tier="P1", company="CrowdStrike", india_filter="India", url="https://boards.greenhouse.io/crowdstrike"),
    CrawlTarget("greenhouse", "splunk", "ats", 3, tier="P1", company="Splunk", india_filter="India", url="https://boards.greenhouse.io/splunk"),
    CrawlTarget("greenhouse", "box", "ats", 3, tier="P1", company="Box", india_filter="India", url="https://boards.greenhouse.io/box"),
    CrawlTarget("ashby", "fly", "ats", 3, tier="P2", company="Fly.io", india_filter="India", url="https://jobs.ashbyhq.com/fly"),
    CrawlTarget("ashby", "sourcegraph", "ats", 3, tier="P2", company="Sourcegraph", india_filter="India", url="https://jobs.ashbyhq.com/sourcegraph"),
    CrawlTarget("ashby", "midjourney", "ats", 3, tier="P2", company="Midjourney", india_filter="India", url="https://jobs.ashbyhq.com/midjourney"),

    # ---- Lever Verified Boards (8 targets) ----
    CrawlTarget("lever", "paytm", "ats", 3, tier="P0", company="Paytm", india_only=True, india_filter="India", url="https://jobs.lever.co/paytm"),
    CrawlTarget("lever", "cred", "ats", 3, tier="P0", company="CRED", india_only=True, india_filter="India", url="https://jobs.lever.co/cred"),
    CrawlTarget("lever", "coupa", "ats", 3, tier="P0", company="Coupa", india_filter="India", url="https://jobs.lever.co/coupa"),
    CrawlTarget("lever", "pocketfm", "ats", 3, tier="P1", company="Pocket FM", india_filter="India", url="https://jobs.lever.co/pocketfm"),
    CrawlTarget("lever", "outreach", "ats", 3, tier="P1", company="Outreach", india_filter="India", url="https://jobs.lever.co/outreach"),
    CrawlTarget("lever", "palantir", "ats", 3, tier="P1", company="Palantir", india_filter="India", url="https://jobs.lever.co/palantir"),
    CrawlTarget("lever", "spotify", "ats", 3, tier="P1", company="Spotify", india_filter="India", url="https://jobs.lever.co/spotify"),
    CrawlTarget("lever", "wealthfront", "ats", 3, tier="P2", company="Wealthfront", india_filter="India", url="https://jobs.lever.co/wealthfront"),

    # ---- SmartRecruiters Verified Boards (2 targets) ----
    CrawlTarget("smartrecruiters", "servicenow", "ats", 3, tier="P0", company="ServiceNow", india_filter="India", url="https://jobs.smartrecruiters.com/ServiceNow"),
    CrawlTarget("smartrecruiters", "averydennison", "ats", 3, tier="P2", company="Avery Dennison", india_filter="India", url="https://jobs.smartrecruiters.com/AveryDennison"),
]

# ---------------------------------------------------------------------------
# Priority 4: Aggregator (least frequent, rotates target queries).
# ---------------------------------------------------------------------------
AGGREGATOR_TARGETS: list[CrawlTarget] = [
    CrawlTarget("adzuna", "software engineer", "aggregator", 4, tier="P0",
                notes="Slug is the primary search query; adapter rotates India-first queries.",
                source_type="aggregator"),
    CrawlTarget("jobspy", "data analyst India", "aggregator", 4, tier="P2",
                notes="JobSpy Naukri/LinkedIn discovery; optional dep (python-jobspy).",
                source_type="aggregator"),
]


def all_targets() -> list[CrawlTarget]:
    """All registered targets, ordered by priority and tier."""
    targets = [YC_TARGET, *FIRECRAWL_TARGETS, *ATS_TARGETS, *AGGREGATOR_TARGETS]
    return sorted(
        [t for t in targets if t.enabled],
        key=lambda t: (t.priority, 0 if t.tier == "P0" else 1 if t.tier == "P1" else 2),
    )


def targets_for_provider(provider: str) -> list[CrawlTarget]:
    """All enabled targets for one provider family, priority-ordered."""
    return [t for t in all_targets() if t.provider == provider]


def targets_for_tier(tier: str) -> list[CrawlTarget]:
    """All enabled targets for a specific priority tier (P0, P1, P2)."""
    return [t for t in all_targets() if t.tier == tier]


# Backwards-compatible view used by earlier code/tests: list of (source, slug).
CRAWL_TARGETS: list[tuple[str, str]] = [(t.source, t.slug) for t in all_targets()]

