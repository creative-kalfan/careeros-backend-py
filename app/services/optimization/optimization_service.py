"""AI Resume Optimization Service for CareerOS Resume Module (Step 5).

Provides AI-powered resume optimization suggestions based on ATS analysis.
All suggestions are validated against the candidate's existing structured resume data.
Never invents experience, skills, companies, or metrics.
"""
from __future__ import annotations

import re
import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from app.models.ats import (
    ATSAnalysisResult,
    ATSScoringConfig,
    RequirementCoverage,
    EvidenceLevel,
    JobRequirementType,
    ParsedJobDescription,
)
from app.models.resume import ResumeContent, ResumeProfile
from app.services.ats.job_description_parser import JobDescriptionParser
from app.services.ats.ats_analyzer import ATSAnalyzer
from app.llm.gateway import get_llm_gateway
from app.llm.types import LLMRequest, LLMTask, LLMProviderError, ResumeSectionSuggestion

logger = logging.getLogger(__name__)


class OptimizationError(Exception):
    """Raised when optimization cannot be performed safely."""
    pass


class OptimizationResult:
    """Structured result from an optimization operation."""
    def __init__(
        self,
        success: bool,
        suggestions: List[Dict[str, Any]] = None,
        evidence_issues: List[str] = None,
        message: str = "",
    ):
        self.success = success
        self.suggestions = suggestions or []
        self.evidence_issues = evidence_issues or []
        self.message = message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "suggestions": self.suggestions,
            "evidence_issues": self.evidence_issues,
            "message": self.message,
        }


