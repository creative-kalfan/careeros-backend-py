"""ATS Scoring Engine & Analyzer for CareerOS Resume Module (Step 4)."""

from __future__ import annotations

import re
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import uuid

from app.models.ats import (
    ParsedJobDescription,
    ATSAnalysisResult,
    RequirementCoverage,
    EvidenceLevel,
    JobRequirementType,
    ATSScoringConfig,
    SemanticAnalysisResult,
    ATSAnalysisMetadata,
)
from app.models.resume import ResumeContent, ResumeProfile
from app.services.ats.job_description_parser import JobDescriptionParser, _PARTIAL_STOP_WORDS
from app.services.ats.semantic_reasoner import ATSSemanticReasoner, _build_resume_text as _semantic_build_resume_text
from app.services.ats.semantic_reconciler import (
    reconcile_requirements,
    build_semantic_metadata,
    apply_reconciliation_to_coverage,
)

logger = logging.getLogger(__name__)

# Section name descriptions for user-safe explanations
_SECTION_DESCRIPTIONS = {
    "skills": "your skills section",
    "experience": "your work experience",
    "internships": "your internship experience",
    "projects": "your projects",
    "education": "your education",
    "certifications": "your certifications",
    "summary": "your professional summary",
    "achievements": "your achievements",
}

