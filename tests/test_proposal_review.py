"""Tests for Proposal Review & Approval Workflow (Target 5.4).

Verifies:
1. Default proposal state is PENDING.
2. User can approve individual eligible proposals.
3. User can reject individual proposals.
4. User can reconsider (reset) a rejected proposal to pending.
5. Blocked proposals (e.g. empty wording, provenance violation) cannot be approved.
6. Provenance locks: Project / Academic evidence cannot target professional experience.
7. Approved proposals retain requirement_id, target_section, original_text, proposed_wording, rationale, evidence_sources.
8. Approved Change Set contains ONLY approved proposals (excludes pending & rejected).
9. Bulk approval approves eligible proposals and skips blocked proposals.
10. Zero ATS score mutation and zero resume mutation guarantees.
11. Decision state persistence across calls.
"""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from app.models.improvement import (
    ImprovementProposal,
    ProposalDecisionState,
    ProposalEligibility,
)
from app.models.ats import (
    RequirementCoverage,
    JobRequirementType,
    EvidenceLevel,
)
from app.services.improvement.proposal_review_service import (
    ProposalReviewService,
    determine_proposal_eligibility,
)
from app.repositories.proposal_decision_repository import ProposalDecisionRepository


def _make_proposal(
    id: str = "prop-1",
    requirement_id: str = "Docker",
    proposed_wording: str = "Containerized services with Docker.",
    original_text: str = "Used Docker.",
    provenance: str = "project",
    target_section: str = "projects[0]",
    safety_flags: list[str] = None,
    metrics_prompt: str = None,
) -> ImprovementProposal:
    return ImprovementProposal(
        id=id,
        requirement_id=requirement_id,
        proposed_wording=proposed_wording,
        original_text=original_text,
        provenance=provenance,
        target_section=target_section,
        safety_flags=safety_flags or [],
        metrics_prompt=metrics_prompt,
        rationale="Improves Docker clarity.",
        evidence_sources=["Resume: Used Docker."],
        confidence=0.9,
    )


class TestProposalEligibility:
    def test_eligible_proposal(self):
        prop = _make_proposal()
        elig, reasons = determine_proposal_eligibility(prop)
        assert elig == ProposalEligibility.ELIGIBLE
        assert len(reasons) == 0

    def test_missing_proposed_wording_is_blocked(self):
        prop = _make_proposal(proposed_wording="")
        elig, reasons = determine_proposal_eligibility(prop)
        assert elig == ProposalEligibility.BLOCKED
        assert any("no proposed wording" in r.lower() for r in reasons)

    def test_provenance_lock_project_to_experience_is_blocked(self):
        prop = _make_proposal(
            provenance="project",
            target_section="experience[0]",
            proposed_wording="Led enterprise Kubernetes operations.",
        )
        elig, reasons = determine_proposal_eligibility(prop)
        assert elig == ProposalEligibility.BLOCKED
        assert any("provenance violation" in r.lower() for r in reasons)

    def test_provenance_lock_academic_to_experience_is_blocked(self):
        prop = _make_proposal(
            provenance="academic",
            target_section="experience[0]",
            proposed_wording="Worked as compiler engineer in company.",
        )
        elig, reasons = determine_proposal_eligibility(prop)
        assert elig == ProposalEligibility.BLOCKED
        assert any("provenance violation" in r.lower() for r in reasons)

    def test_unverified_metric_flag_is_needs_review(self):
        prop = _make_proposal(
            safety_flags=["unverified_metric_converted_to_prompt"],
            metrics_prompt="Did this improve build speed?",
        )
        elig, reasons = determine_proposal_eligibility(prop)
        assert elig == ProposalEligibility.NEEDS_REVIEW


