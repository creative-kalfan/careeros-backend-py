"""Explainable recommendation reason generator."""

from __future__ import annotations

from typing import Any


class RecommendationReasonGenerator:
    """Generates human-readable recommendation reasons.

    Inputs are normalized 0-100 factor scores from PersonalizedJobService plus
    booleans derived from profile/job comparison. Mirrors legacy behavior but
    sources scores from the canonical matching service.
    """

    def generate(
        self,
        match: dict[str, float],
        job: Any,
        profile: Any,
        scoring: dict,
        matched_skills: list[str],
        missing_skills: list[str],
    ) -> list[dict[str, Any]]:
        reasons: list[dict[str, Any]] = []

        overall = match.get("overall", 0)
        role = match.get("role_match", 0)
        skill = match.get("skill_match", 0)
        resume = match.get("resume_match", 0)
        exp = match.get("experience_match", 0)
        loc = match.get("location_match", 0)
        salary = match.get("salary_match", 0)
        company = match.get("company_preference", 0)
        fresh = match.get("freshness", 0)

        # High overall -> resume/role alignment
        if overall >= 90:
            reasons.append({"type": "resume_match", "message": "Excellent resume match.", "weight": 1.0})
        elif overall >= 75:
            reasons.append({"type": "resume_match", "message": "Strong skill overlap.", "weight": 0.9})

        if skill >= 75:
            reasons.append({"type": "skills", "message": "Strong skill overlap.", "weight": 0.85, "evidence": ", ".join(matched_skills[:5]) if matched_skills else None})
        elif skill >= 50 and matched_skills:
            reasons.append({"type": "skills", "message": f"Matches {len(matched_skills)} of your skills.", "weight": 0.7})

        if missing_skills and skill < 50:
            # Inform about gap without being a blocking reason
            pass

        if role >= 80:
            reasons.append({"type": "role", "message": "Matches preferred role.", "weight": 0.8})
        elif role >= 60:
            reasons.append({"type": "role", "message": "Related to your target role.", "weight": 0.65})

        if loc >= 80:
            reasons.append({"type": "location", "message": "Matches preferred location.", "weight": 0.8})
        elif loc >= 60:
            reasons.append({"type": "location", "message": "Location partially matches.", "weight": 0.6})

        # Remote handling derived from location_match + job.remote
        is_remote = bool(getattr(job, "remote", False))
        if is_remote and loc >= 60:
            reasons.append({"type": "remote", "message": "Matches remote preference.", "weight": 0.7})

        if company >= 100:
            reasons.append({"type": "company", "message": "Matches desired company.", "weight": 0.75})

        if exp >= 75:
            reasons.append({"type": "experience", "message": "Fits the requested experience level.", "weight": 0.65})

        if salary >= 75:
            reasons.append({"type": "salary", "message": "Fits the target compensation range.", "weight": 0.6})

        if fresh >= 85:
            reasons.append({"type": "recency", "message": "Recently posted.", "weight": 0.65})
        elif fresh >= 70:
            reasons.append({"type": "recency", "message": "Posted within 2 weeks.", "weight": 0.5})

        # ATS proxy: high overall implies strong ATS prediction
        if overall >= 85 and not any(r["type"] == "resume_match" for r in reasons):
            reasons.append({"type": "ats", "message": "High ATS prediction.", "weight": 0.8})

        # Cap to 6 reasons, ordered by weight
        reasons.sort(key=lambda r: r["weight"], reverse=True)
        return reasons[:6]
