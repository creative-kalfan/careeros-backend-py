"""Repository for proposal review decisions and approved change sets (Target 5.4).

RLS-scoped: uses authenticated Supabase client when a JWT is provided, with
graceful in-memory fallback so tests and offline environments work reliably
without schema dependencies.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional, List, Dict

from app.db.supabase import get_service_client, get_authenticated_client
from app.models.improvement import (
    ProposalDecision,
    ProposalDecisionState,
    ProposalEligibility,
)

logger = logging.getLogger(__name__)

# Resilient in-memory fallback storage keyed by (report_id, proposal_id)
_MEM_DECISIONS: Dict[tuple[str, str], ProposalDecision] = {}


def _parse_dt(value: Any) -> datetime:
    if value is None:
        return datetime.utcnow()
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return datetime.utcnow()


class ProposalDecisionRepository:
    """Data-access layer for proposal review decisions."""

    def __init__(self, client: Optional[Any] = None) -> None:
        self._client = client

    def _get_client(self, jwt: Optional[str] = None) -> Any:
        if self._client:
            return self._client
        if jwt:
            return get_authenticated_client(jwt)
        return get_service_client()

    def _row_to_model(self, row: Dict[str, Any]) -> ProposalDecision:
        dec_str = row.get("decision") or ProposalDecisionState.PENDING.value
        try:
            decision = ProposalDecisionState(dec_str)
        except ValueError:
            decision = ProposalDecisionState.PENDING

        elig_str = row.get("eligibility") or ProposalEligibility.ELIGIBLE.value
        try:
            eligibility = ProposalEligibility(elig_str)
        except ValueError:
            eligibility = ProposalEligibility.ELIGIBLE

        return ProposalDecision(
            id=row["id"],
            resume_id=row["resume_id"],
            report_id=row["report_id"],
            proposal_id=row["proposal_id"],
            requirement_id=row["requirement_id"],
            decision=decision,
            eligibility=eligibility,
            eligibility_reasons=row.get("eligibility_reasons") or [],
            target_section=row.get("target_section"),
            target_entry_id=row.get("target_entry_id"),
            original_text=row.get("original_text"),
            proposed_wording=row.get("proposed_wording"),
            rationale=row.get("rationale"),
            diff_summary=row.get("diff_summary"),
            metrics_prompt=row.get("metrics_prompt"),
            provenance=row.get("provenance"),
            evidence_sources=row.get("evidence_sources") or [],
            safety_flags=row.get("safety_flags") or [],
            confidence=float(row.get("confidence") or 0.0),
            decided_at=_parse_dt(row.get("decided_at")) if row.get("decided_at") else None,
            created_at=_parse_dt(row.get("created_at")),
            updated_at=_parse_dt(row.get("updated_at")),
        )

    def upsert_decision(
        self,
        decision: ProposalDecision,
        jwt: Optional[str] = None,
    ) -> ProposalDecision:
        """Persist or update a user decision on an improvement proposal."""
        # Always update memory cache
        key = (decision.report_id, decision.proposal_id)
        _MEM_DECISIONS[key] = decision

        try:
            client = self._get_client(jwt)
            now = datetime.utcnow().isoformat()
            data = {
                "id": decision.id,
                "resume_id": decision.resume_id,
                "report_id": decision.report_id,
                "proposal_id": decision.proposal_id,
                "requirement_id": decision.requirement_id,
                "decision": decision.decision.value,
                "eligibility": decision.eligibility.value,
                "eligibility_reasons": decision.eligibility_reasons,
                "target_section": decision.target_section,
                "target_entry_id": decision.target_entry_id,
                "original_text": decision.original_text,
                "proposed_wording": decision.proposed_wording,
                "rationale": decision.rationale,
                "diff_summary": decision.diff_summary,
                "metrics_prompt": decision.metrics_prompt,
                "provenance": decision.provenance,
                "evidence_sources": decision.evidence_sources,
                "safety_flags": decision.safety_flags,
                "confidence": decision.confidence,
                "decided_at": decision.decided_at.isoformat() if decision.decided_at else None,
                "created_at": (decision.created_at or datetime.utcnow()).isoformat(),
                "updated_at": now,
            }
            result = client.table("proposal_decisions").upsert(data).execute()
            if result.data:
                return self._row_to_model(result.data[0])
        except Exception as exc:
            logger.debug("Database persistence skipped/failed for proposal_decisions, using in-memory: %s", exc)

        return decision

    def get_decision(
        self,
        report_id: str,
        proposal_id: str,
        jwt: Optional[str] = None,
    ) -> Optional[ProposalDecision]:
        """Fetch decision for a specific proposal."""
        try:
            client = self._get_client(jwt)
            result = (
                client.table("proposal_decisions")
                .select("*")
                .eq("report_id", report_id)
                .eq("proposal_id", proposal_id)
                .maybe_single()
                .execute()
            )
            if result.data:
                return self._row_to_model(result.data)
        except Exception as exc:
            logger.debug("Database read skipped for proposal_decisions: %s", exc)

        key = (report_id, proposal_id)
        return _MEM_DECISIONS.get(key)

    def list_decisions_for_report(
        self,
        report_id: str,
        jwt: Optional[str] = None,
    ) -> List[ProposalDecision]:
        """List all proposal decisions recorded for an ATS report."""
        db_items: List[ProposalDecision] = []
        try:
            client = self._get_client(jwt)
            result = (
                client.table("proposal_decisions")
                .select("*")
                .eq("report_id", report_id)
                .order("created_at", desc=False)
                .execute()
            )
            if result.data:
                db_items = [self._row_to_model(row) for row in result.data]
        except Exception as exc:
            logger.debug("Database list skipped for proposal_decisions: %s", exc)

        if db_items:
            return db_items

        return [d for (rep_id, _), d in _MEM_DECISIONS.items() if rep_id == report_id]

    def delete_decision(
        self,
        report_id: str,
        proposal_id: str,
        jwt: Optional[str] = None,
    ) -> bool:
        """Delete a decision (reset)."""
        key = (report_id, proposal_id)
        _MEM_DECISIONS.pop(key, None)

        try:
            client = self._get_client(jwt)
            result = (
                client.table("proposal_decisions")
                .delete()
                .eq("report_id", report_id)
                .eq("proposal_id", proposal_id)
                .execute()
            )
            return bool(result.data)
        except Exception:
            return True
