"""Optimization Router endpoints for CareerOS Resume Module (Step 5)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Header, status

from app.dependencies import get_current_user
from app.auth.service import AuthContext
from app.models.ats import ATSAnalysisReport
from app.models.resume import ResumeContent
from app.schemas.optimization import (
    OptimizeResumeRequest,
    OptimizeResumeResponse,
    AcceptSuggestionRequest,
    RejectSuggestionRequest,
    SuggestionActionResponse,
    OptimizationSessionResponse,
    ListOptimizationSessionsResponse,
    ReanalyzeRequest,
    ReanalyzeResponse,
    ListOptimizationHistoryResponse,
    GenerateSkillsOptimizationRequest,
    GenerateSkillsOptimizationResponse,
    GenerateSummaryOptimizationRequest,
    GenerateSummaryOptimizationResponse,
    GenerateExperienceBulletOptimizationRequest,
    GenerateExperienceBulletOptimizationResponse,
)
from app.services.ats.ats_analyzer import ATSAnalyzer
from app.services.optimization.optimization_service import OptimizationService
from app.repositories.optimization_repository import optimization_repo
from app.repositories.resume_repository import ResumeRepository
from app.repositories.ats_repository import ATSReportRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/optimization", tags=["optimization"])

resume_repo = ResumeRepository()
ats_repo = ATSReportRepository()
optimization_service = OptimizationService()
analyzer = ATSAnalyzer()


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


def _apply_suggestion_to_content(
    content: ResumeContent, suggestion: Dict[str, Any], edited_text: Optional[str] = None
) -> ResumeContent:
    """Apply an accepted suggestion to a copy of the resume content."""
    content = ResumeContent.from_dict(content.to_dict())
    suggestion_type = suggestion.get("type", "")
    suggested_text = (
        edited_text
        or suggestion.get("suggested_text")
        or suggestion.get("suggestedText")
        or suggestion.get("skill")
        or ""
    ).strip()
    current_text = (
        suggestion.get("current_text")
        or suggestion.get("currentText")
        or ""
    ).strip()

    if suggestion_type == "professional_summary" or suggestion.get("section") == "summary":
        if suggested_text:
            content.profile.summary = suggested_text

    elif suggestion_type in ("experience_bullet", "project_bullet") or suggestion.get("section") in ("experience", "projects"):
        section = suggestion.get("section") or (
            "experience" if suggestion_type == "experience_bullet" else "projects"
        )
        entry_id = suggestion.get("entry_id") or suggestion.get("entryId")
        child_id = suggestion.get("child_id") or suggestion.get("childId")
        entries = content.profile.experience if section == "experience" else content.profile.projects
        for entry in entries:
            if entry.id == entry_id:
                if section == "experience":
                    from app.models.resume import BulletItem

                    # Prefer child_id matching for precise bullet targeting
                    if child_id:
                        for idx, b in enumerate(entry.responsibilities):
                            if b.id == child_id:
                                entry.responsibilities[idx] = BulletItem(id=child_id, text=suggested_text)
                                break
                        else:
                            # Fallback: text-based matching if child_id not found
                            bullet_texts = [b.text for b in entry.responsibilities]
                            if current_text in bullet_texts:
                                idx = bullet_texts.index(current_text)
                                entry.responsibilities[idx] = BulletItem(id=entry.responsibilities[idx].id, text=suggested_text)
                            elif suggested_text:
                                entry.responsibilities.append(BulletItem(text=suggested_text))
                    else:
                        # Legacy text-based matching
                        bullet_texts = [b.text for b in entry.responsibilities]
                        if current_text in bullet_texts:
                            idx = bullet_texts.index(current_text)
                            entry.responsibilities[idx] = BulletItem(id=entry.responsibilities[idx].id, text=suggested_text)
                        elif current_text in entry.achievements:
                            idx = entry.achievements.index(current_text)
                            entry.achievements[idx] = suggested_text
                        elif suggested_text:
                            entry.responsibilities.append(BulletItem(text=suggested_text))
                else:
                    if (not current_text or entry.description == current_text) and suggested_text:
                        entry.description = suggested_text
                    elif suggested_text:
                        entry.description = suggested_text
                break

    elif suggestion_type in ("skills_alignment", "skills_alignment_llm") or suggestion.get("section") == "skills":
        from app.models.resume import SkillCategory

        if content.profile.skills is None:
            content.profile.skills = SkillCategory()

        skill_val = (
            edited_text
            or suggestion.get("suggested_text")
            or suggestion.get("suggestedText")
            or suggestion.get("skill")
            or ""
        ).strip()
        if skill_val:
            skills_to_add = [s.strip() for s in skill_val.replace("\n", ",").split(",") if s.strip()]
            for s in skills_to_add:
                if s not in content.profile.skills.technical:
                    content.profile.skills.technical.append(s)

    return content


@router.post("/generate", response_model=OptimizeResumeResponse)
async def generate_optimizations(
    payload: OptimizeResumeRequest,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> OptimizeResumeResponse:
    """Generate AI optimization suggestions for a resume against a job description."""
    try:
        if not payload.job_description or not payload.job_description.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Job description cannot be empty",
            )

        repo = ResumeRepository(jwt=token)
        resume = repo.get_resume(current_user.user.id, payload.resume_id)
        if not resume:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resume not found or unauthorized access",
            )

        version_id = payload.version_id
        if version_id:
            version = repo.get_version(version_id)
            if not version:
                raise HTTPException(status_code=404, detail="Version not found")
            if version.get("resume_id") != payload.resume_id:
                raise HTTPException(status_code=400, detail="Version does not belong to this resume")
            resume_content = ResumeContent.from_dict(version.get("content") or {})
        else:
            resume_content = ResumeContent.from_dict(resume.get("content"))
        result = optimization_service.optimize_resume(
            resume_content=resume_content,
            job_description=payload.job_description,
            job_title=payload.job_title,
        )

        baseline_score = None
        if payload.ats_report_id:
            report = ats_repo.get_report(payload.ats_report_id, jwt=token)
            if report:
                baseline_score = report.overall_score

        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        session = {
            "id": session_id,
            "resume_id": payload.resume_id,
            "version_id": version_id,
            "ats_report_id": payload.ats_report_id,
            "job_title": payload.job_title,
            "company": payload.company,
            "job_description": payload.job_description,
            "status": "active",
            "suggestions_generated": len(result.suggestions),
            "suggestions_accepted": 0,
            "suggestions_rejected": 0,
            "current_ats_score": baseline_score,
            "baseline_ats_score": baseline_score,
            "target_job_title": payload.job_title,
            "target_company": payload.company,
            "created_at": now,
            "updated_at": now,
        }

        stored_suggestions = []
        for sug in result.suggestions:
            sug_id = str(uuid.uuid4())
            entry_id = sug.get("entry_id") or sug.get("entryId")
            child_id = sug.get("child_id") or sug.get("childId")
            current_text = sug.get("current_text") or sug.get("currentText")
            suggested_text = sug.get("suggested_text") or sug.get("suggestedText") or sug.get("skill")
            affected_keywords = sug.get("affected_keywords") or sug.get("affectedKeywords", [])
            priority = sug.get("priority", "medium")
            action = sug.get("action", "replace")
            status_val = sug.get("status", "pending")

            suggestion_obj = {
                "id": sug_id,
                "type": sug.get("type"),
                "priority": priority,
                "section": sug.get("section"),
                "entry_id": entry_id,
                "child_id": child_id,
                "entryId": entry_id,
                "childId": child_id,
                "current_text": current_text,
                "currentText": current_text,
                "suggested_text": suggested_text,
                "suggestedText": suggested_text,
                "explanation": sug.get("explanation", ""),
                "evidence": sug.get("evidence", []),
                "affected_keywords": affected_keywords,
                "affectedKeywords": affected_keywords,
                "category": sug.get("category"),
                "action": action,
                "skill": sug.get("skill"),
                "similar_in_resume": sug.get("similar_in_resume"),
                "status": status_val,
                "evidence_issues": sug.get("evidence_issues", []),
                "created_at": now,
                "updated_at": now,
            }
            stored_suggestions.append(suggestion_obj)

        try:
            optimization_repo.create_session(session, jwt=token)
            for idx, suggestion_obj in enumerate(stored_suggestions):
                # Use the same ID for both the database record and the suggestion object
                # This allows the frontend to query by primary key which RLS handles correctly
                record = {
                    "id": suggestion_obj["id"],  # Use the same ID
                    "session_id": session_id,
                    "suggestion": suggestion_obj,
                    "resume_snapshot": resume.get("content"),
                    "applied": False,
                    "applied_at": None,
                    "created_at": now,
                    "updated_at": now,
                }
                optimization_repo.create_suggestion(record, jwt=token)
        except Exception as persist_exc:
            logger.warning("Optimization persistence failed: %s", persist_exc)

        return OptimizeResumeResponse(
            session_id=session_id,
            suggestions=stored_suggestions,
            message=result.message,
            evidence_issues=result.evidence_issues,
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Error generating optimizations: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Optimization generation failed",
        )


@router.post("/skills/generate", response_model=GenerateSkillsOptimizationResponse)
async def generate_skills_optimization(
    payload: GenerateSkillsOptimizationRequest,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> GenerateSkillsOptimizationResponse:
    """Generate LLM-powered skills optimization suggestions for a resume."""
    try:
        if not payload.job_description or not payload.job_description.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Job description cannot be empty",
            )

        repo = ResumeRepository(jwt=token)
        resume = repo.get_resume(current_user.user.id, payload.resume_id)
        if not resume:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resume not found or unauthorized access",
            )

        version_id = payload.version_id
        if version_id:
            version = repo.get_version(version_id)
            if not version:
                raise HTTPException(status_code=404, detail="Version not found")
            if version.get("resume_id") != payload.resume_id:
                raise HTTPException(status_code=400, detail="Version does not belong to this resume")
            resume_content = ResumeContent.from_dict(version.get("content") or {})
        else:
            resume_content = ResumeContent.from_dict(resume.get("content"))

        result = optimization_service.generate_skills_optimization_llm(
            resume_content=resume_content,
            job_description=payload.job_description,
            job_title=payload.job_title,
        )

        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        session = {
            "id": session_id,
            "resume_id": payload.resume_id,
            "version_id": version_id,
            "job_title": payload.job_title,
            "company": payload.company,
            "job_description": payload.job_description,
            "status": "active",
            "suggestions_generated": len(result.suggestions),
            "suggestions_accepted": 0,
            "suggestions_rejected": 0,
            "target_job_title": payload.job_title,
            "target_company": payload.company,
            "created_at": now,
            "updated_at": now,
        }

        stored_suggestions = []
        for sug in result.suggestions:
            sug_id = str(uuid.uuid4())
            suggestion_obj = {
                "id": sug_id,
                "type": sug.get("type"),
                "priority": "medium",
                "section": sug.get("section"),
                "entry_id": sug.get("entryId"),
                "current_text": sug.get("currentText"),
                "suggested_text": sug.get("suggestedText"),
                "explanation": sug.get("explanation", ""),
                "evidence": sug.get("evidence", []),
                "affected_keywords": sug.get("affectedKeywords", []),
                "category": sug.get("category"),
                "action": sug.get("action"),
                "skill": sug.get("skill"),
                "similar_in_resume": sug.get("similar_in_resume"),
                "status": sug.get("status", "pending"),
                "evidence_issues": result.evidence_issues,
                "created_at": now,
                "updated_at": now,
            }
            stored_suggestions.append(suggestion_obj)

        try:
            optimization_repo.create_session(session, jwt=token)
            for suggestion_obj in stored_suggestions:
                record = {
                    "id": suggestion_obj["id"],
                    "session_id": session_id,
                    "suggestion": suggestion_obj,
                    "resume_snapshot": resume.get("content"),
                    "applied": False,
                    "applied_at": None,
                    "created_at": now,
                    "updated_at": now,
                }
                optimization_repo.create_suggestion(record, jwt=token)
        except Exception as persist_exc:
            logger.warning("Optimization persistence failed: %s", persist_exc)

        return GenerateSkillsOptimizationResponse(
            session_id=session_id,
            suggestions=stored_suggestions,
            message=result.message,
            evidence_issues=result.evidence_issues,
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Error generating skills optimization: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Skills optimization failed",
        )


@router.post("/summary/generate", response_model=GenerateSummaryOptimizationResponse)
async def generate_summary_optimization(
    payload: GenerateSummaryOptimizationRequest,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> GenerateSummaryOptimizationResponse:
    """Generate LLM-powered professional summary optimization suggestions."""
    try:
        if not payload.job_description or not payload.job_description.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Job description cannot be empty",
            )

        repo = ResumeRepository(jwt=token)
        resume = repo.get_resume(current_user.user.id, payload.resume_id)
        if not resume:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resume not found or unauthorized access",
            )

        version_id = payload.version_id
        if version_id:
            version = repo.get_version(version_id)
            if not version:
                raise HTTPException(status_code=404, detail="Version not found")
            if version.get("resume_id") != payload.resume_id:
                raise HTTPException(status_code=400, detail="Version does not belong to this resume")
            resume_content = ResumeContent.from_dict(version.get("content") or {})
        else:
            resume_content = ResumeContent.from_dict(resume.get("content"))

        result = optimization_service.generate_summary_optimization_llm(
            resume_content=resume_content,
            job_description=payload.job_description,
            job_title=payload.job_title,
        )

        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        session = {
            "id": session_id,
            "resume_id": payload.resume_id,
            "version_id": version_id,
            "job_title": payload.job_title,
            "company": payload.company,
            "job_description": payload.job_description,
            "status": "active",
            "suggestions_generated": len(result.suggestions),
            "suggestions_accepted": 0,
            "suggestions_rejected": 0,
            "target_job_title": payload.job_title,
            "target_company": payload.company,
            "created_at": now,
            "updated_at": now,
        }

        stored_suggestions = []
        for sug in result.suggestions:
            sug_id = str(uuid.uuid4())
            suggestion_obj = {
                "id": sug_id,
                "type": sug.get("type"),
                "priority": "medium",
                "section": sug.get("section"),
                "entry_id": sug.get("entryId"),
                "current_text": sug.get("currentText"),
                "suggested_text": sug.get("suggestedText"),
                "explanation": sug.get("explanation", ""),
                "evidence": sug.get("evidence", []),
                "affected_keywords": sug.get("affectedKeywords", []),
                "category": sug.get("category"),
                "action": sug.get("action"),
                "skill": sug.get("skill"),
                "similar_in_resume": sug.get("similar_in_resume"),
                "status": sug.get("status", "pending"),
                "evidence_issues": result.evidence_issues,
                "created_at": now,
                "updated_at": now,
            }
            stored_suggestions.append(suggestion_obj)

        try:
            optimization_repo.create_session(session, jwt=token)
            for suggestion_obj in stored_suggestions:
                record = {
                    "id": suggestion_obj["id"],
                    "session_id": session_id,
                    "suggestion": suggestion_obj,
                    "resume_snapshot": resume.get("content"),
                    "applied": False,
                    "applied_at": None,
                    "created_at": now,
                    "updated_at": now,
                }
                optimization_repo.create_suggestion(record, jwt=token)
        except Exception as persist_exc:
            logger.warning("Optimization persistence failed: %s", persist_exc)

        return GenerateSummaryOptimizationResponse(
            session_id=session_id,
            suggestions=stored_suggestions,
            message=result.message,
            evidence_issues=result.evidence_issues,
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Error generating summary optimization: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Summary optimization failed",
        )


@router.post("/experience/bullet/generate", response_model=GenerateExperienceBulletOptimizationResponse)
async def generate_experience_bullet_optimization(
    payload: GenerateExperienceBulletOptimizationRequest,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> GenerateExperienceBulletOptimizationResponse:
    """Generate LLM-powered experience bullet optimization suggestion for a single bullet."""
    try:
        if not payload.job_description or not payload.job_description.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Job description cannot be empty",
            )

        repo = ResumeRepository(jwt=token)
        resume = repo.get_resume(current_user.user.id, payload.resume_id)
        if not resume:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resume not found or unauthorized access",
            )

        version_id = payload.version_id
        if version_id:
            version = repo.get_version(version_id)
            if not version:
                raise HTTPException(status_code=404, detail="Version not found")
            if version.get("resume_id") != payload.resume_id:
                raise HTTPException(status_code=400, detail="Version does not belong to this resume")
            resume_content = ResumeContent.from_dict(version.get("content") or {})
        else:
            resume_content = ResumeContent.from_dict(resume.get("content"))

        result = optimization_service.generate_experience_bullet_optimization_llm(
            resume_content=resume_content,
            job_description=payload.job_description,
            entry_id=payload.entry_id,
            bullet_id=payload.bullet_id,
            bullet_text=payload.bullet_text,
            job_title=payload.job_title,
        )

        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        session = {
            "id": session_id,
            "resume_id": payload.resume_id,
            "version_id": version_id,
            "job_title": payload.job_title,
            "company": payload.company,
            "job_description": payload.job_description,
            "status": "active",
            "suggestions_generated": len(result.suggestions),
            "suggestions_accepted": 0,
            "suggestions_rejected": 0,
            "target_job_title": payload.job_title,
            "target_company": payload.company,
            "created_at": now,
            "updated_at": now,
        }

        stored_suggestions = []
        for sug in result.suggestions:
            sug_id = str(uuid.uuid4())
            suggestion_obj = {
                "id": sug_id,
                "type": sug.get("type"),
                "priority": "medium",
                "section": sug.get("section"),
                "entry_id": sug.get("entryId"),
                "child_id": sug.get("childId"),
                "current_text": sug.get("currentText"),
                "suggested_text": sug.get("suggestedText"),
                "explanation": sug.get("explanation", ""),
                "evidence": sug.get("evidence", []),
                "affected_keywords": sug.get("affectedKeywords", []),
                "category": sug.get("category"),
                "action": sug.get("action"),
                "skill": sug.get("skill"),
                "similar_in_resume": sug.get("similar_in_resume"),
                "status": sug.get("status", "pending"),
                "evidence_issues": result.evidence_issues,
                "created_at": now,
                "updated_at": now,
            }
            stored_suggestions.append(suggestion_obj)

        try:
            optimization_repo.create_session(session, jwt=token)
            for suggestion_obj in stored_suggestions:
                record = {
                    "id": suggestion_obj["id"],
                    "session_id": session_id,
                    "suggestion": suggestion_obj,
                    "resume_snapshot": resume.get("content"),
                    "applied": False,
                    "applied_at": None,
                    "created_at": now,
                    "updated_at": now,
                }
                optimization_repo.create_suggestion(record, jwt=token)
        except Exception as persist_exc:
            logger.warning("Optimization persistence failed: %s", persist_exc)

        return GenerateExperienceBulletOptimizationResponse(
            session_id=session_id,
            suggestions=stored_suggestions,
            message=result.message,
            evidence_issues=result.evidence_issues,
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Error generating experience bullet optimization: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Experience bullet optimization failed",
        )


@router.post("/suggestions/accept", response_model=SuggestionActionResponse)
async def accept_suggestion(
    payload: AcceptSuggestionRequest,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> SuggestionActionResponse:
    """Accept an optimization suggestion and apply it to the resume."""
    try:
        logger.info("Accept suggestion: suggestion_id=%s, session_id=%s", payload.suggestion_id, payload.session_id)
        # Ownership is enforced in two layers (defense in depth):
        #   1. RLS — we fetch/update through the authenticated (RLS) client
        #      (jwt=token), never the service-role client, so rows not owned by
        #      the caller are invisible/unwritable at the database policy layer.
        #   2. Explicit application-level ownership verification below.
        record = optimization_repo.get_suggestion(payload.suggestion_id, jwt=token)
        if not record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")

        suggestion = record.get("suggestion", {})
        session = optimization_repo.get_session(payload.session_id, jwt=token)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        if session.get("id") != record.get("session_id"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid session: session ID mismatch")

        # Explicit application-level ownership check: the session (and thus the
        # suggestion) must belong to the authenticated user. get_resume() scopes
        # by user_id, so it returns None for another user's resume.
        repo = ResumeRepository(jwt=token)
        owned_resume = repo.get_resume(current_user.user.id, session["resume_id"])
        if not owned_resume:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to accept this suggestion",
            )

        version_id = session.get("version_id")
        if version_id:
            version = repo.get_version(version_id)
            if not version:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
            base_content = version.get("content") or {}
        else:
            base_content = owned_resume.get("content") or {}

        edited_text = payload.edited_text

        # DOCUMENT CHANGE CONTRACT: a suggestion is only "accepted" when its
        # content change produced a REAL document artifact on a derived version.
        # The master resume is immutable - accepting against it would mutate only
        # JSON state while the visible PDF stays unchanged (fake success).
        if not version_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "The master resume is immutable. Run optimization against a derived "
                    "version so an accepted suggestion can produce a real document artifact."
                ),
            )

        updated_content = _apply_suggestion_to_content(
            ResumeContent.from_dict(base_content), suggestion, edited_text
        )
        updated_suggestion = dict(suggestion)
        updated_suggestion["status"] = "edited" if edited_text else "accepted"
        if edited_text:
            updated_suggestion["suggested_text"] = edited_text

        # Compile and persist the artifact BEFORE recording acceptance. Any failure
        # aborts the operation: no version content change, no "accepted" marker.
        from app.services.resumes.compiler_service import resume_compiler_service

        geom_map = (version.get("meta") or {}).get("geometry") or (owned_resume.get("meta") or {}).get("geometry")
        update_payload: dict[str, Any] = {"content": updated_content.to_dict()}
        try:
            comp_res = resume_compiler_service.compile_and_persist(
                user_id=current_user.user.id,
                version_id=version_id,
                content=updated_content,
                geometry_map=geom_map,
                jwt=token,
            )
        except Exception as c_err:
            logger.error("Artifact compilation on suggestion accept failed: %s", c_err, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Document artifact regeneration failed. The suggestion was NOT applied and no content change was persisted.",
            ) from c_err
        if not comp_res.get("storage_path"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Document artifact regeneration failed. The suggestion was NOT applied and no content change was persisted.",
            )

        meta = dict(version.get("meta") or {})
        meta["storage_path"] = comp_res["storage_path"]
        if comp_res.get("docx_storage_path"):
            meta["docx_storage_path"] = comp_res["docx_storage_path"]
        if comp_res.get("geometry"):
            meta["geometry"] = comp_res["geometry"]
        meta["compilation_strategy"] = comp_res.get("strategy", "document_compiler")
        update_payload["meta"] = meta
        update_payload["source"] = comp_res.get("strategy", "document_compiler")
        repo.update_version(version_id, update_payload)

        # Record acceptance only after the full artifact pipeline succeeded.
        optimization_repo.update_suggestion(
            payload.suggestion_id,
            {
                "suggestion": updated_suggestion,
                "applied": True,
                "applied_at": datetime.utcnow().isoformat(),
            },
            jwt=token,
        )

        # Update session counters using the authenticated (RLS) client.
        suggestions = optimization_repo.list_suggestions_for_session(payload.session_id, jwt=token)
        accepted = sum(1 for s in suggestions if (s.get("suggestion") or {}).get("status") in ("accepted", "edited"))
        rejected = sum(1 for s in suggestions if (s.get("suggestion") or {}).get("status") == "rejected")
        optimization_repo.update_session(
            payload.session_id,
            {"suggestions_accepted": accepted, "suggestions_rejected": rejected},
            jwt=token,
        )

        return SuggestionActionResponse(
            success=True,
            suggestion_id=payload.suggestion_id,
            status=updated_suggestion["status"],
            updated_resume=updated_content.to_dict(),
            message="Suggestion accepted and applied to resume.",
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Error accepting suggestion: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to accept suggestion",
        )


@router.post("/suggestions/reject", response_model=SuggestionActionResponse)
async def reject_suggestion(
    payload: RejectSuggestionRequest,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> SuggestionActionResponse:
    """Reject an optimization suggestion."""
    try:
        jwt_token = current_user.jwt or token
        record = optimization_repo.get_suggestion(payload.suggestion_id, jwt=jwt_token)
        if not record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")

        suggestion = record.get("suggestion", {})
        session = optimization_repo.get_session(payload.session_id, jwt=jwt_token)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid session")

        if session.get("id") != record.get("session_id"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Suggestion does not belong to session")

        repo = ResumeRepository(jwt=jwt_token)
        owned_resume = repo.get_resume(current_user.user.id, session["resume_id"])
        if not owned_resume:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to reject this suggestion",
            )

        updated_suggestion = dict(suggestion)
        updated_suggestion["status"] = "rejected"

        optimization_repo.update_suggestion(
            payload.suggestion_id, {"suggestion": updated_suggestion}, jwt=jwt_token
        )

        suggestions = optimization_repo.list_suggestions_for_session(payload.session_id, jwt=jwt_token)
        accepted = sum(1 for s in suggestions if (s.get("suggestion") or {}).get("status") in ("accepted", "edited"))
        rejected = sum(1 for s in suggestions if (s.get("suggestion") or {}).get("status") == "rejected")
        optimization_repo.update_session(
            payload.session_id,
            {"suggestions_accepted": accepted, "suggestions_rejected": rejected},
            jwt=jwt_token,
        )

        return SuggestionActionResponse(
            success=True,
            suggestion_id=payload.suggestion_id,
            status="rejected",
            updated_resume=None,
            message="Suggestion rejected.",
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("Error rejecting suggestion: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reject suggestion",
        )


@router.get("/sessions/{session_id}", response_model=OptimizationSessionResponse)
async def get_session(
    session_id: str,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> OptimizationSessionResponse:
    """Get an optimization session with all its suggestions."""
    session = optimization_repo.get_session(session_id, jwt=token)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # Ensure user owns the resume
    repo = ResumeRepository(jwt=token)
    resume = repo.get_resume(current_user.user.id, session["resume_id"])
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unauthorized")

    records = optimization_repo.list_suggestions_for_session(session_id, jwt=token)
    return OptimizationSessionResponse(
        session=session,
        suggestions=records,
    )


@router.get("/resume/{resume_id}/sessions", response_model=ListOptimizationSessionsResponse)
async def list_sessions(
    resume_id: str,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> ListOptimizationSessionsResponse:
    """List optimization sessions for a resume."""
    repo = ResumeRepository(jwt=token)
    resume = repo.get_resume(current_user.user.id, resume_id)
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    sessions = optimization_repo.list_sessions_for_resume(resume_id, jwt=token)
    for session in sessions:
        suggestions = optimization_repo.list_suggestions_for_session(session["id"], jwt=token)
        session["suggestions"] = suggestions
    return ListOptimizationSessionsResponse(sessions=sessions)


@router.get("/resume/{resume_id}/history", response_model=ListOptimizationHistoryResponse)
async def get_history(
    resume_id: str,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> ListOptimizationHistoryResponse:
    """Get optimization history for a resume."""
    repo = ResumeRepository(jwt=token)
    resume = repo.get_resume(current_user.user.id, resume_id)
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    history = optimization_repo.get_optimization_history(resume_id, jwt=token)
    return ListOptimizationHistoryResponse(history=history)


@router.post("/reanalyze", response_model=ReanalyzeResponse)
async def reanalyze(
    payload: ReanalyzeRequest,
    current_user: AuthContext = Depends(get_current_user),
    token: Optional[str] = Depends(get_auth_token),
) -> ReanalyzeResponse:
    """Re-run ATS analysis after applying suggestions to measure score delta."""
    try:
        repo = ResumeRepository(jwt=token)
        resume = repo.get_resume(current_user.user.id, payload.resume_id)
        if not resume:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")

        session = optimization_repo.get_session(payload.session_id, jwt=token)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        previous_score = float(session.get("current_ats_score") or 0)

        # Closed-loop ATS: analyze the ACTUAL changed content. When the session
        # targets a derived version, score that version's content - never the
        # (immutable) master resume the user may no longer be editing.
        session_version_id = session.get("version_id")
        if session_version_id:
            version = repo.get_version(session_version_id)
            if not version or version.get("resume_id") != payload.resume_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
            resume_content = ResumeContent.from_dict(version.get("content") or {})
        else:
            resume_content = ResumeContent.from_dict(resume.get("content"))
        analysis_result = analyzer.analyze_resume(
            resume_content=resume_content,
            job_description=payload.job_description,
            job_title=payload.job_title,
            company=payload.company,
        )
        current_score = float(analysis_result.overall_score)

        # Persist updated session score
        optimization_repo.update_session(
            payload.session_id,
            {"current_ats_score": current_score, "status": "completed"},
            jwt=token,
        )

        return ReanalyzeResponse(
            previous_score=previous_score,
            current_score=current_score,
            delta=round(current_score - previous_score, 2),
            report_id="",
            message=(
                f"Score improved by {round(current_score - previous_score, 2)} points."
                if current_score >= previous_score
                else "Score changed after optimization."
            ),
        )

    except HTTPException as he:
        raise he
    