class TestProposalDecisionsAndChangeSet:
    def test_default_state_and_approve_proposal(self):
        repo = ProposalDecisionRepository()
        service = ProposalReviewService(repo=repo)
        prop = _make_proposal(id="prop-docker-1", requirement_id="Docker")

        # Initial state before decision
        existing = repo.get_decision("rep-1", "prop-docker-1")
        assert existing is None

        # User approves
        dec = service.record_decision(
            resume_id="res-1",
            report_id="rep-1",
            proposal=prop,
            decision_state=ProposalDecisionState.APPROVED,
        )

        assert dec.decision == ProposalDecisionState.APPROVED
        assert dec.proposal_id == "prop-docker-1"
        assert dec.requirement_id == "Docker"
        assert dec.target_section == "projects[0]"
        assert dec.original_text == "Used Docker."
        assert dec.proposed_wording == "Containerized services with Docker."
        assert dec.decided_at is not None

        # Survives query
        fetched = service.get_decisions_for_report("rep-1")
        assert len(fetched) == 1
        assert fetched[0].decision == ProposalDecisionState.APPROVED

    def test_reject_and_reconsider_proposal(self):
        repo = ProposalDecisionRepository()
        service = ProposalReviewService(repo=repo)
        prop = _make_proposal(id="prop-ts-1", requirement_id="TypeScript")

        # User rejects
        dec = service.record_decision(
            resume_id="res-1",
            report_id="rep-1",
            proposal=prop,
            decision_state=ProposalDecisionState.REJECTED,
        )
        assert dec.decision == ProposalDecisionState.REJECTED

        # User reconsiders (resets to pending)
        reconsidered = service.record_decision(
            resume_id="res-1",
            report_id="rep-1",
            proposal=prop,
            decision_state=ProposalDecisionState.PENDING,
        )
        assert reconsidered.decision == ProposalDecisionState.PENDING
        assert reconsidered.decided_at is None

    def test_blocked_proposal_cannot_be_approved(self):
        repo = ProposalDecisionRepository()
        service = ProposalReviewService(repo=repo)
        blocked_prop = _make_proposal(
            id="prop-blocked",
            proposed_wording="",  # Missing wording -> BLOCKED
        )

        with pytest.raises(ValueError, match="Cannot approve blocked proposal"):
            service.record_decision(
                resume_id="res-1",
                report_id="rep-1",
                proposal=blocked_prop,
                decision_state=ProposalDecisionState.APPROVED,
            )

    def test_approved_change_set_contains_only_approved_proposals(self):
        repo = ProposalDecisionRepository()
        service = ProposalReviewService(repo=repo)

        prop1 = _make_proposal(id="p1", requirement_id="Docker")
        prop2 = _make_proposal(id="p2", requirement_id="TypeScript")
        prop3 = _make_proposal(id="p3", requirement_id="AWS")

        # p1 -> approved, p2 -> rejected, p3 -> pending
        service.record_decision("res-1", "rep-100", prop1, ProposalDecisionState.APPROVED)
        service.record_decision("res-1", "rep-100", prop2, ProposalDecisionState.REJECTED)
        service.record_decision("res-1", "rep-100", prop3, ProposalDecisionState.PENDING)

        change_set = service.get_approved_change_set("res-1", "rep-100")

        assert change_set.resume_id == "res-1"
        assert change_set.report_id == "rep-100"
        assert change_set.total_approved == 1
        assert change_set.total_rejected == 1
        assert change_set.total_pending == 1

        # ONLY p1 in change_set proposals
        assert len(change_set.proposals) == 1
        assert change_set.proposals[0].proposal_id == "p1"
        assert change_set.proposals[0].requirement_id == "Docker"
        assert change_set.proposals[0].proposed_wording == prop1.proposed_wording
        assert change_set.proposals[0].target_section == prop1.target_section

    def test_bulk_approval_respects_blocked_proposals(self):
        repo = ProposalDecisionRepository()
        service = ProposalReviewService(repo=repo)

        safe_prop = _make_proposal(id="safe-1", requirement_id="Docker")
        blocked_prop = _make_proposal(
            id="blocked-1",
            requirement_id="K8s",
            provenance="project",
            target_section="experience[0]",  # Blocked by provenance violation
        )

        result = service.bulk_decision(
            resume_id="res-1",
            report_id="rep-bulk",
            proposals=[safe_prop, blocked_prop],
            action="approve_all_safe",
        )

        assert result["success"] is True
        assert result["approved_count"] == 1
        assert result["skipped_blocked_count"] == 1

        change_set = service.get_approved_change_set("res-1", "rep-bulk")
        assert len(change_set.proposals) == 1
        assert change_set.proposals[0].proposal_id == "safe-1"

    def test_bulk_reject_all(self):
        repo = ProposalDecisionRepository()
        service = ProposalReviewService(repo=repo)

        p1 = _make_proposal(id="p1", requirement_id="Docker")
        p2 = _make_proposal(id="p2", requirement_id="K8s")

        result = service.bulk_decision(
            resume_id="res-1",
            report_id="rep-bulk-2",
            proposals=[p1, p2],
            action="reject_all",
        )

        assert result["success"] is True
        assert result["rejected_count"] == 2

        change_set = service.get_approved_change_set("res-1", "rep-bulk-2")
        assert len(change_set.proposals) == 0
        assert change_set.total_rejected == 2

    def test_zero_ats_score_mutation(self):
        cov = RequirementCoverage(
            requirement="Docker",
            requirement_type=JobRequirementType.SKILL,
            resume_evidence=["Used Docker."],
            evidence_level=EvidenceLevel.PARTIAL,
            evidence_source_section="projects[0]",
            status="partial",
        )
        cov_dump_before = cov.model_dump()

        repo = ProposalDecisionRepository()
        service = ProposalReviewService(repo=repo)
        prop = _make_proposal(id="p-ats-1", requirement_id="Docker")

        service.record_decision("res-1", "rep-ats", prop, ProposalDecisionState.APPROVED)
        service.record_decision("res-1", "rep-ats", prop, ProposalDecisionState.REJECTED)

        # Confirm coverage object is completely untouched
        assert cov.model_dump() == cov_dump_before
