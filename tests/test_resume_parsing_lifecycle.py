"""Tests for the resume parsing lifecycle: register -> enqueue -> parse -> completed/failed."""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.resume_repository import ResumeRepository
from app.workers.functions import parse_resume_job

# Test PDF with no extractable text (used for failure path)
EMPTY_PDF_CONTENT = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def mock_repo() -> MagicMock:
    repo = MagicMock(spec=ResumeRepository)
    return repo


class TestResumeParsingLifecycle:
    """Verify the full resume parsing lifecycle."""

    def test_parse_resume_job_success(self, tmp_path: Path) -> None:
        """Test that parse_resume_job transitions pending -> completed with content."""
        resume_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        storage_path = f"{user_id}/{uuid.uuid4()}.pdf"

        pdf_path = tmp_path / "test_resume.pdf"
        pdf_path.write_bytes(EMPTY_PDF_CONTENT)

        mock_row = {
            "id": resume_id,
            "user_id": user_id,
            "parse_status": "pending",
            "storage_path": storage_path,
        }

        mock_repo = MagicMock(spec=ResumeRepository)
        mock_repo.get_resume.return_value = mock_row
        mock_repo.create_version.return_value = {"id": str(uuid.uuid4())}

        with patch("app.workers.functions.ResumeRepository", return_value=mock_repo):
            with patch("app.workers.functions.get_service_client") as mock_get_client:
                mock_storage = MagicMock()
                mock_storage.storage.from_.return_value.download.return_value = pdf_path.read_bytes()
                mock_get_client.return_value = mock_storage

                with patch("app.workers.functions.ResumeParsingService") as mock_parser_cls:
                    from app.services.resume_parsing import ParseResult

                    mock_parser = MagicMock()
                    async def mock_parse_file(temp_path, filename):
                        return ParseResult(
                            status="completed",
                            content={"profile": {"personal": {"full_name": "Test User"}}},
                            extracted={"skills_count": 1},
                        )
                    mock_parser.parse_file = mock_parse_file
                    mock_parser_cls.return_value = mock_parser

                    result = asyncio.run(parse_resume_job(
                        ctx={"job_id": "test-job"},
                        resume_id=resume_id,
                        user_id=user_id,
                        storage_path=storage_path,
                    ))

        assert result["success"] is True
        assert result["status"] == "completed"
        mock_repo.update_resume.assert_any_call(
            user_id,
            resume_id,
            {
                "content": {"profile": {"personal": {"full_name": "Test User"}}},
                "meta": {"parse_error": None},
                "parse_status": "completed",
            },
        )
        mock_repo.create_version.assert_called_once()

    def test_parse_resume_job_failure(self, tmp_path: Path) -> None:
        """Test that parse_resume_job transitions pending -> failed on parse error."""
        resume_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        storage_path = f"{user_id}/{uuid.uuid4()}.pdf"

        pdf_path = tmp_path / "bad_resume.pdf"
        pdf_path.write_bytes(b"not a pdf")

        mock_row = {
            "id": resume_id,
            "user_id": user_id,
            "parse_status": "pending",
            "storage_path": storage_path,
        }

        mock_repo = MagicMock(spec=ResumeRepository)
        mock_repo.get_resume.return_value = mock_row

        with patch("app.workers.functions.ResumeRepository", return_value=mock_repo):
            with patch("app.workers.functions.get_service_client") as mock_get_client:
                mock_storage = MagicMock()
                mock_storage.storage.from_.return_value.download.return_value = b"not a pdf"
                mock_get_client.return_value = mock_storage

                with patch("app.workers.functions.ResumeParsingService") as mock_parser_cls:
                    from app.services.resume_parsing import ParseResult

                    mock_parser = MagicMock()
                    async def mock_parse_file(temp_path, filename):
                        return ParseResult(
                            status="failed",
                            content={},
                            extracted={},
                            error="No text content extracted from PDF",
                        )
                    mock_parser.parse_file = mock_parse_file
                    mock_parser_cls.return_value = mock_parser

                    result = asyncio.run(parse_resume_job(
                        ctx={"job_id": "test-job"},
                        resume_id=resume_id,
                        user_id=user_id,
                        storage_path=storage_path,
                    ))

        assert result["success"] is False
        assert result["status"] == "failed"
        mock_repo.update_resume.assert_any_call(
            user_id,
            resume_id,
            {
                "parse_status": "failed",
                "meta": {"parse_error": "No text content extracted from PDF"},
            },
        )

    def test_parse_resume_job_skips_completed(self) -> None:
        """Test that parse_resume_job returns early if already completed."""
        resume_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        storage_path = f"{user_id}/{uuid.uuid4()}.pdf"

        mock_row = {
            "id": resume_id,
            "user_id": user_id,
            "parse_status": "completed",
            "storage_path": storage_path,
        }

        mock_repo = MagicMock(spec=ResumeRepository)
        mock_repo.get_resume.return_value = mock_row

        with patch("app.workers.functions.ResumeRepository", return_value=mock_repo):
            result = asyncio.run(parse_resume_job(
                ctx={"job_id": "test-job"},
                resume_id=resume_id,
                user_id=user_id,
                storage_path=storage_path,
            ))

        assert result["success"] is True
        assert result["status"] == "completed"
        assert result.get("skipped") is True
        mock_repo.update_resume.assert_not_called()

    def test_parse_resume_job_download_failure(self, tmp_path: Path) -> None:
        """Test that parse_resume_job marks failed when storage download fails."""
        resume_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        storage_path = f"{user_id}/{uuid.uuid4()}.pdf"

        mock_row = {
            "id": resume_id,
            "user_id": user_id,
            "parse_status": "pending",
            "storage_path": storage_path,
        }

        mock_repo = MagicMock(spec=ResumeRepository)
        mock_repo.get_resume.return_value = mock_row

        with patch("app.workers.functions.ResumeRepository", return_value=mock_repo):
            with patch("app.workers.functions.get_service_client") as mock_get_client:
                mock_storage = MagicMock()
                mock_storage.storage.from_.return_value.download.side_effect = Exception("Storage error")
                mock_get_client.return_value = mock_storage

                with pytest.raises(Exception, match="Storage error"):
                    asyncio.run(parse_resume_job(
                        ctx={"job_id": "test-job"},
                        resume_id=resume_id,
                        user_id=user_id,
                        storage_path=storage_path,
                    ))

        mock_repo.update_resume.assert_any_call(
            user_id,
            resume_id,
            {
                "parse_status": "failed",
                "meta": {"parse_error": "Failed to download file from storage"},
            },
        )
