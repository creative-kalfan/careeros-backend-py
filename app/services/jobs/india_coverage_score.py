"""India coverage scoring: small internal prioritization model (task §4).

Scores a candidate source on 0-100 for India-first prioritization. India
relevance carries the strongest weight so a source with 10,000 global jobs
but 20 Indian jobs never outranks 300 highly relevant Indian jobs.

Reusable and pipeline-independent: callers pass plain signals, no DB/HTTP.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# Weights sum to 1.0 before the cost penalty. India relevance dominates.
WEIGHTS = {
    "india_relevance": 0.35,
    "india_volume": 0.15,
    "target_role": 0.15,
    "coverage_gap": 0.15,
    "reliability": 0.10,
    "incremental": 0.10,
}

# Cost penalty scale (subtracted after weighting, max 10 points).
COST_PENALTY_MAX = 10.0
COST_NORM_REQUESTS = 50.0  # 50+ requests saturates the penalty


@dataclass(frozen=True)
class SourceSignals:
    """Plain signals for one candidate source (all 0-1 unless noted)."""

    india_relevance: float = 0.0  # share of inventory that is India-relevant
    india_job_volume: int = 0  # absolute India-relevant inventory
    target_role_relevance: float = 0.0  # share in target roles
    coverage_gap: float = 0.0  # 1 = entirely uncovered, 0 = already covered
    reliability: float = 0.5  # source stability (ATS > career page > aggregator)
    incremental_potential: float = 0.0  # expected share of new unique jobs
    crawl_requests: int = 1  # estimated requests per crawl (>=1)
    crawl_failure_rate: float = 0.0  # 0-1 recent failure share


def _clamp01(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _volume_score(volume: int) -> float:
    """Log-scaled 0-1 volume score (1000 India jobs saturates)."""
    try:
        volume = max(0, int(volume))
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, math.log1p(volume) / math.log1p(1000))


def _cost_penalty(requests: int, failure_rate: float) -> float:
    req = max(1, int(requests or 1))
    cost = min(1.0, req / COST_NORM_REQUESTS)
    failures = _clamp01(failure_rate)
    return COST_PENALTY_MAX * (0.7 * cost + 0.3 * failures)


def score_source(signals: SourceSignals) -> float:
    """Return a 0-100 India-first priority score for one source."""
    weighted = (
        WEIGHTS["india_relevance"] * _clamp01(signals.india_relevance)
        + WEIGHTS["india_volume"] * _volume_score(signals.india_job_volume)
        + WEIGHTS["target_role"] * _clamp01(signals.target_role_relevance)
        + WEIGHTS["coverage_gap"] * _clamp01(signals.coverage_gap)
        + WEIGHTS["reliability"] * _clamp01(signals.reliability)
        + WEIGHTS["incremental"] * _clamp01(signals.incremental_potential)
    )
    raw = 100.0 * weighted
    return round(max(0.0, min(100.0, raw - _cost_penalty(signals.crawl_requests, signals.crawl_failure_rate))), 2)


def rank_sources(scored: dict[str, SourceSignals]) -> list[tuple[str, float]]:
    """Rank named sources best-first by score (deterministic, ties by name)."""
    ranked = [(name, score_source(sig)) for name, sig in scored.items()]
    ranked.sort(key=lambda kv: (-kv[1], kv[0]))
    return ranked
