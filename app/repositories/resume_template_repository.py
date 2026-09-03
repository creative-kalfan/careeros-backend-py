"""Resume template repository: reads and writes resume template rows in Supabase."""

from __future__ import annotations

from typing import Any, Optional

from app.db.supabase import get_service_client
from app.models.resume_template import ResumeTemplate

_TEMPLATE_COLUMNS = (
    "id, slug, name, description, source_repository, source_url, author, "
    "license, license_url, attribution_required, modification_allowed, "
    "redistribution_allowed, layout_type, column_count, page_preference, "
    "ats_characteristics, target_roles, target_industries, target_experience_levels, "
    "evidence_type, evidence_description, preview_url, template_path, status, "
    "created_at, updated_at"
)


class ResumeTemplateRepository:
    """Data-access layer for the Supabase ``resume_templates`` table."""

    def __init__(self, client: Optional[Any] = None) -> None:
        self._client = client or get_service_client()

    def list_templates(self, status: str = "active") -> list[dict[str, Any]]:
        result = (
            self._client.table("resume_templates")
            .select(_TEMPLATE_COLUMNS)
            .eq("status", status)
            .order("name")
            .execute()
        )
        return result.data or []

    def get_template_by_slug(self, slug: str) -> Optional[dict[str, Any]]:
        result = (
            self._client.table("resume_templates")
            .select(_TEMPLATE_COLUMNS)
            .eq("slug", slug)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None

    def get_template_by_id(self, template_id: str) -> Optional[dict[str, Any]]:
        result = (
            self._client.table("resume_templates")
            .select(_TEMPLATE_COLUMNS)
            .eq("id", template_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None

    def create_template(self, data: dict[str, Any]) -> dict[str, Any]:
        result = (
            self._client.table("resume_templates")
            .insert(data)
            .select(_TEMPLATE_COLUMNS)
            .single()
            .execute()
        )
        return result.data

    def update_template(self, template_id: str, data: dict[str, Any]) -> Optional[dict[str, Any]]:
        result = (
            self._client.table("resume_templates")
            .update(data)
            .eq("id", template_id)
            .select(_TEMPLATE_COLUMNS)
            .single()
            .execute()
        )
        return result.data

    def delete_template(self, template_id: str) -> bool:
        result = (
            self._client.table("resume_templates")
            .delete()
            .eq("id", template_id)
            .execute()
        )
        return bool(result.data)