class OptimizationService:
    """Core optimization engine that generates evidence-validated suggestions."""

    def __init__(self, config: Optional[ATSScoringConfig] = None):
        self.ats_analyzer = ATSAnalyzer()
        self.config = config or ATSScoringConfig()

    # ---- Evidence Context Building ----

    def _build_evidence_context(self, resume_content: ResumeContent) -> Dict[str, Any]:
        """Build a context map of verified candidate data for evidence validation."""
        profile = resume_content.profile

        context = {
            "skills": {
                "technical": profile.skills.technical if profile.skills else [],
                "tools": profile.skills.tools if profile.skills else [],
                "languages": profile.skills.languages if profile.skills else [],
                "databases": profile.skills.databases if profile.skills else [],
                "analytics": profile.skills.analytics if profile.skills else [],
                "soft_skills": profile.skills.soft_skills if profile.skills else [],
                "custom": profile.skills.custom if profile.skills else {},
            }
            if profile.skills
            else {},

            "experience": [
                {
                    "company": exp.company,
                    "role": exp.role,
                    "location": exp.location,
                    "responsibilities": exp.get_responsibility_texts(),
                    "achievements": exp.achievements,
                    "tools": exp.tools,
                    "metrics": exp.metrics,
                }
                for exp in profile.experience
            ]
            if profile.experience
            else [],

            "projects": [
                {
                    "name": proj.name,
                    "description": proj.description,
                    "contribution": proj.contribution,
                    "technologies": proj.technologies,
                    "results": proj.results,
                    "metrics": proj.metrics,
                }
                for proj in profile.projects
            ]
            if profile.projects
            else [],

            "education": [
                {
                    "institution": edu.institution,
                    "degree": edu.degree,
                    "field": edu.field,
                    "gpa": edu.gpa,
                    "coursework": edu.coursework,
                    "achievements": edu.achievements,
                }
                for edu in profile.education
            ]
            if profile.education
            else [],

            "certifications": [
                {"name": cert.name, "issuer": cert.issuer}
                for cert in profile.certifications
            ]
            if profile.certifications
            else [],

            "achievements": profile.achievements if profile.achievements else [],

            "languages": [
                {"language": lang.language, "proficiency": lang.proficiency}
                for lang in profile.languages
            ]
            if profile.languages
            else [],

            "summary": profile.summary or "",
        }

        return context

    # ---- Suggestion Generation ----

    def generate_summary_optimization(
        self,
        resume_content: ResumeContent,
        job_description: str,
        job_title: Optional[str] = None,
    ) -> OptimizationResult:
        """Generate professional summary optimization suggestions."""
        profile = resume_content.profile
        context = self._build_evidence_context(resume_content)
        parser = JobDescriptionParser()
        parsed_jd = parser.parse_job_description(job_description, job_title)

        suggestions = []

        # Analyze current summary against JD requirements
        current_summary = profile.summary or ""
        if not current_summary:
            return OptimizationResult(
                success=False,
                message="No summary present in resume.",
                evidence_issues=["Resume has no summary section."],
            )

        # Extract key requirements from JD
        required_skills = parsed_jd.required_skills or []
        preferred_skills = parsed_jd.preferred_skills or []
        key_responsibilities = parsed_jd.responsibilities or []

        # Find matching skills from resume
        resume_skills_set = set()
        if profile.skills:
            for item in (
                profile.skills.technical
                + profile.skills.tools
                + profile.skills.languages
                + profile.skills.databases
                + profile.skills.analytics
                + profile.skills.soft_skills
            ):
                resume_skills_set.add(item.lower())

        # Generate suggestion if we have matching content
        matching_skills = [s for s in required_skills if s.lower() in resume_skills_set]

        if matching_skills or current_summary:
            # Build a suggested summary that incorporates matching skills
            # but ONLY using information actually present in the resume
            summary_parts = []

            # Always include the current summary as base
            summary_parts.append(current_summary)

            # Append skill mentions if we have matching skills
            if matching_skills:
                skill_mentions = ", ".join(matching_skills[:3])
                summary_parts.append(
                    f" experienced with {skill_mentions}"
                )

            suggested_summary = " ".join(summary_parts)

            suggestions.append(
                {
                    "type": "professional_summary",
                    "currentText": current_summary,
                    "suggestedText": suggested_summary,
                    "explanation": (
                        f"Incorporated {len(matching_skills)} matching job skills "
                        "while preserving your actual experience."
                    )
                    if matching_skills
                    else "Preserves your original summary with minor formatting.",
                    "evidence": matching_skills,
                    "affectedKeywords": matching_skills,
                }
            )
        else:
            # Not enough information for a meaningful suggestion
            suggestions.append(
                {
                    "type": "professional_summary",
                    "currentText": current_summary,
                    "suggestedText": current_summary,  # Keep as-is
                    "explanation":
                        "Not enough verified information to generate a stronger summary.",
                    "evidence": [],
                    "affectedKeywords": [],
                    "status": "no_change_needed",
                }
            )

        return OptimizationResult(
            success=True,
            suggestions=suggestions,
            message=f"Generated {len(suggestions)} summary optimization suggestion(s).",
        )

    def generate_bullet_optimization(
        self,
        resume_content: ResumeContent,
        job_description: str,
        section: Literal["experience", "projects"],
        entry_id: str,
    ) -> OptimizationResult:
        """Generate bullet point optimization suggestions for experience or projects."""
        profile = resume_content.profile
        context = self._build_evidence_context(resume_content)
        parser = JobDescriptionParser()
        parsed_jd = parser.parse_job_description(job_description)

        suggestions = []
        entry_id_lower = entry_id.lower()

        # Determine which entries to look at
        if section == "experience":
            entries = profile.experience
        else:
            entries = profile.projects

        # Find the matching entry
        matching_entry = None
        for entry in entries:
            if entry_id_lower in entry.id.lower() or entry.id in entry_id_lower:
                matching_entry = entry
                break

        if not matching_entry:
            return OptimizationResult(
                success=False,
                message=f"No {section} entry found with ID: {entry_id}",
                evidence_issues=[f"Could not locate {section} entry."],
            )

        # Extract bullet suggestions based on section type
        if section == "experience":
            current_bullets = matching_entry.get_all_bullet_texts()
        else:
            current_bullets = (
                [matching_entry.description] if matching_entry.description else []
            )

        # Extract key requirements from JD relevant to this section
        key_terms = self._extract_relevant_terms(parsed_jd, section)

        # Generate suggestions for each bullet
        for bullet in current_bullets:
            bullet_suggestions = self._suggest_bullet_improvement(
                bullet, key_terms, section
            )
            for suggestion in bullet_suggestions:
                suggestions.append(
                    {
                        "type": f"{section}_bullet",
                        "section": section,
                        "entryId": matching_entry.id,
                        "currentText": bullet,
                        "suggestedText": suggestion.get("suggested", bullet),
                        "explanation": suggestion.get("explanation", ""),
                        "evidence": suggestion.get("evidence", []),
                        "affectedKeywords": suggestion.get("keywords", []),
                        "status": "pending",
                    }
                )

        return OptimizationResult(
            success=len(suggestions) > 0,
            suggestions=suggestions,
            message=f"Generated {len(suggestions)} bullet optimization suggestion(s).",
        )

    def _extract_relevant_terms(
        self, parsed_jd: ParsedJobDescription, section: Literal["experience", "projects"]
    ) -> List[str]:
        """Extract key terms from JD relevant to a given section."""
        terms = []

        # Get responsibilities
        for resp in parsed_jd.responsibilities:
            terms.append(resp)

        # Get skills
        for skill_list in [
            parsed_jd.required_skills,
            parsed_jd.preferred_skills,
            parsed_jd.technical_skills,
            parsed_jd.soft_skills,
        ]:
            for skill in skill_list:
                terms.append(skill)

        # Get keywords
        for kw in parsed_jd.keywords[:20]:  # Limit to top keywords
            terms.append(kw)

        return list(set(terms))

    def _suggest_bullet_improvement(
        self, bullet: str, key_terms: List[str], section: str
    ) -> Optional[Dict[str, Any]]:
        """Suggest a bullet improvement while validating against evidence."""
        bullet_lower = bullet.lower()
        suggestions = []

        # Check which key terms appear in the existing bullet
        appearing_terms = [t for t in key_terms if t.lower() in bullet_lower]

        if appearing_terms:
            # Term(s) already present - suggest keeping and/or expanding
            suggested_parts = []

            # Check for metrics or specifics that could be added
            has_metric = bool(re.search(r"\b\d+\s*(?:percent|%|years?|hours?|projects?|customers?|revenue|increase|decrease|reduction)\b", bullet, re.I))

            if not has_metric:
                suggested_parts.append(
                    "Consider adding a specific metric or result if you have one."
                )

            # Suggest adding missing key terms that are supported by evidence
            missing_but_relevant = [t for t in appearing_terms if t.lower() not in bullet_lower]

            if missing_but_relevant:
                suggested_parts.append(
                    f"Consider mentioning {' '.join(missing_but_relevant[:2])} if accurately reflected in your work."
                )

            if suggested_parts:
                new_text = bullet + " " + " ".join(suggested_parts)
                suggestions.append(
                    {
                        "suggested": new_text,
                        "explanation": (
                            "Enhances the bullet with relevant terms from the job description "
                            "while preserving your actual experience. "
                            f"Key terms found: {', '.join(appearing_terms)}."
                        ),
                        "evidence": appearing_terms,
                        "keywords": appearing_terms,
                    }
                )
            else:
                # Term(s) already present, no need to add more
                suggestions.append(
                    {
                        "suggested": bullet,
                        "explanation": "Bullet already includes relevant terms from the job description.",
                        "evidence": appearing_terms,
                        "keywords": appearing_terms,
                    }
                )
        else:
            # No key terms appear in the bullet
            if len(bullet.strip()) > 10:
                suggested_parts = [
                    "Consider rephrasing to align with the job description's focus."
                ]

                if suggested_parts:
                    new_text = bullet + " " + suggested_parts[0]
                    suggestions.append(
                        {
                            "suggested": new_text,
                            "explanation":
                                "Rephrasing suggestion based on job description terminology. "
                                "Ensures the language aligns with the role you're targeting.",
                            "evidence": [],
                            "keywords": [],
                        }
                    )

        return suggestions if suggestions else []

    def generate_skills_alignment(
        self,
        resume_content: ResumeContent,
        job_description: str,
    ) -> OptimizationResult:
        """Generate skills alignment suggestions."""
        profile = resume_content.profile
        parser = JobDescriptionParser()
        parsed_jd = parser.parse_job_description(job_description)

        suggestions = []

        # Get resume skills set
        resume_skills_set = set()
        if profile.skills:
            for item in (
                profile.skills.technical
                + profile.skills.tools
                + profile.skills.languages
                + profile.skills.databases
                + profile.skills.analytics
                + profile.skills.soft_skills
            ):
                resume_skills_set.add(item.lower())

        # Get JD skills
        jd_skills = set()
        for skill_list in [
            parsed_jd.required_skills,
            parsed_jd.preferred_skills,
            parsed_jd.technical_skills,
            parsed_jd.soft_skills,
        ]:
            for skill in skill_list:
                jd_skills.add(skill.lower())

        # Categorize
        already_present = resume_skills_set & jd_skills
        missing = jd_skills - resume_skills_set

        # Suggestions for already-present skills
        for skill in already_present:
            suggestions.append(
                {
                    "type": "skills_alignment",
                    "category": "already_present",
                    "skill": next(
                        (s for s in parsed_jd.required_skills + parsed_jd.preferred_skills + parsed_jd.technical_skills + parsed_jd.soft_skills if s.lower() == skill),
                        skill,
                    ),
                    "evidence": "present in resume",
                    "action": "keep",
                }
            )

        # Suggestions for missing skills
        for skill in list(missing)[:5]:  # Limit to top 5
            suggestions.append(
                {
                    "type": "skills_alignment",
                    "category": "missing_without_evidence",
                    "skill": skill,
                    "evidence": "not found in resume",
                    "action": "do_not_add",
                    "message":
                        f"'{skill}' appears in the job description but was not found in your resume. "
                        "Add it only if you genuinely have experience with this skill.",
                }
            )

        # Suggestions for skills that might be there but under different names
        for skill in list(missing)[:3]:
            similar = [
                rs
                for rs in resume_skills_set
                if skill in rs or rs in skill
            ]
            if similar:
                suggestions.append(
                    {
                        "type": "skills_alignment",
                        "category": "possibly_present",
                        "skill": skill,
                        "similar_in_resume": similar[0],
                        "evidence": f"Similar skill '{similar[0]}' found in resume",
                        "action": "verify",
                        "message":
                            f"'{similar[0]}' appears in your resume. "
                            "Verify this matches the job requirement before listing.",
                    }
                )

        return OptimizationResult(
            success=True,
            suggestions=suggestions,
            message=f"Skills analysis: {len(already_present)} present, {len(missing)} missing.",
        )

    def generate_skills_optimization_llm(
        self,
        resume_content: ResumeContent,
        job_description: str,
        job_title: Optional[str] = None,
    ) -> OptimizationResult:
        """Generate LLM-powered skills optimization suggestions.

        Uses the LLM Gateway to produce structured ResumeSectionSuggestion
        objects. Context is minimized to only the skills-relevant subset.
        """
        import asyncio

        profile = resume_content.profile
        parser = JobDescriptionParser()
        parsed_jd = parser.parse_job_description(job_description, job_title)

        current_skills: List[str] = []
        if profile.skills:
            current_skills = list(
                set(
                    profile.skills.technical
                    + profile.skills.tools
                    + profile.skills.languages
                    + profile.skills.databases
                    + profile.skills.analytics
                    + profile.skills.soft_skills
                )
            )

        jd_skills = list(
            set(
                parsed_jd.required_skills
                + parsed_jd.preferred_skills
                + parsed_jd.technical_skills
                + parsed_jd.soft_skills
            )
        )

        already_present = [s for s in jd_skills if s.lower() in [cs.lower() for cs in current_skills]]
        missing = [s for s in jd_skills if s.lower() not in [cs.lower() for cs in current_skills]]

        context_parts = [
            f"Target role: {job_title or 'Not specified'}",
            f"Current skills: {', '.join(current_skills) if current_skills else 'None listed'}",
            f"JD skills: {', '.join(jd_skills) if jd_skills else 'None extracted'}",
            f"Already present: {', '.join(already_present) if already_present else 'None'}",
            f"Missing from resume: {', '.join(missing[:10]) if missing else 'None'}",
        ]
        prompt = "\n".join(context_parts)

        system_instruction = (
            "You are a resume optimization assistant. "
            "Generate a structured skills-section suggestion for the candidate. "
            "Do NOT invent skills the candidate does not have. "
            "Do NOT claim a skill is present merely because the JD requests it. "
            "If a skill is missing but relevant, label it as a recommendation, not as existing. "
            "Return ONLY a JSON object with fields: section, operation, original_content, "
            "suggested_content, rationale, confidence."
        )

        try:
            gateway = get_llm_gateway()
            response = asyncio.run(
                gateway.generate(
                    LLMRequest(
                        task=LLMTask.RESUME_SECTION_SUGGESTION,
                        prompt=prompt,
                        system_instruction=system_instruction,
                        temperature=0.7,
                        max_tokens=512,
                        metadata={"section": "skills"},
                    )
                )
            )
        except LLMProviderError as exc:
            logger.warning("LLM skills optimization failed: %s", exc)
            return OptimizationResult(
                success=False,
                message="AI suggestions are temporarily unavailable. Please try again.",
                evidence_issues=[str(exc)],
            )

        try:
            import json

            data = json.loads(response.content)
        except (ValueError, json.JSONDecodeError):
            return OptimizationResult(
                success=False,
                message="AI returned an invalid response. Please try again.",
                evidence_issues=["Malformed LLM response"],
            )

        # Validate through Pydantic schema
        try:
            suggestion = ResumeSectionSuggestion.model_validate(data)
        except Exception:
            return OptimizationResult(
                success=False,
                message="AI returned an invalid response format. Please try again.",
                evidence_issues=["LLM response failed schema validation"],
            )

        # Enforce section and operation constraints
        if suggestion.section != "skills":
            return OptimizationResult(
                success=False,
                message="AI returned an unexpected response. Please try again.",
                evidence_issues=[f"Expected section 'skills', got '{suggestion.section}'"],
            )
        if suggestion.operation != "replace":
            return OptimizationResult(
                success=False,
                message="AI returned an unexpected response. Please try again.",
                evidence_issues=[f"Expected operation 'replace', got '{suggestion.operation}'"],
            )

        suggestions = [
            {
                "type": "skills_alignment_llm",
                "section": suggestion.section,
                "operation": suggestion.operation,
                "currentText": suggestion.original_content or "\n".join(current_skills),
                "suggestedText": suggestion.suggested_content or "\n".join(current_skills),
                "explanation": suggestion.rationale or "AI-generated skills suggestion.",
                "confidence": suggestion.confidence,
                "evidence": already_present + missing[:5],
                "affectedKeywords": jd_skills[:10],
                "status": "pending",
            }
        ]

        return OptimizationResult(
            success=True,
            suggestions=suggestions,
            message=f"Generated LLM skills optimization suggestion via {response.provider.value}.",
        )

    def generate_summary_optimization_llm(
        self,
        resume_content: ResumeContent,
        job_description: str,
        job_title: Optional[str] = None,
    ) -> OptimizationResult:
        """Generate LLM-powered professional summary optimization suggestion.

        Uses the LLM Gateway to produce a structured ResumeSectionSuggestion
        for the summary section. Context is minimized to only relevant fields.
        The LLM must not invent employers, skills, metrics, or experience.
        """
        import asyncio

        profile = resume_content.profile
        parser = JobDescriptionParser()
        parsed_jd = parser.parse_job_description(job_description, job_title)

        current_summary = profile.summary or ""

        # Build minimal candidate context for factual grounding
        current_skills: List[str] = []
        if profile.skills:
            current_skills = list(
                set(
                    profile.skills.technical
                    + profile.skills.tools
                    + profile.skills.languages
                    + profile.skills.databases
                    + profile.skills.analytics
                    + profile.skills.soft_skills
                )
            )

        experience_highlights: List[str] = []
        if profile.experience:
            for exp in profile.experience[:3]:
                parts = []
                if exp.role:
                    parts.append(exp.role)
                if exp.company:
                    parts.append(f"at {exp.company}")
                if exp.responsibilities:
                    parts.append(f"— {exp.get_responsibility_texts()[0]}")
                experience_highlights.append(" ".join(parts))

        education_highlights: List[str] = []
        if profile.education:
            for edu in profile.education[:2]:
                parts = []
                if edu.degree:
                    parts.append(edu.degree)
                if edu.field:
                    parts.append(f"in {edu.field}")
                if edu.institution:
                    parts.append(f"from {edu.institution}")
                education_highlights.append(" ".join(parts))

        # JD-relevant context
        jd_required = parsed_jd.required_skills[:8]
        jd_preferred = parsed_jd.preferred_skills[:5]
        jd_responsibilities = parsed_jd.responsibilities[:3]

        context_parts = [
            f"Target role: {job_title or parsed_jd.job_title or 'Not specified'}",
            f"Target company: {parsed_jd.company or 'Not specified'}",
            f"Current summary: {current_summary if current_summary else '(empty)'}",
            f"Candidate skills: {', '.join(current_skills) if current_skills else 'None listed'}",
            f"Candidate experience: {'; '.join(experience_highlights) if experience_highlights else 'None listed'}",
            f"Candidate education: {'; '.join(education_highlights) if education_highlights else 'None listed'}",
            f"JD required skills: {', '.join(jd_required) if jd_required else 'None'}",
            f"JD preferred skills: {', '.join(jd_preferred) if jd_preferred else 'None'}",
            f"JD key responsibilities: {'; '.join(jd_responsibilities) if jd_responsibilities else 'None'}",
        ]
        prompt = "\n".join(context_parts)

        system_instruction = (
            "You are a resume optimization assistant specializing in professional summaries. "
            "Generate a concise, targeted professional summary for the candidate's resume. "
            "CRITICAL RULES FOR FACTUAL GROUNDING:\n"
            "- ONLY use information explicitly provided in the candidate context above.\n"
            "- NEVER invent years of experience, employers, job titles, technologies, "
            "certifications, degrees, achievements, metrics, or responsibilities.\n"
            "- If information is absent from the context, OMIT it entirely.\n"
            "- Do NOT fabricate statistics or metrics not present in the resume.\n"
            "- The summary must be grounded in the candidate's actual experience.\n"
            "QUALITY RULES:\n"
            "- Write in concise, professional resume language.\n"
            "- Use ATS-friendly terminology relevant to the target role.\n"
            "- Align the summary with the target job's requirements.\n"
            "- Naturally incorporate relevant keywords from the JD.\n"
            "- Avoid keyword stuffing, generic buzzwords, and excessive adjectives.\n"
            "- The summary should sound like a professional resume, not an AI response.\n"
            "Return ONLY a JSON object with fields: section, operation, original_content, "
            "suggested_content, rationale, confidence."
        )

        try:
            gateway = get_llm_gateway()
            response = asyncio.run(
                gateway.generate(
                    LLMRequest(
                        task=LLMTask.RESUME_SECTION_SUGGESTION,
                        prompt=prompt,
                        system_instruction=system_instruction,
                        temperature=0.7,
                        max_tokens=512,
                        metadata={"section": "summary"},
                    )
                )
            )
        except LLMProviderError as exc:
            logger.warning("LLM summary optimization failed: %s", exc)
            return OptimizationResult(
                success=False,
                message="AI suggestions are temporarily unavailable. Please try again.",
                evidence_issues=[str(exc)],
            )

        try:
            import json

            data = json.loads(response.content)
        except (ValueError, json.JSONDecodeError):
            return OptimizationResult(
                success=False,
                message="AI returned an invalid response. Please try again.",
                evidence_issues=["Malformed LLM response"],
            )

        # Validate through Pydantic schema
        try:
            suggestion = ResumeSectionSuggestion.model_validate(data)
        except Exception:
            return OptimizationResult(
                success=False,
                message="AI returned an invalid response format. Please try again.",
                evidence_issues=["LLM response failed schema validation"],
            )

        # Enforce section and operation constraints
        if suggestion.section != "summary":
            return OptimizationResult(
                success=False,
                message="AI returned an unexpected response. Please try again.",
                evidence_issues=[f"Expected section 'summary', got '{suggestion.section}'"],
            )
        if suggestion.operation != "replace":
            return OptimizationResult(
                success=False,
                message="AI returned an unexpected response. Please try again.",
                evidence_issues=[f"Expected operation 'replace', got '{suggestion.operation}'"],
            )

        suggestions = [
            {
                "type": "professional_summary",
                "section": suggestion.section,
                "operation": suggestion.operation,
                "currentText": suggestion.original_content or current_summary,
                "suggestedText": suggestion.suggested_content or current_summary,
                "explanation": suggestion.rationale or "AI-generated summary suggestion.",
                "confidence": suggestion.confidence,
                "evidence": current_skills[:10],
                "affectedKeywords": jd_required + jd_preferred,
                "status": "pending",
            }
        ]

        return OptimizationResult(
            success=True,
            suggestions=suggestions,
            message=f"Generated LLM summary optimization suggestion via {response.provider.value}.",
        )

    def generate_experience_bullet_optimization_llm(
        self,
        resume_content: ResumeContent,
        job_description: str,
        entry_id: str,
        bullet_id: str,
        bullet_text: str,
        job_title: Optional[str] = None,
    ) -> OptimizationResult:
        """Generate LLM-powered experience bullet optimization suggestion.

        Uses the LLM Gateway to produce a structured ResumeSectionSuggestion
        for a single experience bullet. Context is minimized to only the target
        entry, the specific bullet, and JD requirements. The LLM must not
        invent employers, technologies, certifications, or metrics.
        """
        import asyncio

        profile = resume_content.profile
        parser = JobDescriptionParser()
        parsed_jd = parser.parse_job_description(job_description, job_title)

        # Find the target experience entry
        target_entry = None
        for exp in profile.experience or []:
            if exp.id == entry_id:
                target_entry = exp
                break

        if not target_entry:
            return OptimizationResult(
                success=False,
                message="Experience entry not found.",
                evidence_issues=[f"No entry with id '{entry_id}'"],
            )

        # Build minimal candidate context for the specific entry
        other_bullets = [
            b.text for b in target_entry.responsibilities if b.id != bullet_id
        ]

        experience_context_parts = []
        if target_entry.role:
            experience_context_parts.append(target_entry.role)
        if target_entry.company:
            experience_context_parts.append(f"at {target_entry.company}")
        entry_summary = " ".join(experience_context_parts)

        # JD-relevant context
        jd_required = parsed_jd.required_skills[:8]
        jd_preferred = parsed_jd.preferred_skills[:5]
        jd_responsibilities = parsed_jd.responsibilities[:3]

        context_parts = [
            f"Target role: {job_title or parsed_jd.job_title or 'Not specified'}",
            f"Entry: {entry_summary or 'Not specified'}",
            f"Bullet to improve: {bullet_text}",
            f"Other bullets in this entry: {'; '.join(other_bullets) if other_bullets else 'None'}",
            f"JD required skills: {', '.join(jd_required) if jd_required else 'None'}",
            f"JD preferred skills: {', '.join(jd_preferred) if jd_preferred else 'None'}",
            f"JD key responsibilities: {'; '.join(jd_responsibilities) if jd_responsibilities else 'None'}",
        ]
        prompt = "\n".join(context_parts)

        system_instruction = (
            "You are a resume optimization assistant specializing in experience bullet points. "
            "Rewrite the given bullet to be more impactful, specific, and ATS-friendly. "
            "CRITICAL RULES FOR FACTUAL GROUNDING:\n"
            "- ONLY use information explicitly provided in the candidate context above.\n"
            "- NEVER invent employers, job titles, technologies, certifications, "
            "degrees, achievements, metrics, or responsibilities.\n"
            "- If information is absent from the context, OMIT it entirely.\n"
            "- Do NOT fabricate statistics or metrics not present in the original bullet.\n"
            "QUALITY RULES:\n"
            "- Use strong action verbs at the start of the bullet.\n"
            "- Quantify impact where the original bullet already implies measurable outcomes.\n"
            "- Align the bullet with the target job's requirements.\n"
            "- Use ATS-friendly terminology relevant to the target role.\n"
            "- Keep the bullet concise (1-2 lines max).\n"
            "- Do NOT change the fundamental meaning or responsibilities described.\n"
            "Return ONLY a JSON object with fields: section, operation, original_content, "
            "suggested_content, rationale, confidence."
        )

        try:
            gateway = get_llm_gateway()
            response = asyncio.run(
                gateway.generate(
                    LLMRequest(
                        task=LLMTask.RESUME_SECTION_SUGGESTION,
                        prompt=prompt,
                        system_instruction=system_instruction,
                        temperature=0.7,
                        max_tokens=256,
                        metadata={"section": "experience"},
                    )
                )
            )
        except LLMProviderError as exc:
            logger.warning("LLM experience bullet optimization failed: %s", exc)
            return OptimizationResult(
                success=False,
                message="AI suggestions are temporarily unavailable. Please try again.",
                evidence_issues=[str(exc)],
            )

        try:
            import json

            data = json.loads(response.content)
        except (ValueError, json.JSONDecodeError):
            return OptimizationResult(
                success=False,
                message="AI returned an invalid response. Please try again.",
                evidence_issues=["Malformed LLM response"],
            )

        # Validate through Pydantic schema
        try:
            suggestion = ResumeSectionSuggestion.model_validate(data)
        except Exception:
            return OptimizationResult(
                success=False,
                message="AI returned an invalid response format. Please try again.",
                evidence_issues=["LLM response failed schema validation"],
            )

        # Enforce section and operation constraints
        if suggestion.section != "experience":
            return OptimizationResult(
                success=False,
                message="AI returned an unexpected response. Please try again.",
                evidence_issues=[f"Expected section 'experience', got '{suggestion.section}'"],
            )
        if suggestion.operation != "replace":
            return OptimizationResult(
                success=False,
                message="AI returned an unexpected response. Please try again.",
                evidence_issues=[f"Expected operation 'replace', got '{suggestion.operation}'"],
            )

        suggestions = [
            {
                "type": "experience_bullet",
                "section": suggestion.section,
                "entryId": entry_id,
                "childId": bullet_id,
                "operation": suggestion.operation,
                "currentText": suggestion.original_content or bullet_text,
                "suggestedText": suggestion.suggested_content or bullet_text,
                "explanation": suggestion.rationale or "AI-generated experience bullet suggestion.",
                "confidence": suggestion.confidence,
                "evidence": jd_required + jd_preferred[:3],
                "affectedKeywords": jd_required + jd_preferred,
                "status": "pending",
            }
        ]

        return OptimizationResult(
            success=True,
            suggestions=suggestions,
            message=f"Generated LLM experience bullet optimization suggestion via {response.provider.value}.",
        )

    def generate_section_prioritization(
        self,
        resume_content: ResumeContent,
        job_title: Optional[str] = None,
    ) -> OptimizationResult:
        """Generate section prioritization suggestions."""
        profile = resume_content.profile
        is_fresher = resume_content.meta.is_fresher if resume_content.meta else False

        suggestions = []

        if is_fresher:
            fresher_order = [
                ("summary", "Summary"),
                ("projects", "Projects"),
                ("education", "Education"),
                ("internships", "Internship"),
                ("certifications", "Certifications"),
                ("skills", "Skills"),
            ]
        else:
            experienced_order = [
                ("experience", "Experience"),
                ("skills", "Skills"),
                ("projects", "Projects"),
                ("education", "Education"),
                ("certifications", "Certifications"),
            ]
            order = fresher_order if is_fresher else experienced_order

            for section_key, section_name in order:
                section_has_content = False
                if section_key == "summary":
                    section_has_content = bool(profile.summary)
                elif section_key == "experience":
                    section_has_content = bool(profile.experience)
                elif section_key == "projects":
                    section_has_content = bool(profile.projects)
                elif section_key == "education":
                    section_has_content = bool(profile.education)
                elif section_key == "certifications":
                    section_has_content = bool(profile.certifications)
                elif section_key == "skills":
                    section_has_content = (
                        bool(profile.skills.technical)
                        or bool(profile.skills.tools)
                        or bool(profile.skills.languages)
                    )

                if section_has_content:
                    suggestions.append(
                        {
                            "type": "section_prioritization",
                            "priority": len(suggestions),
                            "section": section_key,
                            "sectionName": section_name,
                            "recommended": True,
                            "evidence": f"{section_name} section present",
                        }
                    )

        return OptimizationResult(
            success=True,
            suggestions=suggestions,
            message=f"Section prioritization suggestions generated for {'fresher' if is_fresher else 'experienced'} candidate.",
        )

    def validate_suggestion(
        self,
        suggestion: Dict[str, Any],
        resume_content: ResumeContent,
    ) -> Tuple[bool, str]:
        """Validate a suggestion against the existing resume data."""
        suggestion_type = suggestion.get("type", "")
        section = suggestion.get("section", "")
        suggested_text = suggestion.get("suggestedText", "")

        context = self._build_evidence_context(resume_content)

        if suggestion_type == "professional_summary":
            if " " + suggested_text + " " not in " " + context["summary"] + " ":
                return False, "Summary suggests information not present in resume."

        elif suggestion_type in ("experience_bullet", "project_bullet"):
            if re.search(r"\b\d+(?:%| percent)\b", suggested_text):
                has_unsupported_metric = (
                    not re.search(
                        r"\b\d+(?:%| percent)\b",
                        context["experience"] + context["projects"] + context["achievements"],
                    )
                )
                if has_unsupported_metric:
                    return False, "Bullet suggests unsupported metrics."

        elif suggestion_type == "skills_alignment":
            category = suggestion.get("category", "")
            if category == "missing_without_evidence":
                if suggestion.get("action") == "add":
                    return False, "Cannot recommend adding skill without resume evidence."

        return True, "Valid"

    def optimize_resume(
        self,
        resume_content: ResumeContent,
        job_description: str,
        job_title: Optional[str] = None,
    ) -> OptimizationResult:
        """Main entry point: generate all applicable optimization suggestions."""
        all_suggestions = []

        # 1. Professional summary
        summary_result = self.generate_summary_optimization(
            resume_content, job_description, job_title
        )
        all_suggestions.extend(summary_result.suggestions)

        # 2. Experience bullet optimization (if experience exists)
        if resume_content.profile.experience:
            bullet_result = self.generate_bullet_optimization(
                resume_content, job_description, "experience", ""
            )
            all_suggestions.extend(bullet_result.suggestions)

        # 3. Project bullet optimization (if projects exist)
        if resume_content.profile.projects:
            bullet_result = self.generate_bullet_optimization(
                resume_content, job_description, "projects", ""
            )
            all_suggestions.extend(bullet_result.suggestions)

        # 4. Skills alignment
        skills_result = self.generate_skills_alignment(resume_content, job_description)
        all_suggestions.extend(skills_result.suggestions)

        # 5. Section prioritization
        section_result = self.generate_section_prioritization(resume_content, job_title)
        all_suggestions.extend(section_result.suggestions)

        # Validate all suggestions
        validated_suggestions = []
        evidence_issues = []
        for suggestion in all_suggestions:
            is_valid, validation_error = self.validate_suggestion(
                suggestion, resume_content
            )
            if is_valid:
                validated_suggestions.append(suggestion)
            else:
                evidence_issues.append(validation_error)

        return OptimizationResult(
            success=True,
            suggestions=validated_suggestions,
            evidence_issues=evidence_issues,
            message=f"Generated {len(validated_suggestions)} validated optimization suggestion(s). "
            f"{len(evidence_issues)} issue(s) flagged.",
        )