"""API routes for Resume Improvement Intelligence (Target 5.1).

Target 5.1: truthful per-requirement improvement assessment.

These routes are thin — all business logic lives in
``app.services.improvement.improvement_service``.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, status

from app.dependencies import get_current_user
from app.auth.service import AuthContext
from app.models.ats import ATSAnalysisReport, RequirementCoverage
from app.models.improvement import (
    ImprovementClassification,
    ImprovementProposal,
    ProposalDecisionState,
    ProposalEligibility,
)
from app.services.improvement.improvement_service import (
    ResumeImprovementService,
    get_improvement_service,
)
from app.services.improvement.proposal_review_service import (
    ProposalReviewService,
    get_proposal_review_service,
    determine_proposal_eligibility,
)
from app.services.improvement.proposal_application_service import (
    ProposalApplicationService,
    get_proposal_application_service,
    ConflictError,
    ProvenanceViolationError,
    UnapprovedProposalError,
)
from app.repositories.ats_repository import ATSReportRepository
from app.models.resume import ResumeContent
from app.repositories.resume_repository import ResumeRepository
from app.schemas.improvement import (
    ImprovementAssessmentResponse,
    ImprovementProposalResponse,
    AssessImprovementResponse,
    ProposalDecisionRequest,
    BulkDecisionRequest,
    ProposalDecisionResponse,
    ListProposalDecisionsResponse,
    ApprovedProposalResponse,
    ApprovedChangeSetResponse,
    BulkDecisionResponse,
    ApplyApprovedImprovementsRequest,
    AppliedProposalSummaryResponse,
    ApplyApprovedImprovementsResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/improvement", tags=["improvement"])

ats_repo = ATSReportRepository()


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


def _get_report_and_coverage(
    report_id: str,
    token: Optional[str],
    user_id: Optional[str] = None,
) -> tuple[ATSAnalysisReport, list[RequirementCoverage]]:
    """Fetch a report and its requirement coverage, raising 404 if missing or unauthorized."""
    report = ats_repo.get_report(report_id, jwt=token)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ATS analysis report not found",
        )
    if user_id and report.resume_id:
        repo = ResumeRepository(jwt=token)
        owned_resume = repo.get_resume(user_id, report.resume_id)
        if not owned_resume:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ATS analysis report not found",
            )
    coverage = [
        RequirementCoverage.model_validate(item)
        for item in (report.requirement_analysis or [])
    ]
    return report, coverage


@router.post(
    "/ats/{report_id}/assess",
    response_model=AssessImprovementResponse,
)
async def assess_improvements(
    report_id: str,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> AssessImprovementResponse:
    """Generate batched evidence-grounded improvement proposals for an ATS report (Target 5.3).

    Strictly review-only: does NOT modify ATS scores or PDF coordinates.
    """
    jwt_token = current_user.jwt or token
    report, coverage = _get_report_and_coverage(report_id, jwt_token, user_id=current_user.user.id)
    service: ResumeImprovementService = get_improvement_service()

    # Load ResumeContent if available
    resume_content = ResumeContent()
    if report.resume_id:
        try:
            resume_repo = ResumeRepository(jwt=jwt_token)
            resume_data = resume_repo.get_by_id(report.resume_id, jwt=jwt_token)
            if resume_data and resume_data.get("content"):
                resume_content = ResumeContent.from_dict(resume_data.get("content") or {})
        except Exception as exc:
            logger.warning("Could not load resume content for %s: %s", report.resume_id, exc)

    batch_result = await service.assess(
        coverage=coverage,
        resume_content=resume_content,
        job_title=report.job_title,
        company=report.company,
    )

    review_service = get_proposal_review_service()
    existing_decisions = review_service.get_decisions_for_report(report_id, jwt=token)
    dec_map = {d.proposal_id: d for d in existing_decisions}

    assessment_responses: list[ImprovementAssessmentResponse] = []
    for ass in batch_result.assessments:
        proposals = []
        for p in ass.proposals:
            elig, elig_reasons = determine_proposal_eligibility(p)
            dec_rec = dec_map.get(p.id)
            dec_state = dec_rec.decision.value if dec_rec else ProposalDecisionState.PENDING.value
            dec_at = dec_rec.decided_at.isoformat() if dec_rec and dec_rec.decided_at else None

            proposals.append(
                ImprovementProposalResponse(
                    id=p.id,
                    requirement_id=p.requirement_id,
                    target_section=p.target_section,
                    target_entry_id=p.target_entry_id,
                    provenance=p.provenance,
                    original_text=p.original_text,
                    proposed_wording=p.proposed_wording,
                    rationale=p.rationale,
                    diff_summary=p.diff_summary,
                    metrics_prompt=p.metrics_prompt,
                    evidence_sources=p.evidence_sources,
                    safety_flags=p.safety_flags,
                    confidence=p.confidence,
                    ai_generated=p.ai_generated,
                    decision=dec_state,
                    eligibility=elig.value,
                    eligibility_reasons=elig_reasons,
                    decided_at=dec_at,
                )
            )
        assessment_responses.append(
            ImprovementAssessmentResponse(
                requirement_id=ass.requirement_id,
                classification=ass.classification.value if hasattr(ass.classification, "value") else str(ass.classification),
                confidence=ass.confidence,
                existing_evidence=ass.existing_evidence,
                evidence_source=ass.evidence_source,
                evidence_type=ass.evidence_type.value if hasattr(ass.evidence_type, "value") else (str(ass.evidence_type) if ass.evidence_type else None),
                current_wording=ass.current_wording,
                proposed_wording=ass.proposed_wording,
                rationale=ass.rationale,
                safety_flags=ass.safety_flags,
                ai_generated=ass.ai_generated,
                proposals=proposals,
            )
        )

    return AssessImprovementResponse(
        success=batch_result.success,
        fallback_used=batch_result.fallback_used,
        message=batch_result.message,
        provider_used=batch_result.provider_used,
        model_used=batch_result.model_used,
        assessments=assessment_responses,
    )


@router.get(
    "/ats/{report_id}/requirements/{requirement_id}",
    response_model=ImprovementAssessmentResponse,
)
async def get_requirement_improvement(
    report_id: str,
    requirement_id: str,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> ImprovementAssessmentResponse:
    """Get the truthful improvement assessment for a single requirement.

    No ATS recalculation occurs — this derives from the existing persisted
    ATS analysis. Does not change ATS scores.
    """
    jwt_token = current_user.jwt or token
    report, coverage = _get_report_and_coverage(report_id, jwt_token, user_id=current_user.user.id)
    service: ResumeImprovementService = get_improvement_service()

    cov = next(
        (c for c in coverage if c.requirement == requirement_id), None
    )
    if cov is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requirement not found in this ATS analysis",
        )

    assessment = service.build_deterministic_assessment(cov, analysis=None)

    review_service = get_proposal_review_service()
    existing_decisions = review_service.get_decisions_for_report(report_id, jwt=token)
    dec_map = {d.proposal_id: d for d in existing_decisions}

    proposals = []
    for p in assessment.proposals:
        elig, elig_reasons = determine_proposal_eligibility(p)
        dec_rec = dec_map.get(p.id)
        dec_state = dec_rec.decision.value if dec_rec else ProposalDecisionState.PENDING.value
        dec_at = dec_rec.decided_at.isoformat() if dec_rec and dec_rec.decided_at else None

        proposals.append(
            ImprovementProposalResponse(
                id=p.id,
                requirement_id=p.requirement_id,
                target_section=p.target_section,
                target_entry_id=p.target_entry_id,
                provenance=p.provenance,
                original_text=p.original_text,
                proposed_wording=p.proposed_wording,
                rationale=p.rationale,
                diff_summary=p.diff_summary,
                metrics_prompt=p.metrics_prompt,
                evidence_sources=p.evidence_sources,
                safety_flags=p.safety_flags,
                confidence=p.confidence,
                ai_generated=p.ai_generated,
                decision=dec_state,
                eligibility=elig.value,
                eligibility_reasons=elig_reasons,
                decided_at=dec_at,
            )
        )

    return ImprovementAssessmentResponse(
        requirement_id=assessment.requirement_id,
        classification=assessment.classification.value if hasattr(assessment.classification, "value") else str(assessment.classification),
        confidence=assessment.confidence,
        existing_evidence=assessment.existing_evidence,
        evidence_source=assessment.evidence_source,
        evidence_type=assessment.evidence_type.value if hasattr(assessment.evidence_type, "value") else (str(assessment.evidence_type) if assessment.evidence_type else None),
        current_wording=assessment.current_wording,
        proposed_wording=assessment.proposed_wording,
        rationale=assessment.rationale,
        safety_flags=assessment.safety_flags,
        ai_generated=assessment.ai_generated,
        proposals=proposals,
    )





# ---------------------------------------------------------------------------
# Target 5.4 — Proposal Review, Approval Workflow & Change Set Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/ats/{report_id}/decisions",
    response_model=ListProposalDecisionsResponse,
)
async def list_proposal_decisions(
    report_id: str,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> ListProposalDecisionsResponse:
    """List all proposal review decisions recorded for an ATS report (Target 5.4)."""
    jwt_token = current_user.jwt or token
    report, _ = _get_report_and_coverage(report_id, jwt_token, user_id=current_user.user.id)
    service = get_proposal_review_service()
    decisions = service.get_decisions_for_report(report_id, jwt=jwt_token)

    summary = {"approved": 0, "rejected": 0, "pending": 0}
    responses: list[ProposalDecisionResponse] = []
    for d in decisions:
        dec_val = d.decision.value if hasattr(d.decision, "value") else str(d.decision)
        if dec_val in summary:
            summary[dec_val] += 1
        responses.append(
            ProposalDecisionResponse(
                id=d.id,
                resume_id=d.resume_id,
                report_id=d.report_id,
                proposal_id=d.proposal_id,
                requirement_id=d.requirement_id,
                decision=dec_val,
                eligibility=d.eligibility.value if hasattr(d.eligibility, "value") else str(d.eligibility),
                eligibility_reasons=d.eligibility_reasons,
                target_section=d.target_section,
                target_entry_id=d.target_entry_id,
                original_text=d.original_text,
                proposed_wording=d.proposed_wording,
                rationale=d.rationale,
                diff_summary=d.diff_summary,
                metrics_prompt=d.metrics_prompt,
                provenance=d.provenance,
                evidence_sources=d.evidence_sources,
                safety_flags=d.safety_flags,
                confidence=d.confidence,
                decided_at=d.decided_at.isoformat() if d.decided_at else None,
                created_at=d.created_at.isoformat() if d.created_at else None,
                updated_at=d.updated_at.isoformat() if d.updated_at else None,
            )
        )

    return ListProposalDecisionsResponse(
        success=True,
        decisions=responses,
        summary=summary,
    )


@router.post(
    "/ats/{report_id}/proposals/{proposal_id}/decision",
    response_model=ProposalDecisionResponse,
)
async def set_proposal_decision(
    report_id: str,
    proposal_id: str,
    payload: ProposalDecisionRequest,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> ProposalDecisionResponse:
    """Record an explicit user decision (approve / reject / pending) on a proposal (Target 5.4).

    Strictly review/decision layer: does NOT modify the resume document or ATS score.
    Blocked proposals cannot be approved.
    """
    jwt_token = current_user.jwt or token
    report, _ = _get_report_and_coverage(report_id, jwt_token, user_id=current_user.user.id)
    service = get_proposal_review_service()

    # Parse desired decision state
    try:
        decision_state = ProposalDecisionState(payload.decision.lower().strip())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid decision state '{payload.decision}'. Must be pending, approved, or rejected.",
        )

    # Reconstruct or resolve proposal
    prop_resp = payload.proposal
    if prop_resp:
        proposal = ImprovementProposal(
            id=proposal_id,
            requirement_id=prop_resp.requirement_id,
            target_section=prop_resp.target_section,
            target_entry_id=prop_resp.target_entry_id,
            provenance=prop_resp.provenance,
            original_text=prop_resp.original_text,
            proposed_wording=prop_resp.proposed_wording,
            rationale=prop_resp.rationale,
            diff_summary=prop_resp.diff_summary,
            metrics_prompt=prop_resp.metrics_prompt,
            evidence_sources=prop_resp.evidence_sources,
            safety_flags=prop_resp.safety_flags,
            confidence=prop_resp.confidence,
            ai_generated=prop_resp.ai_generated,
        )
    else:
        # Check existing decision record for proposal data
        existing_dec = service._repo.get_decision(report_id, proposal_id, jwt=jwt_token)
        if not existing_dec:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Proposal payload is required for first-time decision recording.",
            )
        proposal = ImprovementProposal(
            id=proposal_id,
            requirement_id=existing_dec.requirement_id,
            target_section=existing_dec.target_section,
            target_entry_id=existing_dec.target_entry_id,
            provenance=existing_dec.provenance,
            original_text=existing_dec.original_text,
            proposed_wording=existing_dec.proposed_wording or "",
            rationale=existing_dec.rationale,
            diff_summary=existing_dec.diff_summary,
            metrics_prompt=existing_dec.metrics_prompt,
            evidence_sources=existing_dec.evidence_sources,
            safety_flags=existing_dec.safety_flags,
            confidence=existing_dec.confidence,
        )

    try:
        decision = service.record_decision(
            resume_id=report.resume_id or "",
            report_id=report_id,
            proposal=proposal,
            decision_state=decision_state,
            jwt=jwt_token,
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )

    return ProposalDecisionResponse(
        id=decision.id,
        resume_id=decision.resume_id,
        report_id=decision.report_id,
        proposal_id=decision.proposal_id,
        requirement_id=decision.requirement_id,
        decision=decision.decision.value if hasattr(decision.decision, "value") else str(decision.decision),
        eligibility=decision.eligibility.value if hasattr(decision.eligibility, "value") else str(decision.eligibility),
        eligibility_reasons=decision.eligibility_reasons,
        target_section=decision.target_section,
        target_entry_id=decision.target_entry_id,
        original_text=decision.original_text,
        proposed_wording=decision.proposed_wording,
        rationale=decision.rationale,
        diff_summary=decision.diff_summary,
        metrics_prompt=decision.metrics_prompt,
        provenance=decision.provenance,
        evidence_sources=decision.evidence_sources,
        safety_flags=decision.safety_flags,
        confidence=decision.confidence,
        decided_at=decision.decided_at.isoformat() if decision.decided_at else None,
        created_at=decision.created_at.isoformat() if decision.created_at else None,
        updated_at=decision.updated_at.isoformat() if decision.updated_at else None,
    )


@router.post(
    "/ats/{report_id}/proposals/bulk-decision",
    response_model=BulkDecisionResponse,
)
async def set_bulk_proposal_decision(
    report_id: str,
    payload: BulkDecisionRequest,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> BulkDecisionResponse:
    """Execute bulk approve or reject actions (Target 5.4).

    'approve_all_safe' operates strictly on non-blocked proposals and skips blocked ones.
    """
    jwt_token = current_user.jwt or token
    report, _ = _get_report_and_coverage(report_id, jwt_token, user_id=current_user.user.id)
    service = get_proposal_review_service()

    proposals: list[ImprovementProposal] = [
        ImprovementProposal(
            id=p.id,
            requirement_id=p.requirement_id,
            target_section=p.target_section,
            target_entry_id=p.target_entry_id,
            provenance=p.provenance,
            original_text=p.original_text,
            proposed_wording=p.proposed_wording,
            rationale=p.rationale,
            diff_summary=p.diff_summary,
            metrics_prompt=p.metrics_prompt,
            evidence_sources=p.evidence_sources,
            safety_flags=p.safety_flags,
            confidence=p.confidence,
            ai_generated=p.ai_generated,
        )
        for p in payload.proposals
    ]

    try:
        result = service.bulk_decision(
            resume_id=report.resume_id or "",
            report_id=report_id,
            proposals=proposals,
            action=payload.action,
            jwt=jwt_token,
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )

    decision_responses: list[ProposalDecisionResponse] = [
        ProposalDecisionResponse(
            id=d.id,
            resume_id=d.resume_id,
            report_id=d.report_id,
            proposal_id=d.proposal_id,
            requirement_id=d.requirement_id,
            decision=d.decision.value if hasattr(d.decision, "value") else str(d.decision),
            eligibility=d.eligibility.value if hasattr(d.eligibility, "value") else str(d.eligibility),
            eligibility_reasons=d.eligibility_reasons,
            target_section=d.target_section,
            target_entry_id=d.target_entry_id,
            original_text=d.original_text,
            proposed_wording=d.proposed_wording,
            rationale=d.rationale,
            diff_summary=d.diff_summary,
            metrics_prompt=d.metrics_prompt,
            provenance=d.provenance,
            evidence_sources=d.evidence_sources,
            safety_flags=d.safety_flags,
            confidence=d.confidence,
            decided_at=d.decided_at.isoformat() if d.decided_at else None,
            created_at=d.created_at.isoformat() if d.created_at else None,
            updated_at=d.updated_at.isoformat() if d.updated_at else None,
        )
        for d in result["decisions"]
    ]

    return BulkDecisionResponse(
        success=True,
        action=result["action"],
        updated_count=result["updated_count"],
        approved_count=result["approved_count"],
        rejected_count=result["rejected_count"],
        skipped_blocked_count=result["skipped_blocked_count"],
        decisions=decision_responses,
    )


@router.get(
    "/ats/{report_id}/change-set",
    response_model=ApprovedChangeSetResponse,
)
async def get_approved_change_set(
    report_id: str,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> ApprovedChangeSetResponse:
    """Retrieve the Approved Change Set for an ATS analysis report (Target 5.4).

    Contains ONLY approved proposals. Does NOT perform any resume modification
    or document mutation (strict Target 5.5 boundary).
    """
    jwt_token = current_user.jwt or token
    report, _ = _get_report_and_coverage(report_id, jwt_token, user_id=current_user.user.id)
    service = get_proposal_review_service()
    change_set = service.get_approved_change_set(
        resume_id=report.resume_id or "",
        report_id=report_id,
        jwt=jwt_token,
    )

    proposals = [
        ApprovedProposalResponse(
            proposal_id=p.proposal_id,
            requirement_id=p.requirement_id,
            target_section=p.target_section,
            target_entry_id=p.target_entry_id,
            original_text=p.original_text,
            proposed_wording=p.proposed_wording,
            rationale=p.rationale,
            diff_summary=p.diff_summary,
            metrics_prompt=p.metrics_prompt,
            provenance=p.provenance,
            evidence_sources=p.evidence_sources,
            safety_flags=p.safety_flags,
            confidence=p.confidence,
            approved_at=p.approved_at.isoformat() if p.approved_at else None,
        )
        for p in change_set.proposals
    ]

    return ApprovedChangeSetResponse(
        id=change_set.id,
        resume_id=change_set.resume_id,
        report_id=change_set.report_id,
        created_at=change_set.created_at.isoformat() if change_set.created_at else None,
        updated_at=change_set.updated_at.isoformat() if change_set.updated_at else None,
        proposals=proposals,
        total_approved=change_set.total_approved,
        total_pending=change_set.total_pending,
        total_rejected=change_set.total_rejected,
        status=change_set.status,
    )


@router.post(
    "/ats/{report_id}/apply",
    response_model=ApplyApprovedImprovementsResponse,
)
async def apply_approved_improvements(
    report_id: str,
    body: ApplyApprovedImprovementsRequest,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> ApplyApprovedImprovementsResponse:
    """Apply approved improvement proposals to the structured resume (Target 5.5).

    Strict boundaries:
    - Applies ONLY proposals with explicit decision == "approved".
    - ZERO original PDF modification (uploaded PDF is immutable).
    - ZERO ATS report mutation (persisted ATS report is unchanged).
    - ZERO LLM calls during application.
    - PROVENANCE LOCKS: Project/academic/internship evidence is never promoted to professional experience.
    """
    jwt_token = current_user.jwt or token
    report, _ = _get_report_and_coverage(report_id, jwt_token, user_id=current_user.user.id)
    app_service = get_proposal_application_service()

    try:
        result = app_service.apply_approved_change_set(
            resume_id=report.resume_id or "",
            report_id=report_id,
            user_id=current_user.user.id,
            proposal_ids=body.proposal_ids,
            version_id=body.version_id,
            version_name=body.version_name,
            create_derived_version=body.create_derived_version,
            jwt=jwt_token,
        )
    except ConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except ProvenanceViolationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except UnapprovedProposalError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    applied_proposals = [
        AppliedProposalSummaryResponse(
            proposal_id=p["proposal_id"],
            requirement_id=p["requirement_id"],
            target_section=p.get("target_section"),
            original_text=p.get("original_text"),
            applied_text=p["applied_text"],
            provenance=p.get("provenance"),
            summary=p.get("summary"),
            status=p.get("status", "applied"),
        )
        for p in result["applied_proposals"]
    ]

    return ApplyApprovedImprovementsResponse(
        success=True,
        resume_id=result["resume_id"],
        report_id=result["report_id"],
        version_id=result["version_id"],
        version_name=result["version_name"],
        is_new_version=result["is_new_version"],
        applied_count=result["applied_count"],
        applied_proposals=applied_proposals,
        message=result["message"],
    )


