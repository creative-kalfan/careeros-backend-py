"""Source quality: canonical source tiers and official-source verification.

CareerOS ranks REAL, DIRECT, OFFICIAL company postings above aggregated /
secondary listings. Firecrawl (or any retrieval mechanism) never implies
"official" — the URL's domain is verified against the company identity and
known aggregator/ATS domains before any source-quality upgrade is applied.

Tiers (lower = better):

    1  OFFICIAL_COMPANY_CAREER  — job URL lives on the company's own domain
    2  OFFICIAL_ATS             — job hosted on the company's ATS board
                                  (Greenhouse / Lever / Ashby / ...)
    3  VERIFIED_YC_STARTUP      — Y Combinator board listing
    4  OTHER_VERIFIED_SOURCE    — a known but non-premium source
    5  AGGREGATOR               — secondary boards / aggregators
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------

SOURCE_TIER_OFFICIAL_COMPANY_CAREER = 1
SOURCE_TIER_OFFICIAL_ATS = 2
SOURCE_TIER_VERIFIED_YC_STARTUP = 3
SOURCE_TIER_OTHER_VERIFIED_SOURCE = 4
SOURCE_TIER_AGGREGATOR = 5

TIER_LABELS = {
    SOURCE_TIER_OFFICIAL_COMPANY_CAREER: "official_company_career",
    SOURCE_TIER_OFFICIAL_ATS: "official_ats",
    SOURCE_TIER_VERIFIED_YC_STARTUP: "verified_yc_startup",
    SOURCE_TIER_OTHER_VERIFIED_SOURCE: "other_verified_source",
    SOURCE_TIER_AGGREGATOR: "aggregator",
}

# Known ATS job-board domains. A job hosted here is an OFFICIAL company
# posting (hosted on the company's board) even though the domain is not
# the company's own.
_ATS_HOST_PATTERNS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
    "jobs.smartrecruiters.com": "smartrecruiters",
    "myworkdayjobs.com": "workday",
    "icims.com": "icims",
    "eightfold.ai": "eightfold",
    "jobvite.com": "jobvite",
    "breezy.hr": "breezy",
    "recruitee.com": "recruitee",
    "applytojob.com": "jazz",
}

# Aggregator / secondary-board domains. Jobs discovered here must never be
# treated as official company postings regardless of retrieval mechanism.
_AGGREGATOR_HOST_TOKENS = (
    "linkedin.com", "indeed.com", "glassdoor.com", "naukri.com",
    "ziprecruiter.com", "adzuna.", "monster.com", "shine.com",
    "foundit.", "dice.com", "ycombinator.com", "workatastartup.com",
    "wellfound.com", "angellist.", "cutshort.io", "instahyre.com",
    "hirist.", "timesjobs.com",
)

# Paths that commonly indicate a careers/jobs section of a site.
_CAREER_PATH_TOKENS = ("/careers", "/jobs", "/join", "/openings", "/positions", "/work-with-us")


def _host(url: Optional[str]) -> str:
    """Return the lowercase host of a URL (empty string when unparseable)."""
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def stable_hash(value: str) -> str:
    """Deterministic FNV-1a 32-bit hash (stable across processes)."""
    h = 0x811C9DC5
    for ch in value:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return format(h, "08x")


def detect_ats_provider(url: Optional[str]) -> Optional[str]:
    """Return the ATS provider name when the URL is a known ATS job board."""
    host = _host(url)
    if not host:
        return None
    for pattern, provider in _ATS_HOST_PATTERNS.items():
        if host == pattern or host.endswith("." + pattern):
            return provider
    return None


def is_aggregator_url(url: Optional[str]) -> bool:
    """True when the URL belongs to a known aggregator / secondary board."""
    host = _host(url)
    if not host:
        return False
    return any(token in host for token in _AGGREGATOR_HOST_TOKENS)


def company_domain_token(company: Optional[str]) -> str:
    """Normalize a company name into a domain-ish token ('stripe' etc.)."""
    if not company:
        return ""
    cleaned = "".join(ch for ch in company.lower() if ch.isalnum() or ch == " ")
    words = [
        w for w in cleaned.split()
        if w not in {"inc", "llc", "ltd", "the", "co", "corp", "labs", "technologies", "technology"}
    ]
    return "".join(words) if words else cleaned.replace(" ", "")


def _registrable_domain(host: str) -> str:
    """Rough registrable domain: last two labels ('stripe.com')."""
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def is_official_career_url(
    url: Optional[str],
    company: Optional[str],
    careers_url: Optional[str] = None,
) -> bool:
    """True when the job URL plausibly lives on the company's own domain.

    Verification rules:
      - Aggregators never qualify.
      - ATS-hosted boards do NOT count as the company's own domain (they are
        classified separately as OFFICIAL_ATS).
      - The URL host must be company-related: the company token appears in
        the registrable domain, OR the host matches the host of the known
        careers page the crawl originated from.
    """
    if not url or is_aggregator_url(url) or detect_ats_provider(url):
        return False
    host = _host(url)
    if not host or "." not in host:
        return False
    token = company_domain_token(company)
    if token and len(token) >= 4 and token in _registrable_domain(host).replace(".", ""):
        return True
    if careers_url:
        careers_host = _host(careers_url)
        if careers_host and host == careers_host:
            return True
    return False


@dataclass(frozen=True)
class SourceProvenance:
    """Verified provenance for a single job source."""

    tier: int
    tier_label: str
    provider: str
    is_official: bool
    verified: bool
    confidence: float


def classify_source(
    source_platform: Optional[str],
    url: Optional[str] = None,
    company: Optional[str] = None,
    careers_url: Optional[str] = None,
) -> SourceProvenance:
    """Classify a job's source into the canonical tier model.

    The source platform is the retrieval mechanism; the URL is what decides
    whether the posting is OFFICIAL. Missing/unverifiable data degrades to
    OTHER_VERIFIED_SOURCE with low confidence — never fabricated.
    """
    platform = (source_platform or "").lower()

    if platform == "adzuna":
        return SourceProvenance(SOURCE_TIER_AGGREGATOR, TIER_LABELS[SOURCE_TIER_AGGREGATOR], "adzuna", False, True, 0.5)

    if platform == "ycombinator":
        # A YC listing is a verified startup posting; when its apply URL
        # points at the company's own domain or ATS board, upgrade it.
        if is_official_career_url(url, company):
            return SourceProvenance(SOURCE_TIER_OFFICIAL_COMPANY_CAREER, TIER_LABELS[SOURCE_TIER_OFFICIAL_COMPANY_CAREER], "ycombinator", True, True, 0.9)
        ats = detect_ats_provider(url)
        if ats:
            return SourceProvenance(SOURCE_TIER_OFFICIAL_ATS, TIER_LABELS[SOURCE_TIER_OFFICIAL_ATS], ats, True, True, 0.85)
        return SourceProvenance(SOURCE_TIER_VERIFIED_YC_STARTUP, TIER_LABELS[SOURCE_TIER_VERIFIED_YC_STARTUP], "ycombinator", False, True, 0.75)

    if platform == "firecrawl":
        ats = detect_ats_provider(url)
        if ats:
            return SourceProvenance(SOURCE_TIER_OFFICIAL_ATS, TIER_LABELS[SOURCE_TIER_OFFICIAL_ATS], ats, True, True, 0.9)
        if is_aggregator_url(url):
            return SourceProvenance(SOURCE_TIER_AGGREGATOR, TIER_LABELS[SOURCE_TIER_AGGREGATOR], "firecrawl", False, True, 0.5)
        if is_official_career_url(url, company, careers_url):
            return SourceProvenance(SOURCE_TIER_OFFICIAL_COMPANY_CAREER, TIER_LABELS[SOURCE_TIER_OFFICIAL_COMPANY_CAREER], "firecrawl", True, True, 0.95)
        # Firecrawl retrieved it, but the domain could NOT be verified as
        # official: normal/secondary priority, never a top-tier boost.
        return SourceProvenance(SOURCE_TIER_OTHER_VERIFIED_SOURCE, TIER_LABELS[SOURCE_TIER_OTHER_VERIFIED_SOURCE], "firecrawl", False, False, 0.4)

    # Known ATS adapters: their boards are official company postings.
    ats = detect_ats_provider(url) or (
        platform if platform in {"greenhouse", "lever", "ashby", "smartrecruiters", "workday", "icims"} else None
    )
    if ats:
        return SourceProvenance(SOURCE_TIER_OFFICIAL_ATS, TIER_LABELS[SOURCE_TIER_OFFICIAL_ATS], ats, True, True, 0.9)

    if is_aggregator_url(url):
        return SourceProvenance(SOURCE_TIER_AGGREGATOR, TIER_LABELS[SOURCE_TIER_AGGREGATOR], platform or "unknown", False, True, 0.5)

    if is_official_career_url(url, company, careers_url):
        return SourceProvenance(SOURCE_TIER_OFFICIAL_COMPANY_CAREER, TIER_LABELS[SOURCE_TIER_OFFICIAL_COMPANY_CAREER], platform or "unknown", True, True, 0.85)

    return SourceProvenance(SOURCE_TIER_OTHER_VERIFIED_SOURCE, TIER_LABELS[SOURCE_TIER_OTHER_VERIFIED_SOURCE], platform or "unknown", False, False, 0.4)