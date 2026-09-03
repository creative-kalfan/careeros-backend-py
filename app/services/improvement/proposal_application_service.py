"""Proposal Application Service (Target 5.5).

Implements the safe, deterministic application layer for applying ONLY user-approved
improvement proposals (ApprovedChangeSet) onto the structured resume profile.

Strict boundaries:
- ZERO resume document modification without explicit user approval.
- ZERO PDF byte / renderer / highlight modification (original uploaded PDF is immutable).
- ZERO ATS score recalculation or LLM invocations during application.
- ZERO fabrication of employers, job titles, employment dates, tools, or metrics.
- PROVENANCE LOCKS: Project, academic, internship, and certification evidence is NEVER
  converted or promoted to professional employment experience.
"""

from __future__ import annotations

import copy
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.models.improvement import (
    ApprovedChangeSet,
    ApprovedProposal,
    ProposalDecisionState,
    ProposalEligibility,
)
from app.models.resume import (
    BulletItem,
    CertificationItem,
    ExperienceItem,
    ProjectItem,
    ResumeContent,
    ResumeProfile,
    SkillCategory,
)
from app.repositories.resume_repository import ResumeRepository
from app.services.improvement.proposal_review_service import (
    ProposalReviewService,
    determine_proposal_eligibility,
)

logger = logging.getLogger(__name__)


class ConflictError(ValueError):
    """Raised when a proposal conflicts with the current resume content."""
    pass


class ProvenanceViolationError(ValueError):
    """Raised when an improvement violates provenance locks (e.g. project -> experience)."""
    pass


class UnapprovedProposalError(ValueError):
    """Raised when attempting to apply an unapproved or blocked proposal."""
    pass


def _normalize_text(text: Optional[str]) -> str:
    """Normalize text for whitespace-insensitive comparison."""
    if not text:
        return ""
    # Strip quotes, collapse whitespace, lowercase
    cleaned = re.sub(r'[\s"“”‘’`\']+', " ", text).strip().lower()
    return cleaned


def _texts_match(text1: Optional[str], text2: Optional[str]) -> bool:
    """Check if two texts match with whitespace/quote normalization."""
    n1 = _normalize_text(text1)
    n2 = _normalize_text(text2)
    if not n1 or not n2:
        return False
    return n1 == n2 or n1 in n2 or n2 in n1


def validate_provenance_lock(proposal: ApprovedProposal) -> None:
    """Enforce strict fresher-safety and provenance boundaries.

    Non-professional evidence (project, academic, coursework, certification) must
    NEVER be applied to professional work experience.
    """
    prov = (proposal.provenance or "").lower().strip()
    sec = (proposal.target_section or "").lower().strip()

    if prov in {"project", "academic", "coursework", "certification", "achievement", "freelance", "open_source"}:
        if sec.startswith("experience") and not sec.startswith("internship") and not sec.startswith("project"):
            raise ProvenanceViolationError(
                f"Fresher safety violation: '{prov}' evidence cannot be placed into professional '{sec}'."
            )


def validate_unsupported_metrics(proposal: ApprovedProposal) -> None:
    """Ensure proposals with unverified metrics prompts have not fabricated metrics."""
    if proposal.metrics_prompt:
        if any(flag in proposal.safety_flags for flag in ["unsubstantiated_metric", "fabrication_detected"]):
            raise ValueError(f"Proposal contains unverified metrics: {proposal.metrics_prompt}")


