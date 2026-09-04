"""Security, authorization, and export fallback tests for Resume Studio Phase 2-5."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.auth.service import AuthContext, AuthUser
from app.dependencies import get_current_user
from app.main import app


class TestSecurityPDFMutation:
    """Validates authorization, user isolation, and security on mutate-pdf endpoint."""

    def test_unauthenticated_mutate_pdf_returns_401(self) -> None:
        client = TestClient(app)
        app.dependency_overrides.pop(get_current_user, None)

        response = client.post(
            "/api/resumes/res-123/versions/ver-456/mutate-pdf",
            json={
                "replacement_text": "Hacked",
                "bbox": [50, 50, 200, 100],
            },
        )
        assert response.status_code in (401, 403)

    def test_user_cannot_mutate_another_users_resume(self) -> None:
        """User A attempts to mutate a resume owned by User B."""
        client = TestClient(app)
        mock_repo = MagicMock()
        # Resume not found under attacker-user-id
        mock_repo.return_value.get_resume.return_value = None

        mock_auth = AuthContext(
            user=AuthUser(id="attacker-user-id", email="attacker@example.com"),
            supabase=MagicMock(),
            jwt="attacker-jwt",
        )

        app.dependency_overrides[get_current_user] = lambda: mock_auth
        try:
            with patch("app.api.routes.versions.ResumeRepository", mock_repo):
                response = client.post(
                    "/api/resumes/victim-resume-id/versions/ver-1/mutate-pdf",
                    json={
                        "replacement_text": "Injected text",
                        "bbox": [50, 50, 200, 100],
                    },
                )
                assert response.status_code == 404
                data = response.json()
                msg = data.get("error", {}).get("message") or data.get("detail", "")
                assert "Resume not found" in msg
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_mismatched_version_id_rejected(self) -> None:
        """Version belongs to a different resume ID."""
        client = TestClient(app)
        mock_repo = MagicMock()
        mock_repo.return_value.get_resume.return_value = {
            "id": "resume-1",
            "user_id": "user-1",
        }
        mock_repo.return_value.get_version.return_value = {
            "id": "ver-2",
            "resume_id": "other-resume-id",  # Mismatched!
        }

        mock_auth = AuthContext(
            user=AuthUser(id="user-1", email="user1@example.com"),
            supabase=MagicMock(),
            jwt="user-jwt",
        )

        app.dependency_overrides[get_current_user] = lambda: mock_auth
        try:
            with patch("app.api.routes.versions.ResumeRepository", mock_repo):
                response = client.post(
                    "/api/resumes/resume-1/versions/ver-2/mutate-pdf",
                    json={
                        "replacement_text": "Updated text",
                        "bbox": [50, 50, 200, 100],
                    },
                )
                assert response.status_code == 400
                data = response.json()
                msg = data.get("error", {}).get("message") or data.get("detail", "")
                assert "Version does not belong to this resume" in msg
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_mutate_pdf_fails_gracefully_when_storage_path_missing(self) -> None:
        """If neither version meta nor resume has storage_path, return 400."""
        client = TestClient(app)
        mock_repo = MagicMock()
        mock_repo.return_value.get_resume.return_value = {
            "id": "resume-1",
            "user_id": "user-1",
            "storage_path": None,
        }
        mock_repo.return_value.get_version.return_value = {
            "id": "ver-1",
            "resume_id": "resume-1",
            "meta": {},  # no storage_path
        }

        mock_auth = AuthContext(
            user=AuthUser(id="user-1", email="user1@example.com"),
            supabase=MagicMock(),
            jwt="user-jwt",
        )

        app.dependency_overrides[get_current_user] = lambda: mock_auth
        try:
            with patch("app.api.routes.versions.ResumeRepository", mock_repo):
                response = client.post(
                    "/api/resumes/resume-1/versions/ver-1/mutate-pdf",
                    json={
                        "replacement_text": "Updated text",
                        "bbox": [50, 50, 200, 100],
                    },
                )
                assert response.status_code == 400
                data = response.json()
                msg = data.get("error", {}).get("message") or data.get("detail", "")
                assert "No source PDF available" in msg
        finally:
            app.dependency_overrides.pop(get_current_user, None)


class TestExportFallbackAndSecurity:
    """Validates export endpoints for security and safe template fallback when storage_path is absent."""

    def test_export_pdf_unauthenticated_returns_401(self) -> None:
        client = TestClient(app)
        app.dependency_overrides.pop(get_current_user, None)

        response = client.get("/api/export/resumes/res-1/versions/ver-1/pdf")
        assert response.status_code in (401, 403)

    def test_export_pdf_user_isolation(self) -> None:
        client = TestClient(app)
        mock_repo = MagicMock()
        mock_repo.return_value.get_resume.return_value = None  # user doesn't own resume

        mock_auth = AuthContext(
            user=AuthUser(id="attacker-id", email="attacker@example.com"),
            supabase=MagicMock(),
            jwt="attacker-jwt",
        )

        app.dependency_overrides[get_current_user] = lambda: mock_auth
        try:
            with patch("app.api.routes.export.ResumeRepository", mock_repo):
                response = client.get("/api/export/resumes/victim-res/versions/ver-1/pdf")
                assert response.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_export_pdf_falls_back_to_template_when_storage_path_missing(self) -> None:
        """When storage_path is None, export_version_pdf falls back to export_service.export_pdf."""
        client = TestClient(app)
        mock_repo = MagicMock()
        mock_repo.return_value.get_resume.return_value = {
            "id": "res-1",
            "user_id": "user-1",
            "title": "Alex Resume",
            "storage_path": None,
        }
        mock_repo.return_value.get_version.return_value = {
            "id": "ver-1",
            "resume_id": "res-1",
            "version_name": "Version 1",
            "content": {
                "profile": {
                    "basics": {
                        "name": "Alex Morgan",
                        "headline": "Senior Software Engineer",
                        "email": "alex@example.com",
                    }
                }
            },
            "template": "modern",
            "meta": {},  # No storage_path
        }

        mock_auth = AuthContext(
            user=AuthUser(id="user-1", email="user@example.com"),
            supabase=MagicMock(),
            jwt="valid-jwt",
        )

        fake_generated_pdf = b"%PDF-1.4 Fake Generated PDF Content"

        app.dependency_overrides[get_current_user] = lambda: mock_auth
        try:
            with patch("app.api.routes.export.ResumeRepository", mock_repo), patch(
                "app.api.routes.export.export_service.export_pdf", return_value=fake_generated_pdf
            ) as mock_export_pdf:
                response = client.get("/api/export/resumes/res-1/versions/ver-1/pdf")
                assert response.status_code == 200
                assert response.content == fake_generated_pdf
                assert response.headers["content-type"] == "application/pdf"
                mock_export_pdf.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_export_pdf_falls_back_when_storage_download_fails(self) -> None:
        """When storage_path is present but download throws, falls back to export_service.export_pdf."""
        client = TestClient(app)
        mock_repo = MagicMock()
        mock_repo.return_value.get_resume.return_value = {
            "id": "res-1",
            "user_id": "user-1",
            "title": "Alex Resume",
            "storage_path": "user-1/deleted_file.pdf",
        }
        mock_repo.return_value.get_version.return_value = {
            "id": "ver-1",
            "resume_id": "res-1",
            "version_name": "Version 1",
            "content": {
                "profile": {"basics": {"name": "Alex Morgan"}}
            },
            "template": "minimal",
            "meta": {"storage_path": "user-1/deleted_file.pdf"},
        }

        mock_auth = AuthContext(
            user=AuthUser(id="user-1", email="user@example.com"),
            supabase=MagicMock(),
            jwt="valid-jwt",
        )

        fake_generated_pdf = b"%PDF-1.4 Fallback Generated PDF"
        mock_storage = MagicMock()
        mock_storage.storage.from_.return_value.download.side_effect = Exception("Storage file not found (404)")

        app.dependency_overrides[get_current_user] = lambda: mock_auth
        try:
            with patch("app.api.routes.export.ResumeRepository", mock_repo), patch(
                "app.db.supabase.get_authenticated_client", return_value=mock_storage
            ), patch(
                "app.db.supabase.get_service_client", return_value=mock_storage
            ), patch(
                "app.api.routes.export.export_service.export_pdf", return_value=fake_generated_pdf
            ) as mock_export_pdf:
                response = client.get("/api/export/resumes/res-1/versions/ver-1/pdf")
                assert response.status_code == 200
                assert response.content == fake_generated_pdf
                mock_export_pdf.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_current_user, None)
