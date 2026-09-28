"""Mass hiring detector: deterministic evidence-based classification and campaign tracking.

Signals:
- explicit phrases: mass hiring, bulk hiring, hiring drive, walk-in drive, 50+ openings, etc.
- structured evidence: vacancy count, application deadline, campaign URL, multiple locations.

Confidence: NOT_MASS_HIRING, POSSIBLE_MASS_HIRING, VERIFIED_MASS_HIRING
Status: ACTIVE, ENDING_SOON, EXPIRED, UNKNOWN
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional


_EXPLICIT_VERIFIED_PHRASES = (
    "mass hiring",
    "bulk hiring",
    "hiring drive",
    "recruitment drive",
    "walk-in drive",
    "walk in drive",
    "fresher hiring drive",
    "freshers hiring drive",
    "graduate hiring drive",
    "campus hiring drive",
    "campus recruitment drive",
    "national qualifier test",
    "nqt",
    "off-campus drive",
    "off campus drive",
    "hiring at scale",
    "large-scale hiring",
    "mega hiring",
    "mega drive",
)

_POSSIBLE_PHRASES = (
    "multiple openings",
    "multiple positions",
    "multiple vacancies",
    "aggressive hiring",
    "rapidly expanding team",
    "rapidly hiring",
    "campus hiring",
)

# Standalone walk-in / immediate-hiring phrases (JobSpy walk-in discovery).
# Weaker than the explicit drive phrases above: a title hit is strong
# campaign evidence, but a description hit requires supporting context
# (campaign language, vacancy count, deadline, or venue/date details) to
# avoid fabricating walk-in classifications. Ordered longest-first so the
# most specific phrase wins the signal label.
_WALKIN_STANDALONE_PHRASES = (
    "face-to-face interview",
    "face to face interview",
    "walk-in interview",
    "walk in interview",
    "walkin interview",
    "walk in interviews",
    "immediate joiner",
    "immediate joiners",
    "mega walk-in",
    "mega walkin",
    "mass hiring",
    "open interview",
    "open interviews",
    "walk-in",
    "walkin",
    "walk in",
)

# Venue/date details that corroborate a description-only walk-in mention
# (evidence of a real hiring event, not an incidental phrase).
_WALKIN_VENUE_PATTERN = re.compile(
    r"\b(?:venue|dates?|timings?|reporting\s+time|carry\s+(?:your\s+)?(?:resume|cv)"
    r"|bring\s+(?:your\s+)?(?:resume|cv)|on\s+\d{1,2}(?:st|nd|rd|th)?\b"
    r"|between\s+\d|from\s+\d{1,2}\s*(?:am|pm))\b",
    re.IGNORECASE,
)


# Furniture senses of "walk-in" (closet/wardrobe/cooler) are never hiring
# evidence — strip them before matching so "Walk-in Closet Installer" is
# not classified as a hiring event.
_WALKIN_FURNITURE_PATTERN = re.compile(
    r"walk-?\s*in\s+(?:closet|wardrobe|cooler|freezer|shower|tub)s?",
    re.IGNORECASE,
)


def detect_walkin(title: str = "", description: str = "") -> dict[str, Any]:
    """Evidence-only walk-in detection (no classification ladder here).

    Returns matched phrases with title/description provenance. Incidental
    vendor/recruiter mentions (see _INCIDENTAL_PATTERNS) are excluded so a
    posting is only flagged when the title/description contains sufficient
    real evidence. The confidence ladder lives in detect_mass_hiring.
    """
    t_clean = _WALKIN_FURNITURE_PATTERN.sub(" ", (title or "").lower())
    d_clean = _WALKIN_FURNITURE_PATTERN.sub(" ", (description or "").lower())
    haystack = f"{t_clean} {d_clean}".strip()
    if not haystack:
        return {"is_walkin": False, "signals": []}
    if any(pat.search(haystack) for pat in _INCIDENTAL_PATTERNS):
        return {"is_walkin": False, "signals": []}
    signals: list[str] = []
    for phrase in _WALKIN_STANDALONE_PHRASES:
        if phrase in t_clean:
            signals.append(f"title: walk-in: {phrase}")
        elif phrase in d_clean:
            # Bare short tokens ("walk in") need a word-boundary check so
            # prose like "you will walk into ownership" never matches.
            if len(phrase) <= len("walk in"):
                if re.search(rf"\b{re.escape(phrase)}\b", d_clean):
                    signals.append(f"walk-in: {phrase}")
            else:
                signals.append(f"walk-in: {phrase}")
    # Deduplicate while preserving order (a hyphenated hit also contains
    # shorter variants); keep the most specific signal per provenance.
    seen: set[str] = set()
    ordered: list[str] = []
    for signal in signals:
        marker = signal.split("walk-in: ")[-1]
        key = ("title" if signal.startswith("title:") else "desc") + ":" + marker
        if key in seen:
            continue
        seen.add(key)
        ordered.append(signal)
    return {"is_walkin": bool(ordered), "signals": ordered}

_INCIDENTAL_PATTERNS = (
    re.compile(r"\b(?:provide[s]?|offering|offers?|delivers?|specialize[s]?\s+in)\s+[^.\n]*?\b(?:mass|bulk|campus)\s+hiring\b", re.IGNORECASE),
    re.compile(r"\b(?:mass|bulk|campus)\s+hiring\s+(?:solutions?|platform[s]?|tools?|services?|software|products?|firm|consulting)\b", re.IGNORECASE),
    re.compile(r"\b(?:previous|prior|past|years?\s+of)\s+[^.\n]*?\b(?:hiring|recruitment)\s+drive\b", re.IGNORECASE),
    re.compile(r"\bexperience\s+(?:in|with|managing|conducting|organizing|handling|leading)\s+[^.\n]*?\b(?:hiring\s+drive|recruitment\s+drive|mass\s+hiring|bulk\s+hiring|campus\s+hiring)\b", re.IGNORECASE),
    re.compile(r"\b(?:years?\s+of\s+experience|experience)\s+(?:in|with|of)?\s*[^.\n]*?\b(?:campus\s+hiring|mass\s+hiring|bulk\s+hiring)\b", re.IGNORECASE),
    re.compile(r"\b(?:handled|conducted|organized|managed)\s+[^.\n]*?\b(?:hiring|recruitment)\s+drive\b", re.IGNORECASE),
)

_CAMPAIGN_INDICATORS = (
    re.compile(r"\b(?:we\s+are|announcing|conducting|hosting|inviting|open\s+for|launching|starting|calling\s+all)\s+[^.\n]*?\b(?:hiring\s+drive|recruitment\s+drive|mass\s+hiring|bulk\s+hiring|walk-?in\s+drive|mega\s+drive)\b", re.IGNORECASE),
    re.compile(r"\b(?:join|participate\s+in|attend|register\s+for)\s+(?:our|the)?\s*(?:hiring\s+drive|recruitment\s+drive|walk-?in\s+drive|mega\s+drive|campus\s+drive)\b", re.IGNORECASE),
    re.compile(r"\b(?:walk-?in|walk\s+in)\s+(?:drive|interview[s]?)\s+(?:on|at|between|from|date|venue)\b", re.IGNORECASE),
    re.compile(r"\b(?:batch|class)\s+of\s+20\d\d\b", re.IGNORECASE),
)

_VACANCY_PATTERN = re.compile(
    r"\b(\d{2,4})\+?\s*(?:openings|vacancies|positions|posts|roles)\b",
    re.IGNORECASE,
)

_DEADLINE_PATTERN = re.compile(
    r"(?:apply\s+by|deadline|last\s+date|drive\s+date)[:\s]+([a-zA-Z0-9,\s\/\-]+)",
    re.IGNORECASE,
)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d %Y",
    "%B %d %Y",
)


def _parse_deadline(raw_deadline: str) -> Optional[datetime]:
    """Safely parse deadline date string into UTC datetime. Never fabricates."""
    cleaned = raw_deadline.strip().rstrip(".").strip()
    # Try ISO first
    try:
        dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass

    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

    # Try extracting date pattern like 2026-12-31 from text
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", cleaned)
    if iso_match:
        try:
            dt = datetime.fromisoformat(iso_match.group(1))
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    return None


def detect_mass_hiring(
    title: str = "",
    description: str = "",
    url: str = "",
    location: str = "",
    deadline_str: Optional[str] = None,
) -> dict[str, Any]:
    """Analyze job data for mass-hiring campaign signals.

    Returns a structured dict with confidence, status, and evidence.
    Never fabricates vacancy counts, deadlines, or claims indefinite activity.
    Incidental mentions (e.g. vendor sales or recruiter requirements) are rejected.
    """
    t_clean = (title or "").lower()
    d_clean = (description or "").lower()
    haystack = f"{t_clean} {d_clean}"

    signals_detected: list[str] = []
    confidence = "NOT_MASS_HIRING"
    vacancy_count: Optional[int] = None
    deadline: Optional[str] = deadline_str

    # 1. Check for incidental mentions that must not be counted as campaign evidence
    is_incidental = any(pat.search(haystack) for pat in _INCIDENTAL_PATTERNS)

    # 2. Check title directly: title is strong explicit campaign evidence
    title_has_verified = any(p in t_clean for p in _EXPLICIT_VERIFIED_PHRASES)
    if title_has_verified:
        for phrase in _EXPLICIT_VERIFIED_PHRASES:
            if phrase in t_clean:
                signals_detected.append(f"title: {phrase}")

    # 3. Check explicit verified phrases in description if not purely incidental
    desc_phrases_found: list[str] = []
    for phrase in _EXPLICIT_VERIFIED_PHRASES:
        if phrase in d_clean:
            desc_phrases_found.append(phrase)

    # 4. Extract vacancy count evidence
    v_match = _VACANCY_PATTERN.search(haystack)
    if v_match:
        try:
            count = int(v_match.group(1))
            vacancy_count = count
            signals_detected.append(f"{count}+ openings")
            if count >= 30:
                signals_detected.append("large vacancy count")
        except ValueError:
            pass

    # 5. Extract deadline if not explicitly provided
    if not deadline:
        d_match = _DEADLINE_PATTERN.search(haystack)
        if d_match:
            raw_d = d_match.group(1).strip()[:40]
            deadline = raw_d

    # 6. Check campaign-specific indicators
    has_campaign_language = any(pat.search(haystack) for pat in _CAMPAIGN_INDICATORS)
    if has_campaign_language:
        signals_detected.append("active campaign language")

    # 7. Check possible phrases
    for phrase in _POSSIBLE_PHRASES:
        if phrase in haystack:
            signals_detected.append(phrase)

    # Walk-in evidence (standalone phrases): title hits are strong campaign
    # evidence; description hits need corroboration (campaign language,
    # vacancy count, deadline, or venue/date details).
    walkin = detect_walkin(title or "", description or "")
    walkin_signals: list[str] = walkin["signals"] if not is_incidental else []
    title_walkin = [s for s in walkin_signals if s.startswith("title:")]
    desc_walkin = [s for s in walkin_signals if not s.startswith("title:")]
    has_walkin_venue = bool(_WALKIN_VENUE_PATTERN.search(haystack))

    # Determine confidence:
    # Campaign-specific evidence required for VERIFIED_MASS_HIRING:
    # - Explicit verified phrase in title (or standalone walk-in phrase in title)
    # - OR (explicit verified phrase in desc AND (has_campaign_language or vacancy_count or deadline) AND NOT purely incidental)
    # - OR (standalone walk-in phrase in desc AND corroborating event evidence)
    # - OR massive vacancy count (>= 50 openings)
    if title_has_verified and not is_incidental:
        confidence = "VERIFIED_MASS_HIRING"
    elif title_walkin and not is_incidental:
        confidence = "VERIFIED_MASS_HIRING"
        signals_detected.extend(title_walkin)
    elif desc_phrases_found and not is_incidental and (has_campaign_language or (vacancy_count and vacancy_count >= 30) or deadline):
        confidence = "VERIFIED_MASS_HIRING"
        signals_detected.extend(desc_phrases_found)
    elif desc_walkin and not is_incidental and (
        has_campaign_language
        or (vacancy_count and vacancy_count >= 30)
        or deadline
        or has_walkin_venue
    ):
        confidence = "VERIFIED_MASS_HIRING"
        signals_detected.extend(desc_walkin)
        if has_walkin_venue:
            signals_detected.append("walk-in venue/date details")
    elif vacancy_count and vacancy_count >= 50 and not is_incidental:
        confidence = "VERIFIED_MASS_HIRING"
    elif not is_incidental and (any(p in signals_detected for p in _POSSIBLE_PHRASES) or (vacancy_count and vacancy_count >= 15) or desc_phrases_found or desc_walkin):
        confidence = "POSSIBLE_MASS_HIRING"
        signals_detected.extend([s for s in desc_walkin if s not in signals_detected])
    else:
        confidence = "NOT_MASS_HIRING"

    # Determine status:
    # If deadline exists and is parseable:
    #   deadline < now -> EXPIRED
    #   deadline <= 7 days -> ENDING_SOON
    #   deadline > 7 days -> ACTIVE
    # If deadline exists but cannot be parsed: UNKNOWN (conservative)
    # If no deadline exists: ACTIVE when verified/possible campaign, UNKNOWN otherwise
    status = "UNKNOWN"
    if confidence != "NOT_MASS_HIRING":
        if deadline:
            parsed_dt = _parse_deadline(deadline)
            if parsed_dt is not None:
                now = datetime.now(timezone.utc)
                diff_days = (parsed_dt - now).total_seconds() / 86400
                if diff_days < 0:
                    status = "EXPIRED"
                elif diff_days <= 7:
                    status = "ENDING_SOON"
                else:
                    status = "ACTIVE"
            else:
                # Deadline exists but cannot be parsed -> conservative UNKNOWN
                status = "UNKNOWN"
        else:
            status = "ACTIVE"

    return {
        "confidence": confidence,
        "status": status,
        "signals_detected": signals_detected,
        "vacancy_count": vacancy_count,
        "deadline": deadline,
        "walkin_signals": walkin_signals,
        "walkin_detected": bool(walkin_signals),
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
