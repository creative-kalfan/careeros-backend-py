"""Job Intelligence service for CareerOS.

Extracts structured intelligence from job descriptions using deterministic
extraction utilities. Does not call external AI APIs in Phase 7A.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from app.models.job import NormalizedJob
from app.models.job_intelligence import (
    CertificationInfo,
    EducationInfo,
    JobIntelligence,
    RequirementInfo,
    SeniorityInfo,
    SkillInfo,
    WorkArrangement,
)
from app.services.jobs.extraction_utils import (
    _SKILL_CATEGORIES,
    classify_seniority,
    classify_work_arrangement,
    extract_certifications,
    extract_education,
    extract_keywords,
    extract_requirements,
    extract_responsibilities,
    extract_years_of_experience,
    normalize_skill_name,
    strip_html,
)

logger = logging.getLogger(__name__)


class JobIntelligenceService:
    """Extract structured intelligence from a NormalizedJob."""

    def analyze_job(self, job: NormalizedJob, job_id: str | None = None) -> JobIntelligence:
        """Analyze a job and return structured intelligence."""
        description = strip_html(job.description or "")
        title = job.title or ""
        text = f"{title}\n{description}"

        seniority_level, seniority_confidence = classify_seniority(description, title)
        years_min, years_max = extract_years_of_experience(text)
        work_type, work_confidence = classify_work_arrangement(description)

        skills = self._extract_skills(description)
        requirements = self._extract_requirements(description)
        education = self._extract_education(description)
        certifications = self._extract_certifications(description)
        responsibilities = extract_responsibilities(description)
        keywords = extract_keywords(text)
        industries = self._extract_industries(description)

        return JobIntelligence(
            job_id=job_id or getattr(job, "id", "") or "",
            intelligence_version="1.0",
            generated_at=datetime.utcnow(),
            seniority=SeniorityInfo(
                level=seniority_level,
                years_min=years_min,
                years_max=years_max,
                confidence=seniority_confidence,
            ),
            skills=skills,
            requirements=requirements,
            education=education,
            certifications=certifications,
            keywords=keywords,
            responsibilities=responsibilities,
            industries=industries,
            work_arrangement=WorkArrangement(
                type=work_type,
                confidence=work_confidence,
            ),
        )

    def _extract_skills(self, description: str) -> list[SkillInfo]:
        """Extract skills from job description."""
        raw_skills: list[str] = []
        try:
            from app.services.ats.job_description_parser import JobDescriptionParser
            parser = JobDescriptionParser()
            raw_skills = parser._extract_skills(description)
        except Exception:
            raw_skills = []

        # Also scan for aliases in the shared normalization dictionary.
        text_lower = description.lower()
        from app.services.jobs.extraction_utils import _SKILL_ALIASES
        for alias, canonical in _SKILL_ALIASES.items():
            pattern = rf"\b{re.escape(alias)}\b"
            if re.search(pattern, text_lower):
                if canonical not in raw_skills:
                    raw_skills.append(canonical)

        skills = []
        seen = set()
        for skill_name in raw_skills:
            normalized = normalize_skill_name(skill_name)
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)

            importance = "mentioned"
            if re.search(rf"\b{re.escape(normalized)}\b.*?(?:required|must|essential|needed)", description, re.IGNORECASE):
                importance = "required"
            elif re.search(rf"\b{re.escape(normalized)}\b.*?(?:preferred|nice|plus|desirable)", description, re.IGNORECASE):
                importance = "preferred"

            evidence = ""
            for sentence in description.replace("\n", " ").split("."):
                if normalized.lower() in sentence.lower():
                    evidence = sentence.strip()[:200]
                    break

            skills.append(SkillInfo(
                name=skill_name,
                normalized_name=normalized,
                category=_SKILL_CATEGORIES.get(normalized.lower()),
                importance=importance,
                evidence=evidence,
                confidence="high" if importance in ("required", "preferred") else "medium",
            ))
        return skills

    def _extract_requirements(self, description: str) -> list[RequirementInfo]:
        """Extract requirements from job description."""
        raw = extract_requirements(description)
        return [
            RequirementInfo(
                text=item["text"],
                type=item["type"],
                importance=item["importance"],
                confidence=item["confidence"],
            )
            for item in raw
        ]

    def _extract_education(self, description: str) -> list[EducationInfo]:
        """Extract education requirements from job description."""
        raw = extract_education(description)
        return [
            EducationInfo(
                degree=item.get("degree"),
                field=item.get("field"),
                required=item.get("required", False),
                confidence=item.get("confidence", "low"),
            )
            for item in raw
        ]

    def _extract_certifications(self, description: str) -> list[CertificationInfo]:
        """Extract certification requirements from job description."""
        raw = extract_certifications(description)
        return [
            CertificationInfo(
                name=item["name"],
                required=item.get("required", False),
                confidence=item.get("confidence", "low"),
            )
            for item in raw
        ]

    def _extract_industries(self, description: str) -> list[str]:
        """Extract industry indicators from job description."""
        industries = []
        text_lower = description.lower()
        industry_keywords = {
            "finance": ["bank", "financial", "fintech", "investment"],
            "technology": ["software", "tech", "saas", "cloud"],
            "healthcare": ["health", "medical", "hospital", "pharma"],
            "retail": ["retail", "e-commerce", "ecommerce"],
            "consulting": ["consulting", "advisory", "professional services"],
            "manufacturing": ["manufacturing", "production", "industrial"],
            "energy": ["energy", "oil", "gas", "renewable"],
            "media": ["media", "entertainment", "streaming"],
            "education": ["education", "edtech", "learning"],
        }
        for industry, keywords in industry_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                industries.append(industry)
        return industries
