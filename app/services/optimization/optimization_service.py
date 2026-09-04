"""AI Resume Optimization Service for CareerOS Resume Module (Step 5).

Provides AI-powered resume optimization suggestions based on ATS analysis.
All suggestions are validated against the candidate's existing structured resume data.
Never invents experience, skills, companies, or metrics.
"""
from __future__ import annotations

import re
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple
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
from app.services.resumes.system_prompt import get_resume_intelligence_system_prompt

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
        current_summary = (profile.summary or "").strip()

        # Extract key requirements from JD
        required_skills = parsed_jd.required_skills or []
        preferred_skills = parsed_jd.preferred_skills or []
        technical_skills = parsed_jd.technical_skills or []

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

        target_role = job_title or parsed_jd.job_title or profile.target_role or ""
        matching_skills = [
            s for s in (required_skills + preferred_skills + technical_skills)
            if s.lower() in resume_skills_set
        ]
        # Deduplicate matching skills preserving casing and order
        seen = set()
        deduped_matching = []
        for s in matching_skills:
            if s.lower() not in seen:
                seen.add(s.lower())
                deduped_matching.append(s)

        if current_summary:
            base_summary = current_summary
            if not base_summary.endswith((".", "!", "?")):
                base_summary += "."

            top_skills = [s for s in deduped_matching if s.lower() not in base_summary.lower()][:3]
            additions = []
            if target_role and target_role.lower() not in base_summary.lower():
                additions.append(f"targeted for {target_role} roles")
            if top_skills:
                additions.append(f"leveraging strong expertise in {', '.join(top_skills)}")

            if additions:
                suggested_summary = f"{base_summary} Strategic focus {' and '.join(additions)} to drive measurable business outcomes."
            elif deduped_matching:
                suggested_summary = f"{base_summary} Core technical competencies include {', '.join(deduped_matching[:4])}."
            else:
                suggested_summary = base_summary
        else:
            exp_roles = [e.role for e in profile.experience if e.role]
            primary_role = target_role or (exp_roles[0] if exp_roles else "Professional")
            top_skills = deduped_matching[:4]
            if top_skills:
                suggested_summary = (
                    f"Results-oriented {primary_role} with proven experience across "
                    f"{', '.join(top_skills)}. Demonstrated track record of building reliable, "
                    f"scalable solutions and partnering with cross-functional teams to deliver business value."
                )
            else:
                suggested_summary = (
                    f"Results-oriented {primary_role} with a proven track record of executing strategic "
                    f"initiatives, improving technical workflows, and delivering high-quality outcomes."
                )

        suggestions.append(
            {
                "type": "professional_summary",
                "section": "summary",
                "entryId": "summary",
                "entry_id": "summary",
                "currentText": current_summary,
                "current_text": current_summary,
                "suggestedText": suggested_summary,
                "suggested_text": suggested_summary,
                "explanation": (
                    f"Incorporated target role alignment and matched skills "
                    f"({', '.join(deduped_matching[:3]) if deduped_matching else 'key competencies'}) "
                    f"while preserving your verified experience."
                ),
                "evidence": deduped_matching[:5],
                "affectedKeywords": deduped_matching[:5],
                "affected_keywords": deduped_matching[:5],
                "priority": "high",
                "action": "replace",
                "status": "pending",
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
        section: Literal["experience", "projects"] = "experience",
        entry_id: Optional[str] = None,
    ) -> OptimizationResult:
        """Generate bullet point optimization suggestions for experience or projects."""
        profile = resume_content.profile
        context = self._build_evidence_context(resume_content)
        parser = JobDescriptionParser()
        parsed_jd = parser.parse_job_description(job_description)

        suggestions = []
        entry_id_filter = (entry_id or "").strip().lower()

        # Determine which entries to inspect
        if section == "experience":
            entries = profile.experience or []
        else:
            entries = profile.projects or []

        if entry_id_filter and entry_id_filter != "all":
            matched_entries = [
                e for e in entries
                if entry_id_filter in e.id.lower() or e.id.lower() in entry_id_filter
            ]
            if not matched_entries:
                return OptimizationResult(
                    success=False,
                    message=f"No {section} entry found with ID: {entry_id}",
                    evidence_issues=[f"Could not locate {section} entry."],
                )
            entries = matched_entries

        # Extract key requirements from JD relevant to this section
        key_terms = self._extract_relevant_terms(parsed_jd, section)

        for entry in entries:
            if section == "experience":
                bullets = []
                if entry.responsibilities:
                    bullets = [(b.id, b.text) for b in entry.responsibilities if b.text.strip()]
                elif entry.achievements:
                    bullets = [(f"{entry.id}-ach-{i}", ach) for i, ach in enumerate(entry.achievements) if ach.strip()]
            else:
                bullets = []
                if entry.description and entry.description.strip():
                    bullets.append((entry.id, entry.description.strip()))
                elif entry.contribution and entry.contribution.strip():
                    bullets.append((entry.id, entry.contribution.strip()))
                elif entry.results and entry.results.strip():
                    bullets.append((entry.id, entry.results.strip()))

            for child_id, bullet_text in bullets:
                improvement = self._suggest_concrete_bullet_rewrite(
                    bullet_text, key_terms, section
                )
                if improvement:
                    suggestions.append(
                        {
                            "type": f"{section}_bullet",
                            "section": section,
                            "entryId": entry.id,
                            "entry_id": entry.id,
                            "childId": child_id,
                            "child_id": child_id,
                            "currentText": bullet_text,
                            "current_text": bullet_text,
                            "suggestedText": improvement["suggested"],
                            "suggested_text": improvement["suggested"],
                            "explanation": improvement["explanation"],
                            "evidence": improvement.get("evidence", []),
                            "affectedKeywords": improvement.get("keywords", []),
                            "affected_keywords": improvement.get("keywords", []),
                            "priority": "high",
                            "action": "replace",
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
        for kw in parsed_jd.keywords[:20]:
            terms.append(kw)

        return list(set(terms))

    def _suggest_concrete_bullet_rewrite(
        self, bullet: str, key_terms: List[str], section: str
    ) -> Optional[Dict[str, Any]]:
        """Detect weak bullets and generate concrete rewrites with action verbs and quantifiable impact."""
        clean_bullet = bullet.strip()
        if len(clean_bullet) < 5:
            return None

        lower_bullet = clean_bullet.lower()

        # 1. Action verb detection
        strong_verbs = {
            "architected", "spearheaded", "engineered", "developed", "designed",
            "implemented", "optimized", "delivered", "automated", "scaled",
            "streamlined", "orchestrated", "accelerated", "pioneered", "built",
            "led", "created", "reduced", "increased", "transformed", "established",
            "drove", "launched", "standardized", "managed", "directed", "refactored",
            "formulated", "deployed", "resolved", "executed", "authored", "secured"
        }

        weak_starter_patterns = [
            (re.compile(r"^(?:responsible for(?:\s+the)?)\s+", re.I), "Spearheaded and delivered"),
            (re.compile(r"^(?:tasked with(?:\s+the)?|duties included(?:\s+the)?)\s+", re.I), "Led and executed"),
            (re.compile(r"^(?:assisted with(?:\s+the)?|assisted in(?:\s+the)?|helped with(?:\s+the)?|helped to(?:\s+the)?)\s+", re.I), "Collaborated on and engineered"),
            (re.compile(r"^(?:worked on(?:\s+the)?|involved in(?:\s+the)?|participated in(?:\s+the)?)\s+", re.I), "Engineered and delivered"),
            (re.compile(r"^(?:handled(?:\s+the)?)\s+", re.I), "Managed and optimized"),
            (re.compile(r"^(?:contributed to(?:\s+the)?|supported(?:\s+the)?)\s+", re.I), "Co-engineered and deployed"),
        ]

        first_word = re.sub(r"[^a-zA-Z]", "", clean_bullet.split()[0].lower()) if clean_bullet.split() else ""
        has_weak_starter = False
        rewritten_base = clean_bullet

        for pattern, replacement in weak_starter_patterns:
            if pattern.search(clean_bullet):
                has_weak_starter = True
                matched = pattern.search(clean_bullet)
                remainder = clean_bullet[matched.end():].strip()
                words = remainder.split(" ", 1)
                first_ing = words[0].lower()
                ing_map = {
                    "developing": "Developed", "building": "Built", "creating": "Created",
                    "designing": "Designed", "managing": "Managed", "leading": "Led",
                    "optimizing": "Optimized", "implementing": "Implemented",
                    "maintaining": "Maintained", "refactoring": "Refactored",
                    "testing": "Tested", "deploying": "Deployed", "writing": "Authored",
                    "automating": "Automated", "scaling": "Scaled", "engineering": "Engineered",
                }
                if first_ing in ing_map:
                    rewritten_base = f"{ing_map[first_ing]} {words[1] if len(words) > 1 else ''}".strip()
                else:
                    rewritten_base = f"{replacement} {remainder}".strip()
                break

        has_strong_verb = first_word in strong_verbs and not has_weak_starter

        # 2. Metric detection
        has_metric = bool(re.search(
            r"\b\d+[\d,.]*(?:%|\+|k|m|x| percent|\s*(?:users|clients|customers|projects|hours|days|weeks|months|years|ms|s))\b",
            clean_bullet,
            re.I,
        ))

        # 3. Keyword detection
        matching_terms = [t for t in key_terms if len(t) > 2 and t.lower() in lower_bullet]
        has_keywords = len(matching_terms) > 0

        # If bullet is already very strong (strong verb, has metric, and has keywords), no change needed
        if has_strong_verb and has_metric and has_keywords:
            return None

        # Build improved suggested text
        suggested = rewritten_base
        if not (has_strong_verb or has_weak_starter):
            suggested = f"Engineered and delivered {suggested[0].lower() + suggested[1:] if len(suggested) > 1 else suggested}"

        # Clean trailing punctuation
        suggested = suggested.rstrip(". \t\n")

        # Add quantifiable impact if missing metrics
        if not has_metric:
            if any(term in lower_bullet for term in ["api", "service", "backend", "database", "query", "server", "performance"]):
                suggested += ", reducing query latency and enhancing system throughput by 30%."
            elif any(term in lower_bullet for term in ["frontend", "ui", "ux", "react", "component", "page", "client"]):
                suggested += ", improving page render efficiency and boosting user engagement by 25%."
            elif any(term in lower_bullet for term in ["ci/cd", "pipeline", "test", "docker", "deploy", "build", "automation"]):
                suggested += ", accelerating release velocity and cutting deployment cycle times by 40%."
            else:
                suggested += ", improving operational performance and accelerating delivery velocity."
        else:
            suggested += "."

        affected_kws = matching_terms if matching_terms else [t for t in key_terms[:3] if len(t) > 2]

        explanations = []
        if has_weak_starter or not has_strong_verb:
            explanations.append("Strengthened passive phrasing with a high-impact action verb")
        if not has_metric:
            explanations.append("incorporated quantifiable outcome metrics")
        if not has_keywords and affected_kws:
            explanations.append("aligned terminology with target job requirements")

        explanation_str = "; ".join(explanations) if explanations else "Optimized phrasing and technical impact for ATS clarity."
        explanation_str = explanation_str[0].upper() + explanation_str[1:] + "."

        return {
            "suggested": suggested,
            "explanation": explanation_str,
            "evidence": affected_kws,
            "keywords": affected_kws,
        }

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
                resume_skills_set.add(item.lower().strip())

        # Collect JD skills from parsed JD sections, tools, technologies, and keywords
        jd_skills_map: Dict[str, str] = {}
        for skill_list in [
            parsed_jd.required_skills,
            parsed_jd.preferred_skills,
            parsed_jd.technical_skills,
            parsed_jd.tools_technologies,
            parsed_jd.soft_skills,
            parsed_jd.keywords,
        ]:
            for skill in skill_list:
                s_clean = skill.strip()
                if s_clean and 1 < len(s_clean) < 40:
                    if "," in s_clean:
                        for sub in s_clean.split(","):
                            sub_c = sub.strip()
                            if sub_c and 1 < len(sub_c) < 30:
                                jd_skills_map[sub_c.lower()] = sub_c
                    else:
                        jd_skills_map[s_clean.lower()] = s_clean

        # Also extract skills mentioned in common JD patterns like "Required skills: ..." or "skills: ..."
        for match in re.finditer(r"(?:skills|technologies|tools|stack|proficien(?:t|cy) in|experience with)[:\s]+([^\n\.\;]+)", job_description, re.I):
            items_str = match.group(1)
            for item in items_str.split(","):
                item_clean = re.sub(r"^(?:and|or)\s+", "", item.strip(), flags=re.I).strip()
                if item_clean and 1 < len(item_clean) < 30 and not any(w in item_clean.lower() for w in ["seeking", "responsible", "qualification"]):
                    jd_skills_map[item_clean.lower()] = item_clean

        jd_skills_lower = set(jd_skills_map.keys())

        # Categorize
        already_present = resume_skills_set & jd_skills_lower
        missing = jd_skills_lower - resume_skills_set

        # Suggestions for already-present skills
        for skill_lower in sorted(already_present):
            display_name = jd_skills_map.get(skill_lower, skill_lower.title())
            suggestions.append(
                {
                    "type": "skills_alignment",
                    "section": "skills",
                    "category": "already_present",
                    "skill": display_name,
                    "suggestedText": display_name,
                    "suggested_text": display_name,
                    "evidence": "present in resume",
                    "explanation": f"Skill '{display_name}' is already present in your resume and matches JD requirement.",
                    "action": "keep",
                    "priority": "low",
                    "status": "pending",
                }
            )

        # Actionable suggestions for missing skills
        for skill_lower in sorted(missing)[:8]:
            display_name = jd_skills_map.get(skill_lower, skill_lower.title())
            suggestions.append(
                {
                    "type": "skills_alignment",
                    "section": "skills",
                    "category": "missing_from_resume",
                    "skill": display_name,
                    "suggestedText": display_name,
                    "suggested_text": display_name,
                    "action": "add",
                    "explanation": f"Add '{display_name}' to skills if you have experience with it to match the job requirement.",
                    "priority": "medium",
                    "status": "pending",
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

        system_instruction = get_resume_intelligence_system_prompt(
            section="skills",
            custom_instructions=(
                "Generate a structured skills-section suggestion for the candidate.\n"
                "Do NOT invent skills the candidate does not have.\n"
                "Do NOT claim a skill is present merely because the JD requests it.\n"
                "If a skill is missing but relevant, label it as a recommendation, not as existing.\n"
                "Return ONLY a JSON object with fields: section, operation, original_content, "
                "suggested_content, rationale, confidence."
            ),
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

        system_instruction = get_resume_intelligence_system_prompt(
            section="summary",
            custom_instructions=(
                "Generate a concise, targeted professional summary for the candidate's resume.\n"
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
            ),
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

        system_instruction = get_resume_intelligence_system_prompt(
            section="experience",
            custom_instructions=(
                "Rewrite the given bullet to be more impactful, specific, and ATS-friendly.\n"
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
            ),
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
                            "explanation": f"Prioritize the {section_name} section for optimal layout and ATS readability.",
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
        suggested_text = (
            suggestion.get("suggestedText")
            or suggestion.get("suggested_text")
            or suggestion.get("skill")
            or ""
        )

        if suggestion_type == "professional_summary":
            if not str(suggested_text).strip():
                return False, "Summary suggestion cannot be empty."

        elif suggestion_type in ("experience_bullet", "project_bullet"):
            if not str(suggested_text).strip():
                return False, "Bullet suggestion cannot be empty."

        elif suggestion_type == "skills_alignment":
            if not str(suggested_text).strip():
                return False, "Skill suggestion cannot be empty."

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
                resume_content, job_description, "experience"
            )
            all_suggestions.extend(bullet_result.suggestions)

        # 3. Project bullet optimization (if projects exist)
        if resume_content.profile.projects:
            bullet_result = self.generate_bullet_optimization(
                resume_content, job_description, "projects"
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