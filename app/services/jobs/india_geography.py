"""India geography classification: strict India vs foreign vs ambiguous.

Single source of truth for "is this job India-relevant?" used by ingestion
metrics, provider geography reports, India-only filtering, and the
India-first ranking tiebreaker.

Policy (task §6):
- INDIA only when India is EXPLICITLY present: the word "india", a known
  Indian city, "remote - india" / "india - remote", or a multi-location
  string explicitly including India (e.g. "United States / India").
- AMBIGUOUS global postings ("Remote", "Worldwide", "Global",
  "Multiple Locations", "EMEA", "APAC") are NEVER counted as Indian.
- FOREIGN when a known foreign country/city marker is present and no
  India marker is present.
- UNKNOWN when nothing determinable is present (empty or unrecognized).
  Unknown is never promoted to India.

The provider's original location string is always preserved; this module
only classifies, never rewrites.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

# Canonical Indian city tokens (lowercase substring match). Covers the task
# §1 high-value list plus existing pipeline aliases.
INDIAN_CITY_TOKENS = (
    "bengaluru",
    "bangalore",
    "hyderabad",
    "chennai",
    "madras",
    "mumbai",
    "bombay",
    "pune",
    "delhi",
    "new delhi",
    "gurugram",
    "gurgaon",
    "noida",
    "kolkata",
    "calcutta",
    "ahmedabad",
    "kochi",
    "cochin",
    "jaipur",
    "chandigarh",
    "coimbatore",
    "mohali",
    "dehradun",
    "ajmer",
    "udaipur",
    "indore",
)

# Exact strings (after strip/lower) that are ambiguous, never Indian.
AMBIGUOUS_EXACT = frozenset({
    "remote",
    "worldwide",
    "world wide",
    "global",
    "multiple locations",
    "multiple location",
    "multiple",
    "emea",
    "apac",
    "amer",
    "latam",
    "anywhere",
    "flexible",
    "hybrid",
    "onsite",
    "on-site",
    "work from home",
    "wfh",
})

# Substring markers that make a non-India location ambiguous rather than
# foreign (e.g. "Remote - Worldwide"). Checked after the India test.
AMBIGUOUS_SUBSTRINGS = (
    "worldwide",
    "world wide",
    "multiple locations",
    "multiple location",
)

# Known foreign country/city markers (lowercase substring). Checked only
# after the India test so "United States / India" stays INDIA.
FOREIGN_MARKERS = (
    "london",
    "united kingdom",
    ", uk",
    " uk",
    "new york",
    "san francisco",
    "seattle",
    "boston",
    "chicago",
    "los angeles",
    "austin",
    "toronto",
    "canada",
    "singapore",
    "berlin",
    "germany",
    "sydney",
    "australia",
    "paris",
    "france",
    "amsterdam",
    "netherlands",
    "dublin",
    "ireland",
    "tokyo",
    "japan",
    "united states",
    "usa",
    "u.s.a",
    "united arab emirates",
    "uae",
    "dubai",
)

_INDIA_WORD = re.compile(r"\bindia\b", re.IGNORECASE)

# Relevance labels (task §6 + §5 reporting).
INDIA = "INDIA"
FOREIGN = "FOREIGN"
AMBIGUOUS = "AMBIGUOUS"
UNKNOWN = "UNKNOWN"

RELEVANCE_LABELS = (INDIA, FOREIGN, AMBIGUOUS, UNKNOWN)


def _text(location: Optional[str]) -> str:
    return (location or "").strip()


def contains_india_marker(location: Optional[str]) -> bool:
    """True when India is explicitly present (word or city token)."""
    text = _text(location)
    if not text:
        return False
    lowered = text.lower()
    if _INDIA_WORD.search(text):
        # Guard "indiana, usa" false positive: it contains "indiana" not the
        # word "india" (\b prevents the match), so this is safe.
        return True
    return any(city in lowered for city in INDIAN_CITY_TOKENS)


def classify_india_relevance(
    location: Optional[str],
    remote: Optional[bool] = None,
) -> str:
    """Classify a location string into INDIA | FOREIGN | AMBIGUOUS | UNKNOWN.

    Order matters: India-explicit wins over everything (multi-location
    including India stays INDIA); bare ambiguous strings are AMBIGUOUS;
    foreign markers are FOREIGN; anything else is UNKNOWN.
    """
    text = _text(location)
    if not text:
        return UNKNOWN
    lowered = text.lower().strip(" ,.-")

    # 1. Explicit India (city, country word, or multi-location incl. India).
    if contains_india_marker(text):
        return INDIA

    # 2. Bare ambiguous postings — never Indian.
    if lowered in AMBIGUOUS_EXACT:
        return AMBIGUOUS
    if any(marker in lowered for marker in AMBIGUOUS_SUBSTRINGS):
        return AMBIGUOUS
    # "Remote" with a non-India qualifier and no country is still ambiguous
    # (e.g. "Remote US", "Remote - EMEA", "Remote Global").
    if lowered.startswith("remote") and not any(
        sep in lowered for sep in (",", "/", "|", ";")
    ):
        # "Remote - India" already returned INDIA above; remaining
        # bare-remote forms are ambiguous, not Indian.
        return AMBIGUOUS

    # 3. Explicit foreign geography.
    if any(marker in lowered for marker in FOREIGN_MARKERS):
        return FOREIGN
    # Lone "remote ..." with a foreign qualifier handled above; a location
    # that names a foreign marker anywhere is foreign.
    return UNKNOWN


def is_india_job(location: Optional[str], remote: Optional[bool] = None) -> bool:
    return classify_india_relevance(location, remote) == INDIA


def is_foreign_job(location: Optional[str], remote: Optional[bool] = None) -> bool:
    return classify_india_relevance(location, remote) == FOREIGN


def is_ambiguous_location(location: Optional[str]) -> bool:
    return classify_india_relevance(location) == AMBIGUOUS


def india_first_rank(location: Optional[str], remote: Optional[bool] = None) -> int:
    """Bounded 0-3 India-first ranking score (ranking only, not counting).

    3 = Bengaluru/Bangalore (premier hub), 2 = other explicit India,
    1 = generic remote/ambiguous (above foreign, below India),
    0 = foreign / unknown. Ambiguous globals never score as India.
    """
    relevance = classify_india_relevance(location, remote)
    lowered = (location or "").lower()
    if relevance == INDIA:
        if "bengaluru" in lowered or "bangalore" in lowered:
            return 3
        return 2
    if relevance == AMBIGUOUS or bool(remote) or "remote" in lowered:
        return 1
    return 0


def filter_india_only(jobs: list[Any]) -> list[Any]:
    """Keep only jobs whose location explicitly includes India."""
    return [j for j in jobs if is_india_job(getattr(j, "location", None), getattr(j, "remote", None))]


def _indian_city_of(location: Optional[str]) -> Optional[str]:
    lowered = (location or "").lower()
    for city in INDIAN_CITY_TOKENS:
        if city in lowered:
            return city.title() if city not in ("new delhi",) else "Delhi NCR"
    if _INDIA_WORD.search(location or ""):
        return "India (unspecified)"
    return None


def _foreign_country_of(location: Optional[str]) -> Optional[str]:
    lowered = (location or "").lower()
    mapping = (
        ("london", "UK"), ("united kingdom", "UK"), (" uk", "UK"),
        ("new york", "USA"), ("united states", "USA"), ("usa", "USA"),
        ("toronto", "Canada"), ("canada", "Canada"),
        ("singapore", "Singapore"), ("berlin", "Germany"), ("germany", "Germany"),
        ("sydney", "Australia"), ("australia", "Australia"),
        ("paris", "France"), ("france", "France"),
        ("tokyo", "Japan"), ("japan", "Japan"),
        ("dubai", "UAE"), ("uae", "UAE"),
        ("dublin", "Ireland"), ("ireland", "Ireland"),
        ("amsterdam", "Netherlands"), ("netherlands", "Netherlands"),
    )
    for marker, country in mapping:
        if marker in lowered:
            return country
    return "Other/unspecified"


def geography_report(jobs: list[Any]) -> dict[str, Any]:
    """Provider-agnostic geography breakdown (pure, deterministic).

    Returns total/active-equivalent counts plus India %, top Indian cities,
    top foreign countries, and breakdowns by provider/company/role. Jobs are
    NormalizedJob instances or dict-like rows with location/remote fields.
    """
    total = len(jobs)
    india = foreign = ambiguous = unknown = 0
    city_counter: Counter[str] = Counter()
    country_counter: Counter[str] = Counter()
    by_provider: dict[str, dict[str, int]] = {}
    by_company: dict[str, int] = {}
    by_role: dict[str, int] = {}

    def _get(job: Any, name: str, default: Any = None) -> Any:
        if isinstance(job, dict):
            return job.get(name, default)
        return getattr(job, name, default)

    for job in jobs:
        location = _get(job, "location")
        remote = _get(job, "remote")
        label = classify_india_relevance(location, remote)
        if label == INDIA:
            india += 1
            city = _indian_city_of(location) or "India (unspecified)"
            city_counter[city] += 1
        elif label == FOREIGN:
            foreign += 1
            country_counter[_foreign_country_of(location) or "Other/unspecified"] += 1
        elif label == AMBIGUOUS:
            ambiguous += 1
        else:
            unknown += 1

        provider = str(_get(job, "source_platform") or _get(job, "source_provider") or "unknown")
        bucket = by_provider.setdefault(provider, {"total": 0, "india": 0, "foreign": 0, "ambiguous": 0, "unknown": 0})
        bucket["total"] += 1
        bucket[{"INDIA": "india", "FOREIGN": "foreign", "AMBIGUOUS": "ambiguous"}.get(label, "unknown")] += 1

        company = str(_get(job, "company") or "unknown")
        if label == INDIA:
            by_company[company] = by_company.get(company, 0) + 1

        role = str(_get(job, "role_category") or _get(job, "role") or "unknown")
        if label == INDIA:
            by_role[role] = by_role.get(role, 0) + 1

    india_pct = round(100.0 * india / total, 1) if total else 0.0
    return {
        "total": total,
        "india": india,
        "foreign": foreign,
        "ambiguous": ambiguous,
        "unknown": unknown,
        "india_pct": india_pct,
        "top_indian_cities": city_counter.most_common(10),
        "top_foreign_countries": country_counter.most_common(10),
        "by_provider": by_provider,
        "by_company": dict(sorted(by_company.items(), key=lambda kv: kv[1], reverse=True)[:20]),
        "by_role": dict(sorted(by_role.items(), key=lambda kv: kv[1], reverse=True)),
    }
