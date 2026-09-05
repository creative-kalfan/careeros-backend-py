"""Resume version API routes (Step 6)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.repositories.resume_repository import ResumeRepository
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.resume import (
    ApplyTailoringRequest,
    ApplyVersionOperationRequest,
    MutatePdfRequest,
    ResumeVersionCreate,
    ResumeVersionResponse,
    ResumeVersionUpdate,
    SaveVersionContentRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resumes", tags=["resume-versions"])


def _to_version_response(row: dict[str, Any]) -> ResumeVersionResponse:
    meta = row.get("meta") or {}
    source = meta.get("provenance_source") or row.get("source", "manual") if isinstance(meta, dict) else row.get("source", "manual")
    return ResumeVersionResponse(
        id=row["id"],
        resume_id=row["resume_id"],
        version_name=row.get("version_name", "Untitled Version"),
        source=source,
        content=row.get("content") or {},
        target_job_title=row.get("target_job_title"),
        target_company=row.get("target_company"),
        target_job_id=row.get("target_job_id"),
        target_job_url=row.get("target_job_url"),
        job_description=row.get("job_description"),
        template=row.get("template", "minimal"),
        status=row.get("status", "active"),
        is_master=row.get("is_master", False),
        parent_version_id=row.get("parent_version_id"),
        meta=row.get("meta") or {},
        last_ats_score=row.get("last_ats_score"),
        last_analyzed_at=row.get("last_analyzed_at"),
        sections_config=row.get("sections_config") or {},
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
    )


@router.get(
    "/{resume_id}/versions",
    response_model=SuccessResponse[list[ResumeVersionResponse]],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def list_versions(
    resume_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[list[ResumeVersionResponse]]:
    repo = ResumeRepository(jwt=auth.jwt)
    resume = repo.get_resume(auth.user.id, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    rows = repo.list_versions(resume_id)
    return SuccessResponse(data=[_to_version_response(r) for r in rows])


@router.post(
    "/{resume_id}/versions",
    response_model=SuccessResponse[ResumeVersionResponse],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
)
async def create_version(
    resume_id: str,
    body: ResumeVersionCreate,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ResumeVersionResponse]:
    repo = ResumeRepository(jwt=auth.jwt)
    resume = repo.get_resume(auth.user.id, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    content = body.content or {}
    if not content:
        content = resume.get("content") or {}

    meta = body.model_dump(exclude_none=True)
    if body.parent_version_id:
        parent = repo.get_version(body.parent_version_id)
        if parent:
            parent_meta = parent.get("meta") or {}
            if "storage_path" in parent_meta and "storage_path" not in meta:
                meta["storage_path"] = parent_meta["storage_path"]
            if "docx_storage_path" in parent_meta and "docx_storage_path" not in meta:
                meta["docx_storage_path"] = parent_meta["docx_storage_path"]
            if "geometry" in parent_meta and "geometry" not in meta:
                meta["geometry"] = parent_meta["geometry"]
    if "storage_path" not in meta and resume.get("storage_path"):
        meta["storage_path"] = resume["storage_path"]
    if "geometry" not in meta and (resume.get("meta") or {}).get("geometry"):
        meta["geometry"] = (resume.get("meta") or {})["geometry"]

    row = repo.create_version(
        resume_id=resume_id,
        content=content,
        version_name=body.version_name,
        source=body.source,
        is_master=False,
        parent_version_id=body.parent_version_id,
        target_job_title=body.target_job_title,
        target_company=body.target_company,
        target_job_id=body.target_job_id,
        target_job_url=body.target_job_url,
        job_description=body.job_description,
        template=body.template,
        sections_config=body.sections_config,
        meta=meta,
    )
    return SuccessResponse(data=_to_version_response(row))


@router.get(
    "/versions/{version_id}",
    response_model=SuccessResponse[ResumeVersionResponse],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_version(
    version_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ResumeVersionResponse]:
    repo = ResumeRepository(jwt=auth.jwt)
    row = repo.get_version(version_id)
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    resume = repo.get_resume(auth.user.id, row["resume_id"])
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return SuccessResponse(data=_to_version_response(row))


@router.patch(
    "/versions/{version_id}",
    response_model=SuccessResponse[ResumeVersionResponse],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def update_version(
    version_id: str,
    body: ResumeVersionUpdate,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ResumeVersionResponse]:
    repo = ResumeRepository(jwt=auth.jwt)
    row = repo.get_version(version_id)
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    resume = repo.get_resume(auth.user.id, row["resume_id"])
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        return SuccessResponse(data=_to_version_response(row))

    updated = repo.update_version(version_id, update_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Version not found")
    return SuccessResponse(data=_to_version_response(updated))


@router.delete(
    "/versions/{version_id}",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def delete_version(
    version_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    repo = ResumeRepository(jwt=auth.jwt)
    row = repo.get_version(version_id)
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    resume = repo.get_resume(auth.user.id, row["resume_id"])
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if row.get("is_master"):
        raise HTTPException(status_code=400, detail="Cannot delete the master resume version")
    repo.delete_version(version_id)
    return SuccessResponse(data={"deleted": True})


@router.post(
    "/versions/{version_id}/duplicate",
    response_model=SuccessResponse[ResumeVersionResponse],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def duplicate_version(
    version_id: str,
    body: dict | None = None,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ResumeVersionResponse]:
    repo = ResumeRepository(jwt=auth.jwt)
    row = repo.get_version(version_id)
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    resume = repo.get_resume(auth.user.id, row["resume_id"])
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    new_name = (body or {}).get("version_name") if body else None
    new_row = repo.duplicate_version(version_id, new_name)
    return SuccessResponse(data=_to_version_response(new_row))


@router.post(
    "/versions/{version_id}/set-master",
    response_model=SuccessResponse[ResumeVersionResponse],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def set_master_version(
    version_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ResumeVersionResponse]:
    repo = ResumeRepository(jwt=auth.jwt)
    row = repo.get_version(version_id)
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    resume = repo.get_resume(auth.user.id, row["resume_id"])
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    updated = repo.set_master_version(row["resume_id"], version_id)
    return SuccessResponse(data=_to_version_response(updated))


@router.post(
    "/versions/{version_id}/apply-operation",
    response_model=SuccessResponse[ResumeVersionResponse],
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        400: {"model": ErrorResponse},
    },
)
async def apply_version_operation(
    version_id: str,
    body: ApplyVersionOperationRequest,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ResumeVersionResponse]:
    from app.models.resume import BulletItem, ResumeContent, ResumeProfile, SkillCategory

    repo = ResumeRepository(jwt=auth.jwt)
    row = repo.get_version(version_id)
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    if row.get("is_master"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify master version directly. Please create a derived version before applying operations.",
        )
    resume = repo.get_resume(auth.user.id, row["resume_id"])
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    content = ResumeContent.from_dict(row.get("content") or {})

    operation = body.operation
    section = body.section
    target_id = body.target_id
    replacement = body.replacement or {}

    profile = content.profile
    section_map: dict[str, list[Any]] = {
        "experience": profile.experience,
        "internships": profile.internships,
        "projects": profile.projects,
        "education": profile.education,
        "certifications": profile.certifications,
        "achievements": profile.achievements,
        "leadership": profile.leadership,
        "languages": profile.languages,
        "links": profile.links,
        "additional": profile.additional,
    }

    # Handle scalar sections (summary, target_role) as direct field replacements
    scalar_sections = {"summary", "target_role"}
    if section in scalar_sections:
        if operation == "replace":
            suggested = (
                replacement.get("suggestedText")
                or replacement.get("suggested_text")
                or replacement.get("text")
                or (replacement if isinstance(replacement, str) else "")
                or body.child_text
                or ""
            )
            if not suggested:
                raise HTTPException(status_code=400, detail="replacement.suggestedText is required for summary replace")
            setattr(profile, section, suggested)
        else:
            raise HTTPException(status_code=400, detail=f"Only replace is supported for scalar section: {section}")

    # Handle skills section
    elif section == "skills":
        if operation == "replace":
            suggested = replacement.get("suggestedText") or replacement.get("suggested_text")
            if isinstance(suggested, str):
                new_skills = [s.strip() for s in suggested.replace("\n", ",").split(",") if s.strip()]
                if not profile.skills:
                    profile.skills = SkillCategory(technical=new_skills)
                else:
                    profile.skills.technical = new_skills
            elif isinstance(replacement.get("skills"), dict):
                profile.skills = SkillCategory(**replacement["skills"])
            elif isinstance(replacement.get("technical"), list):
                if not profile.skills:
                    profile.skills = SkillCategory()
                profile.skills.technical = replacement["technical"]
        elif operation == "insert":
            new_skill = (
                body.child_text
                or replacement.get("suggestedText")
                or replacement.get("suggested_text")
                or replacement.get("skill")
            )
            if isinstance(new_skill, str) and new_skill.strip():
                if not profile.skills:
                    profile.skills = SkillCategory(technical=[])
                skills_to_add = [s.strip() for s in new_skill.replace("\n", ",").split(",") if s.strip()]
                for s in skills_to_add:
                    if s not in profile.skills.technical:
                        profile.skills.technical.append(s)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported operation: {operation} for skills")

    else:
        if section not in section_map:
            raise HTTPException(status_code=400, detail=f"Unsupported section: {section}")

        target_list = section_map[section]

        if operation == "replace":
            if not target_id:
                raise HTTPException(status_code=400, detail="target_id is required for replace")
            if not replacement:
                raise HTTPException(status_code=400, detail="replacement is required for replace")
            idx = next((i for i, item in enumerate(target_list) if getattr(item, "id", None) == target_id), None)
            if idx is None:
                raise HTTPException(status_code=404, detail=f"Target {target_id} not found in section {section}")

            # Child-level targeting: replace a specific bullet within an experience or project item
            if body.child_id is not None:
                target_item = target_list[idx]
                responsibilities = getattr(target_item, "responsibilities", None)
                new_text = (
                    body.child_text
                    or replacement.get("suggestedText")
                    or replacement.get("suggested_text")
                    or replacement.get("text")
                    or ""
                )
                if not new_text:
                    raise HTTPException(status_code=400, detail="child_text or replacement.suggestedText is required for bullet replace")

                if responsibilities is not None:
                    bullet_idx = next((i for i, b in enumerate(responsibilities) if getattr(b, "id", None) == body.child_id), None)
                    if bullet_idx is None:
                        # Try currentText matching fallback
                        curr = (replacement.get("currentText") or replacement.get("current_text") or "").strip()
                        if curr:
                            bullet_idx = next((i for i, b in enumerate(responsibilities) if b.text.strip() == curr), None)
                    if bullet_idx is not None:
                        responsibilities[bullet_idx] = BulletItem(id=responsibilities[bullet_idx].id, text=new_text)
                    else:
                        responsibilities.append(BulletItem(id=body.child_id, text=new_text))
                elif hasattr(target_item, "description"):
                    target_item.description = new_text
                else:
                    raise HTTPException(status_code=400, detail=f"Section {section} does not support child targeting")
            else:
                item = target_list[idx]
                clean_replacement = dict(replacement)
                if hasattr(item, "description") and ("suggestedText" in clean_replacement or "suggested_text" in clean_replacement):
                    clean_replacement["description"] = clean_replacement.pop("suggestedText", None) or clean_replacement.pop("suggested_text", None)
                if hasattr(item, "model_copy"):
                    # Filter out keys not in model fields
                    valid_fields = set(item.model_fields.keys())
                    filtered = {k: v for k, v in clean_replacement.items() if k in valid_fields}
                    target_list[idx] = item.model_copy(update=filtered)
                elif isinstance(item, dict):
                    updated_item = dict(item)
                    updated_item.update(clean_replacement)
                    target_list[idx] = updated_item
                else:
                    updated_item = dict(item)
                    updated_item.update(clean_replacement)
                    target_list[idx] = updated_item
        elif operation == "insert":
            # Child-level insert: append a new bullet to an experience item
            if body.child_id is not None and target_id:
                idx = next((i for i, item in enumerate(target_list) if getattr(item, "id", None) == target_id), None)
                if idx is None:
                    raise HTTPException(status_code=404, detail=f"Target {target_id} not found in section {section}")
                target_item = target_list[idx]
                responsibilities = getattr(target_item, "responsibilities", None)
                if responsibilities is None:
                    raise HTTPException(status_code=400, detail=f"Section {section} does not support child targeting")
                new_text = body.child_text or ""
                if not new_text:
                    raise HTTPException(status_code=400, detail="child_text is required for bullet insert")
                responsibilities.append(BulletItem(text=new_text))
            else:
                if not replacement:
                    raise HTTPException(status_code=400, detail="replacement is required for insert")
                new_item = replacement
                new_item.setdefault("id", str(uuid.uuid4()).hex[:12])
                target_list.append(new_item)
        elif operation == "delete":
            # Child-level delete: remove a specific bullet from an experience item
            if body.child_id is not None and target_id:
                idx = next((i for i, item in enumerate(target_list) if getattr(item, "id", None) == target_id), None)
                if idx is None:
                    raise HTTPException(status_code=404, detail=f"Target {target_id} not found in section {section}")
                target_item = target_list[idx]
                responsibilities = getattr(target_item, "responsibilities", None)
                if responsibilities is None:
                    raise HTTPException(status_code=400, detail=f"Section {section} does not support child targeting")
                bullet_idx = next((i for i, b in enumerate(responsibilities) if getattr(b, "id", None) == body.child_id), None)
                if bullet_idx is None:
                    raise HTTPException(status_code=404, detail=f"Bullet {body.child_id} not found in item {target_id}")
                responsibilities.pop(bullet_idx)
            else:
                if not target_id:
                    raise HTTPException(status_code=400, detail="target_id is required for delete")
                idx = next((i for i, item in enumerate(target_list) if getattr(item, "id", None) == target_id), None)
                if idx is None:
                    raise HTTPException(status_code=404, detail=f"Target {target_id} not found in section {section}")
                target_list.pop(idx)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported operation: {operation}")

    content.profile = profile
    update_data: dict[str, Any] = {"content": content.to_dict()}

    new_storage_path, updated_geom, new_docx_path, strategy = _attempt_pdf_mutation_on_operation(
        row=row,
        resume=resume,
        auth=auth,
        version_id=version_id,
        section=section,
        target_id=target_id,
        child_id=body.child_id,
        replacement=replacement,
        child_text=body.child_text,
        content=content,
    )
    # TRUTHFULNESS GATE: an operation is only successful when its content change
    # was turned into a real document artifact. If artifact regeneration failed we
    # must NOT persist the JSON-only update (that is the classic "Suggestion applied
    # to resume" while the PDF stays unchanged failure) and must NOT report success.
    if strategy == "failed":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document artifact regeneration failed. The operation was NOT applied and no content change was persisted.",
        )
    _apply_compiled_artifact(row, resume, content, update_data, new_storage_path, updated_geom, new_docx_path, strategy)

    updated = repo.update_version(version_id, update_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Version not found")
    return SuccessResponse(data=_to_version_response(updated))


def _apply_compiled_artifact(
    row: dict[str, Any],
    resume: dict[str, Any],
    content: Any,
    update_data: dict[str, Any],
    new_storage_path: Any,
    updated_geom: Any,
    new_docx_path: Any,
    strategy: str,
) -> None:
    """Attach compiled artifact paths/geometry + closed-loop ATS score to update_data."""
    if new_storage_path:
        meta = dict(row.get("meta") or {})
        meta["storage_path"] = new_storage_path
        if new_docx_path:
            meta["docx_storage_path"] = new_docx_path
        if updated_geom:
            meta["geometry"] = updated_geom
        meta["compilation_strategy"] = strategy
        update_data["meta"] = meta
        update_data["source"] = strategy or "compiled"

    # Closed-loop ATS re-analysis: if version or resume has job description, recompute score
    jd = row.get("job_description") or resume.get("job_description")
    target_role = row.get("target_job_title") or resume.get("title")
    if jd and jd.strip():
        try:
            from app.services.ats.ats_analyzer import ATSAnalyzer
            analyzer = ATSAnalyzer()
            ats_report = analyzer.analyze_resume(content, jd, job_title=target_role)
            update_data["last_ats_score"] = ats_report.overall_score
            update_data["last_analyzed_at"] = datetime.utcnow().isoformat()
        except Exception as ats_err:
            logger.warning("ATS re-analysis in operation failed: %s", ats_err)


@router.post(
    "/versions/{version_id}/save-content",
    response_model=SuccessResponse[ResumeVersionResponse],
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        400: {"model": ErrorResponse},
    },
)
async def save_version_content(
    version_id: str,
    body: SaveVersionContentRequest,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ResumeVersionResponse]:
    """Manual-editor Save path: full-profile replace + real artifact recompilation.

    Replaces the version's ResumeContent, recompiles PDF/DOCX via the canonical
    compiler, and persists only when the artifact exists in storage. Master
    versions are immutable — callers must derive first. Mirrors the
    apply-operation truthfulness gate: compile failure -> 500, nothing persisted.
    """
    from app.models.resume import ResumeContent

    repo = ResumeRepository(jwt=auth.jwt)
    row = repo.get_version(version_id)
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    if row.get("is_master"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify master version directly. Please create a derived version before saving.",
        )
    resume = repo.get_resume(auth.user.id, row["resume_id"])
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    content = ResumeContent.from_dict(body.content or {})
    update_data: dict[str, Any] = {"content": content.to_dict()}

    geom_map = (row.get("meta") or {}).get("geometry") or (resume.get("meta") or {}).get("geometry")
    try:
        from app.services.resumes.compiler_service import resume_compiler_service

        res = resume_compiler_service.compile_and_persist(
            user_id=auth.user.id,
            version_id=version_id,
            content=content,
            geometry_map=geom_map,
            jwt=auth.jwt,
        )
    except Exception as exc:
        logger.error("Manual save compilation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document artifact regeneration failed. The operation was NOT applied and no content change was persisted.",
        ) from exc

    new_storage_path = res.get("storage_path")
    if not new_storage_path:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document artifact regeneration failed. The operation was NOT applied and no content change was persisted.",
        )
    _apply_compiled_artifact(
        row,
        resume,
        content,
        update_data,
        new_storage_path,
        res.get("geometry"),
        res.get("docx_storage_path"),
        res.get("strategy", "document_compiler"),
    )

    updated = repo.update_version(version_id, update_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Version not found")
    return SuccessResponse(data=_to_version_response(updated))


def _sync_profile_text(
    profile: Any,
    section: Optional[str],
    item_id: Optional[str],
    child_id: Optional[str],
    new_text: str,
) -> None:
    """Synchronize replacement text into the corresponding ResumeProfile structure."""
    from app.models.resume import BulletItem, SkillCategory

    if not section or not new_text:
        return
    sec = section.lower()
    if sec in ("summary", "target_role"):
        setattr(profile, sec, new_text)
        return
    if sec == "skills":
        skills_list = [s.strip() for s in new_text.replace("\n", ",").split(",") if s.strip()]
        if not profile.skills:
            profile.skills = SkillCategory(technical=skills_list)
        else:
            profile.skills.technical = skills_list
        return

    section_map = {
        "experience": profile.experience,
        "internships": profile.internships,
        "projects": profile.projects,
        "education": profile.education,
        "certifications": profile.certifications,
        "achievements": profile.achievements,
        "leadership": profile.leadership,
        "languages": profile.languages,
        "links": profile.links,
        "additional": profile.additional,
    }
    if sec not in section_map:
        return
    items = section_map[sec]
    target_item = None
    if item_id:
        target_item = next((it for it in items if getattr(it, "id", None) == item_id), None)
    if not target_item and items:
        target_item = items[0]

    if target_item:
        if child_id and hasattr(target_item, "responsibilities"):
            b = next((r for r in target_item.responsibilities if getattr(r, "id", None) == child_id), None)
            if b:
                b.text = new_text
            else:
                target_item.responsibilities.append(BulletItem(id=child_id, text=new_text))
        elif hasattr(target_item, "description"):
            target_item.description = new_text
        elif hasattr(target_item, "responsibilities") and target_item.responsibilities:
            target_item.responsibilities[0].text = new_text


def _attempt_pdf_mutation_on_operation(
    row: dict[str, Any],
    resume: dict[str, Any],
    auth: AuthContext,
    version_id: str,
    section: str,
    target_id: Optional[str],
    child_id: Optional[str],
    replacement: Optional[dict[str, Any]],
    child_text: Optional[str],
    content: Optional[ResumeContent] = None,
) -> tuple[Optional[str], Optional[dict[str, Any]], Optional[str], str]:
    """Helper to compile and persist verified PDF and editable DOCX artifacts.

    Chooses between:
      1. Direct PDF Mutation (Pipeline A): for single-block inline modifications
      2. Document Compiler (Pipeline B): for multi-line, reflow, summary, skills, or bullet structural additions
    """
    from app.services.resumes.compiler_service import resume_compiler_service

    if not content:
        return None, None, None, "none"

    source_storage_path = (row.get("meta") or {}).get("storage_path") or resume.get("storage_path")
    geom_map = (row.get("meta") or {}).get("geometry") or (resume.get("meta") or {}).get("geometry")

    curr_text = ""
    suggested_text = ""
    if replacement:
        curr_text = replacement.get("currentText") or replacement.get("current_text") or ""
        suggested_text = (
            replacement.get("suggestedText")
            or replacement.get("suggested_text")
            or replacement.get("text")
            or ""
        )
    if not suggested_text and child_text:
        suggested_text = child_text

    # Search for matching geometry block
    matched_block = None
    if geom_map and isinstance(geom_map, dict):
        pages = geom_map.get("pages", [])
        for p in pages:
            for b in p.get("blocks", []):
                if child_id and b.get("item_id") == child_id:
                    matched_block = b
                    break
                if target_id and b.get("item_id") == target_id:
                    matched_block = b
                    break
                if b.get("section") == section:
                    b_txt = b.get("text", "").lower()
                    if curr_text and curr_text.strip().lower() in b_txt:
                        matched_block = b
                        break
                    if not curr_text and section in ("summary", "target_role"):
                        matched_block = b
                        break
            if matched_block:
                break

    # Decide strategy: Direct mutation only if single bullet/line edit and fits reasonably
    prefer_mutation = False
    mutation_params = None
    if (
        matched_block
        and source_storage_path
        and suggested_text
        and section not in ("summary", "skills")  # Summary and skills require full reflow
    ):
        orig_len = max(1, len(matched_block.get("text", "")))
        new_len = len(suggested_text)
        # Only use direct PDF mutation if text length is comparable (within 30%)
        if abs(new_len - orig_len) / orig_len <= 0.35:
            prefer_mutation = True
            mutation_params = {
                "page_index": matched_block.get("page", 0),
                "bbox": matched_block.get("bbox", []),
                "replacement_text": suggested_text,
                "font_name": matched_block.get("style", {}).get("font_name"),
                "font_size": matched_block.get("style", {}).get("font_size"),
                "is_bold": matched_block.get("style", {}).get("bold", False),
                "is_italic": matched_block.get("style", {}).get("italic", False),
                "text_color": matched_block.get("style", {}).get("color", 0),
            }

    try:
        res = resume_compiler_service.compile_and_persist(
            user_id=auth.user.id,
            version_id=version_id,
            content=content,
            geometry_map=geom_map,
            jwt=auth.jwt,
            prefer_direct_mutation=prefer_mutation,
            mutation_source_path=source_storage_path,
            mutation_params=mutation_params,
        )
        return (
            res.get("storage_path"),
            res.get("geometry"),
            res.get("docx_storage_path"),
            res.get("strategy", "document_compiler"),
        )
    except Exception as exc:
        logger.error("Compiler service failed in operation: %s", exc, exc_info=True)
        return None, None, None, "failed"


@router.post(
    "/{resume_id}/versions/{version_id}/mutate-pdf",
    response_model=SuccessResponse[ResumeVersionResponse],
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def mutate_version_pdf(
    resume_id: str,
    version_id: str,
    body: MutatePdfRequest,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ResumeVersionResponse]:
    """Mutate a PDF version at a specific bounding box or block and create a derived version."""
    from app.models.resume import ResumeContent
    from app.services.resumes.pdf_mutation import PDFMutationEngine
    from app.db.supabase import get_authenticated_client, get_service_client

    repo = ResumeRepository(jwt=auth.jwt)
    resume = repo.get_resume(auth.user.id, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    version = repo.get_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    if version.get("resume_id") != resume_id:
        raise HTTPException(status_code=400, detail="Version does not belong to this resume")

    source_storage_path = (version.get("meta") or {}).get("storage_path") or resume.get("storage_path")
    if not source_storage_path:
        raise HTTPException(status_code=400, detail="No source PDF available for mutation")

    # Fetch PDF bytes from Supabase storage
    try:
        storage_client = get_authenticated_client(auth.jwt)
        pdf_bytes = storage_client.storage.from_("resumes").download(source_storage_path)
    except Exception:
        try:
            storage_client = get_service_client()
            pdf_bytes = storage_client.storage.from_("resumes").download(source_storage_path)
        except Exception as exc:
            logger.error("Failed to download PDF from storage %s: %s", source_storage_path, exc)
            raise HTTPException(status_code=500, detail=f"Failed to download source PDF: {exc}") from exc

    # Run PDFMutationEngine
    version_geom = (version.get("meta") or {}).get("geometry") or (resume.get("meta") or {}).get("geometry")
    try:
        mutated_bytes, updated_geometry = PDFMutationEngine.mutate(
            pdf_bytes=pdf_bytes,
            page_index=body.page_index,
            bbox=body.bbox,
            block_id=body.block_id,
            replacement_text=body.replacement_text,
            geometry_map=version_geom,
            font_name=body.font_name,
            font_size=body.font_size,
            is_bold=body.is_bold,
            is_italic=body.is_italic,
            text_color=body.text_color,
        )
    except Exception as exc:
        logger.error("PDF mutation failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"PDF mutation failed: {exc}") from exc

    # Generate new version id and upload mutated bytes
    new_vid = str(uuid.uuid4())
    target_storage_path = f"{auth.user.id}/versions/{new_vid}.pdf"
    try:
        try:
            storage_client = get_authenticated_client(auth.jwt)
            storage_client.storage.from_("resumes").upload(
                target_storage_path,
                mutated_bytes,
                file_options={"content-type": "application/pdf", "upsert": "true"},
            )
        except Exception:
            storage_client = get_service_client()
            storage_client.storage.from_("resumes").upload(
                target_storage_path,
                mutated_bytes,
                file_options={"content-type": "application/pdf", "upsert": "true"},
            )
    except Exception as exc:
        logger.error("Failed to upload mutated PDF to %s: %s", target_storage_path, exc)
        raise HTTPException(status_code=500, detail=f"Failed to upload mutated PDF: {exc}") from exc

    # Synchronize Profile JSON
    content = ResumeContent.from_dict(version.get("content") or {})
    _sync_profile_text(content.profile, body.section, body.item_id, body.child_id, body.replacement_text)

    # Derive new version row
    new_meta = dict(version.get("meta") or {})
    new_meta["storage_path"] = target_storage_path
    new_meta["geometry"] = updated_geometry
    new_meta["parent_version_id"] = version_id
    new_meta["provenance_source"] = "pdf_edit"

    row = repo.create_version(
        resume_id=resume_id,
        content=content.to_dict(),
        version_name=f"{version.get('version_name', 'Resume')} (Edited)",
        source="pdf_edit",
        is_master=False,
        parent_version_id=version_id,
        target_job_title=version.get("target_job_title"),
        target_company=version.get("target_company"),
        target_job_id=version.get("target_job_id"),
        target_job_url=version.get("target_job_url"),
        job_description=version.get("job_description"),
        template=version.get("template", "minimal"),
        sections_config=version.get("sections_config") or {},
        meta=new_meta,
    )
    return SuccessResponse(data=_to_version_response(row))


@router.post(
    "/{resume_id}/versions/apply-tailoring",
    response_model=SuccessResponse[ResumeVersionResponse],
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def apply_tailoring_version(
    resume_id: str,
    body: ApplyTailoringRequest,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ResumeVersionResponse]:
    """Create a new derived version from tailored profile and compile PDF/DOCX artifacts."""
    from app.models.resume import ResumeContent, ResumeProfile
    from app.services.resumes.compiler_service import resume_compiler_service
    from app.services.ats.ats_analyzer import ATSAnalyzer

    repo = ResumeRepository(jwt=auth.jwt)
    resume = repo.get_resume(auth.user.id, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    parent_version = None
    if body.parent_version_id:
        parent_version = repo.get_version(body.parent_version_id)

    # Reconstruct tailored ResumeContent
    profile_dict = body.tailored_profile
    base_content = (parent_version.get("content") if parent_version else None) or resume.get("content") or {}
    if not profile_dict:
        profile_dict = (base_content.get("profile") if isinstance(base_content, dict) else None) or {}

    # Audit tailored profile against candidate source baseline profile
    from app.services.optimization.numeric_guard import numeric_guard
    source_profile = ResumeProfile.from_dict((base_content.get("profile") if isinstance(base_content, dict) else None) or {})
    audited_dict, guard_issues = numeric_guard.audit_tailored_profile(
        source_profile=source_profile,
        tailored_profile_dict=profile_dict,
    )
    if guard_issues:
        logger.info("NumericFabricationGuard on apply_tailoring detected issues: %s", guard_issues)

    tailored_profile = ResumeProfile.from_dict(audited_dict)
    tailored_content = ResumeContent(profile=tailored_profile)

    # Determine default version name
    v_name = body.version_name
    if not v_name or not v_name.strip():
        role_label = body.job_title or (parent_version.get("target_job_title") if parent_version else None) or "Tailored"
        v_name = f"{role_label} Version ({datetime.utcnow().strftime('%b %d')})"

    geom_map = (
        (parent_version.get("meta") or {}).get("geometry")
        if parent_version
        else (resume.get("meta") or {}).get("geometry")
    )
    new_meta = {
        "provenance_source": "tailoring",
        "parent_version_id": body.parent_version_id,
    }
    if geom_map:
        new_meta["geometry"] = geom_map

    created_row = repo.create_version(
        resume_id=resume_id,
        content=tailored_content.to_dict(),
        version_name=v_name,
        source="tailoring",
        is_master=False,
        parent_version_id=body.parent_version_id,
        target_job_title=body.job_title or (parent_version.get("target_job_title") if parent_version else None),
        target_company=body.company or (parent_version.get("target_company") if parent_version else None),
        job_description=body.job_description or (parent_version.get("job_description") if parent_version else None),
        template=body.template or (parent_version.get("template") if parent_version else "minimal"),
        sections_config=body.sections_config or (parent_version.get("sections_config") if parent_version else {}),
        meta=new_meta,
    )
    version_id = created_row["id"]

    # Compile and persist DOCX & PDF artifacts
    try:
        comp_res = resume_compiler_service.compile_and_persist(
            user_id=auth.user.id,
            version_id=version_id,
            content=tailored_content,
            geometry_map=geom_map,
            jwt=auth.jwt,
        )
    except Exception as exc:
        logger.error("Compilation failed for tailored version %s: %s", version_id, exc, exc_info=True)
        repo.delete_version(version_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document compilation failed for tailored version.",
        ) from exc

    storage_path = comp_res.get("storage_path")
    if not storage_path:
        repo.delete_version(version_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document compilation failed for tailored version (storage path missing).",
        )

    # Calculate closed-loop ATS score if job description is present
    last_ats_score = None
    jd = body.job_description or (parent_version.get("job_description") if parent_version else None)
    target_role = body.job_title or (parent_version.get("target_job_title") if parent_version else None)
    if jd and jd.strip():
        try:
            analyzer = ATSAnalyzer()
            ats_report = analyzer.analyze_resume(tailored_content, jd, job_title=target_role)
            last_ats_score = ats_report.overall_score
        except Exception as ats_exc:
            logger.warning("Closed-loop ATS score calculation failed: %s", ats_exc)

    updated_meta = dict(new_meta)
    updated_meta["storage_path"] = storage_path
    if comp_res.get("docx_storage_path"):
        updated_meta["docx_storage_path"] = comp_res["docx_storage_path"]
    if comp_res.get("geometry"):
        updated_meta["geometry"] = comp_res["geometry"]
    updated_meta["compilation_strategy"] = comp_res.get("strategy", "document_compiler")

    update_payload: dict[str, Any] = {
        "meta": updated_meta,
        "source": comp_res.get("strategy", "document_compiler"),
    }
    if last_ats_score is not None:
        update_payload["last_ats_score"] = last_ats_score
        update_payload["last_analyzed_at"] = datetime.utcnow().isoformat()

    updated_version = repo.update_version(version_id, update_payload)
    if not updated_version:
        raise HTTPException(status_code=404, detail="Version update failed")

    return SuccessResponse(data=_to_version_response(updated_version))