def locate_and_apply_mutation(
    profile: ResumeProfile,
    proposal: ApprovedProposal,
) -> Tuple[bool, str]:
    """Locate target in ResumeProfile and apply proposed wording deterministically.

    Returns (applied: bool, applied_summary: str).
    Raises ConflictError if target cannot be found or text has drifted.
    """
    target_section = (proposal.target_section or "").strip()
    target_entry_id = proposal.target_entry_id
    original_text = proposal.original_text
    proposed_wording = proposal.proposed_wording.strip()

    # 1. Summary / Target Role scalar sections
    if target_section.lower() in {"summary", "profile.summary"}:
        if original_text and profile.summary:
            if not _texts_match(profile.summary, original_text):
                raise ConflictError(
                    f"Resume summary changed since proposal was generated for requirement '{proposal.requirement_id}'."
                )
        profile.summary = proposed_wording
        return True, "Updated professional summary"

    if target_section.lower() in {"target_role", "profile.target_role"}:
        profile.target_role = proposed_wording
        return True, "Updated target role"

    # 2. Skills section
    if target_section.lower().startswith("skills"):
        # Proposed wording could be a skill addition or list of skills
        # Extract skills from proposed wording (split by commas/bullets)
        new_skills = [
            s.strip().strip("-•*,")
            for s in re.split(r'[,;•\n\r]+', proposed_wording)
            if s.strip().strip("-•*,")
        ]
        if not new_skills:
            new_skills = [proposed_wording]

        # Determine skill subcategory (default to technical)
        subcat = "technical"
        if "." in target_section:
            subcat = target_section.split(".")[-1].lower()

        existing_list: list[str] = getattr(profile.skills, subcat, profile.skills.technical)
        added: list[str] = []
        for s in new_skills:
            if s and not any(_normalize_text(s) == _normalize_text(e) for e in existing_list):
                existing_list.append(s)
                added.append(s)

        return True, f"Added skills to {subcat}: {', '.join(added) if added else 'updated skills'}"

    # 3. Experience section (Work Experience)
    if target_section.lower().startswith("experience"):
        # Match by target_section index e.g. experience[0] or target_entry_id
        match = re.search(r"experience\[(\d+)\]", target_section.lower())
        idx = int(match.group(1)) if match else None

        if idx is not None and idx >= len(profile.experience):
            raise ConflictError(
                f"Target section '{target_section}' not found in resume (only {len(profile.experience)} items exist)."
            )

        target_items = [profile.experience[idx]] if idx is not None else profile.experience
        if target_entry_id:
            found = [e for e in profile.experience if getattr(e, "id", None) == target_entry_id]
            if found:
                target_items = found

        for exp in target_items:
            # Check responsibilities bullets
            for bullet_idx, b in enumerate(exp.responsibilities):
                if original_text and _texts_match(b.text, original_text):
                    exp.responsibilities[bullet_idx] = BulletItem(id=b.id, text=proposed_wording)
                    return True, f"Updated bullet in experience ({exp.company or exp.role or 'item'})"

            # If no original_text match, but specific entry was targeted, append bullet
            if not original_text and (idx is not None or target_entry_id):
                exp.responsibilities.append(BulletItem(text=proposed_wording))
                return True, f"Added bullet to experience ({exp.company or exp.role or 'item'})"

        # If original_text was specified but not found in targeted experience, check for drift
        if original_text:
            raise ConflictError(
                f"Original text not found in experience for requirement '{proposal.requirement_id}'. Resume content may have changed."
            )

    # 4. Internships section
    if target_section.lower().startswith("internship"):
        match = re.search(r"internships?\[(\d+)\]", target_section.lower())
        idx = int(match.group(1)) if match else None

        if idx is not None and idx >= len(profile.internships):
            raise ConflictError(
                f"Target section '{target_section}' not found in resume (only {len(profile.internships)} internships exist)."
            )

        target_items = [profile.internships[idx]] if idx is not None else profile.internships
        if target_entry_id:
            found = [e for e in profile.internships if getattr(e, "id", None) == target_entry_id]
            if found:
                target_items = found

        for exp in target_items:
            for bullet_idx, b in enumerate(exp.responsibilities):
                if original_text and _texts_match(b.text, original_text):
                    exp.responsibilities[bullet_idx] = BulletItem(id=b.id, text=proposed_wording)
                    return True, f"Updated bullet in internship ({exp.company or exp.role or 'item'})"

            if not original_text and (idx is not None or target_entry_id):
                exp.responsibilities.append(BulletItem(text=proposed_wording))
                return True, f"Added bullet to internship ({exp.company or exp.role or 'item'})"

        if original_text:
            raise ConflictError(
                f"Original text not found in internship for requirement '{proposal.requirement_id}'."
            )

    # 5. Projects section
    if target_section.lower().startswith("project"):
        match = re.search(r"projects?\[(\d+)\]", target_section.lower())
        idx = int(match.group(1)) if match else None

        if idx is not None and idx >= len(profile.projects):
            raise ConflictError(
                f"Target section '{target_section}' not found in resume (only {len(profile.projects)} projects exist)."
            )

        target_items = [profile.projects[idx]] if idx is not None else profile.projects
        if target_entry_id:
            found = [p for p in profile.projects if getattr(p, "id", None) == target_entry_id]
            if found:
                target_items = found

        for proj in target_items:
            # Check description
            if proj.description and original_text and _texts_match(proj.description, original_text):
                proj.description = proposed_wording
                return True, f"Updated description in project '{proj.name or 'item'}'"

            # Check contribution
            if proj.contribution and original_text and _texts_match(proj.contribution, original_text):
                proj.contribution = proposed_wording
                return True, f"Updated contribution in project '{proj.name or 'item'}'"

            # If targeting project and no description exists, or explicit match
            if not original_text and (idx is not None or target_entry_id):
                if not proj.description:
                    proj.description = proposed_wording
                else:
                    proj.contribution = proposed_wording
                return True, f"Updated project '{proj.name or 'item'}'"

        if original_text:
            # Check if original_text exists in any project
            for proj in profile.projects:
                if proj.description and _texts_match(proj.description, original_text):
                    proj.description = proposed_wording
                    return True, f"Updated description in project '{proj.name or 'item'}'"

            raise ConflictError(
                f"Original text not found in projects for requirement '{proposal.requirement_id}'."
            )

    # 6. Certifications section
    if target_section.lower().startswith("certification"):
        if original_text:
            for cert in profile.certifications:
                if _texts_match(cert.name, original_text):
                    cert.name = proposed_wording
                    return True, f"Updated certification '{cert.name}'"
        else:
            # Append new certification if not present
            if not any(_normalize_text(c.name) == _normalize_text(proposed_wording) for c in profile.certifications):
                profile.certifications.append(CertificationItem(name=proposed_wording))
                return True, f"Added certification '{proposed_wording}'"

    # 7. Education section
    if target_section.lower().startswith("education"):
        if original_text:
            for edu in profile.education:
                # Check coursework
                for c_idx, c in enumerate(edu.coursework):
                    if _texts_match(c, original_text):
                        edu.coursework[c_idx] = proposed_wording
                        return True, f"Updated coursework in education '{edu.institution or 'item'}'"
                # Check achievements
                for a_idx, a in enumerate(edu.achievements):
                    if _texts_match(a, original_text):
                        edu.achievements[a_idx] = proposed_wording
                        return True, f"Updated achievement in education '{edu.institution or 'item'}'"

    # 8. Fallback: Search all sections for original_text if target_section was generic
    if original_text:
        # Check projects
        for proj in profile.projects:
            if proj.description and _texts_match(proj.description, original_text):
                proj.description = proposed_wording
                return True, f"Updated project '{proj.name or 'item'}'"

        # Check internships
        for exp in profile.internships:
            for bullet_idx, b in enumerate(exp.responsibilities):
                if _texts_match(b.text, original_text):
                    exp.responsibilities[bullet_idx] = BulletItem(id=b.id, text=proposed_wording)
                    return True, f"Updated internship bullet"

        # Check experience (only if provenance permits)
        prov = (proposal.provenance or "").lower().strip()
        if prov in {"professional", "experience", "work"}:
            for exp in profile.experience:
                for bullet_idx, b in enumerate(exp.responsibilities):
                    if _texts_match(b.text, original_text):
                        exp.responsibilities[bullet_idx] = BulletItem(id=b.id, text=proposed_wording)
                        return True, f"Updated experience bullet"

    # If we reached here, target could not be resolved cleanly
    raise ConflictError(
        f"Unable to locate target section '{target_section}' or matching text for requirement '{proposal.requirement_id}'."
    )


