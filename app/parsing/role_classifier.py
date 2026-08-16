"""RoleClassifier

Maps job titles and free-text user target-role input into role category buckets.
Uses a centralized taxonomy with exact canonical role matching, alias matching,
and keyword patterns as fallbacks.

Usable on BOTH job titles and user free-text target-role input.
"""

from __future__ import annotations

from typing import Sequence

from app.parsing.role_taxonomy import (
    _CATEGORY_FOR_CANONICAL,
    _CANONICAL_FOR_ALIAS,
    get_category_for_role,
    normalize_role,
)

RoleCategory = str

# Keyword -> category mapping as fallback for roles not yet in the taxonomy.
# Longer/more-specific patterns are checked first to prevent false matches.
_FALLBACK_PATTERNS: list[tuple[list[str], str]] = [
    (
        [
            "engineering manager",
            "tech lead",
            "team lead",
            "director of engineering",
            "director, engineering",
            "head of engineering",
        ],
        "Management",
    ),
    (
        [
            "product manager",
            "product owner",
            "product lead",
            "head of product",
            "director of product",
        ],
        "Product & Business",
    ),
    (
        [
            "devops",
            "sre",
            "site reliability",
            "platform engineer",
            "infrastructure engineer",
            "release engineer",
        ],
        "Software Engineering",
    ),
    (
        [
            "qa engineer",
            "test engineer",
            "automation engineer",
            "quality assurance",
            "qa lead",
            "test lead",
            "qa manager",
        ],
        "Software Engineering",
    ),
    (
        [
            "ios engineer",
            "android engineer",
            "mobile engineer",
            "mobile developer",
            "swift developer",
            "kotlin developer",
            "react native",
        ],
        "Software Engineering",
    ),
    (
        [
            "ux designer",
            "ui designer",
            "product designer",
            "interaction designer",
            "visual designer",
            "graphic designer",
            "design lead",
            "head of design",
            "user researcher",
        ],
        "Design & Creative",
    ),
    (
        [
            "security engineer",
            "security analyst",
            "detection and response",
            "appsec",
            "infosec",
        ],
        "Software Engineering",
    ),
    (
        [
            "developer advocate",
            "devrel",
            "technical evangelist",
        ],
        "Software Engineering",
    ),
    (
        [
            "software engineer",
            "software eng",
            "swe",
            "backend engineer",
            "backend eng",
            "frontend engineer",
            "frontend eng",
            "front-end engineer",
            "back-end engineer",
            "full stack",
            "full-stack",
            "staff engineer",
            "principal engineer",
            "software developer",
            "software dev",
            "web developer",
            "application engineer",
            "support engineer",
        ],
        "Software Engineering",
    ),
]

_ALL_CATEGORIES: list[RoleCategory] = [
    "Software Engineering",
    "Product & Business",
    "Data & Analytics",
    "Finance & BFSI",
    "Sales & Marketing",
    "HR & People",
    "Design & Creative",
    "Customer & Operations",
    "Supply Chain & Logistics",
    "Engineering (Core)",
    "Healthcare, Science & Other Professional",
    "Other",
]


def classify(text: str | None) -> str:
    """Classify a job title or user free-text target-role input into a role_category.

    Returns the matched ``RoleCategory``, or ``"Other"`` if nothing matches
    (including None/non-string input).
    """
    if not text or not isinstance(text, str):
        return "Other"

    # Try taxonomy-based normalization first.
    canonical = normalize_role(text)
    if canonical:
        category = get_category_for_role(canonical)
        if category:
            return category

    # Fallback: keyword patterns.
    normalized = text.lower()
    for keywords, category in _FALLBACK_PATTERNS:
        for keyword in keywords:
            if keyword in normalized:
                return category

    return "Other"


def classify_many(texts: Sequence[str]) -> list[RoleCategory]:
    """Classify multiple texts and return deduplicated set of categories."""
    categories: set[str] = set()
    for text in texts:
        categories.add(classify(text))
    return list(categories)


def get_all_categories() -> list[RoleCategory]:
    """Get all valid role categories (for validation, UI dropdowns, etc.)"""
    return list(_ALL_CATEGORIES)