"""Canonical skill vocabulary for crawler skill extraction.

Single source of truth for the lightweight ``_KNOWN_SKILLS`` substring scan
used by ATS adapters and aggregators. Previously duplicated verbatim across
5 modules (ashby, greenhouse, lever, smartrecruiters, adzuna); any drift
between copies would silently skew skill coverage per source.

Behavior is intentionally preserved exactly: case-insensitive substring match,
canonical-list order, empty input -> [].
"""

from __future__ import annotations

__all__ = ["KNOWN_SKILLS", "extract_known_skills"]

KNOWN_SKILLS: list[str] = [
    "typescript", "javascript", "react", "next.js", "node", "python",
    "java", "sql", "postgresql", "aws", "docker", "kubernetes", "graphql",
    "rest", "agile", "leadership", "communication", "product", "figma",
    "tailwind", "supabase", "redis", "mongodb", "machine learning",
    "data analysis", "project management",
]


def extract_known_skills(text: str) -> list[str]:
    """Return canonical skills found as case-insensitive substrings of ``text``."""
    normalized = (text or "").lower()
    return [s for s in KNOWN_SKILLS if s in normalized]