class ProposalApplicationService:
    """Service governing the atomic application of approved proposals."""

    def __init__(
        self,
        review_service: Optional[ProposalReviewService] = None,
        resume_repo: Optional[ResumeRepository] = None,
    ) -> None:
        self._review_service = review_service or ProposalReviewService()
        self._resume_repo = resume_repo

    def apply_approved_change_set(
        self,
        resume_id: str,
        report_id: str,
        user_id: str,
        jwt: Optional[str] = None,
        version_id: Optional[str] = None,
        proposal_ids: Optional[List[str]] = None,
        create_derived_version: bool = True,
        version_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply approved proposals atomically to a resume version.

        1. Fetches ApprovedChangeSet (only proposals with decision == "approved").
        2. Filters by proposal_ids if provided.
        3. Loads base resume content.
        4. Validates provenance, fresher locks, and stale drift atomically.
        5. Mutates working copy of ResumeContent.
        6. Persists new derived version (or updates specified version).
        7. Returns structured application report with audit trail.
        """
        # Step 1: Retrieve approved change set
        change_set: ApprovedChangeSet = self._review_service.get_approved_change_set(
            resume_id=resume_id,
            report_id=report_id,
            jwt=jwt,
            user_id=user_id,
        )

        approved_proposals = change_set.proposals
        if proposal_ids:
            target_ids = set(proposal_ids)
            approved_proposals = [p for p in approved_proposals if p.proposal_id in target_ids]

        if not approved_proposals:
            raise UnapprovedProposalError("No approved proposals available to apply for this report.")

        # Step 2: Load Resume and Base Version
        repo = self._resume_repo or ResumeRepository(jwt=jwt)
        resume = repo.get_resume(user_id, resume_id)
        if not resume:
            raise ValueError(f"Resume '{resume_id}' not found.")

        base_version_id = version_id
        base_version = None
        if base_version_id:
            base_version = repo.get_version(base_version_id)
            if not base_version:
                raise ValueError(f"Version '{base_version_id}' not found.")
            if base_version.get("resume_id") != resume_id:
                raise ValueError(f"Version '{base_version_id}' does not belong to resume '{resume_id}'.")

        # Base content from version or master resume
        raw_content = base_version.get("content") if base_version else resume.get("content")
        content = ResumeContent.from_dict(raw_content or {})
        working_profile = copy.deepcopy(content.profile)

        # Step 3: Atomic Validation & Mutation
        applied_summaries: List[Dict[str, Any]] = []

        for proposal in approved_proposals:
            # 3.1 Provenance lock check
            validate_provenance_lock(proposal)

            # 3.2 Metrics & unsupported claims check
            validate_unsupported_metrics(proposal)

            # 3.3 Locate and mutate
            applied, summary_text = locate_and_apply_mutation(working_profile, proposal)
            if applied:
                applied_summaries.append({
                    "proposal_id": proposal.proposal_id,
                    "requirement_id": proposal.requirement_id,
                    "target_section": proposal.target_section,
                    "original_text": proposal.original_text,
                    "applied_text": proposal.proposed_wording,
                    "provenance": proposal.provenance,
                    "summary": summary_text,
                    "status": "applied",
                })

        # Step 4: Commit changes to version
        content.profile = working_profile
        now_iso = datetime.utcnow().isoformat()

        # Decide whether to create new version or update existing non-master
        is_master_base = base_version.get("is_master", False) if base_version else True
        should_create_new = create_derived_version or is_master_base or not base_version_id

        final_version_id = base_version_id
        final_version_name = base_version.get("version_name") if base_version else "Master"

        if should_create_new:
            v_name = version_name or f"Optimized - {len(applied_summaries)} Approved ATS Improvements"
            new_version_row = repo.create_version(
                resume_id=resume_id,
                content=content.to_dict(),
                version_name=v_name,
                source="approved_improvement",
                is_master=False,
                parent_version_id=base_version_id,
                meta={
                    "applied_proposals": [s["proposal_id"] for s in applied_summaries],
                    "report_id": report_id,
                    "applied_count": len(applied_summaries),
                    "applied_at": now_iso,
                },
            )
            final_version_id = new_version_row["id"]
            final_version_name = new_version_row.get("version_name", v_name)
        else:
            # Update existing non-master version
            meta = base_version.get("meta") or {}
            existing_applied = meta.get("applied_proposals", [])
            new_applied = list(set(existing_applied + [s["proposal_id"] for s in applied_summaries]))
            meta["applied_proposals"] = new_applied
            meta["last_applied_at"] = now_iso
            meta["report_id"] = report_id

            updated_row = repo.update_version(
                version_id=final_version_id,  # type: ignore
                data={
                    "content": content.to_dict(),
                    "meta": meta,
                },
            )
            if not updated_row:
                raise ValueError(f"Failed to update version '{final_version_id}'.")

        return {
            "success": True,
            "resume_id": resume_id,
            "report_id": report_id,
            "version_id": final_version_id,
            "version_name": final_version_name,
            "is_new_version": should_create_new,
            "applied_count": len(applied_summaries),
            "applied_proposals": applied_summaries,
            "message": f"Successfully applied {len(applied_summaries)} approved improvements to resume version.",
        }


# Singleton factory
_proposal_application_service: Optional[ProposalApplicationService] = None


def get_proposal_application_service() -> ProposalApplicationService:
    global _proposal_application_service
    if _proposal_application_service is None:
        _proposal_application_service = ProposalApplicationService()
    return _proposal_application_service
