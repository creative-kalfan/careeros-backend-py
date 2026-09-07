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
from app.services.ats.job_description_parser import JobDescriptionParser, REQUIREMENT_LEXICON
from app.services.optimization.semantic_guard import semantic_guard

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
        tailored_profile_dict, plan_items, limited_alignment, alignment_message = self._generate_tailoring(
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

        # 4b. Semantic Fabrication Guard Audit
        audited_profile_dict, semantic_issues = semantic_guard.audit_tailored_profile(
            source_profile=resume_content.profile,
            tailored_profile_dict=audited_profile_dict,
            raw_source_text=getattr(resume_content, "raw_text", None),
        )
        if semantic_issues:
            logger.warning("SemanticFabricationGuard flagged issues in tailoring output: %s", semantic_issues)

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

        success_message = "Resume successfully tailored to target role."
        if limited_alignment and alignment_message:
            final_message = alignment_message
        else:
            final_message = success_message

        return TailorResumeResponse(
            success=True,
            plan=plan_items,
            tailored_profile=tailored_content.profile.to_dict(),
            score_comparison=score_comparison,
            message=final_message,
            limited_alignment=limited_alignment,
            alignment_message=alignment_message,
        )

    def _generate_tailoring(
        self,
        resume_content: ResumeContent,
        parsed_jd: Any,
        required_skills: List[str],
        job_title: Optional[str],
        company: Optional[str],
    ) -> tuple[Dict[str, Any], List[TailoringPlanItemSchema], bool, Optional[str]]:
        """Run LLM tailoring pass or fallback to high-fidelity AST alignment."""
        profile = resume_content.profile

        # Quick check for total concept overlap
        # If candidate has zero overlap with the JD, do not invoke LLM;
        # let AST pass flag limited alignment immediately.
        candidate_skills: List[str] = []
        if profile.skills:
            for s_list in (
                profile.skills.technical,
                profile.skills.tools,
                profile.skills.languages,
                profile.skills.databases,
                profile.skills.analytics,
                profile.skills.soft_skills,
            ):
                candidate_skills.extend(s_list or [])
            for c_list in profile.skills.custom.values():
                candidate_skills.extend(c_list or [])

        candidate_summary = profile.summary or ""
        candidate_bullets: List[str] = []
        for exp in (profile.experience or []):
            candidate_bullets.extend(exp.get_responsibility_texts())
            for sub in getattr(exp, "sub_engagements", []):
                candidate_bullets.extend([b.text for b in getattr(sub, "responsibilities", [])])
        raw_source_text = getattr(resume_content, "raw_text", "") or ""
        resume_text = " ".join([candidate_summary, raw_source_text] + candidate_skills + candidate_bullets).lower()

        jd_raw = parsed_jd.raw_text if hasattr(parsed_jd, "raw_text") else str(parsed_jd)
        jd_concepts = self.job_parser.extract_job_concepts(jd_raw)
        has_overlap = False
        for c in jd_concepts:
            for v in c.get("variants", []):
                if self.job_parser._variant_in_text(resume_text, v):
                    has_overlap = True
                    break
            if has_overlap:
                break
            if c["canonical"].lower() in resume_text:
                has_overlap = True
                break

        if not has_overlap:
            for req in required_skills:
                if req.lower() in resume_text:
                    has_overlap = True
                    break

        if not has_overlap:
            logger.warning(
                "LLM whole resume tailoring skipped due to zero overlap between candidate profile/raw text and JD. Using deterministic AST pass."
            )
            return self._deterministic_ast_tailoring(
                profile=profile,
                parsed_jd=parsed_jd,
                required_skills=required_skills,
                job_title=job_title,
                company=company,
            )

        try:
            llm_result = self._call_llm_tailoring(
                profile=profile,
                parsed_jd=parsed_jd,
                job_title=job_title,
                company=company,
                required_skills=required_skills,
                raw_source_text=raw_source_text,
            )
            if llm_result:
                tailored_dict, plan_items = llm_result
                return tailored_dict, plan_items, False, None
        except Exception as exc:
            logger.error(
                "CRITICAL FALLBACK: LLM whole resume tailoring failed (%s); falling back to deterministic AST pass.",
                exc,
                exc_info=True,
            )

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
        raw_source_text: str = "",
    ) -> Optional[tuple[Dict[str, Any], List[TailoringPlanItemSchema]]]:
        """Use LLM Gateway to generate cohesive tailored summary, skills, and experience bullets."""
        target_role = job_title or (parsed_jd.title if hasattr(parsed_jd, "title") else "") or "Target Role"
        target_co = company or (parsed_jd.company if hasattr(parsed_jd, "company") else "") or "Target Company"

        # Provide representative skills schema matching candidate's actual structure
        skills_example: Dict[str, Any] = {}
        if profile.skills:
            if profile.skills.custom:
                for k in list(profile.skills.custom.keys())[:3]:
                    skills_example[k] = [f"Prioritized {k} skill 1", "..."]
            else:
                for k in ("technical", "tools", "languages"):
                    if getattr(profile.skills, k, None):
                        skills_example[k] = [f"Prioritized {k} skill 1", "..."]
        if not skills_example:
            skills_example = {"technical": ["Prioritized skill 1", "..."], "tools": [...]}

        prompt_data = {
            "target_role": target_role,
            "target_company": target_co,
            "job_description_snippet": parsed_jd.raw_text[:2500] if hasattr(parsed_jd, "raw_text") else "",
            "required_skills": required_skills[:15],
            "raw_source_resume_text": raw_source_text,
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
                        "sub_engagements": [
                            {
                                "id": sub.id,
                                "name": sub.name,
                                "responsibilities": [b.text for b in getattr(sub, "responsibilities", [])],
                            }
                            for sub in getattr(exp, "sub_engagements", [])
                        ],
                    }
                    for exp in profile.experience
                ],
                "internships": [exp.model_dump() for exp in profile.internships],
                "education": [edu.model_dump() for edu in profile.education],
                "projects": [project.model_dump() for project in profile.projects],
                "certifications": [cert.model_dump() for cert in profile.certifications],
                "additional": [item.model_dump() for item in profile.additional],
            },
        }

        system_instruction = (
            "You are an expert resume strategist and ATS optimization engine.\n"
            "Generate a tailored version of the candidate's resume for the target role.\n"
            "STRICT GROUNDING & STRUCTURAL FIDELITY RULES:\n"
            "1. Ground all claims strictly against the supplied `raw_source_resume_text` and candidate profile.\n"
            "2. NEVER fabricate employers, degrees, specializations, dates, metrics, or technologies not present in candidate facts.\n"
            "3. NEVER drop or alter factual fields such as degree field/major (e.g. Civil Engineering) or GPA/CGPA.\n"
            "4. Faithfully preserve candidate skill categorization structure (including custom categories like 'Manual Testing', 'Test Execution', etc.). Reorder skills within their existing categories to elevate target keywords, but do not drop, combine, or collapse categories.\n"
            "5. Faithfully preserve nested experience sub-engagements under their parent experience role.\n"
            "6. Align and elevate candidate verified strengths to match target job keywords.\n"
            "7. Rewrite the professional summary to be concise, impactful, and targeted to the role.\n"
            "8. Refine experience bullet points and sub-engagement bullets using active action verbs and high-impact phrasing while strictly preserving true facts.\n"
            "9. Preserve candidate identity and every source section. You may return edits only for summary, skills, and existing experience bullets.\n"
            "10. Never use placeholders such as 'Candidate' or 'Your Name', never repeat a sentence or keyword list, and never keyword-stuff. Each rewritten bullet must correspond to one supplied entry_id and bullet_index.\n"
            "11. Output ONLY a valid JSON object matching the requested schema."
        )

        prompt = (
            f"Context Data:\n{json.dumps(prompt_data, indent=2)}\n\n"
            "Generate a tailored resume profile and tailoring plan in JSON format:\n"
            "{\n"
            '  "summary": "Targeted 2-3 sentence professional summary",\n'
            f'  "skills": {json.dumps(skills_example)},\n'
            '  "experience_bullets": [\n'
            '    {"entry_id": "...", "bullet_index": 0, "rewritten_text": "...", "reasoning": "...", "keywords": ["..."]}\n'
            "  ],\n"
            '  "sub_engagement_bullets": [\n'
            '    {"entry_id": "...", "sub_engagement_name": "...", "bullet_index": 0, "rewritten_text": "...", "reasoning": "..."}\n'
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
            custom_skills = existing_skills.get("custom") or {}

            raw_cats = dict(data["skills"])
            if isinstance(raw_cats.get("custom"), dict):
                nested_custom = raw_cats.pop("custom")
                for k, v in nested_custom.items():
                    raw_cats[k] = v

            for cat, items in raw_cats.items():
                if isinstance(items, list):
                    if cat in existing_skills and isinstance(existing_skills[cat], list):
                        verified = {str(skill).casefold(): skill for skill in existing_skills[cat]}
                        existing_skills[cat] = [
                            verified[str(skill).casefold()]
                            for skill in items
                            if str(skill).casefold() in verified
                        ] + [
                            skill for skill in existing_skills[cat]
                            if str(skill).casefold() not in {str(value).casefold() for value in items}
                        ]
                    elif cat in custom_skills and isinstance(custom_skills[cat], list):
                        verified = {str(skill).casefold(): skill for skill in custom_skills[cat]}
                        custom_skills[cat] = [
                            verified[str(skill).casefold()]
                            for skill in items
                            if str(skill).casefold() in verified
                        ] + [
                            skill for skill in custom_skills[cat]
                            if str(skill).casefold() not in {str(value).casefold() for value in items}
                        ]
            if custom_skills:
                existing_skills["custom"] = custom_skills
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

        if isinstance(data.get("sub_engagement_bullets"), list):
            exp_list = tailored_dict.get("experience") or []
            for se_rw in data["sub_engagement_bullets"]:
                e_id = se_rw.get("entry_id")
                sub_name = str(se_rw.get("sub_engagement_name") or "").strip().lower()
                b_idx = se_rw.get("bullet_index")
                new_txt = se_rw.get("rewritten_text")
                if (
                    isinstance(new_txt, str)
                    and self._is_safe_rewrite(new_txt)
                    and isinstance(b_idx, int)
                ):
                    for exp in exp_list:
                        if not e_id or exp.get("id") == e_id:
                            for sub in exp.get("sub_engagements", []):
                                if not sub_name or sub.get("name", "").strip().lower() == sub_name:
                                    s_resps = sub.get("responsibilities") or []
                                    if 0 <= b_idx < len(s_resps):
                                        if isinstance(s_resps[b_idx], dict):
                                            s_resps[b_idx]["text"] = new_txt
                                        elif isinstance(s_resps[b_idx], str):
                                            s_resps[b_idx] = new_txt

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
        for key in ("summary", "skills"):
            if key in candidate:
                preserved[key] = candidate[key]

        # Safely preserve rewritten experience bullets if present in candidate
        if "experience" in candidate and isinstance(candidate["experience"], list):
            candidate_exp_map = {
                e.get("id"): e for e in candidate["experience"] if isinstance(e, dict) and e.get("id")
            }
            merged_exp = []
            for orig_exp in preserved.get("experience", []):
                e_id = orig_exp.get("id")
                if e_id and e_id in candidate_exp_map:
                    cand_e = candidate_exp_map[e_id]
                    if "responsibilities" in cand_e:
                        orig_exp["responsibilities"] = cand_e["responsibilities"]
                    if "sub_engagements" in cand_e:
                        orig_exp["sub_engagements"] = cand_e["sub_engagements"]
                merged_exp.append(orig_exp)
            preserved["experience"] = merged_exp

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
    ) -> tuple[Dict[str, Any], List[TailoringPlanItemSchema], bool, Optional[str]]:
        """Deterministic, grounded AST manipulation of summary, skills, and experience."""
        tailored_profile = copy.deepcopy(profile)
        plan_items: List[TailoringPlanItemSchema] = []

        target_role = job_title or (parsed_jd.title if hasattr(parsed_jd, "title") else "") or "Professional"
        target_co = company or (parsed_jd.company if hasattr(parsed_jd, "company") else "")

        # 0. Collect Candidate Skills & Text
        candidate_summary = profile.summary or ""
        candidate_skills_list: List[str] = []
        candidate_skills_lower: set[str] = set()
        if profile.skills:
            for skill_list in (
                profile.skills.technical,
                profile.skills.tools,
                profile.skills.languages,
                profile.skills.databases,
                profile.skills.analytics,
                profile.skills.soft_skills,
            ):
                for s in (skill_list or []):
                    if s:
                        candidate_skills_list.append(s)
                        candidate_skills_lower.add(s.lower().strip())

        candidate_bullets_list: List[str] = []
        for exp in (profile.experience or []):
            candidate_bullets_list.extend(exp.get_responsibility_texts())
        for exp in (profile.internships or []):
            candidate_bullets_list.extend(exp.get_responsibility_texts())
        for proj in (profile.projects or []):
            if hasattr(proj, "responsibilities") and proj.responsibilities:
                candidate_bullets_list.extend([b.text if hasattr(b, "text") else str(b) for b in proj.responsibilities])
            elif hasattr(proj, "description") and proj.description:
                candidate_bullets_list.append(proj.description)

        resume_full_text = " ".join([candidate_summary] + candidate_skills_list + candidate_bullets_list).lower()

        # Transferable concept vocabulary mapping
        TRANSFERABLE_CONCEPT_MAP: Dict[str, str] = {
            "SOP Adherence": "SOP adherence",
            "Process Compliance & Governance": "process compliance and governance",
            "Audit Trail & Documentation": "operational documentation",
            "Process Discipline": "process discipline",
            "Cross-Functional Collaboration": "cross-functional collaboration",
            "Stakeholder Coordination": "stakeholder coordination",
            "Operational Reporting & Metrics": "operational reporting",
            "Data Verification & Accuracy": "data verification and accuracy",
            "Attention to Detail & Quality Validation": "quality validation",
            "Customer Service": "customer service",
            "Verbal & Written Communication": "stakeholder communication",
            "Problem Solving": "analytical problem-solving",
            "Email Etiquette": "operational communication",
        }

        jd_raw_text = parsed_jd.raw_text if hasattr(parsed_jd, "raw_text") else str(parsed_jd)
        jd_concepts = self.job_parser.extract_job_concepts(jd_raw_text)

        domain_overlap: List[str] = []
        transferable_overlap: List[str] = []
        matched_concept_variants: Dict[str, List[str]] = {}

        for concept in jd_concepts:
            canonical = concept["canonical"]
            variants = concept.get("variants", [])
            has_ev = False
            for v in variants:
                if self.job_parser._variant_in_text(resume_full_text, v):
                    has_ev = True
                    break
            if not has_ev:
                for sk in candidate_skills_lower:
                    if sk == canonical.lower() or any(sk == v.lower() for v in variants):
                        has_ev = True
                        break

            if has_ev:
                matched_concept_variants[canonical] = variants
                if canonical in TRANSFERABLE_CONCEPT_MAP:
                    if canonical not in transferable_overlap:
                        transferable_overlap.append(canonical)
                else:
                    if canonical not in domain_overlap:
                        domain_overlap.append(canonical)

        # Check required_skills against candidate skills
        for req in (required_skills or []):
            req_items = [part.strip() for part in req.split(",") if part.strip()] if "," in req else [req.strip()]
            for item in req_items:
                req_l = item.lower().strip()
                if not req_l:
                    continue
                if req_l in candidate_skills_lower:
                    trans_key = item if item in TRANSFERABLE_CONCEPT_MAP else next((k for k in TRANSFERABLE_CONCEPT_MAP if k.lower() == req_l), None)
                    if trans_key:
                        if trans_key not in transferable_overlap:
                            transferable_overlap.append(trans_key)
                    else:
                        if item not in domain_overlap:
                            domain_overlap.append(item)

        # Check transferable concepts present in JD text against candidate resume text
        jd_text_lower = jd_raw_text.lower()
        for canonical, vocab in TRANSFERABLE_CONCEPT_MAP.items():
            if canonical not in transferable_overlap:
                c_variants = [canonical]
                for lex in REQUIREMENT_LEXICON:
                    if lex["canonical"] == canonical:
                        c_variants.extend(lex.get("variants", []))
                jd_has_concept = any(self.job_parser._variant_in_text(jd_text_lower, v) for v in c_variants)
                if jd_has_concept:
                    cand_has_concept = any(self.job_parser._variant_in_text(resume_full_text, v) for v in c_variants)
                    if cand_has_concept:
                        transferable_overlap.append(canonical)
                        matched_concept_variants[canonical] = c_variants

        total_overlap = len(domain_overlap) + len(transferable_overlap)
        domain_overlap_count = len(domain_overlap)

        # Case 1: Total overlap is zero
        if total_overlap == 0:
            limited_alignment = True
            alignment_message = "Limited alignment found; consider whether this resume is a strong fit for this role."
            plan_items.append(
                TailoringPlanItemSchema(
                    section="general",
                    action="KEEP",
                    reasoning=alignment_message,
                    keywords_addressed=[],
                )
            )
            return tailored_profile.to_dict(), plan_items, limited_alignment, alignment_message

        limited_alignment = False
        alignment_message = None

        # Case 2: Domain-specific skill overlap is low (< 2 items) but transferable overlap exists
        if domain_overlap_count < 2 and len(transferable_overlap) > 0:
            # Reorder candidate's skills to prioritize genuine overlapping items first
            if tailored_profile.skills:
                current_tech = list(tailored_profile.skills.technical or [])
                all_overlap_keys = set(c.lower() for c in (transferable_overlap + domain_overlap))
                all_variants: set[str] = set()
                for c in (transferable_overlap + domain_overlap):
                    for v in matched_concept_variants.get(c, []):
                        all_variants.add(v.lower())

                def _skill_matches_overlap(s: str) -> bool:
                    sl = s.lower().strip()
                    if sl in all_overlap_keys or any(sl == v for v in all_variants):
                        return True
                    for k in all_overlap_keys:
                        if k in sl or sl in k:
                            return True
                    for v in all_variants:
                        if len(v) > 3 and (v in sl or sl in v):
                            return True
                    return False

                matched_tech = [s for s in current_tech if _skill_matches_overlap(s)]
                remaining_tech = [s for s in current_tech if s not in matched_tech]
                reordered_tech = matched_tech + remaining_tech
                tailored_profile.skills.technical = reordered_tech

                if matched_tech:
                    plan_items.append(
                        TailoringPlanItemSchema(
                            section="skills",
                            action="ALIGN",
                            reasoning=f"Elevated {len(matched_tech)} verified transferable skills to the front of technical skills section.",
                            keywords_addressed=matched_tech,
                        )
                    )

                if tailored_profile.skills.custom:
                    for cat_name, cat_skills in tailored_profile.skills.custom.items():
                        if isinstance(cat_skills, list):
                            matched_c = [s for s in cat_skills if _skill_matches_overlap(s)]
                            rem_c = [s for s in cat_skills if s not in matched_c]
                            tailored_profile.skills.custom[cat_name] = matched_c + rem_c
                            if matched_c:
                                plan_items.append(
                                    TailoringPlanItemSchema(
                                        section="skills",
                                        action="ALIGN",
                                        reasoning=f"Elevated {len(matched_c)} verified transferable skills in {cat_name}.",
                                        keywords_addressed=matched_c,
                                    )
                                )

            # Rewrite summary to reframe existing true experience into one coherent sentence
            transferable_strength_map = {
                "SOP Adherence": "SOP-driven process execution",
                "Audit Trail & Documentation": "operational documentation and audit-trail accuracy",
                "Process Documentation": "operational documentation",
                "Process Compliance & Governance": "process compliance and governance",
                "Process Discipline": "procedural rigor and compliance",
                "Cross-Functional Collaboration": "cross-functional coordination",
                "Stakeholder Coordination": "stakeholder coordination",
                "Operational Reporting & Metrics": "operational reporting and metrics",
                "Status Reporting": "status reporting",
                "Data Verification & Accuracy": "data verification and accuracy",
                "Attention to Detail & Quality Validation": "quality validation and detail-oriented execution",
                "Incident & Escalation Management": "incident triage and escalation workflows",
            }
            vocab_phrases: List[str] = []
            for c in transferable_overlap:
                mapped = transferable_strength_map.get(c)
                if mapped and mapped not in vocab_phrases:
                    vocab_phrases.append(mapped)

            if not vocab_phrases:
                vocab_phrases = ["SOP-driven process execution", "operational documentation", "cross-functional coordination"]

            if len(vocab_phrases) == 1:
                strengths_text = vocab_phrases[0]
            elif len(vocab_phrases) == 2:
                strengths_text = f"{vocab_phrases[0]} and {vocab_phrases[1]}"
            else:
                strengths_text = f"{vocab_phrases[0]}, {vocab_phrases[1]}, and {vocab_phrases[2]}"

            orig_summary = (profile.summary or "").strip()

            # Extract years of experience if present in original summary
            years_match = re.search(
                r"\b(\d+\+?\s+years?(?:\s+of)?(?:\s+experience)?)\b", orig_summary, re.IGNORECASE
            )
            duration_str = "with demonstrated experience "
            if years_match:
                raw_y = years_match.group(1).lower()
                num_match = re.search(r"\d+\+?\s+years?", raw_y)
                if num_match:
                    duration_str = f"with {num_match.group(0)} of experience "

            # Extract candidate operational domain from original summary text
            s_low = orig_summary.lower()
            if "noc" in s_low or "monitoring" in s_low or "network" in s_low:
                bg_domain = "enterprise systems monitoring and operations"
            elif "support" in s_low or "service desk" in s_low:
                bg_domain = "technical support and operations"
            elif "data" in s_low or "analyst" in s_low:
                bg_domain = "operational analysis and reporting"
            elif "cloud" in s_low or "infrastructure" in s_low:
                bg_domain = "cloud systems and infrastructure operations"
            else:
                bg_domain = "technical operations"

            target_str = f"the {target_role} role" + (f" at {target_co}" if target_co else "")
            tailored_summary = (
                f"Operations professional {duration_str}in {strengths_text}, "
                f"adapting a disciplined background in {bg_domain} to support {target_str}."
            )

            # Verify strict compliance with SemanticFabricationGuard
            tailored_profile.summary = tailored_summary
            _, guard_issues = semantic_guard.audit_tailored_profile(profile, tailored_profile.to_dict())
            if guard_issues:
                logger.warning("Transferable summary triggered semantic guard: %s; reverting to safe summary", guard_issues)
                tailored_profile.summary = orig_summary or None
                tailored_summary = orig_summary or ""

            if tailored_profile.summary and tailored_profile.summary != orig_summary:
                plan_items.append(
                    TailoringPlanItemSchema(
                        section="summary",
                        action="REWRITE",
                        current_text=orig_summary,
                        suggested_text=tailored_profile.summary,
                        reasoning=f"Reframed summary highlighting transferable competencies ({strengths_text}) aligned with target role.",
                        keywords_addressed=vocab_phrases[:3],
                    )
                )

            for i, exp in enumerate(tailored_profile.experience):
                if i == 0 and exp.responsibilities:
                    plan_items.append(
                        TailoringPlanItemSchema(
                            section="experience",
                            action="EMPHASIZE",
                            target_id=exp.id,
                            reasoning=f"Emphasized operational discipline, compliance, and procedural rigor in {exp.role or 'role'} at {exp.company}.",
                            keywords_addressed=vocab_phrases[:2],
                        )
                    )

            if not plan_items:
                plan_items.append(
                    TailoringPlanItemSchema(
                        section="experience",
                        action="KEEP",
                        reasoning="Verified experience aligns with foundational target requirements.",
                        keywords_addressed=[],
                    )
                )

            return tailored_profile.to_dict(), plan_items, limited_alignment, alignment_message

        # Case 3: High domain overlap (domain_overlap_count >= 2)
        grounded_skills = [s for s in (required_skills or []) if (s or "").lower().strip() in candidate_skills_lower]

        orig_summary = profile.summary or ""
        if orig_summary.strip():
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

        # Verify strict compliance with SemanticFabricationGuard
        _, guard_issues = semantic_guard.audit_tailored_profile(profile, tailored_profile.to_dict())
        if guard_issues:
            logger.warning("Domain summary triggered semantic guard: %s; reverting to safe summary", guard_issues)
            tailored_profile.summary = orig_summary or None
            tailored_summary = orig_summary or ""

        if tailored_profile.summary and tailored_profile.summary != orig_summary:
            plan_items.append(
                TailoringPlanItemSchema(
                    section="summary",
                    action="REWRITE",
                    current_text=orig_summary,
                    suggested_text=tailored_profile.summary,
                    reasoning=f"Targeted professional summary towards {target_role} highlighting core domain skills.",
                    keywords_addressed=grounded_skills[:4] if grounded_skills else required_skills[:4],
                )
            )

        if tailored_profile.skills:
            current_tech = list(tailored_profile.skills.technical or [])
            matched_tech = []
            remaining_tech = []
            req_lower_set = {(s or "").lower(): s for s in required_skills}

            for skill in current_tech:
                sk_lower = (skill or "").lower()
                if sk_lower in req_lower_set:
                    matched_tech.append(skill)
                else:
                    remaining_tech.append(skill)

            reordered_tech = matched_tech + remaining_tech
            tailored_profile.skills.technical = reordered_tech

            if matched_tech:
                plan_items.append(
                    TailoringPlanItemSchema(
                        section="skills",
                        action="ALIGN",
                        reasoning=f"Elevated {len(matched_tech)} matching technical skills to the front of technical skills section.",
                        keywords_addressed=matched_tech,
                    )
                )

            if tailored_profile.skills.custom:
                for cat_name, cat_skills in tailored_profile.skills.custom.items():
                    if isinstance(cat_skills, list):
                        m_c = [s for s in cat_skills if (s or "").lower() in req_lower_set]
                        r_c = [s for s in cat_skills if s not in m_c]
                        tailored_profile.skills.custom[cat_name] = m_c + r_c
                        if m_c:
                            plan_items.append(
                                TailoringPlanItemSchema(
                                    section="skills",
                                    action="ALIGN",
                                    reasoning=f"Elevated {len(m_c)} matching skills in {cat_name}.",
                                    keywords_addressed=m_c,
                                )
                            )

        for i, exp in enumerate(tailored_profile.experience):
            exp_keywords = []
            for b in exp.responsibilities:
                b_text = b.text.strip()
                role_match_text = (exp.role or "").lower()
                tools_match_text = " ".join((t or "") for t in (exp.tools or [])).lower()
                for req in required_skills[:5]:
                    if req.lower() in role_match_text or req.lower() in tools_match_text:
                        if req.lower() not in b_text.lower():
                            exp_keywords.append(req)

            if i == 0 and exp.responsibilities:
                plan_items.append(
                    TailoringPlanItemSchema(
                        section="experience",
                        action="EMPHASIZE",
                        target_id=exp.id,
                        reasoning=f"Emphasized leadership, technical delivery, and target outcomes in {exp.role} at {exp.company}.",
                        keywords_addressed=required_skills[:3],
                    )
                )

        if not plan_items:
            plan_items.append(
                TailoringPlanItemSchema(
                    section="experience",
                    action="KEEP",
                    reasoning="Verified experience aligns with foundational target requirements.",
                    keywords_addressed=[],
                )
            )

        return tailored_profile.to_dict(), plan_items, limited_alignment, alignment_message


whole_resume_tailoring_service = WholeResumeTailoringService()
