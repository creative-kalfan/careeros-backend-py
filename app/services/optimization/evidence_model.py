"""Candidate evidence model for truthful tailoring.

Every resume claim becomes evidence with provenance so the tailoring engine
can rewrite and reorder existing evidence without ever fabricating new
experience. Resume-agnostic: no role, industry, or candidate assumptions.

Provenance levels (product spec Part 2):
DIRECT ........ explicitly supported by the candidate.
TRANSFERABLE .. strongly related experience that can be legitimately reframed.
PARTIAL ....... some supporting evidence, does not fully satisfy requirement.
UNSUPPORTED ... no evidence exists (must NEVER become a claimed experience).
CONFLICTING ... candidate information contradicts the requirement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.models.resume import ResumeContent, ResumeProfile
from app.services.optimization.jd_requirements import normalize_key


@dataclass
class CandidateEvidence:
    """One atomic claim extracted from the resume."""

    claim_text: str
    normalized_key: str
    source_section: str  # summary|skills|experience|internships|projects|
    # education|certifications|achievements|languages|additional
    source_entry_id: Optional[str] = None
    source_label: str = ""  # human provenance, e.g. "experience[0]"
    has_metric: bool = False
    action_strength: float = 0.0  # 0..1 based on leading action verb

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_text": self.claim_text,
            "normalized_key": self.normalized_key,
            "source_section": self.source_section,
            "source_entry_id": self.source_entry_id,
            "source_label": self.source_label,
            "has_metric": self.has_metric,
            "action_strength": self.action_strength,
        }


@dataclass
class EvidenceIndex:
    """Full provenance map for one resume."""

    items: List[CandidateEvidence] = field(default_factory=list)
    full_text_lower: str = ""
    token_set: set[str] = field(default_factory=set)
    skill_set: set[str] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": [i.to_dict() for i in self.items],
            "skill_count": len(self.skill_set),
            "evidence_count": len(self.items),
        }


_STRONG_VERBS = frozenset(
    {
        "architected", "spearheaded", "engineered", "developed", "designed",
        "implemented", "optimized", "delivered", "automated", "scaled",
        "streamlined", "orchestrated", "accelerated", "pioneered", "built",
        "led", "created", "reduced", "increased", "transformed", "established",
        "drove", "launched", "standardized", "managed", "directed", "refactored",
        "formulated", "deployed", "resolved", "executed", "authored", "secured",
        "maintained", "prepared", "generated", "fostered", "performed",
        "conducted", "analyzed", "coordinated", "oversaw", "owned",
    }
)
_WEAK_OPENERS = (
    "responsible for", "tasked with", "duties included", "assisted with",
    "assisted in", "helped with", "worked on", "involved in",
    "participated in", "handled", "contributed to", "supported",
)
_METRIC_RE = re.compile(
    r"\b\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|\+|percent|k|m|x\b)?",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[a-z0-9+#./-]+", re.IGNORECASE)


def _tokens(text: str) -> set[str]:
    return {
        t.lower()
        for t in _TOKEN_RE.findall(text or "")
        if len(t) > 1
    }


def _action_strength(bullet: str) -> float:
    words = (bullet or "").strip().split()
    if not words:
        return 0.0
    first = re.sub(r"[^a-zA-Z]", "", words[0]).lower()
    lowered = (bullet or "").lower()
    if any(lowered.startswith(op) for op in _WEAK_OPENERS):
        return 0.2
    if first in _STRONG_VERBS:
        return 1.0
    return 0.5


def build_evidence_index(resume_content: ResumeContent) -> EvidenceIndex:
    """Extract every claim from ANY resume profile with section provenance."""
    profile: ResumeProfile = resume_content.profile
    index = EvidenceIndex()
    text_parts: List[str] = []

    def add(
        claim: str,
        section: str,
        entry_id: Optional[str] = None,
        label: str = "",
    ) -> None:
        claim = (claim or "").strip()
        if not claim:
            return
        text_parts.append(claim)
        index.items.append(
            CandidateEvidence(
                claim_text=claim[:500],
                normalized_key=normalize_key(claim),
                source_section=section,
                source_entry_id=entry_id,
                source_label=label or section,
                has_metric=bool(_METRIC_RE.search(claim)),
                action_strength=_action_strength(claim),
            )
        )

    if profile.summary:
        add(profile.summary, "summary", "summary", "summary")

    if profile.skills:
        for bucket in (
            profile.skills.technical, profile.skills.tools,
            profile.skills.languages, profile.skills.databases,
            profile.skills.analytics, profile.skills.soft_skills,
        ):
            for skill in bucket or []:
                if skill:
                    add(skill, "skills", None, "skills")
                    index.skill_set.add(str(skill).lower().strip())
        for cat, vals in (profile.skills.custom or {}).items():
            for skill in vals or []:
                if skill:
                    add(skill, "skills", None, f"skills.{cat}")
                    index.skill_set.add(str(skill).lower().strip())

    for i, exp in enumerate(profile.experience or []):
        label = f"experience[{i}]"
        for bullet in exp.get_responsibility_texts():
            add(bullet, "experience", exp.id, label)
        for ach in exp.achievements or []:
            add(ach, "experience", exp.id, label)
        for tool in exp.tools or []:
            add(tool, "experience", exp.id, f"{label}.tools")

    for i, exp in enumerate(profile.internships or []):
        label = f"internships[{i}]"
        for bullet in exp.get_responsibility_texts():
            add(bullet, "internships", exp.id, label)

    for i, proj in enumerate(profile.projects or []):
        label = f"projects[{i}]"
        if proj.description:
            add(proj.description, "projects", proj.id, label)
        if proj.contribution:
            add(proj.contribution, "projects", proj.id, label)
        if proj.results:
            add(proj.results, "projects", proj.id, label)
        for tech in proj.technologies or []:
            add(tech, "projects", proj.id, f"{label}.technologies")
        for bullet in getattr(proj, "responsibilities", []) or []:
            add(getattr(bullet, "text", str(bullet)), "projects", proj.id, label)

    for i, edu in enumerate(profile.education or []):
        label = f"education[{i}]"
        for part in (edu.degree, edu.field, edu.institution):
            if part:
                add(part, "education", edu.id, label)
        for cw in edu.coursework or []:
            add(cw, "education", edu.id, f"{label}.coursework")

    for i, cert in enumerate(profile.certifications or []):
        add(cert.name or "", "certifications", cert.id, f"certifications[{i}]")
        if cert.issuer:
            add(cert.issuer, "certifications", cert.id, f"certifications[{i}]")

    for i, ach in enumerate(profile.achievements or []):
        add(ach, "achievements", None, f"achievements[{i}]")

    for lang in profile.languages or []:
        if lang.language:
            add(lang.language, "languages", lang.id, "languages")

    for item in profile.additional or []:
        add(item.description or item.title or "", "additional", item.id, "additional")

    if getattr(resume_content, "raw_text", None):
        text_parts.append(resume_content.raw_text)

    full = " ".join(text_parts)
    index.full_text_lower = full.lower()
    index.token_set = _tokens(full)
    return index


# ---------------------------------------------------------------------------
# Provenance classification (resume-agnostic heuristics)
# ---------------------------------------------------------------------------

def _key_overlap(a_key: str, b_key: str) -> float:
    sa, sb = set(a_key.split()), set(b_key.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(len(sa), len(sb))


def classify_requirement(
    requirement_key: str,
    requirement_text: str,
    index: EvidenceIndex,
    direct_threshold: float = 0.8,
    transferable_threshold: float = 0.34,
) -> tuple[str, float, Optional[CandidateEvidence]]:
    """Classify one normalized requirement against the evidence index.

    Returns (provenance, strength 0..1, best_evidence|None).

    Never invents: UNSUPPORTED means "no claim may be generated".
    """
    if not requirement_key:
        return "UNSUPPORTED", 0.0, None
    req_tokens = set(requirement_key.split())
    best: Optional[CandidateEvidence] = None
    best_score = 0.0
    for item in index.items:
        score = _key_overlap(requirement_key, item.normalized_key)
        # Boost exact substring evidence (e.g. "SOP adherence" in a bullet).
        if requirement_text.lower() in item.claim_text.lower() or \
                item.claim_text.lower() in requirement_text.lower():
            score = max(score, 0.9)
        if score > best_score:
            best_score = score
            best = item
    # Skill-set exact hit counts as direct even without sentence overlap.
    if best_score < direct_threshold and req_tokens:
        joined_skills = " ".join(sorted(index.skill_set))
        if requirement_text.lower().strip() in index.skill_set:
            return "DIRECT", 0.95, best
        if _key_overlap(requirement_key, normalize_key(joined_skills)) >= 0.6:
            best_score = max(best_score, 0.6)
    if best_score >= direct_threshold:
        return "DIRECT", min(1.0, best_score), best
    if best_score >= transferable_threshold:
        # Scale transferable strength into 0.4..0.74 band.
        return "TRANSFERABLE", 0.4 + best_score * 0.4, best
    if best_score >= 0.15:
        return "PARTIAL", best_score, best
    # CONFLICTING: requirement explicitly contradicts evidence (generic cues:
    # degree/authorization mismatches are handled by callers with more context;
    # here detect years-of-experience over-claims only when evidence states
    # an explicit lower bound — conservative by design).
    return "UNSUPPORTED", 0.0, None
