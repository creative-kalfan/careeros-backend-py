"""Recommendation scorer: wraps PersonalizedJobService scoring.

Reuses the canonical 8-factor PersonalizedJobService.calculate_match_score
rather than inventing a parallel algorithm. Maps the overall score to
priority/level and threshold for recommendation.
"""

from __future__ import annotations

from typing import Optional


class RecommendationScorer:
    """Deterministic scorer that delegates to the existing matching system.

    The recommendation score IS the personalized overall match score (0-100).
    No duplicate weights are introduced; we reuse PersonalizedJobService's
    weights: role 20, skill 20, resume 15, experience 10, location 15,
    salary 10, company 5, freshness 5.

    Priority thresholds mirror the legacy RecommendationScorer:
        >=90 excellent, >=80 strong, >=70 good, >=60 possible, <60 no-rec.
    """

    def score(self, overall: float) -> dict:
        score = int(round(max(0, min(100, overall))))
        level = self._level_for_score(score)
        priority = self._priority_for_score(score)
        return {
            "score": score,
            "level": level,
            "priority": priority,
            "should_recommend": score >= 60 and priority is not None,
        }

    @staticmethod
    def _level_for_score(score: int) -> str:
        if score >= 90:
            return "Excellent Match"
        if score >= 80:
            return "Strong Match"
        if score >= 70:
            return "Good Match"
        if score >= 60:
            return "Possible Match"
        return "Do not recommend"

    @staticmethod
    def _priority_for_score(score: int) -> Optional[str]:
        if score >= 90:
            return "excellent"
        if score >= 80:
            return "strong"
        if score >= 70:
            return "good"
        if score >= 60:
            return "possible"
        return None
