"""Proposal Review and Approval Service (Target 5.4).

Implements the deterministic review, approve/reject state management, eligibility
validation, anti-fabrication provenance checks, and Approved Change Set generation.

Strict boundaries:
- ZERO resume document modification (Target 5.5 boundary).
- ZERO PDF byte/renderer modification.
- ZERO ATS score recalculation or LLM invocation on review actions.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Any

from app.models.improvement import (
    ImprovementProposal,
    ProposalDecision,
    ProposalDecisionState,
    ProposalEligibility,
    ApprovedProposal,
    ApprovedChangeSet,
)
from app.repositories.proposal_decision_repository import ProposalDecisionRepository

logger = logging.getLogger(__name__)


def determine_proposal_eligibility(
    proposal: ImprovementProposal,
) -> Tuple[ProposalEligibility, List[str]]:
    """Deterministically determine if a proposal is ELIGIBLE, NEEDS_REVIEW, or BLOCKED.

    Blocked proposals cannot be approved under any circumstances.
    """
    reasons: List[str] = []

    # 1. Missing proposed wording check
    wording = proposal.proposed_wording or ""
    if not wording.strip():
        reasons.append("Proposal has no proposed wording.")
        return ProposalEligibility.BLOCKED, reasons

    # 2. Provenance Lock Violations
    prov = (proposal.provenance or "").lower().strip()
    sec = (proposal.target_section or "").lower().strip()

    # Project/academic evidence must never target professional experience
    if prov in {"project", "academic", "coursework", "certification", "achievement"}:
        if sec.startswith("experience") and not sec.startswith("internship") and not sec.startswith("project"):
            reasons.append(f"Provenance violation: '{prov}' evidence cannot be placed into professional '{sec}'.")
            return ProposalEligibility.BLOCKED, reasons

    # 3. Critical safety flags
    blocking_flags = {
        "provenance_violation",
        "fabrication_detected",
        "invalid_provenance",
        "scope_inflation_blocked",
    }
    for flag in proposal.safety_flags:
        if flag in blocking_flags:
            reasons.append(f"Blocked by safety guardrail: {flag}.")
            return ProposalEligibility.BLOCKED, reasons

    # 4. Needs Review Warnings (e.g. unverified metrics converted to prompt)
    if "unverified_metric_converted_to_prompt" in proposal.safety_flags or proposal.metrics_prompt:
        reasons.append("Contains unverified metric converted to prompt — review wording before approval.")
        return ProposalEligibility.NEEDS_REVIEW, reasons

    return ProposalEligibility.ELIGIBLE, []


class ProposalReviewService:
    """Service governing proposal decisions and approved change sets."""

    def __init__(self, repo: Optional[ProposalDecisionRepository] = None) -> None:
        self._repo = repo or ProposalDecisionRepository()

    def get_decisions_for_report(
        self,
        report_id: str,
        jwt: Optional[str] = None,
    ) -> List[ProposalDecision]:
        """Fetch all recorded decisions for an ATS report."""
        return self._repo.list_decisions_for_report(report_id, jwt=jwt)

    def record_decision(
        self,
        resume_id: str,
        report_id: str,
        proposal: ImprovementProposal,
        decision_state: ProposalDecisionState,
        jwt: Optional[str] = None,
    ) -> ProposalDecision:
        """Record or update a user's decision on a proposal.

        Validates eligibility: BLOCKED proposals cannot be approved.
        """
        eligibility, eligibility_reasons = determine_proposal_eligibility(
            proposal
        )

        if decision_state == ProposalDecisionState.APPROVED:
            if eligibility == ProposalEligibility.BLOCKED:
                error_msg = "; ".join(eligibility_reasons) or "Proposal is blocked by safety guardrails."
                raise ValueError(f"Cannot approve blocked proposal: {error_msg}")

        existing = self._repo.get_decision(report_id, proposal.id, jwt=jwt)
        now = datetime.utcnow()

        decision = ProposalDecision(
            id=existing.id if existing else None or f"dec-{proposal.id}",
            resume_id=resume_id,
            report_id=report_id,
            proposal_id=proposal.id,
            requirement_id=proposal.requirement_id,
            decision=decision_state,
            eligibility=eligibility,
            eligibility_reasons=eligibility_reasons,
            target_section=proposal.target_section,
            target_entry_id=proposal.target_entry_id,
            original_text=proposal.original_text,
            proposed_wording=proposal.proposed_wording,
            rationale=proposal.rationale,
            diff_summary=proposal.diff_summary,
            metrics_prompt=proposal.metrics_prompt,
            provenance=proposal.provenance,
            evidence_sources=proposal.evidence_sources,
            safety_flags=proposal.safety_flags,
            confidence=proposal.confidence,
            decided_at=now if decision_state != ProposalDecisionState.PENDING else None,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )

        return self._repo.upsert_decision(decision, jwt=jwt)

    def bulk_decision(
        self,
        resume_id: str,
        report_id: str,
        proposals: List[ImprovementProposal],
        action: str,
        jwt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute bulk decision (approve_all_safe or reject_all).

        Bulk approve operates ONLY on eligible proposals and skips blocked ones.
        """
        updated_decisions: List[ProposalDecision] = []
        approved_count = 0
        rejected_count = 0
        skipped_blocked_count = 0

        if action == "approve_all_safe":
            for prop in proposals:
                eligibility, _ = determine_proposal_eligibility(prop)
                if eligibility == ProposalEligibility.BLOCKED:
                    skipped_blocked_count += 1
                    continue
                # Eligible or Needs Review -> Approve
                dec = self.record_decision(
                    resume_id=resume_id,
                    report_id=report_id,
                    proposal=prop,
                    decision_state=ProposalDecisionState.APPROVED,
                    jwt=jwt,
                )
                updated_decisions.append(dec)
                approved_count += 1

        elif action == "reject_all":
            for prop in proposals:
                dec = self.record_decision(
                    resume_id=resume_id,
                    report_id=report_id,
                    proposal=prop,
                    decision_state=ProposalDecisionState.REJECTED,
                    jwt=jwt,
                )
                updated_decisions.append(dec)
                rejected_count += 1

        else:
            raise ValueError(f"Unknown bulk action: {action}")

        return {
            "success": True,
            "action": action,
            "updated_count": len(updated_decisions),
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "skipped_blocked_count": skipped_blocked_count,
            "decisions": updated_decisions,
        }

    def get_approved_change_set(
        self,
        resume_id: str,
        report_id: str,
        jwt: Optional[str] = None,
    ) -> ApprovedChangeSet:
        """Construct the ApprovedChangeSet from all approved decisions for this report.

        Contains ONLY approved proposals. Excludes pending and rejected proposals.
        Does NOT perform any resume rewriting (Target 5.5 boundary).
        """
        all_decisions = self._repo.list_decisions_for_report(report_id, jwt=jwt)

        approved_proposals: List[ApprovedProposal] = []
        total_approved = 0
        total_pending = 0
        total_rejected = 0

        for d in all_decisions:
            if d.decision == ProposalDecisionState.APPROVED and d.proposed_wording:
                total_approved += 1
                approved_proposals.append(
                    ApprovedProposal(
                        proposal_id=d.proposal_id,
                        requirement_id=d.requirement_id,
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
                        approved_at=d.decided_at or d.updated_at or datetime.utcnow(),
                    )
                )
            elif d.decision == ProposalDecisionState.REJECTED:
                total_rejected += 1
            else:
                total_pending += 1

        return ApprovedChangeSet(
            id=f"changeset-{report_id}",
            resume_id=resume_id,
            report_id=report_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            proposals=approved_proposals,
            total_approved=total_approved,
            total_pending=total_pending,
            total_rejected=total_rejected,
            status="active" if approved_proposals else "draft",
        )


_review_service_instance: Optional[ProposalReviewService] = None


def get_proposal_review_service() -> ProposalReviewService:
    global _review_service_instance
    if _review_service_instance is None:
        _review_service_instance = ProposalReviewService()
    return _review_service_instance
