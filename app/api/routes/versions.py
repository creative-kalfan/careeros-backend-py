"""Resume version API routes (Step 6)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.repositories.resume_repository import ResumeRepository
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.resume import (
    ApplyVersionOperationRequest,
    ResumeVersionCreate,
    ResumeVersionResponse,
    ResumeVersionUpdate,
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
        meta=body.model_dump(exclude_none=True),
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

    # Unset existing master
    repo._client.table("resume_versions").update({"is_master": False}).eq("resume_id", row["resume_id"]).execute()
    # Set new master
    updated = repo.update_version(version_id, {"is_master": True})
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
            suggested = replacement.get("suggestedText") or replacement.get("suggested_text") or ""
            if not suggested:
                raise HTTPException(status_code=400, detail="replacement.suggestedText is required for summary replace")
            setattr(profile, section, suggested)
            content.profile = profile
            updated = repo.update_version(version_id, {"content": content.to_dict()})
            if not updated:
                raise HTTPException(status_code=404, detail="Version not found")
            return SuccessResponse(data=_to_version_response(updated))
        else:
            raise HTTPException(status_code=400, detail=f"Only replace is supported for scalar section: {section}")

    # Handle skills section
    if section == "skills":
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
            content.profile = profile
            updated = repo.update_version(version_id, {"content": content.to_dict()})
            if not updated:
                raise HTTPException(status_code=404, detail="Version not found")
            return SuccessResponse(data=_to_version_response(updated))
        elif operation == "insert":
            new_skill = body.child_text or replacement.get("suggestedText") or replacement.get("suggested_text")
            if isinstance(new_skill, str) and new_skill.strip():
                if not profile.skills:
                    profile.skills = SkillCategory(technical=[new_skill.strip()])
                elif new_skill.strip() not in profile.skills.technical:
                    profile.skills.technical.append(new_skill.strip())
            content.profile = profile
            updated = repo.update_version(version_id, {"content": content.to_dict()})
            if not updated:
                raise HTTPException(status_code=404, detail="Version not found")
            return SuccessResponse(data=_to_version_response(updated))
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported operation: {operation} for skills")

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

        # Child-level targeting: replace a specific bullet within an experience item
        if body.child_id is not None:
            target_item = target_list[idx]
            responsibilities = getattr(target_item, "responsibilities", None)
            if responsibilities is None:
                raise HTTPException(status_code=400, detail=f"Section {section} does not support child targeting")
            bullet_idx = next((i for i, b in enumerate(responsibilities) if getattr(b, "id", None) == body.child_id), None)
            if bullet_idx is None:
                raise HTTPException(status_code=404, detail=f"Bullet {body.child_id} not found in item {target_id}")
            new_text = body.child_text or replacement.get("suggestedText") or replacement.get("suggested_text") or ""
            if not new_text:
                raise HTTPException(status_code=400, detail="child_text or replacement.suggestedText is required for bullet replace")
            responsibilities[bullet_idx] = BulletItem(id=body.child_id, text=new_text)
        else:
            item = target_list[idx]
            if hasattr(item, "model_copy"):
                target_list[idx] = item.model_copy(update=replacement)
            elif isinstance(item, dict):
                updated_item = dict(item)
                updated_item.update(replacement)
                target_list[idx] = updated_item
            else:
                updated_item = dict(item)
                updated_item.update(replacement)
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
            new_item.setdefault("id", str(__import__("uuid").uuid4()).hex[:12])
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
    updated = repo.update_version(version_id, {"content": content.to_dict()})
    if not updated:
        raise HTTPException(status_code=404, detail="Version not found")
    return SuccessResponse(data=_to_version_response(updated))
