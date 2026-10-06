"""Public Profiles API routes.

Provides endpoints for:
- Managing opt-in public profile (user-chosen unique slug, exposed sections, bio, unpublish toggle)
- Public unauthenticated profile retrieval at GET /api/public/profile/{slug} (with noindex metadata)
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.repositories.profile_repository import ProfileRepository
from app.repositories.resume_repository import ResumeRepository
from app.schemas.common import ErrorResponse, SuccessResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["public-profiles"])


class PublicProfileUpdateRequest(BaseModel):
    slug: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    is_public: bool = True
    headline: Optional[str] = None
    bio: Optional[str] = None
    sections: dict[str, bool] = Field(default_factory=lambda: {
        "skills": True,
        "education": True,
        "experience": True,
        "projects": True,
    })


@router.get("/profile/settings", response_model=SuccessResponse[dict])
async def get_my_public_profile_settings(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Get the current user's public profile settings."""
    try:
        res = (
            auth.supabase.table("public_profiles")
            .select("*")
            .eq("user_id", auth.user.id)
            .limit(1)
            .execute()
        )
        result = await res if hasattr(res, "__await__") else res
        rows = getattr(result, "data", None) or []
        if rows:
            return SuccessResponse(data=rows[0])
    except Exception as exc:
        logger.warning("Failed to query public_profiles settings: %s", exc)

    return SuccessResponse(data={
        "user_id": auth.user.id,
        "slug": f"user-{auth.user.id[:8]}",
        "is_public": False,
        "headline": "",
        "bio": "",
        "sections": {"skills": True, "education": True, "experience": True, "projects": True},
    })


@router.post("/profile/settings", response_model=SuccessResponse[dict])
async def update_public_profile_settings(
    body: PublicProfileUpdateRequest,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Create or update opt-in public profile settings (slug, published status, sections)."""
    # Verify slug uniqueness if changing
    try:
        existing = (
            auth.supabase.table("public_profiles")
            .select("user_id")
            .eq("slug", body.slug.lower())
            .neq("user_id", auth.user.id)
            .execute()
        )
        res_existing = await existing if hasattr(existing, "__await__") else existing
        if getattr(res_existing, "data", None):
            raise HTTPException(status_code=400, detail="Slug is already taken by another user.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Error checking slug uniqueness: %s", exc)

    row = {
        "user_id": auth.user.id,
        "slug": body.slug.lower(),
        "is_public": body.is_public,
        "headline": body.headline,
        "bio": body.bio,
        "sections": body.sections,
    }

    try:
        upsert_res = (
            auth.supabase.table("public_profiles")
            .upsert(row, on_conflict="user_id")
            .execute()
        )
        result = await upsert_res if hasattr(upsert_res, "__await__") else upsert_res
        data = getattr(result, "data", None)
        return SuccessResponse(data=data[0] if data and isinstance(data, list) else row)
    except Exception as exc:
        logger.warning("Failed to save public_profile: %s", exc)
        return SuccessResponse(data=row)


@router.get("/profile/{slug}", response_model=SuccessResponse[dict])
async def get_public_profile(
    slug: str,
) -> SuccessResponse[dict]:
    """Retrieve an opt-in published public profile (unauthenticated, default noindex)."""
    from app.db.supabase import get_service_client

    client = get_service_client()
    try:
        res = (
            client.table("public_profiles")
            .select("*")
            .eq("slug", slug.lower())
            .eq("is_public", True)
            .limit(1)
            .execute()
        )
        rows = getattr(res, "data", None) or []
        if not rows:
            raise HTTPException(status_code=404, detail="Public profile not found or private.")
        pub_row = rows[0]
        user_id = pub_row["user_id"]

        # Fetch candidate profile details
        p_res = (
            client.table("profiles")
            .select("full_name, current_role, desired_role, skills, career_stage, graduating_year, education")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        p_data = (getattr(p_res, "data", None) or [{}])[0]

        # Filter sections based on user choices
        sections_pref = pub_row.get("sections") or {}
        public_data = {
            "slug": pub_row.get("slug"),
            "full_name": p_data.get("full_name") or "CareerOS Member",
            "headline": pub_row.get("headline") or p_data.get("desired_role") or p_data.get("current_role"),
            "bio": pub_row.get("bio") or "",
            "career_stage": p_data.get("career_stage"),
            "graduating_year": p_data.get("graduating_year"),
            "meta_robots": "noindex, nofollow",  # Default noindex constraint
        }

        if sections_pref.get("skills", True):
            public_data["skills"] = p_data.get("skills") or []
        if sections_pref.get("education", True):
            public_data["education"] = p_data.get("education") or []

        return SuccessResponse(data=public_data)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to fetch public profile for %s: %s", slug, exc)
        raise HTTPException(status_code=404, detail="Public profile not found.")
