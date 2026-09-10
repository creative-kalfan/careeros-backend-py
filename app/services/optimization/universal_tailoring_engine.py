"""Universal deterministic tailoring engine (Stages 4–5).

Truthful, resume-agnostic tailoring: rewrites and reorders EXISTING evidence
rather than fabricating new experience. Every generated string is traceable
to source evidence; unsupported requirements never become claimed experience.

This is the deterministic fallback used when the LLM pass is unavailable
(and the primary path for overlap-grounded ATS alignment). The LLM pass in
``whole_resume_tailoring_service`` remains for cohesive rewrites; both paths
are audited by the numeric + semantic fabrication guards before persistence.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.models.resume import ResumeProfile
from app.schemas.optimization import TailoringPlanItemSchema
from app.services.optimization.content_prioritizer import (
    recency_weights_for_entries,
    score_items,
)
from app.services.optimization.evidence_matcher import MatchReport
from app.services.optimization.evidence_model import EvidenceIndex
from app.services.optimization.jd_requirements import UniversalJD, normalize_key

logger = logging.getLogger(__name__)

_LIMITED_MESSAGE = (
    "Limited alignment found; consider whether this resume is a strong fit for this role."
)
_YEARS_RE = re.compile(r"\b(\d+\+?\s+years?(?:\s+of)?(?:\s+experience)?)\b", re.IGNORECASE)
_CLAUSE_SPLIT_RE = re.compile(r",|\band\b|\bfor\b|\bto\b|\bwith\b", re.IGNORECASE)


def _extract_duration_phrase(original_summary: str) -> str:
    m = _YEARS_RE.search(original_summary or "")
    if m:
        num = re.search(r"\d+\+?\s+years?", m.group(1).lower())
        if num:
            return f"with {num.group(0)} of experience "
    return "with demonstrated experience "


def _candidate_domain_label(profile: ResumeProfile) -> str:
    """Derive a generic domain label from the candidate's own roles/text.

    Uses the most recent experience role verbatim when available; falls back
    to the headline/target role; never invents an industry.
    """
    for exp in profile.experience or []:
        if exp.role:
            return str(exp.role).strip()
    for exp in profile.internships or []:
        if exp.role:
            return str(exp.role).strip()
    personal = getattr(profile, "personal", None)
    if personal is not None and getattr(personal, "headline", None):
        return str(personal.headline).strip()
    if getattr(profile, "target_role", None):
        return str(profile.target_role).strip()
    return "professional experience"


def _short_strength_phrase(claim: str, requirement_key: str) -> str:
    """Compress long evidence to its most requirement-relevant clause.

    Keeps summaries concise and truthful: the returned clause is candidate
    wording (word-boundary safe), chosen by stem overlap with the matched
    requirement. A leading action verb is dropped so the clause reads as a
    strength noun phrase ("rigorous SOP adherence").
    """
    claim = " ".join((claim or "").split()).strip(" .;:")
    if len(claim) <= 72:
        return claim
    req_tokens = set((requirement_key or "").split())
    clauses = [c.strip(" .;:") for c in _CLAUSE_SPLIT_RE.split(claim)]
    clauses = [c for c in clauses if len(c) >= 12]
    if not clauses:
        return claim[:72].rsplit(" ", 1)[0]
    best = max(clauses, key=lambda c: (len(set(normalize_key(c).split()) & req_tokens), -len(c)))
    words = best.split()
    if len(words) > 3 and re.fullmatch(r"[A-Za-z]+ed", words[0] or ""):
        best = " ".join(words[1:])
    return best


def _find_prose_grounding(skill_label: str, index: EvidenceIndex) -> str:
    """Ground a skill label in the candidate's own prose when possible.

    Returns the first non-skills evidence (bullet, achievement, summary)
    containing the skill phrase verbatim, so summaries cite natural resume
    language instead of bare skill labels. Empty when no prose exists —
    callers then fall back to the skill label itself.
    """
    needle = " ".join((skill_label or "").split()).lower()
    if len(needle) < 3:
        return ""
    for item in index.items:
        if item.source_section == "skills":
            continue
        if needle in (item.claim_text or "").lower():
            return item.claim_text
    return ""


def _top_matched_strengths(
    report: MatchReport, index: EvidenceIndex, limit: int = 3
) -> List[Tuple[str, str]]:
    """Return [(display_phrase, keywords_addressed)] for claimable matches.

    Display phrases use the CANDIDATE's own evidence wording (truthful
    reframe), never raw JD wording — except when the JD phrase itself is
    verbatim candidate vocabulary. Ordered by strength × importance.
    """
    weight = {"high": 3.0, "medium": 2.0, "low": 1.0}
    ranked = sorted(
        report.claimable,
        key=lambda m: (m.strength * weight.get(m.requirement.importance, 1.0)),
        reverse=True,
    )
    strengths: List[Tuple[str, str]] = []
    seen_token_sets: List[set[str]] = []
    for m in ranked:
        claim = (m.candidate_phrasing or "").strip()
        # Skill labels read as keyword stuffing in prose: prefer the
        # candidate's own bullet/summary wording that evidences the skill.
        if (
            m.evidence is not None
            and m.evidence.source_section == "skills"
            and claim
        ):
            prose = _find_prose_grounding(claim, index)
            if prose:
                claim = prose
        req_text = m.requirement.text.strip()
        if claim and len(" ".join(claim.split())) <= 72:
            phrase = " ".join(claim.split())
        elif req_text.lower() in index.full_text_lower and len(req_text) <= 72:
            phrase = req_text
        else:
            phrase = _short_strength_phrase(claim or req_text, m.requirement.normalized_key)
        if not phrase:
            continue
        token_set = set(normalize_key(phrase).split())
        # Skip exact duplicates and sub-phrases of an already-selected
        # strength ("SOP" after "SOP Adherence") to keep the summary crisp.
        if not token_set or any(token_set <= prev for prev in seen_token_sets):
            continue
        seen_token_sets.append(token_set)
        strengths.append((phrase, m.requirement.text))
        if len(strengths) >= limit:
            break
    return strengths


def _reorder_skill_list(skills: List[str], report: MatchReport) -> Tuple[List[str], List[str]]:
    """Reorder one skill category by JD relevance (stable, no drops)."""
    if not skills:
        return [], []
    from app.services.optimization.content_prioritizer import _jd_relevance_for_text

    scored = sorted(
        enumerate(skills),
        key=lambda pair: (-_jd_relevance_for_text(str(pair[1]), report), pair[0]),
    )
    reordered = [s for _, s in scored]
    # Matched = skills with positive relevance (moved to front).
    matched = [s for _, s in scored if _jd_relevance_for_text(str(s), report) > 0][:6]
    return reordered, matched


def run_universal_tailoring(
    profile: ResumeProfile,
    universal_jd: UniversalJD,
    report: MatchReport,
    evidence_index: EvidenceIndex,
    job_title: Optional[str] = None,
    company: Optional[str] = None,
    is_fresher: bool = False,
) -> Tuple[Dict[str, Any], List[TailoringPlanItemSchema], bool, Optional[str]]:
    """Execute generic deterministic tailoring over ANY resume + JD."""
    tailored = copy.deepcopy(profile)
    plan: List[TailoringPlanItemSchema] = []

    if not report.has_any_overlap:
        plan.append(
            TailoringPlanItemSchema(
                section="general",
                action="KEEP",
                reasoning=_LIMITED_MESSAGE,
                keywords_addressed=[],
            )
        )
        return tailored.to_dict(), plan, True, _LIMITED_MESSAGE

    target_role = (job_title or universal_jd.job_title or "target role").strip() or "target role"
    target_co = (company or universal_jd.company or "").strip()

    # -- 1. Skills: reorder within existing categories, never drop/combine --
    if tailored.skills:
        for attr in ("technical", "tools", "languages", "databases", "analytics", "soft_skills"):
            current = list(getattr(tailored.skills, attr, None) or [])
            if not current:
                continue
            reordered, matched = _reorder_skill_list(current, report)
            if reordered != current:
                setattr(tailored.skills, attr, reordered)
            if matched:
                plan.append(
                    TailoringPlanItemSchema(
                        section="skills",
                        action="ALIGN",
                        reasoning=(
                            f"Elevated {len(matched)} verified skill(s) matching "
                            f"target requirements to the front of {attr}."
                        ),
                        keywords_addressed=matched,
                    )
                )
        for cat_name, cat_skills in list((tailored.skills.custom or {}).items()):
            if not isinstance(cat_skills, list) or not cat_skills:
                continue
            reordered, matched = _reorder_skill_list(cat_skills, report)
            if reordered != cat_skills:
                tailored.skills.custom[cat_name] = reordered
            if matched:
                plan.append(
                    TailoringPlanItemSchema(
                        section="skills",
                        action="ALIGN",
                        reasoning=(
                            f"Elevated {len(matched)} verified skill(s) in {cat_name}."
                        ),
                        keywords_addressed=matched,
                    )
                )

    # -- 2. Summary: truthful reframe from candidate evidence + target role --
    strengths = _top_matched_strengths(report, evidence_index, limit=3)
    orig_summary = (profile.summary or "").strip()
    duration = _extract_duration_phrase(orig_summary)
    domain = _candidate_domain_label(profile)
    role_target = f"the {target_role} role" + (f" at {target_co}" if target_co else "")

    if strengths:
        phrases = [p for p, _ in strengths]
        if len(phrases) == 1:
            strengths_text = phrases[0]
        elif len(phrases) == 2:
            strengths_text = f"{phrases[0]} and {phrases[1]}"
        else:
            strengths_text = f"{phrases[0]}, {phrases[1]}, and {phrases[2]}"
        if orig_summary:
            base = orig_summary.rstrip(".")
            tailored_summary = (
                f"{base} with demonstrated strength in {strengths_text}, "
                f"targeting {role_target}."
            )
            # Guard against runaway length: prefer concise reframe.
            if len(tailored_summary) > 520:
                tailored_summary = (
                    f"{domain} professional {duration}in {strengths_text}, "
                    f"targeting {role_target}."
                )
        else:
            tailored_summary = (
                f"{domain} professional {duration}in {strengths_text}, "
                f"targeting {role_target}."
            )
    else:
        if orig_summary:
            tailored_summary = (
                f"{orig_summary.rstrip('.')} targeting {role_target}."
            )
        else:
            tailored_summary = f"{domain} professional targeting {role_target}."
    tailored.summary = tailored_summary or None
    if tailored.summary and tailored.summary != (profile.summary or None):
        plan.append(
            TailoringPlanItemSchema(
                section="summary",
                action="REWRITE",
                current_text=orig_summary,
                suggested_text=tailored.summary,
                reasoning=(
                    "Reframed summary around verified candidate strengths "
                    "aligned with target requirements."
                ),
                keywords_addressed=[k for _, k in strengths][:3] or [target_role],
            )
        )

    # -- 3. Reconstruction: Problem -> Action -> Technology -> Outcome --
    from app.services.optimization.resume_reconstruction import (
        reconstruct_profile_projects_and_experience,
    )

    tailored, recon_notes = reconstruct_profile_projects_and_experience(
        tailored, universal_jd, evidence_index
    )
    for note in recon_notes[:2]:
        plan.append(
            TailoringPlanItemSchema(
                section="experience",
                action="REWRITE",
                reasoning=note,
                keywords_addressed=[k for _, k in strengths][:2],
            )
        )

    # -- 4. Experience: emphasize highest-value entry (no bullet fabrication) --
    entries = list(tailored.experience or [])
    if entries:
        recency = recency_weights_for_entries(len(entries))
        bullet_items: List[Dict[str, Any]] = []
        for pos, exp in enumerate(entries):
            for b in exp.responsibilities or []:
                bullet_items.append(
                    {
                        "id": b.id,
                        "section": "experience",
                        "text": b.text,
                        "has_metric": bool(re.search(r"\d", b.text or "")),
                        "action_strength": 0.6,
                        "_entry": pos,
                    }
                )
        top_entry = 0
        if bullet_items:
            scored = score_items(bullet_items, report, [recency[b["_entry"]] for b in bullet_items])
            # Aggregate by entry to find the highest-value position.
            entry_totals: Dict[int, float] = {}
            for b, s in zip(bullet_items, scored):
                entry_totals[b["_entry"]] = entry_totals.get(b["_entry"], 0.0) + s.total
            top_entry = max(entry_totals, key=lambda k: entry_totals[k])
        top_exp = entries[top_entry]
        plan.append(
            TailoringPlanItemSchema(
                section="experience",
                action="EMPHASIZE",
                target_id=top_exp.id,
                reasoning=(
                    f"Emphasized verified strengths in "
                    f"{top_exp.role or 'role'}" + (f" at {top_exp.company}" if top_exp.company else "") + "."
                ),
                keywords_addressed=[k for _, k in strengths][:2],
            )
        )

    if not plan:
        plan.append(
            TailoringPlanItemSchema(
                section="experience",
                action="KEEP",
                reasoning="Verified experience aligns with foundational target requirements.",
                keywords_addressed=[],
            )
        )

    # -- 4. Structure: order sections by aggregate content value (advisory) --
    # No fixed templates ("skills first", "always include projects"): the
    # order follows measured section value for THIS candidate + JD. This is
    # advisory in the deterministic pass — rendering keeps the source
    # template's geometry order; the plan records the recommendation.
    plan.append(_structure_plan_item(profile, report, is_fresher))
    return tailored.to_dict(), plan, False, None


def _structure_plan_item(
    profile: ResumeProfile, report: MatchReport, is_fresher: bool
) -> TailoringPlanItemSchema:
    """Build the advisory section-ordering plan item (Stage 5b)."""
    from app.services.optimization.content_prioritizer import score_items
    from app.services.optimization.structure_optimizer import plan_structure

    items: List[Dict[str, Any]] = []
    if profile.summary:
        items.append({"id": "summary", "section": "summary", "text": profile.summary})
    for exp in profile.experience or []:
        for b in exp.responsibilities or []:
            items.append({"id": b.id, "section": "experience", "text": b.text})
    for exp in profile.internships or []:
        for b in exp.responsibilities or []:
            items.append({"id": b.id, "section": "internships", "text": b.text})
    for proj in profile.projects or []:
        if proj.description:
            items.append({"id": proj.id, "section": "projects", "text": proj.description})
        for tech in proj.technologies or []:
            items.append({"id": proj.id, "section": "projects", "text": tech})
    for edu in profile.education or []:
        items.append({
            "id": edu.id, "section": "education",
            "text": " ".join(filter(None, [edu.degree, edu.field, edu.institution])),
        })
    if profile.skills:
        for bucket in (
            profile.skills.technical, profile.skills.tools,
            profile.skills.languages, profile.skills.databases,
            profile.skills.analytics, profile.skills.soft_skills,
        ):
            for skill in bucket or []:
                items.append({"id": f"skill-{skill}", "section": "skills", "text": skill})
        for vals in (profile.skills.custom or {}).values():
            for skill in vals or []:
                items.append({"id": f"skill-{skill}", "section": "skills", "text": skill})
    for cert in profile.certifications or []:
        if cert.name:
            items.append({"id": cert.id, "section": "certifications", "text": cert.name})

    available = sorted({i["section"] for i in items})
    if not available:
        return TailoringPlanItemSchema(
            section="structure",
            action="KEEP",
            reasoning="No substantive sections to reorder.",
            keywords_addressed=[],
        )
    structure = plan_structure(available, score_items(items, report), is_fresher=is_fresher)
    return TailoringPlanItemSchema(
        section="structure",
        action="ALIGN",
        reasoning=(
            "Recommended section order by measured content value for this role: "
            + ", ".join(structure.section_order)
            + "."
        ),
        keywords_addressed=[],
    )
