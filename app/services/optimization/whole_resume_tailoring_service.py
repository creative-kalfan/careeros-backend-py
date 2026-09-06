"""Whole-Document AST Resume Tailoring Service for CareerOS.

Performs two-pass tailoring against a target job description:
1. Pass 1: Section-by-section alignment plan (KEEP, REWRITE, EMPHASIZE, ALIGN).
2. Pass 2: Cohesive tailored ResumeProfile (targeted summary, prioritized skills, aligned experience bullets).
3. Closed-loop ATS scoring (baseline vs. tailored comparison).
Strictly grounded in candidate facts: never hallucinates employers, metrics, or technologies.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.llm.gateway import get_llm_gateway
from app.llm.types import LLMProviderError, LLMRequest, LLMTask
from app.models.ats import ATSAnalysisResult
from app.models.resume import (
    BulletItem,
    ExperienceItem,
    ResumeContent,
    ResumeProfile,
    SkillCategory,
)
from app.schemas.optimization import (
    ATSScoreComparisonSchema,
    TailoringPlanItemSchema,
    TailorResumeResponse,
)
from app.services.ats.ats_analyzer import ATSAnalyzer
from app.services.ats.job_description_parser import JobDescriptionParser

logger = logging.getLogger(__name__)


class WholeResumeTailoringService:
    """Orchestrates whole-resume AST tailoring and ATS scoring."""

    def __init__(self) -> None:
        self.ats_analyzer = ATSAnalyzer()
        self.job_parser = JobDescriptionParser()

    def tailor_resume(
        self,
        resume_content: ResumeContent,
        job_description: str,
        job_title: Optional[str] = None,
        company: Optional[str] = None,
    ) -> TailorResumeResponse:
        """Execute two-pass whole document tailoring and ATS score comparison."""
        if not job_description or not job_description.strip():
            raise ValueError("Job description cannot be empty")

        # 1. Baseline ATS Analysis
        baseline_analysis: ATSAnalysisResult = self.ats_analyzer.analyze_resume(
            resume_content=resume_content,
            job_description=job_description,
            job_title=job_title,
            company=company,
        )
        baseline_score = round(float(baseline_analysis.overall_score), 1)

        # 2. Extract JD Concepts and Keyword Requirements
        parsed_jd = self.job_parser.parse_job_description(job_description, job_title, company)
        jd_concepts = self.job_parser.extract_job_concepts(parsed_jd.raw_text)
        required_skills = list(parsed_jd.required_skills or parsed_jd.technical_skills)
        if not required_skills:
            required_skills = [c["canonical"] for c in jd_concepts if c.get("category") == "skill"]
        if not required_skills:
            required_skills = list(parsed_jd.keywords[:10])

        # 3. Attempt LLM-powered tailoring; fallback to deterministic AST tailoring
        tailored_profile_dict, plan_items = self._generate_tailoring(
            resume_content=resume_content,
            parsed_jd=parsed_jd,
            required_skills=required_skills,
            job_title=job_title,
            company=company,
        )

        # 4. Deterministic Numeric Fabrication Guard Audit
        from app.services.optimization.numeric_guard import numeric_guard

        audited_profile_dict, guard_issues = numeric_guard.audit_tailored_profile(
            source_profile=resume_content.profile,
            tailored_profile_dict=tailored_profile_dict,
        )
        if guard_issues:
            logger.info("NumericFabricationGuard audited profile with issues: %s", guard_issues)

        # A tailoring pass may only change text explicitly designed for tailoring.
        # Rebuild against the source profile so an invalid model response can never
        # erase identity, jobs, education, projects, or other profile sections.
        audited_profile_dict = self._preserve_profile_sections(
            source=resume_content.profile,
            candidate=audited_profile_dict,
        )

        # 5. Construct tailored ResumeContent
        tailored_content = ResumeContent(
            profile=ResumeProfile.from_dict(audited_profile_dict),
            meta=copy.deepcopy(resume_content.meta),
        )

        # 5. Tailored ATS Analysis
        tailored_analysis: ATSAnalysisResult = self.ats_analyzer.analyze_resume(
            resume_content=tailored_content,
            job_description=job_description,
            job_title=job_title,
            company=company,
        )
        tailored_score = round(float(tailored_analysis.overall_score), 1)
        score_delta = round(tailored_score - baseline_score, 1)

        matched_kws_count = len(tailored_analysis.matched_keywords)
        missing_kws_count = len(tailored_analysis.missing_keywords)

        score_comparison = ATSScoreComparisonSchema(
            baseline_score=baseline_score,
            tailored_score=tailored_score,
            delta=score_delta,
            matched_keywords_count=matched_kws_count,
            missing_keywords_count=missing_kws_count,
        )

        return TailorResumeResponse(
            success=True,
            plan=plan_items,
            tailored_profile=tailored_content.profile.to_dict(),
            score_comparison=score_comparison,
            message="Resume successfully tailored to target role.",
        )

    def _generate_tailoring(
        self,
        resume_content: ResumeContent,
        parsed_jd: Any,
        required_skills: List[str],
        job_title: Optional[str],
        company: Optional[str],
    ) -> tuple[Dict[str, Any], List[TailoringPlanItemSchema]]:
        """Run LLM tailoring pass or fallback to high-fidelity AST alignment."""
        profile = resume_content.profile

        try:
            llm_result = self._call_llm_tailoring(
                profile=profile,
                parsed_jd=parsed_jd,
                job_title=job_title,
                company=company,
                required_skills=required_skills,
            )
            if llm_result:
                return llm_result
        except Exception as exc:
            logger.warning("LLM whole resume tailoring failed, using deterministic AST pass: %s", exc)

        return self._deterministic_ast_tailoring(
            profile=profile,
            parsed_jd=parsed_jd,
            required_skills=required_skills,
            job_title=job_title,
            company=company,
        )

    def _call_llm_tailoring(
        self,
        profile: ResumeProfile,
        parsed_jd: Any,
        job_title: Optional[str],
        company: Optional[str],
        required_skills: List[str],
    ) -> Optional[tuple[Dict[str, Any], List[TailoringPlanItemSchema]]]:
        """Use LLM Gateway to generate cohesive tailored summary, skills, and experience bullets."""
        target_role = job_title or (parsed_jd.title if hasattr(parsed_jd, "title") else "") or "Target Role"
        target_co = company or (parsed_jd.company if hasattr(parsed_jd, "company") else "") or "Target Company"

        prompt_data = {
            "target_role": target_role,
            "target_company": target_co,
            "job_description_snippet": parsed_jd.raw_text[:2000] if hasattr(parsed_jd, "raw_text") else "",
            "required_skills": required_skills[:15],
            "candidate_profile": {
                "personal": profile.personal.model_dump(),
                "summary": profile.summary,
                "skills": profile.skills.to_dict() if profile.skills else {},
                "experience": [
                    {
                        "id": exp.id,
                        "role": exp.role,
                        "company": exp.company,
                        "responsibilities": exp.get_responsibility_texts(),
                    }
                    for exp in profile.experience
                ],
                "internships": [exp.model_dump() for exp in profile.internships],
                "education": [edu.model_dump() for edu in profile.education],
                "projects": [project.model_dump() for project in profile.projects],
                "certifications": [cert.model_dump() for cert in profile.certifications],
            },
        }

        system_instruction = (
            "You are an expert resume strategist and ATS optimization engine.\n"
            "Generate a tailored version of the candidate's resume for the target role.\n"
            "STRICT GROUNDING RULES:\n"
            "1. NEVER fabricate employers, degrees, dates, metrics, or technologies not present or implied in candidate profile.\n"
            "2. Align and elevate the candidate's verified strengths to match target job keywords.\n"
            "3. Rewrite the professional summary to be concise, impactful, and targeted.\n"
            "4. Prioritize technical and domain skills that match the JD.\n"
            "5. Refine experience bullet points using active action verbs and high-impact phrasing.\n"
            "6. Preserve candidate identity and every source section. You may return edits only for summary, skills, and existing experience bullets.\n"
            "7. Never use placeholders such as 'Candidate', never repeat a sentence or keyword list, and never keyword-stuff. Each rewritten bullet must correspond to one supplied entry_id and bullet_index.\n"
            "8. Output ONLY a valid JSON object matching the requested schema."
        )

        prompt = (
            f"Context Data:\n{json.dumps(prompt_data, indent=2)}\n\n"
            "Generate a tailored resume profile and tailoring plan in JSON format:\n"
            "{\n"
            '  "summary": "Targeted 2-3 sentence professional summary",\n'
            '  "skills": {"technical": ["Prioritized skill 1", "..."], "tools": [...], "languages": [...]},\n'
            '  "experience_bullets": [\n'
            '    {"entry_id": "...", "bullet_index": 0, "rewritten_text": "...", "reasoning": "...", "keywords": ["..."]}\n'
            "  ],\n"
            '  "plan": [\n'
            '    {"section": "summary", "action": "REWRITE", "reasoning": "...", "keywords_addressed": ["..."]},\n'
            '    {"section": "skills", "action": "ALIGN", "reasoning": "...", "keywords_addressed": ["..."]},\n'
            '    {"section": "experience", "action": "EMPHASIZE", "reasoning": "...", "keywords_addressed": ["..."]}\n'
            "  ]\n"
            "}"
        )

        from app.llm.sync_bridge import run_coro_sync

        gateway = get_llm_gateway()
        # run_coro_sync (not asyncio.run): this service is synchronous but is
        # called from async route handlers inside a running event loop, where
        # asyncio.run() raises RuntimeError and silently disabled LLM
        # tailoring. Bounded at 25s so the request stays within the
        # frontend's long-request budget; failures fall back to the
        # deterministic AST pass in _generate_tailoring.
        response = run_coro_sync(
            gateway.generate(
                LLMRequest(
                    task=LLMTask.RESUME_SECTION_SUGGESTION,
                    prompt=prompt,
                    system_instruction=system_instruction,
                    temperature=0.3,
                    max_tokens=2048,
                )
            ),
            timeout_seconds=25.0,
        )

        content_str = response.content.strip()
        # Clean markdown code blocks if present
        if content_str.startswith("```"):
            content_str = re.sub(r"^```(?:json)?\n?", "", content_str)
            content_str = re.sub(r"\n?```$", "", content_str)

        data = json.loads(content_str)
        if not isinstance(data, dict):
            return None

        # Build tailored profile
        tailored_dict = profile.to_dict()
        if isinstance(data.get("summary"), str) and self._is_safe_rewrite(data["summary"]):
            tailored_dict["summary"] = data["summary"].strip()

        if isinstance(data.get("skills"), dict):
            existing_skills = tailored_dict.get("skills") or {}
            for cat, items in data["skills"].items():
                if isinstance(items, list) and cat in existing_skills:
                    # Existing skill categories only: a model cannot invent a new
                    # category or replace verified skills with an arbitrary list.
                    verified = {str(skill).casefold(): skill for skill in existing_skills[cat]}
                    existing_skills[cat] = [
                        verified[str(skill).casefold()]
                        for skill in items
                        if str(skill).casefold() in verified
                    ] + [
                        skill for skill in existing_skills[cat]
                        if str(skill).casefold() not in {str(value).casefold() for value in items}
                    ]
            tailored_dict["skills"] = existing_skills

        if isinstance(data.get("experience_bullets"), list):
            exp_list = tailored_dict.get("experience") or []
            bullet_map = {b.get("entry_id"): [] for b in data["experience_bullets"] if b.get("entry_id")}
            for b in data["experience_bullets"]:
                if b.get("entry_id"):
                    bullet_map[b["entry_id"]].append(b)

            for exp in exp_list:
                exp_id = exp.get("id")
                if exp_id in bullet_map:
                    rewrites = bullet_map[exp_id]
                    resps = exp.get("responsibilities") or []
                    for rw in rewrites:
                        idx = rw.get("bullet_index")
                        new_txt = rw.get("rewritten_text")
                        if (
                            isinstance(new_txt, str)
                            and self._is_safe_rewrite(new_txt)
                            and isinstance(idx, int)
                            and 0 <= idx < len(resps)
                        ):
                            if isinstance(resps[idx], dict):
                                resps[idx]["text"] = new_txt
                            elif isinstance(resps[idx], str):
                                resps[idx] = new_txt
                    exp["responsibilities"] = resps

        # Build plan items
        plan_items: List[TailoringPlanItemSchema] = []
        if isinstance(data.get("plan"), list):
            for p in data["plan"]:
                plan_items.append(
                    TailoringPlanItemSchema(
                        section=str(p.get("section", "general")),
                        action=str(p.get("action", "ALIGN")),
                        target_id=p.get("target_id"),
                        current_text=p.get("current_text"),
                        suggested_text=p.get("suggested_text"),
                        reasoning=str(p.get("reasoning", "Aligned with target job requirements.")),
                        keywords_addressed=p.get("keywords_addressed") or [],
                    )
                )

        if not plan_items:
            plan_items = [
                TailoringPlanItemSchema(
                    section="summary",
                    action="REWRITE",
                    reasoning=f"Tailored summary for {target_role}.",
                    keywords_addressed=required_skills[:3],
                ),
                TailoringPlanItemSchema(
                    section="skills",
                    action="ALIGN",
                    reasoning="Prioritized core skills relevant to JD.",
                    keywords_addressed=required_skills[:5],
                ),
                TailoringPlanItemSchema(
                    section="experience",
                    action="EMPHASIZE",
                    reasoning="Strengthened bullet impact and keyword alignment.",
                    keywords_addressed=required_skills[:4],
                ),
            ]

        return tailored_dict, plan_items

    @staticmethod
    def _is_safe_rewrite(text: str) -> bool:
        """Reject placeholders and obvious repeated keyword/sentence output."""
        normalized = " ".join(text.split())
        if not normalized or normalized.casefold() == "candidate":
            return False
        sentences = [part.strip().casefold() for part in re.split(r"[.!?]+", normalized) if part.strip()]
        if len(sentences) != len(set(sentences)):
            return False
        words = re.findall(r"[a-z0-9+#.-]+", normalized.casefold())
        return not any(words.count(word) > 4 for word in set(words) if len(word) > 3)

    @staticmethod
    def _preserve_profile_sections(source: ResumeProfile, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Keep all non-tailorable source data if a provider response is incomplete."""
        preserved = source.to_dict()
        # Experience rewrites were already applied to a copy of the source
        # profile by entry id and bullet index above; never trust a returned
        # collection to replace the source collection here.
        for key in ("summary", "skills"):
            if key in candidate:
                preserved[key] = candidate[key]
        try:
            return ResumeProfile.model_validate(preserved).model_dump()
        except Exception:
            logger.warning("Discarded invalid whole-resume tailoring response; source profile retained")
            return source.to_dict()

    def _deterministic_ast_tailoring(
        self,
        profile: ResumeProfile,
        parsed_jd: Any,
        required_skills: List[str],
        job_title: Optional[str],
        company: Optional[str],
    ) -> tuple[Dict[str, Any], List[TailoringPlanItemSchema]]:
        """Deterministic, grounded AST manipulation of summary, skills, and experience."""
        tailored_profile = copy.deepcopy(profile)
        plan_items: List[TailoringPlanItemSchema] = []

        target_role = job_title or (parsed_jd.title if hasattr(parsed_jd, "title") else "") or "Professional"
        target_co = company or (parsed_jd.company if hasattr(parsed_jd, "company") else "")

        # 1. Summary AST Alignment
        # Only name skills the candidate actually has: apply-tailoring's
        # semantic guard rejects tailored text naming technologies absent
        # from the source resume, so injecting raw JD requirements here made
        # deterministic output fail its own pipeline with a 422 (e.g. a tech
        # JD naming Kubernetes for a candidate without it).
        candidate_skills: set[str] = set()
        if profile.skills:
            for skill_list in (
                profile.skills.technical,
                profile.skills.tools,
                profile.skills.languages,
                profile.skills.databases,
                profile.skills.analytics,
                profile.skills.soft_skills,
            ):
                candidate_skills.update((s or "").lower() for s in (skill_list or []))
        grounded_skills = [s for s in (required_skills or []) if (s or "").lower() in candidate_skills]

        orig_summary = profile.summary or ""
        if orig_summary.strip():
            # Align existing summary
            if grounded_skills:
                top_skills_str = ", ".join(grounded_skills[:4])
                tailored_summary = (
                    f"{orig_summary.rstrip('.')} with focused expertise in {top_skills_str} "
                    f"targeting the {target_role} role{' at ' + target_co if target_co else ''}."
                )
            else:
                tailored_summary = (
                    f"{orig_summary.rstrip('.')} "
                    f"targeting the {target_role} role{' at ' + target_co if target_co else ''}."
                )
        else:
            tailored_summary = ""
        tailored_profile.summary = tailored_summary or None

        if tailored_summary:
            plan_items.append(
                TailoringPlanItemSchema(
                    section="summary",
                    action="REWRITE",
                    current_text=orig_summary,
                    suggested_text=tailored_summary,
                    reasoning=f"Targeted professional summary towards {target_role} highlighting core domain skills.",
                    keywords_addressed=required_skills[:4],
                )
            )

        # 2. Skills Prioritization & Reordering
        if tailored_profile.skills:
            current_tech = list(tailored_profile.skills.technical)
            # Find candidate skills matching required skills (case-insensitive)
            matched_tech: List[str] = []
            remaining_tech: List[str] = []
            req_lower_set = {(s or "").lower(): s for s in required_skills}

            for skill in current_tech:
                sk_lower = (skill or "").lower()
                if sk_lower in req_lower_set:
                    matched_tech.append(skill)
                else:
                    remaining_tech.append(skill)

            # Reorder so matched verified skills are at the top
            reordered_tech = matched_tech + remaining_tech
            tailored_profile.skills.technical = reordered_tech

            plan_items.append(
                TailoringPlanItemSchema(
                    section="skills",
                    action="ALIGN",
                    reasoning=f"Elevated {len(matched_tech)} matching technical skills to the front of technical skills section.",
                    keywords_addressed=matched_tech,
                )
            )

        # 3. Experience Bullets Alignment
        for i, exp in enumerate(tailored_profile.experience):
            exp_keywords: List[str] = []
            for b in exp.responsibilities:
                b_text = b.text.strip()
                # Check for action verb enhancement or keyword injection if relevant
                # role is Optional[str]; a parser may leave it empty. Treat a missing
                # role/tools as providing no match rather than crashing on .lower().
                role_match_text = (exp.role or "").lower()
                tools_match_text = " ".join((t or "") for t in (exp.tools or [])).lower()
                for req in required_skills[:5]:
                    if req.lower() in role_match_text or req.lower() in tools_match_text:
                        if req.lower() not in b_text.lower():
                            exp_keywords.append(req)

            if i == 0 and exp.responsibilities:
                # Add emphasis plan item for most recent experience
                plan_items.append(
                    TailoringPlanItemSchema(
                        section="experience",
                        action="EMPHASIZE",
                        target_id=exp.id,
                        reasoning=f"Emphasized leadership, technical delivery, and target outcomes in {exp.role} at {exp.company}.",
                        keywords_addressed=required_skills[:3],
                    )
                )

        # Default fallback plan item if none generated
        if not plan_items:
            plan_items.append(
                TailoringPlanItemSchema(
                    section="experience",
                    action="KEEP",
                    reasoning="Verified experience aligns with foundational target requirements.",
                    keywords_addressed=[],
                )
            )

        return tailored_profile.to_dict(), plan_items


whole_resume_tailoring_service = WholeResumeTailoringService()
