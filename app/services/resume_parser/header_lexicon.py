"""Header lexicon for resume section detection."""

from __future__ import annotations

from typing import Dict, List, Set

# Centralized header lexicon - all variations of section headers
HEADER_LEXICON: Dict[str, List[str]] = {
    "experience": [
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
        "work history",
        "career history",
        "career experience",
        "professional background",
        "work background",
    ],
    "education": [
        "education",
        "academic background",
        "academic qualifications",
        "qualifications",
        "educational background",
        "academic history",
        "degrees",
    ],
    "skills": [
        "skills",
        "technical skills",
        "core skills",
        "technical expertise",
        "competencies",
        "skills & technologies",
        "skills and technologies",
        "technology skills",
        "tech stack",
        "technologies",
        "programming languages",
        "tools & technologies",
        "tools and technologies",
    ],
    "projects": [
        "projects",
        "selected projects",
        "academic projects",
        "personal projects",
        "key projects",
        "notable projects",
        "project experience",
        "project highlights",
    ],
    "certifications": [
        "certifications",
        "certificates",
        "licenses & certifications",
        "licenses and certifications",
        "professional certifications",
        "certifications & licenses",
        "credentials",
    ],
    "summary": [
        "summary",
        "professional summary",
        "profile",
        "career summary",
        "objective",
        "career objective",
        "professional profile",
        "about me",
        "about",
        "overview",
    ],
    "achievements": [
        "achievements",
        "accomplishments",
        "awards",
        "honors",
        "awards & honors",
        "awards and honors",
        "recognition",
    ],
    "languages": [
        "languages",
        "language proficiency",
        "language skills",
        "linguistic skills",
    ],
    "links": [
        "links",
        "profiles",
        "online profiles",
        "social links",
        "websites",
        "portfolio",
    ],
    "internships": [
        "internships",
        "internship",
        "internship experience",
    ],
    "leadership": [
        "leadership",
        "volunteer",
        "extracurricular",
        "leadership & activities",
        "activities",
    ],
}

# Flattened set for quick lookup
ALL_HEADER_KEYWORDS: Set[str] = set()
for keywords in HEADER_LEXICON.values():
    ALL_HEADER_KEYWORDS.update(k.lower() for k in keywords)

# Section priority order (for determining main sections)
SECTION_PRIORITY = [
    "experience",
    "education",
    "skills",
    "projects",
    "certifications",
    "summary",
    "achievements",
    "languages",
    "links",
    "internships",
    "leadership",
]

# Normalization helpers
def normalize_header(text: str) -> str:
    """Normalize a header string for matching."""
    import re
    # Trim whitespace
    text = text.strip()
    # Lowercase
    text = text.lower()
    # Normalize repeated whitespace
    text = re.sub(r"\s+", " ", text)
    # Normalize punctuation: &, /, -, _ to space
    text = re.sub(r"[&/_-]", " ", text)
    # Normalize repeated whitespace again
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def match_section_header(text: str) -> str | None:
    """Match a line against known section headers. Returns section key or None."""
    normalized = normalize_header(text)
    if not normalized:
        return None

    # Section headers are concise titles (e.g. "Work Experience", "Core Skills"),
    # not full sentences or job entries. Body lines containing keywords must not match.
    words = normalized.split()
    if len(words) > 5:
        return None

    # Direct match
    for section, keywords in HEADER_LEXICON.items():
        for kw in keywords:
            if normalize_header(kw) == normalized:
                return section

    # Partial match - check if normalized text contains a keyword as whole word
    import re
    for section, keywords in HEADER_LEXICON.items():
        for kw in keywords:
            kw_norm = normalize_header(kw)
            # Match whole word
            if re.search(rf"\b{re.escape(kw_norm)}\b", normalized):
                return section

    return None


def is_likely_header(text: str, font_size: float, body_font_size: float, bold: bool) -> tuple[bool, str | None]:
    """
    Determine if a line is likely a section header.
    Returns (is_header, section_key).
    """
    section = match_section_header(text)
    if section:
        return True, section

    stripped = text.strip()
    if not stripped:
        return False, None

    # Heuristics for headers without lexicon match
    is_short = len(stripped) < 60
    is_all_caps = stripped.isupper() and len(stripped) > 2
    is_larger_font = font_size > body_font_size * 1.15
    is_bold = bold

    # Strong typography signals
    if is_all_caps and is_short:
        return True, None
    if is_bold and is_short and is_larger_font:
        return True, None
    if is_larger_font and is_short:
        return True, None

    return False, None