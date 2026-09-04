"""Resume repository: reads and writes resume rows in Supabase."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from app.db.supabase import get_authenticated_client, get_service_client
from app.models.resume import ResumeContent, ResumeMeta, ResumeProfile

logger = logging.getLogger(__name__)

_RESUME_COLUMNS = (
    "id, user_id, title, file_url, original_filename, storage_path, "
    "parse_status, content, meta, created_at, updated_at"
)


class ResumeRepository:
    """Data-access layer for the Supabase ``resumes`` table.

    By default the repository uses the service-role client (bypasses RLS) for
    internal/background work. When a user JWT is supplied — either via the
    ``jwt`` constructor argument or the ``jwt`` parameter on individual methods
    — a *synchronous* RLS-authenticated client is built via
    ``get_authenticated_client(jwt)`` so that every query is scoped to
    ``auth.uid()`` and the user can only touch their own rows.
    """

    def __init__(self, client: Optional[Any] = None, jwt: Optional[str] = None) -> None:
        if jwt:
            self._client = get_authenticated_client(jwt)
        else:
            self._client = client or get_service_client()

    def _get_client(self, jwt: Optional[str] = None) -> Any:
        if jwt:
            return get_authenticated_client(jwt)
        return self._client

    def list_resumes(self, user_id: str) -> list[dict[str, Any]]:
        result = (
            self._client.table("resumes")
            .select(_RESUME_COLUMNS)
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .execute()
        )
        return result.data or []

    def get_resume(self, user_id: str, resume_id: str) -> Optional[dict[str, Any]]:
        try:
            uuid.UUID(str(resume_id))
        except (ValueError, TypeError):
            return None
        result = (
            self._client.table("resumes")
            .select(_RESUME_COLUMNS)
            .eq("user_id", user_id)
            .eq("id", resume_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        row = rows[0] if rows else None
        if not row:
            return row

        # Auto-canonicalize legacy bullet data in resumes.content
        raw_content = row.get("content") or {}
        if raw_content and self._needs_bullet_canonicalization(raw_content):
            from app.models.resume import ResumeContent

            content = ResumeContent.from_dict(raw_content)
            content.canonicalize()
            canonicalized = content.to_dict()
            self.update_resume(user_id, resume_id, {"content": canonicalized})
            row["content"] = canonicalized

        return row

    def find_by_storage_path(
        self, user_id: str, storage_path: str
    ) -> Optional[dict[str, Any]]:
        """Return an existing resume for this user + storage_path, or None.

        Used for idempotency: if registration is retried after success, we
        must NOT create a second resume.
        """
        result = (
            self._client.table("resumes")
            .select(_RESUME_COLUMNS)
            .eq("user_id", user_id)
            .eq("storage_path", storage_path)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None

    def get_by_id(self, resume_id: str, jwt: Optional[str] = None) -> Optional[dict[str, Any]]:
        try:
            uuid.UUID(str(resume_id))
        except (ValueError, TypeError):
            return None
        client = self._get_client(jwt)
        result = (
            client.table("resumes")
            .select(_RESUME_COLUMNS)
            .eq("id", resume_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        row = rows[0] if rows else None
        if not row:
            return row

        # Auto-canonicalize legacy bullet data in resumes.content
        raw_content = row.get("content") or {}
        if raw_content and self._needs_bullet_canonicalization(raw_content):
            from app.models.resume import ResumeContent

            content = ResumeContent.from_dict(raw_content)
            content.canonicalize()
            canonicalized = content.to_dict()
            # Use service-role client for canonicalization write-back
            self._client.table("resumes").update({"content": canonicalized}).eq("id", resume_id).execute()
            row["content"] = canonicalized

        return row

    def create_resume(
        self,
        user_id: str,
        title: str = "Untitled Resume",
        file_url: Optional[str] = None,
        original_filename: Optional[str] = None,
        storage_path: Optional[str] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user_id": user_id,
            "title": title,
            "parse_status": "pending",
        }
        if file_url:
            payload["file_url"] = file_url
        if original_filename:
            payload["original_filename"] = original_filename
        if storage_path:
            payload["storage_path"] = storage_path

        result = (
            self._client.table("resumes")
            .insert(payload)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None

    def update_resume(
        self, user_id: str, resume_id: str, update_data: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        if not update_data:
            return self.get_resume(user_id, resume_id)

        result = (
            self._client.table("resumes")
            .update(update_data)
            .eq("user_id", user_id)
            .eq("id", resume_id)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None

    def delete_resume(self, user_id: str, resume_id: str) -> bool:
        result = (
            self._client.table("resumes")
            .delete()
            .eq("user_id", user_id)
            .eq("id", resume_id)
            .execute()
        )
        return bool(result.data)

    @staticmethod
    def _coerce_version_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if not row:
            return row
        meta = row.get("meta")
        if isinstance(meta, dict) and meta.get("provenance_source"):
            row["source"] = meta["provenance_source"]
        return row

    def create_version(
        self,
        resume_id: str,
        content: dict[str, Any],
        version_name: str = "v1",
        source: str = "manual",
        is_master: bool = False,
        parent_version_id: str | None = None,
        target_job_title: str | None = None,
        target_company: str | None = None,
        target_job_id: str | None = None,
        target_job_url: str | None = None,
        job_description: str | None = None,
        template: str = "minimal",
        sections_config: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta_payload = dict(meta or {})
        payload: dict[str, Any] = {
            "resume_id": resume_id,
            "version_name": version_name,
            "source": source,
            "content": content,
            "is_master": is_master,
            "parent_version_id": parent_version_id,
            "target_job_title": target_job_title,
            "target_company": target_company,
            "target_job_id": target_job_id,
            "target_job_url": target_job_url,
            "job_description": job_description,
            "template": template,
            "sections_config": sections_config or {},
            "meta": meta_payload,
        }
        try:
            result = (
                self._client.table("resume_versions")
                .insert(payload)
                .execute()
            )
        except Exception as exc:
            err_str = str(exc)
            if "resume_versions_source_check" in err_str or "23514" in err_str:
                logger.warning(
                    "DB check constraint rejected source '%s'; falling back to meta.provenance_source",
                    source,
                )
                meta_payload["provenance_source"] = source
                payload["source"] = "manual"
                payload["meta"] = meta_payload
                result = (
                    self._client.table("resume_versions")
                    .insert(payload)
                    .execute()
                )
            else:
                raise

        rows = result.data or []
        if not rows:
            return None
        return self._coerce_version_row(rows[0])

    def get_version(self, version_id: str) -> Optional[dict[str, Any]]:
        result = (
            self._client.table("resume_versions")
            .select("*")
            .eq("id", version_id)
            .single()
            .execute()
        )
        row = result.data
        if not row:
            return row

        # Auto-canonicalize legacy bullet data on first load
        raw_content = row.get("content") or {}
        if raw_content and self._needs_bullet_canonicalization(raw_content):
            from app.models.resume import ResumeContent

            content = ResumeContent.from_dict(raw_content)
            content.canonicalize()
            canonicalized = content.to_dict()
            self.update_version(version_id, {"content": canonicalized})
            row["content"] = canonicalized

        return self._coerce_version_row(row)

    @staticmethod
    def _needs_bullet_canonicalization(raw_content: dict[str, Any]) -> bool:
        """Check if content has legacy list[str] responsibilities that need IDs."""
        from app.models.resume import ResumeContent

        return ResumeContent._has_legacy_bullets(raw_content)

    def list_versions(self, resume_id: str) -> list[dict[str, Any]]:
        try:
            uuid.UUID(str(resume_id))
        except (ValueError, TypeError):
            return []
        result = (
            self._client.table("resume_versions")
            .select("*")
            .eq("resume_id", resume_id)
            .neq("status", "deleted")
            .order("is_master", desc=True)
            .order("created_at", desc=True)
            .execute()
        )
        return [self._coerce_version_row(r) for r in (result.data or [])]

    def update_version(self, version_id: str, update_data: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not update_data:
            return self.get_version(version_id)
        result = (
            self._client.table("resume_versions")
            .update(update_data)
            .eq("id", version_id)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return None
        return self._coerce_version_row(rows[0])

    def delete_version(self, version_id: str) -> bool:
        result = (
            self._client.table("resume_versions")
            .update({"status": "deleted"})
            .eq("id", version_id)
            .execute()
        )
        return bool(result.data)

    def get_master_version(self, resume_id: str) -> Optional[dict[str, Any]]:
        result = (
            self._client.table("resume_versions")
            .select("*")
            .eq("resume_id", resume_id)
            .eq("is_master", True)
            .eq("status", "active")
            .single()
            .execute()
        )
        return self._coerce_version_row(result.data)

    def set_master_version(self, resume_id: str, version_id: str) -> dict[str, Any]:
        """Safely unsets existing master version for a resume and sets the target version as master."""
        self._client.table("resume_versions").update({"is_master": False}).eq("resume_id", resume_id).execute()
        updated = self.update_version(version_id, {"is_master": True})
        if not updated:
            raise ValueError(f"Version {version_id} not found")
        return updated

    def duplicate_version(self, version_id: str, new_name: str | None = None) -> dict[str, Any]:
        source = self.get_version(version_id)
        if not source:
            raise ValueError("Source version not found")
        new_name = new_name or f"Copy of {source.get('version_name', 'Version')}"
        return self.create_version(
            resume_id=source["resume_id"],
            content=source.get("content", {}),
            version_name=new_name,
            source="manual",
            is_master=False,
            target_job_title=source.get("target_job_title"),
            target_company=source.get("target_company"),
            target_job_id=source.get("target_job_id"),
            target_job_url=source.get("target_job_url"),
            job_description=source.get("job_description"),
            template=source.get("template", "minimal"),
            sections_config=source.get("sections_config", {}),
            meta=source.get("meta", {}),
        )
