"""Numeric Fabrication Guard for CareerOS Tailoring Pipeline.

Deterministic validation guard to ensure that tailored resume ASTs do not
fabricate, hallucinate, or inflate quantitative metrics, percentages, multipliers,
or numerical figures not present in the candidate's verified source profile.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.models.resume import ResumeProfile

logger = logging.getLogger(__name__)

# Regular expressions for quantitative metrics, percentages, multipliers, numbers
_NUMBER_PATTERN = re.compile(
    r"(?:\b\d+(?:,\d{3})*(?:\.\d+)?%?\+?|\b\d+[kKmMbB]\b|\b\d+x\b)",
    re.IGNORECASE,
)
_DATE_YEAR_PATTERN = re.compile(r"^(?:19|20)\d{2}$")


class NumericFabricationGuard:
    """Extracts and verifies quantitative metrics between source and tailored ASTs."""

    @staticmethod
    def extract_numbers(text: Optional[str]) -> Set[str]:
        """Extract canonical normalized numerical strings from text."""
        if not text or not isinstance(text, str):
            return set()

        tokens = set()
        matches = _NUMBER_PATTERN.findall(text)
        for m in matches:
            norm = m.strip().lower()
            # Ignore plain 4-digit years (e.g., 2020, 2024) to allow normal date handling
            if _DATE_YEAR_PATTERN.fullmatch(norm):
                continue
            # Remove leading zeros/commas for normalization
            norm_clean = norm.replace(",", "")
            tokens.add(norm_clean)
        return tokens

    @classmethod
    def extract_profile_numbers(cls, profile: ResumeProfile) -> Set[str]:
        """Extract all valid quantitative numbers from candidate source profile."""
        nums: Set[str] = set()

        if profile.summary:
            nums.update(cls.extract_numbers(profile.summary))

        if profile.skills:
            for s in (profile.skills.technical or []) + (profile.skills.tools or []) + (profile.skills.soft_skills or []):
                nums.update(cls.extract_numbers(s))

        for exp in profile.experience:
            nums.update(cls.extract_numbers(exp.role))
            nums.update(cls.extract_numbers(exp.company))
            for b in exp.responsibilities:
                nums.update(cls.extract_numbers(b.text if hasattr(b, "text") else str(b)))
            for ach in exp.achievements:
                nums.update(cls.extract_numbers(ach))

        for edu in profile.education:
            nums.update(cls.extract_numbers(edu.degree))
            nums.update(cls.extract_numbers(edu.institution))
            for cw in edu.coursework:
                nums.update(cls.extract_numbers(cw))

        for proj in profile.projects:
            nums.update(cls.extract_numbers(proj.name))
            nums.update(cls.extract_numbers(proj.description))
            for b in proj.bullets:
                nums.update(cls.extract_numbers(b.text if hasattr(b, "text") else str(b)))

        for cert in profile.certifications:
            nums.update(cls.extract_numbers(cert.name if hasattr(cert, "name") else str(cert)))

        return nums

    @classmethod
    def audit_tailored_profile(
        cls,
        source_profile: ResumeProfile,
        tailored_profile_dict: Dict[str, Any],
        strict: bool = False,
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Audit tailored profile against source profile numbers.

        If ungrounded numbers are found:
        - Logs violations and returns flagged issues.
        """
        source_nums = cls.extract_profile_numbers(source_profile)
        issues: List[str] = []
        cleaned_dict = dict(tailored_profile_dict)

        # 1. Audit Summary
        summary = cleaned_dict.get("summary")
        if summary and isinstance(summary, str):
            tailored_summary_nums = cls.extract_numbers(summary)
            ungrounded = tailored_summary_nums - source_nums
            if ungrounded:
                msg = f"Ungrounded numbers in tailored summary: {', '.join(sorted(ungrounded))}"
                logger.warning(msg)
                issues.append(msg)

        # 2. Audit Experience Bullets
        experiences = cleaned_dict.get("experience")
        if isinstance(experiences, list):
            for exp_idx, exp in enumerate(experiences):
                if not isinstance(exp, dict):
                    continue
                resps = exp.get("responsibilities") or []
                for b_idx, b in enumerate(resps):
                    b_text = b.get("text") if isinstance(b, dict) else str(b)
                    b_nums = cls.extract_numbers(b_text)
                    ungrounded = b_nums - source_nums
                    if ungrounded:
                        msg = (
                            f"Ungrounded numbers in experience bullet [exp {exp_idx}, bullet {b_idx}]: "
                            f"{', '.join(sorted(ungrounded))}"
                        )
                        logger.warning(msg)
                        issues.append(msg)

        # 3. Audit Projects
        projects = cleaned_dict.get("projects")
        if isinstance(projects, list):
            for prj_idx, prj in enumerate(projects):
                if not isinstance(prj, dict):
                    continue
                desc = prj.get("description")
                if desc and isinstance(desc, str):
                    p_nums = cls.extract_numbers(desc)
                    ungrounded = p_nums - source_nums
                    if ungrounded:
                        msg = f"Ungrounded numbers in project description [prj {prj_idx}]: {', '.join(sorted(ungrounded))}"
                        logger.warning(msg)
                        issues.append(msg)

        return cleaned_dict, issues


numeric_guard = NumericFabricationGuard()
