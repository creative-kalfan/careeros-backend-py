"""Source priority: source quality as a bounded ranking dimension.

Official company career postings get the strongest boost, aggregator
listings get a penalty, and the total influence on the final 0-100 ranking
is deliberately small (±4 points) so candidate relevance always dominates:

    official 92% match (92 + 4 = 96)  >  secondary 94% match (94 - 1 = 93)
    official 40% match (40 + 4 = 44)  <  official 92% match (92 + 4 = 96)
"""

from __future__ import annotations

from typing import Any

from app.crawlers.source_quality import (
    SOURCE_TIER_AGGREGATOR,
    SOURCE_TIER_OFFICIAL_ATS,
    SOURCE_TIER_OFFICIAL_COMPANY_CAREER,
    SOURCE_TIER_OTHER_VERIFIED_SOURCE,
    SOURCE_TIER_VERIFIED_YC_STARTUP,
)

# Bounded bonus/penalty (points on the 0-100 recommendation scale) per tier.
SOURCE_TIER_BONUS = {
    SOURCE_TIER_OFFICIAL_COMPANY_CAREER: 4.0,
    SOURCE_TIER_OFFICIAL_ATS: 3.0,
    SOURCE_TIER_VERIFIED_YC_STARTUP: 2.0,
    SOURCE_TIER_OTHER_VERIFIED_SOURCE: 0.0,
    SOURCE_TIER_AGGREGATOR: -1.0,
}

_DEFAULT_BONUS = SOURCE_TIER_BONUS[SOURCE_TIER_OTHER_VERIFIED_SOURCE]
_MAX_BONUS = max(SOURCE_TIER_BONUS.values())


def source_quality_bonus(job: Any) -> float:
    """Return the bounded source-quality bonus for a job (or DB row dict).

    Accepts a NormalizedJob or a dict-like row. Unknown/missing tiers get a
    neutral 0 bonus so legacy data ranks exactly as before.
    """
    if job is None:
        return _DEFAULT_BONUS
    tier = None
    if isinstance(job, dict):
        tier = job.get("source_tier")
    else:
        tier = getattr(job, "source_tier", None)
    if tier is None:
        return _DEFAULT_BONUS
    try:
        tier = int(tier)
    except (TypeError, ValueError):
        return _DEFAULT_BONUS
    return SOURCE_TIER_BONUS.get(tier, _DEFAULT_BONUS)


def combined_rank_score(match_overall: float, job: Any) -> float:
    """Final ranking value: candidate match plus the source-quality bonus."""
    return float(match_overall or 0) + source_quality_bonus(job)
