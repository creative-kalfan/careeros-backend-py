"""Friendly batch evidence discovery routes for resume tailoring.

Thin handlers: business logic lives in
``app.services.optimization.improvement_opportunities``. Reuses JD
extraction, evidence model/matcher, universal tailoring engine, ATS
scoring, and semantic guard — no second pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.models.resume import ResumeContent
from app.models.tailoring_evidence import (
    CandidateExperienceResponse,
    ExperienceContext,
    TailoringImprovementOpportunity,
)
from app.repositories.resume_repository import ResumeRepository
from app.schemas.tailoring_evidence import (
    ConfirmedFactSchema,
    ImpactSchema,
    OpportunityCardSchema,
    OpportunityRequest,
    OpportunityResponse,
    PlanItemSchema,
    RespondRequest,
    RespondResponse,
)
from app.services.optimization.evidence_matcher import match_requirements
from app.services.optimization.evidence_model import build_evidence_index
from app.services.optimization.improvement_opportunities import (
    FRIENDLY_BATCH_HEADING,
    FRIENDLY_BATCH_SUBHEADING,
    FRIENDLY_INPUT_LABEL,
    FRIENDLY_INPUT_PLACEHOLDER,
    FRIENDLY_SELECT_HINT,
    FRIENDLY_SKIP_LABEL,
    FRIENDLY_SUBMIT_LABEL,
    FRIENDLY_SUCCESS_NOTE,
    discover_opportunities,
    extract_facts_from_response,
    get_max_opportunities,
    retaylor_with_confirmed_facts,
)
from app.services.optimization.jd_requirements import parse_universal_jd

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/optimization/tailoring-evidence", tags=["optimization"])


def get_auth_token(authorization: Optional[str] = Header(None)) -> Optional[str]:
    if not authorization:
        return None
    try:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
    except Exception:
        pass
    return None


def _resolve_content(
    *,
    user_id: str,
    resume_id: Optional[str],
    version_id: Optional[str],
    content: Optional[Dict[str, Any]],
    token: Optional[str],
) -> ResumeContent:
    """Load resume content by id (ownership-checked) or use inline content."""
    if content:
        return ResumeContent.from_dict(content)
    if not resume_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "RESUME_REQUIRED",
                "message": "Provide resume content or a resume_id for evidence discovery.",
            },
        )
    repo = ResumeRepository(jwt=token)
    resume = repo.get_resume(user_id, resume_id)
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESUME_NOT_FOUND", "message": "Resume not found."},
        )
    if version_id:
        version = repo.get_version(version_id)
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "VERSION_NOT_FOUND", "message": "Resume version not found."},
            )
        if version.get("resume_id") != resume_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "VERSION_RESUME_MISMATCH",
                    "message": "Version does not belong to this resume.",
                },
            )
        return ResumeContent.from_dict(version.get("content") or {})
    return ResumeContent.from_dict(resume.get("content") or {})


def _build_opportunities(
    resume_content: ResumeContent,
    job_description: str,
    job_title: Optional[str],
    company: Optional[str],
    max_opportunities: Optional[int],
    known_fact_keys: List[str],
    declined_requirement_ids: List[str],
) -> List[TailoringImprovementOpportunity]:
    try:
        universal_jd = parse_universal_jd(job_description, job_title, company)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "JD_REQUIRED", "message": "Job description cannot be empty."},
        )
    index = build_evidence_index(resume_content)
    report = match_requirements(universal_jd, index)
    return discover_opportunities(
        universal_jd,
        report,
        index,
        max_opportunities=max_opportunities,
        known_fact_keys=known_fact_keys,
        declined_requirement_ids=declined_requirement_ids,
    )


@router.post("/opportunities", response_model=OpportunityResponse)
async def get_opportunities(
    payload: OpportunityRequest,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> OpportunityResponse:
    """Surface ONE batch of high-value improvement opportunities."""
    try:
        if not payload.job_description or not payload.job_description.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "JD_REQUIRED", "message": "Job description cannot be empty."},
            )
        resume_content = _resolve_content(
            user_id=current_user.user.id,
            resume_id=payload.resume_id,
            version_id=payload.version_id,
            content=payload.content,
            token=token,
        )
        opportunities = _build_opportunities(
            resume_content,
            payload.job_description,
            payload.job_title,
            payload.company,
            payload.max_opportunities,
            list(payload.known_fact_keys or []),
            list(payload.declined_requirement_ids or []),
        )
        cards = [
            OpportunityCardSchema(
                id=o.id,
                requirement_id=o.requirement_id,
                display_label=o.display_label,
                friendly_title=o.friendly_title,
                friendly_prompt=o.friendly_prompt,
                friendly_helper=o.friendly_helper,
                context_options=[c.value for c in o.candidate_context_options],
                confidence=o.confidence,
                status=o.status.value,
            )
            for o in opportunities
        ]
        cap = get_max_opportunities(payload.max_opportunities)
        if not opportunities:
            message = (
                "Your resume already covers the key areas for this role — "
                "no extra questions needed."
            )
        else:
            message = f"Found {len(opportunities)} area(s) worth a quick check (limit {cap})."
        return OpportunityResponse(
            success=True,
            heading=FRIENDLY_BATCH_HEADING,
            subheading=FRIENDLY_BATCH_SUBHEADING,
            select_hint=FRIENDLY_SELECT_HINT,
            input_label=FRIENDLY_INPUT_LABEL,
            input_placeholder=FRIENDLY_INPUT_PLACEHOLDER,
            skip_label=FRIENDLY_SKIP_LABEL,
            submit_label=FRIENDLY_SUBMIT_LABEL,
            opportunities=cards,
            message=message,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Tailoring evidence opportunities failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "OPPORTUNITIES_FAILED",
                "message": "Could not prepare improvement suggestions. Please try again.",
            },
        )


@router.post("/respond", response_model=RespondResponse)
async def respond_with_experience(
    payload: RespondRequest,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> RespondResponse:
    """Accept ONE collective answer, extract facts, re-tailor, and rescore."""
    try:
        if not payload.job_description or not payload.job_description.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "JD_REQUIRED", "message": "Job description cannot be empty."},
            )
        resume_content = _resolve_content(
            user_id=current_user.user.id,
            resume_id=payload.resume_id,
            version_id=payload.version_id,
            content=payload.content,
            token=token,
        )
        # Re-derive server-side: opportunity ids are deterministic
        # (sha1 of the normalized requirement), so the selected ids from the
        # /opportunities call match without server-side sessions. Client-sent
        # cards are display-only and never trusted for matching state.
        opportunities = _build_opportunities(
            resume_content,
            payload.job_description,
            payload.job_title,
            payload.company,
            None,
            [],
            [],
        )
        if not opportunities:
            # Fall back to lenient parsing of client-sent cards so a valid
            # answer is never dropped when re-derivation finds no gaps.
            for raw in payload.opportunities or []:
                try:
                    opportunities.append(
                        TailoringImprovementOpportunity.model_validate(raw)
                    )
                except Exception:
                    try:
                        opportunities.append(
                            TailoringImprovementOpportunity(
                                id=str(raw.get("id") or raw.get("requirement_id") or ""),
                                requirement_id=str(
                                    raw.get("requirement_id")
                                    or raw.get("requirementId")
                                    or ""
                                ),
                                normalized_requirement=str(
                                    raw.get("normalized_requirement")
                                    or raw.get("normalizedRequirement")
                                    or ""
                                ),
                                display_label=str(
                                    raw.get("display_label")
                                    or raw.get("displayLabel")
                                    or ""
                                ),
                                friendly_title=str(raw.get("friendly_title") or raw.get("friendlyTitle") or ""),
                                friendly_prompt=str(raw.get("friendly_prompt") or raw.get("friendlyPrompt") or ""),
                                friendly_helper=str(raw.get("friendly_helper") or raw.get("friendlyHelper") or ""),
                            )
                        )
                    except Exception:
                        continue

        hints = {}
        for key, value in (payload.context_hints or {}).items():
            try:
                hints[key] = ExperienceContext(str(value).lower().strip())
            except ValueError:
                continue
        candidate_response = CandidateExperienceResponse(
            opportunity_ids=[o.id for o in opportunities],
            selected_ids=list(payload.selected_ids or []),
            free_text=payload.free_text or "",
            context_hints=hints,
        )
        extracted = extract_facts_from_response(opportunities, candidate_response)

        if not extracted.facts:
            impact = ImpactSchema(
                baseline_score=0.0,
                tailored_score=0.0,
                delta=0.0,
                materially_improved=False,
                headline="No changes yet.",
                improvements=[],
                explanation=extracted.needs_clarification
                or "Thanks — we'll keep tailoring with your existing experience.",
            )
            return RespondResponse(
                success=True,
                facts=[],
                declined_ids=list(extracted.declined_ids),
                needs_clarification=extracted.needs_clarification,
                success_note="",
                tailored_profile={},
                plan=[],
                impact=impact,
                guard_issues=[],
                message="No confirmed experience to apply yet.",
            )

        try:
            result = retaylor_with_confirmed_facts(
                resume_content=resume_content,
                job_description=payload.job_description,
                facts=extracted.facts,
                job_title=payload.job_title,
                company=payload.company,
            )
        except ValueError as ve:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "SEMANTIC_FABRICATION", "message": str(ve)},
            )

        plan_items = []
        for item in result.get("plan") or []:
            try:
                plan_items.append(
                    PlanItemSchema(
                        section=str(getattr(item, "section", "general")),
                        action=str(getattr(item, "action", "ALIGN")),
                        target_id=getattr(item, "target_id", None),
                        current_text=getattr(item, "current_text", None),
                        suggested_text=getattr(item, "suggested_text", None),
                        reasoning=str(getattr(item, "reasoning", "")),
                        keywords_addressed=list(getattr(item, "keywords_addressed", []) or []),
                    )
                )
            except Exception:
                continue
        impact_model = result.get("impact")
        impact_schema = ImpactSchema(
            baseline_score=float(getattr(impact_model, "baseline_score", 0.0)),
            tailored_score=float(getattr(impact_model, "tailored_score", 0.0)),
            delta=float(getattr(impact_model, "delta", 0.0)),
            materially_improved=bool(getattr(impact_model, "materially_improved", False)),
            headline=str(getattr(impact_model, "headline", "")),
            improvements=list(getattr(impact_model, "improvements", []) or []),
            explanation=str(getattr(impact_model, "explanation", "")),
        )
        return RespondResponse(
            success=True,
            facts=[
                ConfirmedFactSchema(
                    id=f.id,
                    opportunity_id=f.opportunity_id,
                    requirement_id=f.requirement_id,
                    display_label=f.display_label,
                    candidate_context=f.candidate_context.value,
                    candidate_description=f.candidate_description,
                    project_name=f.project_name,
                    provenance=f.provenance,
                    confidence=f.confidence,
                )
                for f in extracted.facts
            ],
            declined_ids=list(extracted.declined_ids),
            needs_clarification=extracted.needs_clarification,
            success_note=FRIENDLY_SUCCESS_NOTE,
            tailored_profile=dict(result.get("tailored_profile") or {}),
            plan=plan_items,
            impact=impact_schema,
            guard_issues=list(result.get("guard_issues") or []),
            message=impact_schema.explanation,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Tailoring evidence respond failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "RESPOND_FAILED",
                "message": "Could not apply your experience. Please try again.",
            },
        )
