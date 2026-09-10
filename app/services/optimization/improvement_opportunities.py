"""Friendly batch evidence discovery for universal resume tailoring.

Pipeline position::

    JD -> parse_universal_jd -> build_evidence_index -> match_requirements
        -> discover_opportunities (this module)
        -> ONE collective candidate interaction
        -> extract_facts_from_response
        -> build_augmented_profile -> run_universal_tailoring
        -> semantic/numeric guards -> ATS rescore -> impact summary

Design constraints (from product spec + AGENTS.md conventions):

- Reuses JD extraction, evidence model, matcher, prioritizer, universal
  tailoring engine, ATS scoring, and semantic guard. No second pipeline.
- No role/industry branches and no fixed domain vocabulary. Every signal
  below is derived from requirement importance, match provenance, evidence
  overlap, and generic context cues.
- Internal provenance stays strict (DIRECT/TRANSFERABLE/PARTIAL/
  UNSUPPORTED/CONFLICTING). Candidate-facing copy is translated to friendly
  language in exactly one place (``_friendly_copy``).
- Friction controls: batch-only surfacing, configurable cap, low-impact
  suppression, already-supported suppression, known-fact/declined reuse.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.models.resume import ResumeContent, ResumeProfile
from app.models.tailoring_evidence import (
    CandidateConfirmedFact,
    CandidateExperienceResponse,
    ExperienceContext,
    ExtractedBatchResult,
    OpportunityStatus,
    OpportunityType,
    RetailorImpact,
    TailoringImprovementOpportunity,
)
from app.services.optimization.evidence_matcher import MatchReport, RequirementMatch
from app.services.optimization.evidence_model import EvidenceIndex
from app.services.optimization.jd_requirements import (
    UniversalJD,
    group_equivalent_requirements,
    normalize_key,
)
from app.services.optimization.skill_relationships import (
    RequirementCategory,
    RelationshipStrength,
    classify_requirement_type,
    skill_relationship_engine,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (env-overridable, never hard-coded into call sites)
# ---------------------------------------------------------------------------

DEFAULT_MAX_OPPORTUNITIES = 5
MIN_OPPORTUNITIES = 1
HARD_MAX_OPPORTUNITIES = 6
MATERIAL_IMPROVEMENT_THRESHOLD = 1.0

_IMPORTANCE_WEIGHT = {"high": 3.0, "medium": 2.0, "low": 1.0}
_CATEGORY_WEIGHT = {
    "hard": 1.5,
    "technical_skill": 1.4,
    "tool": 1.4,
    "responsibility": 1.2,
    "preferred": 0.8,
    "domain_knowledge": 1.0,
    "terminology": 0.7,
    "experience": 0.9,
    "education": 0.6,
    "certification": 0.7,
    "soft_skill": 0.5,
    "behavioral": 0.5,
    "location": 0.2,
    "work_authorization": 0.3,
}


def get_max_opportunities(explicit: Optional[int] = None) -> int:
    """Resolve the surfaced-opportunity cap: explicit > env > default."""
    if explicit is not None:
        try:
            value = int(explicit)
        except (TypeError, ValueError):
            value = DEFAULT_MAX_OPPORTUNITIES
        return max(MIN_OPPORTUNITIES, min(HARD_MAX_OPPORTUNITIES, value))
    try:
        from app.config import get_settings

        value = int(get_settings().tailoring_max_opportunities)
        return max(MIN_OPPORTUNITIES, min(HARD_MAX_OPPORTUNITIES, value))
    except Exception:
        return DEFAULT_MAX_OPPORTUNITIES


# ---------------------------------------------------------------------------
# Friendly candidate-facing language (single translation layer)
# ---------------------------------------------------------------------------

# Harsh auditor terms that must NEVER appear in candidate-facing copy. Kept
# here so tests can assert the translation layer stays friendly.
BANNED_CANDIDATE_PHRASES = (
    "provide evidence",
    "unsupported claim",
    "requirement not satisfied",
    "insufficient evidence",
    "prove your experience",
    "missing qualification",
    "requirement not met",
    "failed to satisfy",
    "unsupported",
)

FRIENDLY_BATCH_HEADING = "A few things could make your match stronger"
FRIENDLY_BATCH_SUBHEADING = (
    "Your target role mentions a few areas that aren't showing clearly "
    "on your resume. Have you worked with any of these?"
)
FRIENDLY_SELECT_HINT = (
    "Select anything you've used — including personal, academic, freelance, "
    "open-source, or project experience where appropriate."
)
FRIENDLY_INPUT_LABEL = "Tell us a little about where you used them."
FRIENDLY_INPUT_PLACEHOLDER = (
    "For example: where you used each area — a project, course, internship, "
    "or role — all in your own words, in one message."
)
FRIENDLY_SKIP_LABEL = "Skip for now"
FRIENDLY_SUBMIT_LABEL = "Use my experience"
FRIENDLY_SUCCESS_NOTE = "Nice — that gives us more to work with."
FRIENDLY_DECLINED_NOTE = (
    "No problem — we'll keep tailoring with your existing experience."
)


def _friendly_copy(display_label: str, opportunity_type: OpportunityType) -> Tuple[str, str, str]:
    """Translate one opportunity into supportive candidate-facing copy."""
    title = display_label
    if opportunity_type == OpportunityType.BURIED_EXPERIENCE:
        prompt = (
            f"If you've worked with {display_label}, we can highlight it "
            "more clearly."
        )
    elif opportunity_type == OpportunityType.PROJECT_LEVERAGE:
        prompt = f"Have you used {display_label} anywhere, such as a project?"
    elif opportunity_type == OpportunityType.REPOSITION_TRANSFERABLE:
        prompt = (
            f"Have you done anything similar to {display_label} that we "
            "could better connect to this role?"
        )
    elif opportunity_type == OpportunityType.CLARIFY_RELEVANCE:
        prompt = (
            f"This could improve your match — have you used {display_label} "
            "anywhere?"
        )
    elif opportunity_type == OpportunityType.TOOL_EXPOSURE:
        prompt = (
            f"Have you worked with {display_label}? If so, tell us a little "
            "about where you used it."
        )
    else:
        prompt = f"Have you worked with {display_label}?"
    helper = "Your resume could be stronger here."
    return title, prompt, helper


def _assert_friendly(text: str) -> None:
    lowered = (text or "").lower()
    for banned in BANNED_CANDIDATE_PHRASES:
        assert banned not in lowered, f"Candidate copy leaked harsh phrase: {banned!r}"


# ---------------------------------------------------------------------------
# Opportunity discovery + ranking
# ---------------------------------------------------------------------------


@dataclass
class _ScoredCandidate:
    match: RequirementMatch
    score: float
    opportunity_type: OpportunityType
    related: List[str]
    friendly_title: Optional[str] = None
    friendly_prompt: Optional[str] = None
    friendly_helper: Optional[str] = None


def _classify_opportunity_type(match: RequirementMatch) -> OpportunityType:
    """Derive the opportunity shape from provenance + category (generic)."""
    category = (match.requirement.category or "").lower()
    if match.provenance == "PARTIAL":
        if match.evidence is not None and match.evidence.source_section in (
            "projects",
            "education",
            "internships",
        ):
            return OpportunityType.PROJECT_LEVERAGE
        return OpportunityType.CLARIFY_RELEVANCE
    if match.provenance == "TRANSFERABLE":
        if match.evidence is not None and match.evidence.source_section == "projects":
            return OpportunityType.PROJECT_LEVERAGE
        return OpportunityType.REPOSITION_TRANSFERABLE
    # UNSUPPORTED from here on.
    if match.evidence is not None and (match.candidate_phrasing or "").strip():
        return OpportunityType.BURIED_EXPERIENCE
    if category in ("tool", "technical_skill"):
        return OpportunityType.TOOL_EXPOSURE
    return OpportunityType.MISSING_SKILL


def _potential_impact(match: RequirementMatch) -> float:
    """Estimated ATS value of resolving this gap (0..~5, generic)."""
    importance = _IMPORTANCE_WEIGHT.get((match.requirement.importance or "medium").lower(), 1.0)
    category = _CATEGORY_WEIGHT.get((match.requirement.category or "").lower(), 0.8)
    # Gaps hurt more than weak support: UNSUPPORTED carries full weight,
    # TRANSFERABLE/PARTIAL/CONFLICTING carry partial weight.
    gap_weight = {
        "UNSUPPORTED": 1.0,
        "PARTIAL": 0.7,
        "TRANSFERABLE": 0.5,
        "CONFLICTING": 0.4,
        "DIRECT": 0.0,
    }.get(match.provenance, 0.0)
    strength_gap = max(0.0, 1.0 - float(match.strength or 0.0))
    return round(importance * category * gap_weight * (0.5 + 0.5 * strength_gap), 3)


def _likelihood_boost(match: RequirementMatch, index: EvidenceIndex) -> float:
    """Candidate-profile likelihood: nearby evidence suggests askability."""
    if match.evidence is None:
        return 0.0
    # Any related evidence (even weak) makes a friendly question worthwhile;
    # strong existing support means no question is needed at all (filtered
    # earlier), so this only fires for PARTIAL/TRANSFERABLE-adjacent gaps.
    section = (match.evidence.source_section or "").lower()
    section_boost = {
        "projects": 0.6,
        "internships": 0.5,
        "education": 0.4,
        "certifications": 0.4,
        "experience": 0.3,
        "skills": 0.2,
    }.get(section, 0.15)
    return round(section_boost * float(match.strength or 0.0), 3)


def _display_label(requirement_text: str) -> str:
    """Short human label: leading list-intro prose is trimmed generically."""
    text = " ".join((requirement_text or "").split()).strip(" .;:-")
    # Trim generic list introductions ("proficiency in X" -> "X").
    text = re.sub(
        r"^(?:proficiency in|experience with|experience in|knowledge of|"
        r"hands-?on (?:experience )?(?:with|in)|familiarity with|exposure to)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    if len(text) > 64:
        text = text[:64].rsplit(" ", 1)[0].rstrip(" ,;:")
    return text or requirement_text[:64]


# Generic filler never probed when detecting mentions (language words, not
# role vocabulary). Mirrors the JD module's stop phrases without importing
# its private constant.
_MENTION_STOPWORDS = frozenset(
    {
        "and", "or", "the", "a", "an", "we", "are", "for", "with", "you",
        "your", "our", "team", "role", "position", "company", "candidate",
        "experience", "experiences", "experienced", "skill", "skills",
        "skilled", "year", "years", "strong", "proven", "ability",
        "proficiency", "proficient", "knowledge", "including", "such",
        "etc", "using", "use", "used", "work", "worked", "working",
    }
)


def _conciseness_bonus(label: str) -> float:
    """Short concrete cards ("Docker") beat full-sentence cards in a batch."""
    n = len(label or "")
    if n <= 28:
        return 0.9
    if n <= 44:
        return 0.4
    if n > 80:
        return -0.6
    return 0.0


def _coverage_of(candidate_key: str, selected_keys: List[str]) -> float:
    """Token coverage of one requirement key by already-selected keys."""
    tokens = set(candidate_key.split())
    if not tokens:
        return 0.0
    covered: set[str] = set()
    for key in selected_keys:
        covered |= set(key.split())
    return len(tokens & covered) / len(tokens)


def discover_opportunities(
    universal_jd: UniversalJD,
    report: MatchReport,
    index: EvidenceIndex,
    max_opportunities: Optional[int] = None,
    known_fact_keys: Optional[Sequence[str]] = None,
    declined_requirement_ids: Optional[Sequence[str]] = None,
    min_impact: float = 0.4,
) -> List[TailoringImprovementOpportunity]:
    """Identify the highest-value batch of improvement opportunities.

    Friction controls applied in order:
    1. Skip already-supported requirements (DIRECT, or claimable with high
       strength — asking would be noise).
    2. Skip low-impact requirements (cannot materially improve the resume).
    3. Skip already-answered facts and declined requirements (no repeats).
    4. Deduplicate semantically-equivalent requirements (one card per idea).
    5. Rank by potential value and cap to the configured maximum.
    """
    cap = get_max_opportunities(max_opportunities)
    known_keys = {normalize_key(k) for k in (known_fact_keys or []) if k}
    declined_ids = set(declined_requirement_ids or [])

    scored: List[_ScoredCandidate] = []
    has_office_card: bool = False
    for match in report.matches:
        req = match.requirement
        req_id = req.text
        if req_id in declined_ids:
            continue
        if req.normalized_key in known_keys:
            continue
        # 1. Already sufficiently supported — never question.
        if match.provenance == "DIRECT":
            continue
        if match.is_claimable and float(match.strength or 0.0) >= 0.8:
            continue
        # 2. Intelligent questioning suppression (Soft skills, Office tools, Reconstructable ecosystem)
        is_direct_or_claimable = (match.provenance == "DIRECT") or (
            match.is_claimable and float(match.strength or 0.0) >= 0.8
        )
        if not skill_relationship_engine.should_question_candidate(
            req.text, req.category, index, is_direct_or_claimable
        ):
            continue

        # If office requirement, consolidate so we never ask per-tool questions (Section 2.B)
        req_type, _ = classify_requirement_type(req.text, req.category)
        if req_type == RequirementCategory.PRODUCTIVITY_OFFICE:
            if has_office_card:
                continue
            has_office_card = True

        # 3. Low-impact suppression.
        impact = _potential_impact(match)
        if impact < min_impact:
            continue
        # Trivially short / location / auth / boilerplate requirements are never worth a
        # question in a batch interaction.
        category = (req.category or "").lower()
        if category in ("location", "work_authorization", "boilerplate", "administrative"):
            continue
        # Also check for application process phrases directly
        if re.search(r"\b(complete (?:your|the) application|submit (?:your|the) (?:application|resume)|equal opportunity|background check|apply online)\b", req.text.lower()):
            continue
        if len(req.normalized_key.split()) == 0:
            continue
        likelihood = _likelihood_boost(match, index)
        importance = _IMPORTANCE_WEIGHT.get((req.importance or "medium").lower(), 1.0)
        score = round(
            impact * 2.0 + likelihood + importance * 0.3
            + _conciseness_bonus(_display_label(req.text)),
            3,
        )
        related = []
        if match.evidence is not None and match.candidate_phrasing:
            related = [match.candidate_phrasing[:280]]
        scored.append(
            _ScoredCandidate(
                match=match,
                score=score,
                opportunity_type=_classify_opportunity_type(match),
                related=related,
            )
        )

    # 4. Deduplicate: group equivalent requirement texts, keep best per group.
    groups = group_equivalent_requirements([s.match.requirement.text for s in scored])
    by_text = {s.match.requirement.text: s for s in scored}
    deduped: List[_ScoredCandidate] = []
    for group in groups:
        members = [by_text[t] for t in group if t in by_text]
        if not members:
            continue
        members.sort(key=lambda s: s.score, reverse=True)
        best = members[0]
        # Merge related excerpts from dropped duplicates for context.
        for other in members[1:]:
            best.related.extend(other.related)
        best.related = best.related[:3]
        # Redundancy penalty already handled by grouping; small uniqueness
        # bonus for groups that stood alone.
        if len(members) == 1:
            best.score = round(best.score + 0.1, 3)
        deduped.append(best)

    # 4b. Generalize Candidate Question Grouping (Section 4)
    # If candidate has a verified root language (e.g. Python, Go, Rust, React, etc.)
    # and multiple JD requirements are related ecosystem tools, group them collectively
    # into a single card rather than separate repetitive interrogation cards.
    root_groups: Dict[str, List[_ScoredCandidate]] = {}
    non_grouped: List[_ScoredCandidate] = []
    for cand in deduped:
        req_text = cand.match.requirement.text
        strength, root, fam = skill_relationship_engine.evaluate_relationship(index.skill_set, req_text)
        is_actual_cand_skill = bool(
            root and any(c.lower().strip() == root.lower().strip() for c in index.skill_set)
        )
        if (
            strength == RelationshipStrength.STRONG_ECOSYSTEM
            and root
            and is_actual_cand_skill
            and fam
            and fam.id not in ("cloud_devops", "soft_skills", "productivity_office")
        ):
            root_groups.setdefault(root, []).append(cand)
        else:
            non_grouped.append(cand)

    consolidated_cands: List[_ScoredCandidate] = list(non_grouped)
    for root, cands in root_groups.items():
        if len(cands) >= 2:
            labels = [_display_label(c.match.requirement.text) for c in cands]
            combined_label = ", ".join(labels)
            combined_req_text = ", ".join(c.match.requirement.text for c in cands)
            combined_norm = " ".join(c.match.requirement.normalized_key for c in cands)
            combined_related = [f"Verified {root} experience on your resume"]
            for c in cands:
                combined_related.extend(c.related)
            combined_related = combined_related[:3]
            score = max(c.score for c in cands) + 0.3
            from app.services.optimization.jd_requirements import UniversalRequirement
            comp_req = UniversalRequirement(
                text=combined_req_text,
                normalized_key=combined_norm,
                importance=cands[0].match.requirement.importance,
                category="tool",
            )
            comp_match = RequirementMatch(
                requirement=comp_req,
                provenance="UNSUPPORTED",
                strength=0.0,
            )
            root_disp = root.title() if len(root) > 1 else root.upper()
            friendly_title = f"Tools commonly used with {root_disp}"
            friendly_prompt = (
                f"Your {root_disp} experience is already relevant here. "
                f"This role also mentions a few tools commonly used alongside {root_disp}. "
                f"Have you used any of these?"
            )
            friendly_helper = "Tell us a little about where you used them, if you remember."
            consolidated_cands.append(
                _ScoredCandidate(
                    match=comp_match,
                    score=score,
                    opportunity_type=OpportunityType.TOOL_EXPOSURE,
                    related=combined_related,
                    friendly_title=friendly_title,
                    friendly_prompt=friendly_prompt,
                    friendly_helper=friendly_helper,
                )
            )
        else:
            consolidated_cands.extend(cands)

    deduped = consolidated_cands

    # 5. Rank by value, suppress long statements already covered by selected
    # short cards ("Strong experience with React..." is covered once "React"
    # and "TypeScript" cards are selected), then cap.
    deduped.sort(key=lambda s: s.score, reverse=True)
    picked: List[_ScoredCandidate] = []
    picked_keys: List[str] = []
    for cand in deduped:
        if len(picked) >= cap:
            break
        label = _display_label(cand.match.requirement.text)
        if len(label) > 44 and _coverage_of(cand.match.requirement.normalized_key, picked_keys) >= 0.5:
            continue
        picked.append(cand)
        picked_keys.append(cand.match.requirement.normalized_key)
    opportunities: List[TailoringImprovementOpportunity] = []
    for cand in picked:
        # Deterministic id from the normalized requirement: the /respond
        # endpoint re-derives opportunities statelessly, so ids must match
        # across calls for the same JD without server-side sessions.
        match = cand.match
        label = _display_label(match.requirement.text)
        title, prompt, helper = _friendly_copy(label, cand.opportunity_type)
        if cand.friendly_title:
            title = cand.friendly_title
        if cand.friendly_prompt:
            prompt = cand.friendly_prompt
        if cand.friendly_helper:
            helper = cand.friendly_helper
        for text in (title, prompt, helper):
            _assert_friendly(text)
        opportunities.append(
            TailoringImprovementOpportunity(
                id=hashlib.sha1(
                    match.requirement.normalized_key.encode("utf-8")
                ).hexdigest()[:12],
                requirement_id=match.requirement.text,
                normalized_requirement=match.requirement.normalized_key,
                display_label=label,
                importance=(match.requirement.importance or "medium").lower(),
                potential_impact=_potential_impact(match),
                existing_support=(match.candidate_phrasing or "")[:280] or None,
                opportunity_type=cand.opportunity_type,
                related_resume_content=list(cand.related),
                candidate_context_options=list(ExperienceContext),
                confidence=round(min(1.0, 0.4 + cand.score / 10.0), 3),
                status=OpportunityStatus.PENDING,
                friendly_title=title,
                friendly_prompt=prompt,
                friendly_helper=helper,
            )
        )
    return opportunities


# ---------------------------------------------------------------------------
# Batch answer extraction (deterministic, no LLM, no invented detail)
# ---------------------------------------------------------------------------

# Generic context cues — how candidates describe *where* they used something
# in any industry. These are language patterns, not role vocabulary.
_CONTEXT_CUES: List[Tuple[ExperienceContext, Tuple[str, ...]]] = [
    (ExperienceContext.INTERNSHIP, ("internship", "intern ", "as an intern", "summer intern")),
    (ExperienceContext.FREELANCE, ("freelance", "freelancer", "client project", "contract work", "consulting")),
    (ExperienceContext.ACADEMIC, ("college", "university", "school", "class project", "coursework", "course project", "academic", "semester", "thesis", "dissertation", "assignment", "lab ")),
    (ExperienceContext.OPEN_SOURCE, ("open source", "open-source", "oss contribution", "github contribution", "contributed to")),
    (ExperienceContext.VOLUNTEERING, ("volunteer", "volunteering", "nonprofit", "non-profit", "ngo ", "community")),
    (ExperienceContext.CERTIFICATION, ("certification", "certified", "certificate", "credential")),
    (ExperienceContext.TRAINING, ("training", "bootcamp", "workshop", "course ", "coursera", "udemy", "learned", "tutorial")),
    (ExperienceContext.PROJECT, ("project", "side project", "personal project", "built a", "built an", "developed a", "created a", "dashboard project", "app ")),
    (ExperienceContext.PROFESSIONAL, ("at work", "in my role", "my employer", "full-time", "full time", "on the job", "professionally", "production", "my team at", "at my company")),
]

_UNCERTAIN_RECALL_RE = re.compile(
    r"\b(don't remember|do not remember|can't remember|cannot remember|"
    r"not sure where|not sure which|can't recall|cannot recall|hard to recall|"
    r"forgot where|forgot which|don't recall|do not recall|"
    r"used before|used it before|worked with before|worked with it before|years ago)\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(
    r"\b(haven't|have not|hasn't|has not|never used|never worked|"
    r"no experience|not familiar|not used|did not use|haven't used|"
    r"don't know|no idea|didn't|did not|don't|do not|doesn't|does not)\b",
    re.IGNORECASE,
)
_PROJECT_NAME_RE = re.compile(
    r"(?:my|our|the)\s+([a-z0-9][a-z0-9 _-]{1,40}?)\s+project\b", re.IGNORECASE
)
_COARSE_SPLIT_RE = re.compile(r"[.;\n]+|,")
_FINE_SPLIT_RE = re.compile(r",|;|\bbut\b|\band\b|\bplus\b|\bas well as\b", re.IGNORECASE)


def _tokens_lower(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[a-z0-9+#./-]{2,}", text or "")}


def _mentions_requirement(free_text: str, normalized_key: str, display_label: str) -> bool:
    """True when the candidate's answer plausibly references this area.

    Generic token overlap — no fixed vocabulary. A requirement with no
    overlapping tokens is treated as unmentioned (insufficient to act on).
    """
    hay = _tokens_lower(free_text)
    if not hay:
        return False
    label_tokens = _tokens_lower(display_label)
    key_tokens = set((normalized_key or "").split())
    probe = (label_tokens | key_tokens) - _MENTION_STOPWORDS
    if not probe:
        return False
    overlap = probe & hay
    if not overlap:
        return False
    # Single generic token overlap ("data", "project") is not a mention;
    # require the most distinctive token or at least two shared tokens.
    if len(overlap) >= 2:
        return True
    distinctive = sorted(probe, key=len, reverse=True)[:2]
    return any(t in hay for t in distinctive if len(t) >= 4)


def _split_coarse(free_text: str) -> List[str]:
    """Split an answer into coarse clauses (sentence/comma boundaries)."""
    return [p.strip() for p in _COARSE_SPLIT_RE.split(free_text or "") if p.strip()]


def _split_fine(coarse_clause: str) -> List[str]:
    """Split a coarse clause into fine segments (conjunction boundaries)."""
    return [p.strip() for p in _FINE_SPLIT_RE.split(coarse_clause or "") if p.strip()]


def _classify_context_for(
    mentioning_segments: Sequence[str],
    sibling_segments: Sequence[str],
    hint: Optional[ExperienceContext],
) -> ExperienceContext:
    """Classify where experience comes from — conservative by design.

    An explicit UI hint wins. Otherwise cues are read from the segment(s)
    that actually mention the area. Sibling segments from the same sentence
    only contribute when the mentioning segment itself carries no cue
    ("I used React" inherits "college" from its sibling "TypeScript in my
    college project", but never "internship" from an unrelated clause about
    a different area). Defaults to OTHER (never professional) so nothing is
    upgraded into employment it was not described as.
    """
    if hint is not None:
        return hint
    for scope in (mentioning_segments, sibling_segments):
        lowered = f" {' '.join(scope).lower()} "
        for context, cues in _CONTEXT_CUES:
            if any(cue in lowered for cue in cues):
                return context
    return ExperienceContext.OTHER


def _extract_project_name(free_text: str) -> Optional[str]:
    m = _PROJECT_NAME_RE.search(free_text or "")
    if not m:
        return None
    name = " ".join(m.group(1).split()).strip(" -_,.")
    if len(name) < 2 or len(name) > 48:
        return None
    return name


def _project_name_for_clauses(
    mentioning_segments: Sequence[str],
    sibling_segments: Sequence[str],
    global_project_name: Optional[str],
) -> Optional[str]:
    """Attach the candidate's project name only when the area's own sentence
    evokes project work without a competing context cue.

    Sibling segments from the same sentence may supply the name itself
    ("I used React" + "TypeScript in my college dashboard project"), but a
    competing cue in the mentioning segment ("internship") always blocks the
    link. Prevents inventing associations across unrelated clauses.
    """
    if not global_project_name:
        return None
    own = " ".join(mentioning_segments).lower()
    scope = f"{own} {' '.join(sibling_segments).lower()}"
    if "project" not in scope:
        return None
    competing = ("internship", "freelance", "client", "employer", "at work",
                 "full-time", "full time", "volunteer", "certification")
    if any(cue in own for cue in competing):
        return None
    name_words = set(global_project_name.lower().split())
    if name_words & set(re.findall(r"[a-z0-9]+", scope)):
        return global_project_name
    return None


def _area_verdict(
    fine_groups: Sequence[Sequence[str]],
    free_text: str,
    normalized_key: str,
    display_label: str,
) -> str:
    """Per-area verdict for one shared answer: "confirm" | "decline" | "uncertain_recall" | "ambiguous".

    Fine segments mentioning the area are split by negation: affirmed
    mentions confirm, negated mentions decline, and negation wins ties (never
    add on doubt). If candidate expresses difficulty remembering the specific
    project/place, it is marked as "uncertain_recall" rather than "decline".
    """
    affirmed: List[str] = []
    negated: List[str] = []
    uncertain: List[str] = []
    for group in fine_groups:
        for segment in group:
            if _mentions_requirement(segment, normalized_key, display_label):
                if _UNCERTAIN_RECALL_RE.search(segment):
                    uncertain.append(segment)
                elif _NEGATION_RE.search(segment):
                    negated.append(segment)
                else:
                    affirmed.append(segment)
    if affirmed and not negated:
        return "confirm"
    if uncertain and not negated:
        return "uncertain_recall"
    if negated:
        return "decline"
    if _UNCERTAIN_RECALL_RE.search(free_text or "") and len((free_text or "").split()) <= 14:
        return "uncertain_recall"
    if _NEGATION_RE.search(free_text or "") and len((free_text or "").split()) <= 12:
        return "decline"
    return "ambiguous"


def _sibling_segments(
    fine_groups: Sequence[Sequence[str]], mentioning: Sequence[str]
) -> List[str]:
    """Sibling fine segments sharing a coarse clause with a mention."""
    mentioned = set(mentioning)
    siblings: List[str] = []
    for group in fine_groups:
        if any(seg in mentioned for seg in group):
            siblings.extend(seg for seg in group if seg not in mentioned)
    return siblings


def extract_facts_from_response(
    opportunities: Sequence[TailoringImprovementOpportunity],
    response: CandidateExperienceResponse,
) -> ExtractedBatchResult:
    """Extract structured facts from ONE collective natural-language answer.

    - Selected + mentioned + not negated -> confirmed fact (context from
      generic cues; never invented detail).
    - Selected + negated, or explicitly unselected with negation -> declined
      (stays unsupported, never re-asked via declined_ids).
    - Selected + uncertain recall ("don't remember where") -> confirmed
      familiarity without false project claims; never mass-declined.
    - Selected but unmentioned/ambiguous -> at most ONE compact clarification
      for the whole batch (never per-skill interrogation).
    """
    by_id = {o.id: o for o in opportunities}
    selected = [by_id[s] for s in response.selected_ids if s in by_id]
    result = ExtractedBatchResult()
    free_text = (response.free_text or "").strip()

    if not selected:
        return result

    if not free_text:
        # Nothing usable yet — one compact clarification, not per-item probes.
        labels = ", ".join(o.display_label for o in selected[:6])
        result.needs_clarification = (
            f"Thanks for selecting {labels}. Tell us a little about where "
            "you used each one and we'll see if we can work them into "
            "your resume."
        )
        result.unusable_ids = [o.id for o in selected]
        return result

    project_name = _extract_project_name(free_text)
    ambiguous: List[TailoringImprovementOpportunity] = []

    fine_groups = [_split_fine(coarse) for coarse in _split_coarse(free_text)]
    if free_text and not any(fine_groups):
        fine_groups = [[free_text]]

    for opp in selected:
        sub_tools = [s.strip() for s in opp.display_label.split(",") if s.strip()]
        if len(sub_tools) > 1:
            has_general_affirmation = any(
                aff in free_text.lower()
                for aff in ("used all", "used both", "worked with all", "worked with these", "used these", "experience with all", "used each", "used them")
            )
            has_general_decline = (
                bool(_NEGATION_RE.search(free_text))
                and any(dec in free_text.lower() for dec in ("none of", "never used any", "haven't used any", "no experience with any", "neither"))
            )
            if has_general_decline:
                result.declined_ids.append(opp.id)
                continue

            sub_facts_added = 0
            for sub_tool in sub_tools:
                sub_norm = normalize_key(sub_tool)
                sub_verdict = _area_verdict(fine_groups, free_text, sub_norm, sub_tool)
                if sub_verdict == "decline":
                    continue
                if sub_verdict == "uncertain_recall":
                    context = response.context_hints.get(opp.id) or ExperienceContext.OTHER
                    result.facts.append(
                        CandidateConfirmedFact(
                            opportunity_id=opp.id,
                            requirement_id=sub_tool,
                            normalized_requirement=sub_norm,
                            display_label=sub_tool,
                            selected=True,
                            candidate_context=context,
                            candidate_description=f"Confirmed familiarity with {sub_tool} from background",
                            project_name=None,
                            provenance="candidate_confirmed",
                            confidence=0.55,
                        )
                    )
                    sub_facts_added += 1
                    continue
                is_mentioned = _mentions_requirement(free_text, sub_norm, sub_tool)
                if is_mentioned or has_general_affirmation:
                    mentioning = [
                        seg for group in fine_groups for seg in group
                        if _mentions_requirement(seg, sub_norm, sub_tool) and not _NEGATION_RE.search(seg)
                    ]
                    if not mentioning and has_general_affirmation:
                        mentioning = [free_text]
                    siblings = _sibling_segments(fine_groups, mentioning)
                    context = _classify_context_for(
                        mentioning,
                        siblings,
                        response.context_hints.get(opp.id),
                    )
                    result.facts.append(
                        CandidateConfirmedFact(
                            opportunity_id=opp.id,
                            requirement_id=sub_tool,
                            normalized_requirement=sub_norm,
                            display_label=sub_tool,
                            selected=True,
                            candidate_context=context,
                            candidate_description=" ".join(mentioning)[:500],
                            project_name=_project_name_for_clauses(mentioning, siblings, project_name),
                            provenance="candidate_confirmed",
                            confidence=0.75 if context != ExperienceContext.OTHER else 0.6,
                        )
                    )
                    sub_facts_added += 1
            if sub_facts_added == 0 and not has_general_decline:
                ambiguous.append(opp)
            continue

        verdict = _area_verdict(
            fine_groups, free_text, opp.normalized_requirement, opp.display_label
        )
        if verdict == "decline":
            result.declined_ids.append(opp.id)
            continue
        if verdict == "uncertain_recall":
            # Candidate recalled using it, but couldn't remember where.
            # Do NOT decline (never treat 'don't remember where' as 'never used').
            context = response.context_hints.get(opp.id) or ExperienceContext.OTHER
            result.facts.append(
                CandidateConfirmedFact(
                    opportunity_id=opp.id,
                    requirement_id=opp.requirement_id,
                    normalized_requirement=opp.normalized_requirement,
                    display_label=opp.display_label,
                    selected=True,
                    candidate_context=context,
                    candidate_description=f"Confirmed familiarity with {opp.display_label} from background",
                    project_name=None,
                    provenance="candidate_confirmed",
                    confidence=0.55,
                )
            )
            continue
        if verdict == "ambiguous":
            ambiguous.append(opp)
            continue
        mentioning = [
            seg
            for group in fine_groups
            for seg in group
            if _mentions_requirement(seg, opp.normalized_requirement, opp.display_label)
            and not _NEGATION_RE.search(seg)
        ]
        siblings = _sibling_segments(fine_groups, mentioning)
        context = _classify_context_for(
            mentioning,
            siblings,
            response.context_hints.get(opp.id),
        )
        result.facts.append(
            CandidateConfirmedFact(
                opportunity_id=opp.id,
                requirement_id=opp.requirement_id,
                normalized_requirement=opp.normalized_requirement,
                display_label=opp.display_label,
                selected=True,
                candidate_context=context,
                candidate_description=" ".join(mentioning)[:500],
                project_name=_project_name_for_clauses(mentioning, siblings, project_name),
                provenance="candidate_confirmed",
                confidence=0.75 if context != ExperienceContext.OTHER else 0.6,
            )
        )

    # Explicit "no" for unselected opportunities is also honored (a negated
    # mention declines them; silence about them means nothing).
    for opp in opportunities:
        if opp.id in response.selected_ids or opp.id in result.declined_ids:
            continue
        if (
            _area_verdict(
                fine_groups, free_text, opp.normalized_requirement, opp.display_label
            )
            == "decline"
        ):
            # Only explicit negated mentions count here — a short global
            # negation must not mass-decline areas the answer never names.
            named_decline = any(
                _mentions_requirement(seg, opp.normalized_requirement, opp.display_label)
                and _NEGATION_RE.search(seg)
                for group in fine_groups
                for seg in group
            )
            if named_decline:
                result.declined_ids.append(opp.id)

    if ambiguous:
        # Sufficient facts were still used immediately; only genuinely
        # missing detail triggers ONE shared clarification.
        if not result.facts:
            labels = ", ".join(o.display_label for o in ambiguous[:6])
            result.needs_clarification = (
                f"We couldn't quite tell how you've used {labels}. If any "
                "apply, mention where you used each one — a project, course, "
                "internship, or role — and we'll take it from there."
            )
            result.unusable_ids = [o.id for o in ambiguous]
        else:
            result.unusable_ids = [o.id for o in ambiguous]
    return result


# ---------------------------------------------------------------------------
# Truthful merge into the tailoring evidence context
# ---------------------------------------------------------------------------

# Parenthetical, period-free notes: they double as prose grounding for the
# summary reframe ("strength in React (college dashboard project)"), so they
# must read cleanly mid-sentence. Only the confirmed label + generic context
# words + the candidate's own project name — never numbers or employers.
_CONTEXT_NOTE = {
    ExperienceContext.PROFESSIONAL: "{label} (professional experience)",
    ExperienceContext.INTERNSHIP: "{label} (internship experience)",
    ExperienceContext.FREELANCE: "{label} (freelance work)",
    ExperienceContext.ACADEMIC: "{label} (academic project)",
    ExperienceContext.PROJECT: "{label} (project experience)",
    ExperienceContext.OPEN_SOURCE: "{label} (open-source contribution)",
    ExperienceContext.VOLUNTEERING: "{label} (volunteering)",
    ExperienceContext.CERTIFICATION: "{label} (certification)",
    ExperienceContext.TRAINING: "{label} (training)",
    ExperienceContext.OTHER: "{label} (confirmed experience)",
}


def _context_sentence(fact: CandidateConfirmedFact) -> str:
    label = (fact.display_label or "").strip()
    if fact.project_name and fact.candidate_context in (
        ExperienceContext.PROJECT,
        ExperienceContext.ACADEMIC,
        ExperienceContext.OTHER,
    ):
        # Candidate's own project name, quoted without embellishment.
        return f"{label} ({fact.project_name} project)"
    template = _CONTEXT_NOTE.get(
        fact.candidate_context, _CONTEXT_NOTE[ExperienceContext.OTHER]
    )
    return template.format(label=label)


def build_augmented_profile(
    profile: ResumeProfile, facts: Sequence[CandidateConfirmedFact]
) -> ResumeProfile:
    """Merge confirmed facts into a working copy of the profile.

    Truthfulness rules enforced here:
    - Facts are added as skills + a plain ``additional`` note in the
      candidate's confirmed context. Non-professional contexts are never
      converted into employment entries, years, or metrics.
    - No numbers, employers, or responsibilities are synthesized. The added
      sentence contains only the confirmed label + generic context words.
    - The master profile is never mutated (deep copy).
    """
    augmented = copy.deepcopy(profile)
    if augmented.skills is None:
        from app.models.resume import SkillCategory

        augmented.skills = SkillCategory()

    existing_skills = {
        str(s).lower().strip()
        for bucket in (
            augmented.skills.technical,
            augmented.skills.tools,
            augmented.skills.languages,
            augmented.skills.databases,
            augmented.skills.analytics,
            augmented.skills.soft_skills,
        )
        for s in (bucket or [])
    }
    existing_skills |= {
        str(s).lower().strip()
        for vals in (augmented.skills.custom or {}).values()
        for s in (vals or [])
    }
    existing_notes = {(a.description or "").lower().strip() for a in (augmented.additional or [])}

    for fact in facts:
        label = (fact.display_label or "").strip()
        if not label:
            continue
        # 1. Ensure the confirmed area is a listed skill (technical bucket —
        #    the engine reorders within categories, never across them).
        if label.lower().strip() not in existing_skills:
            augmented.skills.technical.append(label)
            existing_skills.add(label.lower().strip())
        # 2. Ground it in prose so summaries/experience positioning can cite
        #    candidate language instead of bare skill labels.
        sentence = _context_sentence(fact)
        if sentence.lower().strip() not in existing_notes:
            from app.models.resume import AdditionalItem

            augmented.additional.append(AdditionalItem(title="Confirmed experience", description=sentence))
            existing_notes.add(sentence.lower().strip())
    return augmented


# ---------------------------------------------------------------------------
# Re-tailoring over the augmented evidence context
# ---------------------------------------------------------------------------


def _friendly_improvements(
    facts: Sequence[CandidateConfirmedFact],
    summary_changed: bool,
    skills_reordered: bool,
    baseline_score: float,
    tailored_score: float,
) -> Tuple[List[str], str]:
    improvements: List[str] = []
    for fact in facts:
        context_word = {
            ExperienceContext.PROFESSIONAL: "role",
            ExperienceContext.INTERNSHIP: "internship",
            ExperienceContext.FREELANCE: "freelance work",
            ExperienceContext.ACADEMIC: "academic work",
            ExperienceContext.PROJECT: "project",
            ExperienceContext.OPEN_SOURCE: "open-source work",
            ExperienceContext.VOLUNTEERING: "volunteering",
            ExperienceContext.CERTIFICATION: "certification",
            ExperienceContext.TRAINING: "training",
            ExperienceContext.OTHER: "background",
        }.get(fact.candidate_context, "background")
        improvements.append(
            f"{fact.display_label} experience from your {context_word} is now represented."
        )
    if skills_reordered:
        improvements.append("Relevant skills are now ordered toward the target role.")
    if summary_changed:
        improvements.append("Your summary now reflects the newly confirmed experience.")
    delta = round(tailored_score - baseline_score, 1)
    if delta >= MATERIAL_IMPROVEMENT_THRESHOLD:
        headline = "Your resume is now a stronger match for this role."
        explanation = (
            f"Match improved from {baseline_score:.0f}% to {tailored_score:.0f}% "
            "after working your confirmed experience into the resume."
        )
    elif facts:
        headline = "Your resume now reflects the experience you confirmed."
        explanation = (
            "The match score moved only a little, because the confirmed areas "
            "overlap with experience already on your resume or carry modest "
            "weight for this particular role. Nothing was added that you "
            "didn't confirm."
        )
    else:
        headline = FRIENDLY_DECLINED_NOTE
        explanation = (
            "No changes were made based on unconfirmed areas. Tailoring "
            "continues to use your existing verified experience."
        )
    return improvements[:8], f"{headline} {explanation}".strip()


def retaylor_with_confirmed_facts(
    resume_content: ResumeContent,
    job_description: str,
    facts: Sequence[CandidateConfirmedFact],
    job_title: Optional[str] = None,
    company: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge facts, re-run universal matching + tailoring, guards, rescore.

    Returns a dict with ``tailored_profile``, ``plan``, ``baseline_score``,
    ``tailored_score``, ``impact`` and ``guard_issues``. Raises ValueError
    with a safe message when the semantic guard rejects the output.
    """
    from app.services.ats.ats_analyzer import ATSAnalyzer
    from app.services.optimization.evidence_matcher import match_requirements
    from app.services.optimization.evidence_model import build_evidence_index
    from app.services.optimization.jd_requirements import parse_universal_jd
    from app.services.optimization.numeric_guard import numeric_guard
    from app.services.optimization.semantic_guard import semantic_guard
    from app.services.optimization.universal_tailoring_engine import run_universal_tailoring

    if not job_description or not job_description.strip():
        raise ValueError("Job description cannot be empty")

    analyzer = ATSAnalyzer()
    baseline = analyzer.analyze_resume(
        resume_content=resume_content,
        job_description=job_description,
        job_title=job_title,
        company=company,
    )
    baseline_score = round(float(baseline.overall_score), 1)

    original_summary = (resume_content.profile.summary or "").strip()
    original_skills = list(resume_content.profile.skills.technical or []) if resume_content.profile.skills else []

    if not facts:
        improvements, explanation = _friendly_improvements([], False, False, baseline_score, baseline_score)
        impact = RetailorImpact(
            baseline_score=baseline_score,
            tailored_score=baseline_score,
            delta=0.0,
            materially_improved=False,
            headline=FRIENDLY_DECLINED_NOTE,
            improvements=[],
            explanation=explanation,
        )
        return {
            "tailored_profile": copy.deepcopy(resume_content.profile).to_dict(),
            "plan": [],
            "baseline_score": baseline_score,
            "tailored_score": baseline_score,
            "impact": impact,
            "guard_issues": [],
            "applied_fact_count": 0,
        }

    augmented_profile = build_augmented_profile(resume_content.profile, facts)
    augmented_content = ResumeContent(profile=augmented_profile, meta=copy.deepcopy(resume_content.meta))
    if getattr(resume_content, "raw_text", None):
        augmented_content.raw_text = resume_content.raw_text

    universal_jd = parse_universal_jd(job_description, job_title, company)
    index = build_evidence_index(augmented_content)
    report = match_requirements(universal_jd, index)
    tailored_dict, plan, _limited, _message = run_universal_tailoring(
        profile=augmented_profile,
        universal_jd=universal_jd,
        report=report,
        evidence_index=index,
        job_title=job_title,
        company=company,
        is_fresher=bool(getattr(getattr(resume_content, "meta", None), "is_fresher", False)),
    )

    # Guards judge the augmented source (which legitimately contains the
    # candidate-confirmed facts) — never the pre-confirmation profile.
    _, numeric_issues = numeric_guard.audit_tailored_profile(
        source_profile=augmented_profile, tailored_profile_dict=tailored_dict
    )
    allowed = {*(job_title or "").split(), *(company or "").split()}
    _, semantic_issues = semantic_guard.audit_tailored_profile(
        source_profile=augmented_profile,
        tailored_profile_dict=tailored_dict,
        raw_source_text=getattr(augmented_content, "raw_text", None),
        allowed_terms={t.lower() for t in allowed if t},
    )
    guard_issues = list(numeric_issues) + list(semantic_issues)
    if semantic_issues:
        raise ValueError(
            "Tailoring output did not pass truthfulness checks and was discarded."
        )

    from app.models.resume import ResumeProfile as _Profile

    tailored_content = ResumeContent(
        profile=_Profile.from_dict(tailored_dict), meta=copy.deepcopy(resume_content.meta)
    )
    rescored = analyzer.analyze_resume(
        resume_content=tailored_content,
        job_description=job_description,
        job_title=job_title,
        company=company,
    )
    tailored_score = round(float(rescored.overall_score), 1)

    new_summary = (tailored_dict.get("summary") or "").strip()
    new_skills = list((tailored_dict.get("skills") or {}).get("technical") or [])
    summary_changed = bool(new_summary and new_summary != original_summary)
    skills_reordered = bool(new_skills and new_skills != original_skills)

    improvements, explanation = _friendly_improvements(
        facts, summary_changed, skills_reordered, baseline_score, tailored_score
    )
    delta = round(tailored_score - baseline_score, 1)
    impact = RetailorImpact(
        baseline_score=baseline_score,
        tailored_score=tailored_score,
        delta=delta,
        materially_improved=delta >= MATERIAL_IMPROVEMENT_THRESHOLD,
        headline=explanation.split(".")[0].strip() + "." if explanation else "",
        improvements=improvements,
        explanation=explanation,
    )
    return {
        "tailored_profile": tailored_dict,
        "plan": plan,
        "baseline_score": baseline_score,
        "tailored_score": tailored_score,
        "impact": impact,
        "guard_issues": guard_issues,
        "applied_fact_count": len(facts),
    }
