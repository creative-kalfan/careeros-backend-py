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
    MutatePdfRequest,
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

    new_storage_path, updated_geom = _attempt_pdf_mutation_on_operation(
        row=row,
        resume=resume,
        auth=auth,
        section=section,
        target_id=target_id,
        child_id=body.child_id,
        replacement=replacement,
        child_text=body.child_text,
    )
    if new_storage_path and updated_geom:
        meta = dict(row.get("meta") or {})
        meta["storage_path"] = new_storage_path
        meta["geometry"] = updated_geom
        update_data["meta"] = meta
        update_data["source"] = "pdf_edit"

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
    section: str,
    target_id: Optional[str],
    child_id: Optional[str],
    replacement: Optional[dict[str, Any]],
    child_text: Optional[str],
) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    """Helper to synchronously mutate PDF and upload when storage_path and geometry exist."""
    from app.services.resumes.pdf_mutation import PDFMutationEngine
    from app.db.supabase import get_authenticated_client, get_service_client

    source_storage_path = (row.get("meta") or {}).get("storage_path") or resume.get("storage_path")
    geom_map = (row.get("meta") or {}).get("geometry") or (resume.get("meta") or {}).get("geometry")

    if not source_storage_path or not geom_map:
        return None, None

    try:
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

        if not suggested_text:
            return None, None

        # Search for matching block
        matched_block = None
        pages = geom_map.get("pages", []) if isinstance(geom_map, dict) else []
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

        if not matched_block:
            return None, None

        # Download PDF bytes
        try:
            storage_client = get_authenticated_client(auth.jwt)
            pdf_bytes = storage_client.storage.from_("resumes").download(source_storage_path)
        except Exception:
            storage_client = get_service_client()
            pdf_bytes = storage_client.storage.from_("resumes").download(source_storage_path)

        mutated_bytes, updated_geom = PDFMutationEngine.mutate(
            pdf_bytes=pdf_bytes,
            page_index=matched_block.get("page", 0),
            bbox=matched_block.get("bbox"),
            replacement_text=suggested_text,
            font_name=matched_block.get("style", {}).get("font_name"),
            font_size=matched_block.get("style", {}).get("font_size"),
            is_bold=matched_block.get("style", {}).get("bold", False),
            is_italic=matched_block.get("style", {}).get("italic", False),
            text_color=matched_block.get("style", {}).get("color", 0),
        )

        new_vid = str(uuid.uuid4())
        new_storage_path = f"{auth.user.id}/versions/{new_vid}.pdf"
        try:
            storage_client = get_authenticated_client(auth.jwt)
            storage_client.storage.from_("resumes").upload(
                new_storage_path,
                mutated_bytes,
                file_options={"content-type": "application/pdf", "upsert": "true"},
            )
        except Exception:
            storage_client = get_service_client()
            storage_client.storage.from_("resumes").upload(
                new_storage_path,
                mutated_bytes,
                file_options={"content-type": "application/pdf", "upsert": "true"},
            )
        return new_storage_path, updated_geom
    except Exception as exc:
        logger.warning("PDF mutation in operation skipped/failed: %s", exc)
        return None, None


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