class ATSAnalyzer:
    """Core ATS Engine analyzing resumes against job descriptions."""

    def __init__(self, config: Optional[ATSScoringConfig] = None, semantic_reasoner: Optional[ATSSemanticReasoner] = None):
        self.config = config or ATSScoringConfig()
        self.parser = JobDescriptionParser()
        self._semantic_reasoner = semantic_reasoner

    def _locate_evidence_section(self, profile: ResumeProfile, evidence_text: str) -> Optional[str]:
        """Locate which resume section contains the given evidence text.

        Returns a human-readable section identifier like "skills",
        "experience[0]", "projects[1]", etc., or None if not found.
        """
        if not evidence_text:
            return None
        ev_lower = evidence_text.lower()

        # Skills section
        s = profile.skills
        if s:
            for item in s.technical + s.tools + s.languages + s.databases + s.analytics + s.soft_skills:
                if item.lower() in ev_lower or ev_lower in item.lower():
                    return "skills"
            for cat, custom_list in s.custom.items():
                for item in custom_list:
                    if item.lower() in ev_lower or ev_lower in item.lower():
                        return "skills"

        # Experience section
        for i, exp in enumerate(profile.experience):
            for bullet in exp.get_all_bullet_texts():
                if ev_lower in bullet.lower() or bullet.lower() in ev_lower:
                    return f"experience[{i}]"
            for tool in exp.tools:
                if tool.lower() in ev_lower or ev_lower in tool.lower():
                    return f"experience[{i}].tools"

        # Internships
        for i, intern in enumerate(profile.internships):
            for bullet in intern.get_all_bullet_texts():
                if ev_lower in bullet.lower() or bullet.lower() in ev_lower:
                    return f"internships[{i}]"
            for tool in intern.tools:
                if tool.lower() in ev_lower or ev_lower in tool.lower():
                    return f"internships[{i}].tools"

        # Projects
        for i, proj in enumerate(profile.projects):
            for tech in proj.technologies:
                if tech.lower() in ev_lower or ev_lower in tech.lower():
                    return f"projects[{i}].technologies"
            if proj.description and (ev_lower in proj.description.lower() or proj.description.lower() in ev_lower):
                return f"projects[{i}]"

        # Education
        for i, edu in enumerate(profile.education):
            if edu.degree and (ev_lower in edu.degree.lower() or edu.degree.lower() in ev_lower):
                return f"education[{i}]"
            if edu.field and (ev_lower in edu.field.lower() or edu.field.lower() in ev_lower):
                return f"education[{i}]"
            for cw in edu.coursework:
                if cw.lower() in ev_lower or ev_lower in cw.lower():
                    return f"education[{i}].coursework"

        # Certifications
        for i, cert in enumerate(profile.certifications):
            if cert.name and (ev_lower in cert.name.lower() or cert.name.lower() in ev_lower):
                return f"certifications[{i}]"

        # Summary
        if profile.summary and ev_lower in profile.summary.lower():
            return "summary"

        # Achievements
        for i, ach in enumerate(profile.achievements):
            if ev_lower in ach.lower() or ach.lower() in ev_lower:
                return f"achievements[{i}]"

        return None

    def _generate_evidence_explanation(
        self,
        requirement: str,
        final_status: str,
        evidence_level: str,
        evidence_source_section: Optional[str],
        reasoning_source: str,
        semantic_reasoning: Optional[str] = None,
    ) -> str:
        """Generate a user-safe explanation for the requirement evidence mapping."""
        if final_status == "matched":
            section_desc = _SECTION_DESCRIPTIONS.get(evidence_source_section.split("[")[0] if evidence_source_section else "", "your resume")
            if reasoning_source == "LLM":
                base = f"Your resume contains evidence satisfying the '{requirement}' requirement, identified through semantic analysis."
            else:
                base = f"Your resume directly satisfies the '{requirement}' requirement."
            if evidence_level == "strong":
                return f"{base} The evidence is strong and found in {section_desc}."
            else:
                return f"{base} Found in {section_desc}."
        elif final_status == "partial":
            section_desc = _SECTION_DESCRIPTIONS.get(evidence_source_section.split("[")[0] if evidence_source_section else "", "your resume")
            if semantic_reasoning:
                return f"Your resume contains related evidence for '{requirement}' but does not fully satisfy the requirement. {semantic_reasoning}"
            return f"Your resume contains partial evidence for '{requirement}' found in {section_desc}, but does not fully satisfy the requirement."
        elif final_status == "missing":
            return f"No evidence of '{requirement}' was found in your resume."
        else:
            return f"Could not determine whether '{requirement}' is present in your resume."

    def _extract_all_resume_text(self, profile: ResumeProfile) -> str:
        """Extract all textual content from a structured resume for keyword scanning."""
        parts = []

        # Personal details
        if profile.personal:
            p = profile.personal
            parts.extend([p.full_name or "", p.headline or "", p.location or ""])

        # Summary
        if profile.summary:
            parts.append(profile.summary)

        # Experience
        for exp in profile.experience:
            parts.extend([exp.company or "", exp.role or "", exp.location or "", exp.metrics or ""])
            parts.extend(exp.get_responsibility_texts())
            parts.extend(exp.achievements)
            parts.extend(exp.tools)

        # Internships
        for intern in profile.internships:
            parts.extend([intern.company or "", intern.role or "", intern.location or "", intern.metrics or ""])
            parts.extend(intern.get_responsibility_texts())
            parts.extend(intern.achievements)
            parts.extend(intern.tools)

        # Education
        for edu in profile.education:
            parts.extend([edu.institution or "", edu.degree or "", edu.field or "", edu.location or ""])
            parts.extend(edu.coursework)
            parts.extend(edu.achievements)

        # Skills
        s = profile.skills
        if s:
            parts.extend(s.technical)
            parts.extend(s.tools)
            parts.extend(s.languages)
            parts.extend(s.databases)
            parts.extend(s.analytics)
            parts.extend(s.soft_skills)
            for cat, custom_list in s.custom.items():
                parts.extend(custom_list)

        # Projects
        for proj in profile.projects:
            parts.extend([proj.name or "", proj.description or "", proj.problem or "", proj.contribution or "", proj.results or "", proj.metrics or ""])
            parts.extend(proj.technologies)

        # Certifications
        for cert in profile.certifications:
            parts.extend([cert.name or "", cert.issuer or ""])

        # Achievements
        parts.extend(profile.achievements)

        # Leadership
        for lead in profile.leadership:
            parts.extend([lead.organization or "", lead.role or "", lead.description or ""])

        # Languages
        for lang in profile.languages:
            parts.extend([lang.language or "", lang.proficiency or ""])

        # Additional
        for add in profile.additional:
            parts.extend([add.title or "", add.description or ""])

        return " ".join([p for p in parts if p]).strip()

    def _get_resume_skills_set(self, profile: ResumeProfile) -> set[str]:
        """Collect all skills from skills section and experiences as lowercase set."""
        skills = set()
        s = profile.skills
        if s:
            for item in s.technical + s.tools + s.databases + s.analytics + s.soft_skills:
                skills.add(self.parser.normalize_skill(item).lower())
            for cat, custom_list in s.custom.items():
                for item in custom_list:
                    skills.add(self.parser.normalize_skill(item).lower())

        # Also grab skills/tools listed in experiences/projects
        for exp in profile.experience + profile.internships:
            for tool in exp.tools:
                skills.add(self.parser.normalize_skill(tool).lower())

        for proj in profile.projects:
            for tech in proj.technologies:
                skills.add(self.parser.normalize_skill(tech).lower())

        return skills

    def _concept_status(self, resume_text_lower: str, resume_skills: set[str], concept: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Classify a JD requirement concept against resume evidence.

        Returns (status, evidence) where status is one of:
          "matched"   - canonical or a variant appears in the resume
          "partial"   - related evidence exists but requirement not fully satisfied
          "missing"   - no meaningful evidence found
        Matching is concept/phrase based, not single-token lexical.
        """
        candidates = [concept["canonical"]] + list(concept["variants"])

        # 1. Matched: canonical/variant present (phrase -> substring, token -> boundary).
        for c in candidates:
            cl = c.lower()
            if not cl:
                continue
            if " " in cl or "-" in cl or "/" in cl or not cl.isalnum():
                if cl in resume_text_lower:
                    return "matched", c
            elif re.search(rf"\b{re.escape(cl)}\b", resume_text_lower):
                return "matched", c
        # Also matched if a normalized skill form is in the candidate's skill set.
        for c in candidates:
            if c.lower() in resume_skills:
                return "matched", c

        # 2. Partial: a meaningful subset of the concept's significant words appears.
        sig_words = [
            w for w in re.findall(r"[a-z0-9]+", concept["canonical"].lower())
            if len(w) > 3 and w not in _PARTIAL_STOP_WORDS
        ]
        if sig_words:
            present = [w for w in sig_words if re.search(rf"\b{re.escape(w)}\b", resume_text_lower)]
            if present and len(present) >= max(1, (len(sig_words) + 1) // 2):
                return "partial", present[0]

        return "missing", None

    def _analyze_requirement_concepts(
        self, resume_text_lower: str, resume_skills: set[str], concepts: List[Dict[str, Any]], profile: Optional[ResumeProfile] = None
    ) -> Dict[str, Any]:
        """Concept-aware replacement for lexical keyword/skill analysis.

        Each JD-relevant concept is classified matched/partial/missing and routed to
        keywords (non-skill categories) or skills (skill category). Scores are weighted
        by requirement importance so high-value concepts dominate over generic words.
        Also builds enriched requirement_coverage entries.
        """
        _IMPORTANCE_WEIGHT = {"high": 3.0, "medium": 2.0, "low": 1.0}
        _CAT_TO_TYPE = {
            "requirement": JobRequirementType.REQUIRED,
            "skill": JobRequirementType.SKILL,
            "qualification": JobRequirementType.QUALIFICATION,
            "experience": JobRequirementType.EXPERIENCE,
            "work_condition": JobRequirementType.WORK_CONDITION,
            "responsibility": JobRequirementType.RESPONSIBILITY,
        }

        matched_kw: List[str] = []
        missing_kw: List[str] = []
        partial_kw: List[str] = []
        matched_sk: List[str] = []
        missing_sk: List[str] = []
        partial_sk: List[str] = []
        coverage: List[RequirementCoverage] = []

        _STATUS_WEIGHT = {"matched": 1.0, "partial": 0.5, "missing": 0.0}

        kw_weight_total = 0.0
        kw_weight_hit = 0.0
        sk_weight_total = 0.0
        sk_weight_hit = 0.0
        kw_evidence_breakdown: Dict[str, int] = {}
        sk_evidence_breakdown: Dict[str, int] = {}
        kw_status_breakdown: Dict[str, int] = {}
        sk_status_breakdown: Dict[str, int] = {}

        for concept in concepts:
            status, evidence = self._concept_status(resume_text_lower, resume_skills, concept)
            imp = _IMPORTANCE_WEIGHT.get(concept["importance"], 1.0)
            canonical = concept["canonical"]
            cat = concept["category"]

            status_w = _STATUS_WEIGHT.get(status, 0.0)
            effective_weight = imp * status_w

            if status == "matched":
                ev_list = [evidence]
                ev_level = EvidenceLevel.STRONG
            elif status == "partial":
                ev_list = [evidence]
                ev_level = EvidenceLevel.PARTIAL
            else:
                ev_list = []
                ev_level = EvidenceLevel.NONE

            if cat == "skill":
                if status == "matched":
                    matched_sk.append(canonical)
                elif status == "partial":
                    partial_sk.append(canonical)
                else:
                    missing_sk.append(canonical)
                sk_weight_total += imp
                sk_weight_hit += effective_weight
            else:
                if status == "matched":
                    matched_kw.append(canonical)
                elif status == "partial":
                    partial_kw.append(canonical)
                else:
                    missing_kw.append(canonical)
                kw_weight_total += imp
                kw_weight_hit += effective_weight

            # Locate which resume section provided the evidence
            source_section = self._locate_evidence_section(profile, evidence) if evidence else None

            # Generate user-safe explanation
            explanation = self._generate_evidence_explanation(
                requirement=canonical,
                final_status=status,
                evidence_level=ev_level.value,
                evidence_source_section=source_section,
                reasoning_source="Deterministic",
            )

            coverage.append(RequirementCoverage(
                requirement=canonical,
                requirement_type=_CAT_TO_TYPE.get(cat, JobRequirementType.REQUIRED),
                resume_evidence=ev_list,
                evidence_level=ev_level,
                evidence_sources=(["resume_text"] if ev_list else []),
                category=cat,
                importance=concept["importance"],
                status=status,
                job_evidence=concept["job_evidence"],
                deterministic_status=status,
                evidence_source_section=source_section,
                evidence_explanation=explanation,
            ))

            # Track evidence quality per category
            if cat == "skill":
                sk_evidence_breakdown[ev_level.value] = sk_evidence_breakdown.get(ev_level.value, 0) + 1
            else:
                kw_evidence_breakdown[ev_level.value] = kw_evidence_breakdown.get(ev_level.value, 0) + 1

        keyword_score = (kw_weight_hit / kw_weight_total * 100.0) if kw_weight_total else 70.0
        skills_score = (sk_weight_hit / sk_weight_total * 100.0) if sk_weight_total else 70.0

        # Apply evidence quality bonus: strong evidence boosts score, no evidence caps it
        kw_strong = kw_evidence_breakdown.get("strong", 0)
        kw_partial = kw_evidence_breakdown.get("partial", 0)
        kw_total_ev = kw_strong + kw_partial + kw_evidence_breakdown.get("none", 0)
        if kw_total_ev > 0:
            strong_ratio = kw_strong / kw_total_ev
            keyword_score = min(keyword_score * (1.0 + 0.1 * strong_ratio), 100.0)

        sk_strong = sk_evidence_breakdown.get("strong", 0)
        sk_partial = sk_evidence_breakdown.get("partial", 0)
        sk_total_ev = sk_strong + sk_partial + sk_evidence_breakdown.get("none", 0)
        if sk_total_ev > 0:
            strong_ratio = sk_strong / sk_total_ev
            skills_score = min(skills_score * (1.0 + 0.1 * strong_ratio), 100.0)

        # Track status breakdown for diagnostics
        for status_type in ["matched", "partial", "missing"]:
            kw_status_breakdown[status_type] = sum(
                1 for c in coverage if c.category != "skill" and c.status == status_type
            )
            sk_status_breakdown[status_type] = sum(
                1 for c in coverage if c.category == "skill" and c.status == status_type
            )

        return {
            "matched_keywords": matched_kw,
            "missing_keywords": missing_kw,
            "partial_keywords": partial_kw,
            "matched_skills": matched_sk,
            "missing_skills": missing_sk,
            "partial_skills": partial_sk,
            "keyword_score": round(keyword_score, 1),
            "skills_score": round(skills_score, 1),
            "coverage": coverage,
            "keyword_status_breakdown": kw_status_breakdown,
            "skills_status_breakdown": sk_status_breakdown,
            "keyword_evidence_breakdown": kw_evidence_breakdown,
            "skills_evidence_breakdown": sk_evidence_breakdown,
        }

    def _analyze_experience(self, profile: ResumeProfile, parsed_job: ParsedJobDescription) -> tuple[float, List[RequirementCoverage]]:
        """Analyze candidates' experience and projects against JD responsibilities."""
        coverage_list = []
        scores = []

        # Extract candidates' total professional experience years
        candidate_years = 0
        if profile.experience:
            candidate_years = len(profile.experience)  # Basic fallback: 1 year per experience item for now or check profile meta
        if profile.internships:
            candidate_years += len(profile.internships) * 0.5

        # Check total requirements
        responsibilities = parsed_job.responsibilities or ["Analyze requirements & perform roles effectively."]

        for resp in responsibilities:
            evidence = []
            level = EvidenceLevel.NONE
            sources = []

            resp_lower = resp.lower()

            # Search in professional experience responsibilities/achievements
            for exp in profile.experience:
                found_in_exp = False
                for bullet in exp.get_all_bullet_texts():
                    # Semantic heuristic: check for shared key terms
                    words = set(re.findall(r"\w+", bullet.lower()))
                    resp_words = set(re.findall(r"\w+", resp_lower))
                    intersection = words.intersection(resp_words)
                    # Filter out common stop words
                    meaningful_intersection = {w for w in intersection if len(w) > 3}

                    if len(meaningful_intersection) >= 2 or any(word in bullet.lower() for word in ["analyze", "dashboard", "reporting", "built", "develop"] if word in resp_lower):
                        evidence.append(bullet)
                        found_in_exp = True

                if found_in_exp:
                    sources.append("experience")

            # Search in projects
            for proj in profile.projects:
                found_in_proj = False
                if proj.description and any(word in proj.description.lower() for word in ["analyze", "dashboard", "build", "develop", "report"] if word in resp_lower):
                    evidence.append(proj.description)
                    found_in_proj = True

                if found_in_proj:
                    sources.append("projects")

            # Determine evidence level
            if len(evidence) >= 1:
                # If there's at least one evidence with very high overlap, mark as STRONG
                has_strong = False
                for ev in evidence:
                    if any(word in ev.lower() for word in ["analyze", "dashboard", "build", "develop", "report"] if word in resp_lower):
                        has_strong = True
                        break
                if has_strong or len(evidence) >= 2:
                    level = EvidenceLevel.STRONG
                    scores.append(100.0)
                else:
                    level = EvidenceLevel.PARTIAL
                    scores.append(50.0)
            else:
                level = EvidenceLevel.NONE
                scores.append(0.0)

            # Map evidence level to status for deterministic_status
            exp_status = "matched" if level == EvidenceLevel.STRONG else ("partial" if level == EvidenceLevel.PARTIAL else "missing")

            coverage_list.append(RequirementCoverage(
                requirement=resp,
                requirement_type=JobRequirementType.RESPONSIBILITY,
                resume_evidence=evidence,
                evidence_level=level,
                evidence_sources=sources,
                deterministic_status=exp_status,
                evidence_source_section=sources[0] if sources else None,
                evidence_explanation=(
                    f"Experience evidence found for '{resp}' in your work experience."
                    if level != EvidenceLevel.NONE
                    else f"No experience evidence found for '{resp}'."
                ),
            ))

        avg_score = sum(scores) / len(scores) if scores else 70.0
        return avg_score, coverage_list

    def _analyze_qualification(self, profile: ResumeProfile, parsed_job: ParsedJobDescription) -> float:
        """Score degree & certifications against JD requirements."""
        edu_score = 70.0  # Default base

        jd_education = " ".join(parsed_job.education_requirements).lower()
        if not jd_education:
            return 90.0  # If no education requirements, don't penalize

        candidate_degrees = [edu.degree.lower() for edu in profile.education if edu.degree]
        candidate_fields = [edu.field.lower() for edu in profile.education if edu.field]

        has_bachelors = any("bachelor" in d or "b.t" in d or "b.s" in d or "btech" in d or "bs" in d for d in candidate_degrees)
        has_masters = any("master" in d or "m.t" in d or "m.s" in d or "mtech" in d or "ms" in d or "mba" in d for d in candidate_degrees)

        if "master" in jd_education:
            if has_masters:
                edu_score = 100.0
            elif has_bachelors:
                edu_score = 80.0
            else:
                edu_score = 50.0
        elif "bachelor" in jd_education:
            if has_bachelors or has_masters:
                edu_score = 100.0
            else:
                edu_score = 60.0

        # Adjust score carefully for field of study relevance
        if any(f in " ".join(candidate_fields) for f in ["computer", "engineering", "science", "technology", "data", "math", "statistics"]):
            edu_score = min(edu_score + 10.0, 100.0)

        return edu_score

    def _analyze_structure(self, profile: ResumeProfile, template_metadata: Optional[Dict[str, Any]] = None) -> float:
        """Check sections presence and templates' ATS compatibility characteristics."""
        structure_score = 100.0
        penalties = 0.0

        # Essential section checks
        if not profile.personal or not profile.personal.email or not profile.personal.phone:
            penalties += 15.0
        if not profile.skills or (not profile.skills.technical and not profile.skills.tools):
            penalties += 15.0
        if not profile.experience and not profile.projects:
            penalties += 20.0
        if not profile.education:
            penalties += 10.0

        # Template compatibility checks
        if template_metadata:
            layout = template_metadata.get("layout", "single-column")
            if layout == "multi-column":
                penalties += 10.0  # Multi-column layout potentially reduces parsing reliability in some ATS systems
            if template_metadata.get("has_charts", False):
                penalties += 10.0  # Graphical elements/skill bars are problematic for parser

        return max(structure_score - penalties, 50.0)

    def analyze_resume(self, resume_content: ResumeContent, job_description: str, job_title: Optional[str] = None, company: Optional[str] = None, template_metadata: Optional[Dict[str, Any]] = None) -> ATSAnalysisResult:
        """Main entry point for ATS Analysis Engine."""
        parsed_job = self.parser.parse_job_description(job_description, job_title, company)
        profile = resume_content.profile

        # 1 + 2. Requirement/skill concept analysis (concept-based, not lexical tokens)
        resume_text = self._extract_all_resume_text(profile)
        resume_text_lower = resume_text.lower()
        resume_skills = self._get_resume_skills_set(profile)
        concepts = self.parser.extract_job_concepts(parsed_job.raw_text)
        concept_result = self._analyze_requirement_concepts(resume_text_lower, resume_skills, concepts, profile=profile)

        matched_kws = concept_result["matched_keywords"]
        missing_kws = concept_result["missing_keywords"]
        partial_kws = concept_result["partial_keywords"]
        matched_skills = concept_result["matched_skills"]
        missing_skills = concept_result["missing_skills"]
        partial_skills = concept_result["partial_skills"]

        keyword_score = concept_result["keyword_score"]
        skills_score = concept_result["skills_score"]

        # 3. Experience & Project Relevance Match
        exp_score, exp_coverage = self._analyze_experience(profile, parsed_job)

        # 4. Qualification Match (Degree, Fields, Certifications)
        qual_score = self._analyze_qualification(profile, parsed_job)

        # 5. Structure & Formatting Check
        structure_score = self._analyze_structure(profile, template_metadata)

        # 6. Overall Weighted Score calculation
        # Adjust weights based on whether candidate is fresher or experienced
        is_fresher = resume_content.meta.is_fresher or False
        exp_weight = self.config.fresher_experience_weight if is_fresher else self.config.experienced_experience_weight
        structure_weight = 0.25 if is_fresher else self.config.structure_weight

        # Normalize weights so they sum to 1.0
        remaining_weight = 1.0 - (exp_weight + structure_weight)
        keyword_weight = remaining_weight * 0.4
        skills_weight = remaining_weight * 0.4
        qual_weight = remaining_weight * 0.2

        overall_score = (
            (keyword_score * keyword_weight) +
            (skills_score * skills_weight) +
            (exp_score * exp_weight) +
            (qual_score * qual_weight) +
            (structure_score * structure_weight)
        )

        # Critical requirement penalty: missing high-importance concepts reduce score
        high_importance_missing = [
            c for c in concept_result["coverage"]
            if c.status == "missing" and c.importance == "high"
        ]
        if high_importance_missing:
            penalty = min(len(high_importance_missing) * 5.0, 25.0)
            overall_score = max(overall_score - penalty, 0.0)

        # 7. Recommendations Generation
        high_priority = []
        medium_priority = []
        low_priority = []

        if len(missing_skills) > 0:
            high_priority.append(
                f"Consider adding missing key skills to your resume: {', '.join(missing_skills[:3])}."
            )
        if len(missing_kws) >= 2:
            medium_priority.append(
                f"Optimize requirement matching: try to naturally integrate '{missing_kws[0]}' and '{missing_kws[1]}' into your professional summary or projects section."
            )
        elif len(missing_kws) == 1:
            medium_priority.append(
                f"Optimize requirement matching: try to naturally integrate '{missing_kws[0]}' into your professional summary or projects section."
            )
        if is_fresher and not profile.projects:
            high_priority.append(
                "As a fresher, adding specific academic or personal projects is highly recommended to showcase practical capability."
            )
        if not is_fresher and len(profile.experience) < 2:
            medium_priority.append(
                "Expand details on professional experience roles, providing clear bullets highlighting metrics, tools used, and key actions."
            )
        if structure_score < 90.0:
            low_priority.append(
                "Simplify resume layout: ensure a clean single-column text-based format without complicated graphics or custom layout tables."
            )

        recommendations = high_priority + medium_priority + low_priority

        # Explain why score was given
        analysis_explanation = {
            "overall": "This score represents how well your resume matches the target job description based on key components: job-relevant requirements/skills, professional experience alignment, qualifications, and formatting.",
            "keyword": f"Matched {len(matched_kws)} of {len(matched_kws) + len(missing_kws) + len(partial_kws)} job-relevant requirement concepts.",
            "skills": f"Matched {len(matched_skills)} of {len(matched_skills) + len(missing_skills) + len(partial_skills)} key job skills.",
            "experience": "Analyzed alignments of professional experiences and projects with core responsibilities outlined in the job description.",
            "qualification": "Analyzed matches on academic degree level, field of study relevance, and related credentials.",
            "structure": "Validated layout structure compatibility, ensuring presence of standard headings, email/phone contact information, and clean text layout."
        }

        # Build final section analysis summary
        section_analysis = {
            "contact_info": profile.personal is not None and profile.personal.email is not None,
            "skills_present": profile.skills is not None,
            "experience_present": len(profile.experience) > 0,
            "education_present": len(profile.education) > 0,
            "projects_present": len(profile.projects) > 0
        }

        template_analysis = {
            "layout": "single-column",
            "is_ats_friendly": True,
            "compatibility_rating": "ATS-friendly" if structure_score >= 90.0 else "Potential ATS compatibility concern"
        }

        return ATSAnalysisResult(
            overall_score=round(overall_score, 1),
            keyword_match_score=round(keyword_score, 1),
            skills_match_score=round(skills_score, 1),
            experience_relevance_score=round(exp_score, 1),
            qualification_match_score=round(qual_score, 1),
            structure_format_score=round(structure_score, 1),
            matched_keywords=matched_kws,
            missing_keywords=missing_kws,
            partial_keywords=partial_kws,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            partial_skills=partial_skills,
            requirement_coverage=concept_result["coverage"] + exp_coverage,
            recommendations=recommendations,
            high_priority_recommendations=high_priority,
            medium_priority_recommendations=medium_priority,
            low_priority_recommendations=low_priority,
            template_analysis=template_analysis,
            section_analysis=section_analysis,
            analysis_explanation=analysis_explanation
        )

    def _run_semantic_reasoning(
        self,
        resume_content: ResumeContent,
        concepts: List[Dict[str, Any]],
        concept_result: Dict[str, Any],
    ) -> tuple[Optional[SemanticAnalysisResult], Optional[ATSAnalysisMetadata]]:
        """Run LLM semantic reasoning on requirement concepts.

        Returns (result, metadata) tuple. Both may be None if semantic reasoning
        is unavailable. The deterministic engine remains authoritative regardless.
        """
        if self._semantic_reasoner is None:
            return None, None

        try:
            import asyncio
            result = asyncio.run(
                self._semantic_reasoner.analyze_requirements(
                    concepts=concepts,
                    resume_content=resume_content,
                    deterministic_coverage=concept_result.get("coverage"),
                )
            )
            if result.success:
                return result, None  # metadata built later after reconciliation
            else:
                # LLM failed — build failure metadata
                metadata = ATSAnalysisMetadata(
                    semantic_available=True,
                    semantic_success=False,
                    semantic_model=result.model_used,
                    semantic_provider=result.provider_used,
                    semantic_latency_ms=result.latency_ms,
                )
                return result, metadata
        except Exception as exc:
            logger.warning("Semantic reasoning failed, falling back to deterministic: %s", exc)
            metadata = ATSAnalysisMetadata(
                semantic_available=True,
                semantic_success=False,
            )
            return None, metadata

    def analyze_resume(self, resume_content: ResumeContent, job_description: str, job_title: Optional[str] = None, company: Optional[str] = None, template_metadata: Optional[Dict[str, Any]] = None) -> ATSAnalysisResult:
        """Main entry point for ATS Analysis Engine."""
        parsed_job = self.parser.parse_job_description(job_description, job_title, company)
        profile = resume_content.profile

        # 1 + 2. Requirement/skill concept analysis (concept-based, not lexical tokens)
        resume_text = self._extract_all_resume_text(profile)
        resume_text_lower = resume_text.lower()
        resume_skills = self._get_resume_skills_set(profile)
        concepts = self.parser.extract_job_concepts(parsed_job.raw_text)
        concept_result = self._analyze_requirement_concepts(resume_text_lower, resume_skills, concepts, profile=profile)

        matched_kws = concept_result["matched_keywords"]
        missing_kws = concept_result["missing_keywords"]
        partial_kws = concept_result["partial_keywords"]
        matched_skills = concept_result["matched_skills"]
        missing_skills = concept_result["missing_skills"]
        partial_skills = concept_result["partial_skills"]

        keyword_score = concept_result["keyword_score"]
        skills_score = concept_result["skills_score"]

        # 2b. LLM Semantic Reasoning (augments, does not replace, deterministic results)
        semantic_metadata = None
        semantic_result, failed_metadata = self._run_semantic_reasoning(resume_content, concepts, concept_result)

        if failed_metadata is not None:
            semantic_metadata = failed_metadata

        if semantic_result and semantic_result.success and semantic_result.assessments:
            # Reconcile deterministic + semantic results
            reconciled, upgrades, overrides = reconcile_requirements(
                concept_coverage=concept_result["coverage"],
                semantic_result=semantic_result,
                resume_text_lower=resume_text_lower,
            )

            # Update coverage with reconciled results
            concept_result["coverage"] = apply_reconciliation_to_coverage(
                concept_result["coverage"], reconciled
            )

            # Rebuild matched/missing/partial lists from reconciled coverage
            matched_kws = [
                c.requirement for c in concept_result["coverage"]
                if c.category != "skill" and c.status == "matched"
            ]
            missing_kws = [
                c.requirement for c in concept_result["coverage"]
                if c.category != "skill" and c.status == "missing"
            ]
            partial_kws = [
                c.requirement for c in concept_result["coverage"]
                if c.category != "skill" and c.status == "partial"
            ]
            matched_skills = [
                c.requirement for c in concept_result["coverage"]
                if c.category == "skill" and c.status == "matched"
            ]
            missing_skills = [
                c.requirement for c in concept_result["coverage"]
                if c.category == "skill" and c.status == "missing"
            ]
            partial_skills = [
                c.requirement for c in concept_result["coverage"]
                if c.category == "skill" and c.status == "partial"
            ]

            # Recalculate scores from reconciled coverage
            _STATUS_WEIGHT = {"matched": 1.0, "partial": 0.5, "missing": 0.0}
            _IMPORTANCE_WEIGHT = {"high": 3.0, "medium": 2.0, "low": 1.0}

            kw_weight_total = 0.0
            kw_weight_hit = 0.0
            sk_weight_total = 0.0
            sk_weight_hit = 0.0

            for cov in concept_result["coverage"]:
                imp = _IMPORTANCE_WEIGHT.get(cov.importance, 1.0)
                status_w = _STATUS_WEIGHT.get(cov.status, 0.0)
                effective_weight = imp * status_w

                if cov.category == "skill":
                    sk_weight_total += imp
                    sk_weight_hit += effective_weight
                else:
                    kw_weight_total += imp
                    kw_weight_hit += effective_weight

            keyword_score = (kw_weight_hit / kw_weight_total * 100.0) if kw_weight_total else 70.0
            skills_score = (sk_weight_hit / sk_weight_total * 100.0) if sk_weight_total else 70.0

            # Re-apply evidence quality bonus from updated coverage
            kw_evidence_breakdown: Dict[str, int] = {}
            sk_evidence_breakdown: Dict[str, int] = {}
            for cov in concept_result["coverage"]:
                if cov.category == "skill":
                    sk_evidence_breakdown[cov.evidence_level.value] = sk_evidence_breakdown.get(cov.evidence_level.value, 0) + 1
                else:
                    kw_evidence_breakdown[cov.evidence_level.value] = kw_evidence_breakdown.get(cov.evidence_level.value, 0) + 1

            kw_strong = kw_evidence_breakdown.get("strong", 0)
            kw_partial_ev = kw_evidence_breakdown.get("partial", 0)
            kw_total_ev = kw_strong + kw_partial_ev + kw_evidence_breakdown.get("none", 0)
            if kw_total_ev > 0:
                strong_ratio = kw_strong / kw_total_ev
                keyword_score = min(keyword_score * (1.0 + 0.1 * strong_ratio), 100.0)

            sk_strong = sk_evidence_breakdown.get("strong", 0)
            sk_partial_ev = sk_evidence_breakdown.get("partial", 0)
            sk_total_ev = sk_strong + sk_partial_ev + sk_evidence_breakdown.get("none", 0)
            if sk_total_ev > 0:
                strong_ratio = sk_strong / sk_total_ev
                skills_score = min(skills_score * (1.0 + 0.1 * strong_ratio), 100.0)

            # Build semantic metadata
            semantic_metadata = build_semantic_metadata(
                semantic_result=semantic_result,
                reconciled_count=len(reconciled),
                upgrades=upgrades,
                overrides=overrides,
            )

        # 3. Experience & Project Relevance Match
        exp_score, exp_coverage = self._analyze_experience(profile, parsed_job)

        # 4. Qualification Match (Degree, Fields, Certifications)
        qual_score = self._analyze_qualification(profile, parsed_job)

        # 5. Structure & Formatting Check
        structure_score = self._analyze_structure(profile, template_metadata)

        # 6. Overall Weighted Score calculation
        # Adjust weights based on whether candidate is fresher or experienced
        is_fresher = resume_content.meta.is_fresher or False
        exp_weight = self.config.fresher_experience_weight if is_fresher else self.config.experienced_experience_weight
        structure_weight = 0.25 if is_fresher else self.config.structure_weight

        # Normalize weights so they sum to 1.0
        remaining_weight = 1.0 - (exp_weight + structure_weight)
        keyword_weight = remaining_weight * 0.4
        skills_weight = remaining_weight * 0.4
        qual_weight = remaining_weight * 0.2

        overall_score = (
            (keyword_score * keyword_weight) +
            (skills_score * skills_weight) +
            (exp_score * exp_weight) +
            (qual_score * qual_weight) +
            (structure_score * structure_weight)
        )

        # Critical requirement penalty: missing high-importance concepts reduce score
        high_importance_missing = [
            c for c in concept_result["coverage"]
            if c.status == "missing" and c.importance == "high"
        ]
        if high_importance_missing:
            penalty = min(len(high_importance_missing) * 5.0, 25.0)
            overall_score = max(overall_score - penalty, 0.0)

        # 7. Recommendations Generation
        high_priority = []
        medium_priority = []
        low_priority = []

        if len(missing_skills) > 0:
            high_priority.append(
                f"Consider adding missing key skills to your resume: {', '.join(missing_skills[:3])}."
            )
        if len(missing_kws) >= 2:
            medium_priority.append(
                f"Optimize requirement matching: try to naturally integrate '{missing_kws[0]}' and '{missing_kws[1]}' into your professional summary or projects section."
            )
        elif len(missing_kws) == 1:
            medium_priority.append(
                f"Optimize requirement matching: try to naturally integrate '{missing_kws[0]}' into your professional summary or projects section."
            )
        if is_fresher and not profile.projects:
            high_priority.append(
                "As a fresher, adding specific academic or personal projects is highly recommended to showcase practical capability."
            )
        if not is_fresher and len(profile.experience) < 2:
            medium_priority.append(
                "Expand details on professional experience roles, providing clear bullets highlighting metrics, tools used, and key actions."
            )
        if structure_score < 90.0:
            low_priority.append(
                "Simplify resume layout: ensure a clean single-column text-based format without complicated graphics or custom layout tables."
            )

        recommendations = high_priority + medium_priority + low_priority

        # Explain why score was given
        analysis_explanation = {
            "overall": "This score represents how well your resume matches the target job description based on key components: job-relevant requirements/skills, professional experience alignment, qualifications, and formatting.",
            "keyword": f"Matched {len(matched_kws)} of {len(matched_kws) + len(missing_kws) + len(partial_kws)} job-relevant requirement concepts.",
            "skills": f"Matched {len(matched_skills)} of {len(matched_skills) + len(missing_skills) + len(partial_skills)} key job skills.",
            "experience": "Analyzed alignments of professional experiences and projects with core responsibilities outlined in the job description.",
            "qualification": "Analyzed matches on academic degree level, field of study relevance, and related credentials.",
            "structure": "Validated layout structure compatibility, ensuring presence of standard headings, email/phone contact information, and clean text layout."
        }

        # Add semantic reasoning explanation if available
        if semantic_metadata and semantic_metadata.semantic_success:
            analysis_explanation["semantic_reasoning"] = (
                f"LLM semantic analysis evaluated {semantic_metadata.reconciled_count} requirements, "
                f"upgrading {semantic_metadata.semantic_upgrades} from missing/partial to matched."
            )

        # Build final section analysis summary
        section_analysis = {
            "contact_info": profile.personal is not None and profile.personal.email is not None,
            "skills_present": profile.skills is not None,
            "experience_present": len(profile.experience) > 0,
            "education_present": len(profile.education) > 0,
            "projects_present": len(profile.projects) > 0
        }

        template_analysis = {
            "layout": "single-column",
            "is_ats_friendly": True,
            "compatibility_rating": "ATS-friendly" if structure_score >= 90.0 else "Potential ATS compatibility concern"
        }

        return ATSAnalysisResult(
            overall_score=round(overall_score, 1),
            keyword_match_score=round(keyword_score, 1),
            skills_match_score=round(skills_score, 1),
            experience_relevance_score=round(exp_score, 1),
            qualification_match_score=round(qual_score, 1),
            structure_format_score=round(structure_score, 1),
            matched_keywords=matched_kws,
            missing_keywords=missing_kws,
            partial_keywords=partial_kws,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            partial_skills=partial_skills,
            requirement_coverage=concept_result["coverage"] + exp_coverage,
            recommendations=recommendations,
            high_priority_recommendations=high_priority,
            medium_priority_recommendations=medium_priority,
            low_priority_recommendations=low_priority,
            template_analysis=template_analysis,
            section_analysis=section_analysis,
            analysis_explanation=analysis_explanation,
            semantic_metadata=semantic_metadata,
        )
