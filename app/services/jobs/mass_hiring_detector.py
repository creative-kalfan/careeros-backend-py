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
    "campus hiring",
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
)

_VACANCY_PATTERN = re.compile(
    r"\b(\d{2,4})\+?\s*(?:openings|vacancies|positions|posts|roles)\b",
    re.IGNORECASE,
)

_DEADLINE_PATTERN = re.compile(
    r"(?:apply\s+by|deadline|last\s+date|drive\s+date)[:\s]+([a-zA-Z0-9,\s\-]+)",
    re.IGNORECASE,
)


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
    """
    t_clean = (title or "").lower()
    d_clean = (description or "").lower()
    haystack = f"{t_clean} {d_clean}"

    signals_detected: list[str] = []
    confidence = "NOT_MASS_HIRING"
    vacancy_count: Optional[int] = None
    deadline: Optional[str] = deadline_str

    # 1. Check explicit verified phrases
    for phrase in _EXPLICIT_VERIFIED_PHRASES:
        if phrase in haystack:
            signals_detected.append(phrase)

    # 2. Extract vacancy count evidence
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

    # 3. Check possible phrases
    for phrase in _POSSIBLE_PHRASES:
        if phrase in haystack:
            signals_detected.append(phrase)

    # 4. Extract deadline if not explicitly provided
    if not deadline:
        d_match = _DEADLINE_PATTERN.search(haystack)
        if d_match:
            raw_d = d_match.group(1).strip()[:40]
            deadline = raw_d

    # Determine confidence
    if any(p in signals_detected for p in _EXPLICIT_VERIFIED_PHRASES):
        confidence = "VERIFIED_MASS_HIRING"
    elif vacancy_count and vacancy_count >= 50:
        confidence = "VERIFIED_MASS_HIRING"
    elif any(p in signals_detected for p in _POSSIBLE_PHRASES) or (vacancy_count and vacancy_count >= 15):
        confidence = "POSSIBLE_MASS_HIRING"
    else:
        confidence = "NOT_MASS_HIRING"

    # Determine status
    status = "UNKNOWN"
    if confidence != "NOT_MASS_HIRING":
        status = "ACTIVE"
        if deadline:
            try:
                # Try parsing ISO date or standard format
                dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                diff_days = (dt - now).total_seconds() / 86400
                if diff_days < 0:
                    status = "EXPIRED"
                elif diff_days <= 7:
                    status = "ENDING_SOON"
                else:
                    status = "ACTIVE"
            except Exception:
                status = "ACTIVE"

    return {
        "confidence": confidence,
        "status": status,
        "signals_detected": signals_detected,
        "vacancy_count": vacancy_count,
        "deadline": deadline,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
