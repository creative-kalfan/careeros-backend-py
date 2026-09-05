"""Interview Preparation domain models.

Covers question categories, session/question schemas, the structured LLM
output contract, interview-type awareness, answer-framework templates, and
source-fingerprint helpers for staleness detection.

Fabrication rule (enforced in ``app.services.interview_prep.grounding``):
talking points and evidence must reference actual candidate evidence. When
evidence does not exist the system surfaces
``UNSUPPORTED_EVIDENCE_MARKER`` instead of inventing content.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


UNSUPPORTED_EVIDENCE_MARKER = "Not supported by current resume evidence."

VALID_CATEGORIES = (
    "behavioral",
    "technical",
    "role_specific",
    "resume_deep_dive",
    "situational",
    "company_context",
)

VALID_DIFFICULTIES = ("foundational", "intermediate", "advanced")

VALID_STATUSES = ("generating", "ready", "failed")

CATEGORY_LABELS: dict[str, str] = {
    "behavioral": "Behavioral",
    "technical": "Technical",
    "role_specific": "Role-specific",
    "resume_deep_dive": "Resume deep-dive",
    "situational": "Situational",
    "company_context": "Company & context",
}


class InterviewType(str, Enum):
    """Normalized interview round types."""

    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    HIRING_MANAGER = "hiring_manager"
    RECRUITER = "recruiter"
    ASSESSMENT = "assessment"
    GENERAL = "general"


# Desired category mix per interview type. Weights sum ~1.0; the planner
# converts them into concrete per-category counts for a target total.
INTERVIEW_TYPE_PLANS: dict[str, dict[str, float]] = {
    "technical": {
        "technical": 0.35,
        "role_specific": 0.20,
        "resume_deep_dive": 0.15,
        "situational": 0.15,
        "behavioral": 0.10,
        "company_context": 0.05,
    },
    "behavioral": {
        "behavioral": 0.40,
        "situational": 0.20,
        "resume_deep_dive": 0.15,
        "role_specific": 0.10,
        "company_context": 0.10,
        "technical": 0.05,
    },
    "hiring_manager": {
        "role_specific": 0.25,
        "resume_deep_dive": 0.20,
        "behavioral": 0.20,
        "situational": 0.15,
        "technical": 0.10,
        "company_context": 0.10,
    },
    "recruiter": {
        "behavioral": 0.25,
        "company_context": 0.25,
        "role_specific": 0.20,
        "resume_deep_dive": 0.15,
        "situational": 0.10,
        "technical": 0.05,
    },
    "assessment": {
        "technical": 0.25,
        "situational": 0.25,
        "role_specific": 0.20,
        "resume_deep_dive": 0.15,
        "behavioral": 0.10,
        "company_context": 0.05,
    },
    "general": {
        "behavioral": 0.20,
        "technical": 0.20,
        "role_specific": 0.20,
        "resume_deep_dive": 0.15,
        "situational": 0.15,
        "company_context": 0.10,
    },
}

ANSWER_FRAMEWORKS: dict[str, dict[str, Any]] = {
    "behavioral": {
        "type": "STAR",
        "steps": ["Situation", "Task", "Action", "Result", "Reflection"],
        "guidance": "Anchor each step in a real experience from the resume. "
        "Keep the Situation/Task brief; spend most time on Action and the measured Result.",
    },
    "technical": {
        "type": "Problem-Approach-Validation",
        "steps": ["Problem", "Constraints", "Approach", "Trade-offs",
                  "Implementation", "Validation", "Result"],
        "guidance": "State the problem and constraints first, compare approaches "
        "with trade-offs, then describe what was actually implemented and how it was validated.",
    },
    "system_design": {
        "type": "Requirements-Architecture",
        "steps": ["Requirements", "Architecture", "Data flow", "Scaling",
                  "Reliability", "Failure modes", "Trade-offs"],
        "guidance": "Clarify requirements before drawing architecture. Cover data flow, "
        "scaling, reliability, and failure modes explicitly.",
    },
    "situational": {
        "type": "STAR",
        "steps": ["Situation", "Task", "Action", "Result", "Reflection"],
        "guidance": "Describe what you would do and ground it in what you have done before. "
        "Name the analogous past experience explicitly.",
    },
    "general": {
        "type": "Point-Evidence-Outcome",
        "steps": ["Point", "Evidence", "Outcome"],
        "guidance": "Make one clear point, support it with resume evidence, close with the outcome.",
    },
}


def infer_interview_type(name: str | None) -> tuple[str, bool]:
    """Infer a normalized interview type from a free-text round name.

    Returns ``(interview_type, assumed)`` where ``assumed`` is True when the
    name carried no recognizable signal and a balanced default was used.
    Never invents interviewer information.
    """
    raw = (name or "").strip().lower()
    if not raw:
        return InterviewType.GENERAL.value, True
    if any(k in raw for k in ("system design", "architecture", "technical", "coding",
                              "debug", "engineering", "take home", "take-home")):
        # "take-home" style assessments are technical in nature but assessed;
        # keep explicit assessment keywords authoritative below.
        if any(k in raw for k in ("assessment", "take-home", "take home", "task", "case study")):
            return InterviewType.ASSESSMENT.value, False
        return InterviewType.TECHNICAL.value, False
    if any(k in raw for k in ("assessment", "task", "case study", "work sample")):
        return InterviewType.ASSESSMENT.value, False
    if any(k in raw for k in ("behavioral", "behavior", "values", "culture", "star")):
        return InterviewType.BEHAVIORAL.value, False
    if any(k in raw for k in ("hiring manager", "manager", "team lead", "director", "vp ")):
        return InterviewType.HIRING_MANAGER.value, False
    if any(k in raw for k in ("hr", "recruiter", "screen", "phone", "intro", "logistics")):
        return InterviewType.RECRUITER.value, False
    if any(k in raw for k in ("final", "onsite", "panel", "loop")):
        return InterviewType.GENERAL.value, True
    return InterviewType.GENERAL.value, True


def plan_categories(interview_type: str, total: int = 8) -> list[str]:
    """Expand an interview-type plan into an ordered category list."""
    weights = INTERVIEW_TYPE_PLANS.get(interview_type, INTERVIEW_TYPE_PLANS["general"])
    total = max(3, min(10, total))
    counts: dict[str, int] = {cat: int(w * total) for cat, w in weights.items()}
    # Distribute the remainder to the highest-weight categories.
    remainder = total - sum(counts.values())
    ordered = sorted(weights, key=lambda c: weights[c], reverse=True)
    idx = 0
    while remainder > 0:
        counts[ordered[idx % len(ordered)]] += 1
        remainder -= 1
        idx += 1
    result: list[str] = []
    for cat in ordered:
        result.extend([cat] * counts[cat])
    return result[:total]


def framework_for(category: str, question: str = "") -> dict[str, Any]:
    """Return the answer-framework template for a question category."""
    q = (question or "").lower()
    if category == "technical" and any(
        k in q for k in ("design", "architect", "scale", "system")
    ):
        return ANSWER_FRAMEWORKS["system_design"]
    if category in ("behavioral", "situational"):
        return ANSWER_FRAMEWORKS["behavioral"]
    if category == "technical":
        return ANSWER_FRAMEWORKS["technical"]
    return ANSWER_FRAMEWORKS["general"]


def build_source_fingerprint(
    job_description: str = "",
    resume_updated_at: str | None = None,
    interview_type: str = "general",
    resume_id: str | None = None,
) -> str:
    """Build a lightweight fingerprint of the generation source context."""
    material = "|".join([
        interview_type,
        resume_id or "",
        resume_updated_at or "",
        hashlib.sha256((job_description or "").encode("utf-8")).hexdigest(),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Structured LLM output contract
# ---------------------------------------------------------------------------


class InterviewPrepQuestionDraft(BaseModel):
    """One LLM-drafted preparation question (validated before persistence)."""

    category: str = Field(description="One of the six supported categories")
    question: str = Field(description="The interview question text")
    difficulty: str = "intermediate"
    rationale: str = Field(default="", description="Why this question matters for this candidate")
    resume_evidence: list[str] = Field(
        default_factory=list,
        description="Verbatim or near-verbatim evidence strings from the resume",
    )
    talking_points: list[str] = Field(
        default_factory=list,
        description="Concise talking points grounded in candidate evidence",
    )
    expected_signals: list[str] = Field(default_factory=list)
    related_jd_requirements: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(
        default_factory=list,
        description="JD requirements the resume does not support (explicit gaps)",
    )


class InterviewPrepLLMOutput(BaseModel):
    """Top-level structured response for a preparation generation pass."""

    questions: list[InterviewPrepQuestionDraft] = Field(default_factory=list)
    assumption_note: str = ""
    gaps: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API schemas
# ---------------------------------------------------------------------------


class InterviewPrepGenerateRequest(BaseModel):
    application_id: str
    interview_id: Optional[str] = None
    resume_id: Optional[str] = None
    job_id: Optional[str] = None
    question_count: int = 8
    async_mode: bool = False


class InterviewPrepQuestionUpdate(BaseModel):
    is_prepared: Optional[bool] = None
    is_bookmarked: Optional[bool] = None
