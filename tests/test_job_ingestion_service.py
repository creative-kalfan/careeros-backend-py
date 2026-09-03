"""Tests for the job ingestion service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.models.job import NormalizedJob
from app.services.jobs.job_ingestion_service import JobIngestionService


@pytest.fixture
def ingestion_service() -> JobIngestionService:
    """Return a JobIngestionService with mocked repository and job service."""
    service = JobIngestionService()
    service.job_repository = MagicMock()
    service.job_repository.upsert_jobs.return_value = {"inserted": 1, "updated": 0}
    service.job_service = MagicMock()
    return service


def _make_normalized_job(title: str = "Software Engineer") -> NormalizedJob:
    """Create a minimal NormalizedJob for testing."""
    return NormalizedJob(
        id=f"job-{title.lower().replace(' ', '-')}",
        title=title,
        company="Test Company",
        location="Remote",
        description="A test job description.",
        url="https://example.com/job",
        source="test",
        source_id=f"src-{title.lower().replace(' ', '-')}",
        employment_type="full_time",
        seniority_level="mid",
        role_category="engineering",
        posted_at="2026-01-01T00:00:00Z",
        deadline=None,
        salary_min=None,
        salary_max=None,
        currency=None,
        is_remote=True,
        is_active=True,
        skills=[],
        raw_data={},
    )


@pytest.mark.asyncio
async def test_ingest_ashby_jobs(ingestion_service: JobIngestionService) -> None:
    """Test ingesting jobs from Ashby."""
    mock_job = _make_normalized_job("Product Designer")
    ingestion_service.job_service.normalize_and_classify.return_value = mock_job

    mock_adapter = AsyncMock()
    mock_adapter.discover_jobs.return_value = [MagicMock(), MagicMock()]

    with patch(
        "app.services.jobs.job_ingestion_service.AshbyAdapter",
        return_value=mock_adapter,
    ) as mock_ashby_cls:
        result = await ingestion_service.ingest_ashby_jobs("notion")

    mock_ashby_cls.assert_called_once_with("notion")
    mock_adapter.discover_jobs.assert_awaited_once()
    assert ingestion_service.job_service.normalize_and_classify.call_count == 2
    ingestion_service.job_repository.upsert_jobs.assert_called_once()
    assert result == {"inserted": 1, "updated": 0}


@pytest.mark.asyncio
async def test_ingest_adzuna_jobs(ingestion_service: JobIngestionService) -> None:
    """Test ingesting jobs from Adzuna."""
    mock_job = _make_normalized_job("Backend Engineer")
    ingestion_service.job_service.normalize_and_classify.return_value = mock_job

    mock_adapter = AsyncMock()
    mock_adapter.search_by_query.return_value = [MagicMock(), MagicMock(), MagicMock()]

    with patch(
        "app.services.jobs.job_ingestion_service.AdzunaAdapter",
        return_value=mock_adapter,
    ) as mock_adzuna_cls:
        result = await ingestion_service.ingest_adzuna_jobs("software engineer")

    mock_adzuna_cls.assert_called_once_with()
    # New behavior: ADZUNA_BATCH_SIZE=8 broad queries × 3 countries + 3 primary searches = 27 calls
    # Each returns 3 jobs, so 27 × 3 = 81 total crawled jobs → 81 normalizations
    assert mock_adapter.search_by_query.await_count == 27
    assert ingestion_service.job_service.normalize_and_classify.call_count == 81
    ingestion_service.job_repository.upsert_jobs.assert_called_once()
    assert result == {"inserted": 1, "updated": 0}


@pytest.mark.asyncio
async def test_ingest_all(ingestion_service: JobIngestionService) -> None:
    """Test ingesting from all sources."""
    mock_job = _make_normalized_job("Full Stack Engineer")
    ingestion_service.job_service.normalize_and_classify.return_value = mock_job

    mock_ashby_adapter = AsyncMock()
    mock_ashby_adapter.discover_jobs.return_value = [MagicMock()]

    mock_greenhouse_adapter = AsyncMock()
    mock_greenhouse_adapter.discover_jobs.return_value = [MagicMock()]

    mock_smartrecruiters_adapter = AsyncMock()
    mock_smartrecruiters_adapter.discover_jobs.return_value = [MagicMock()]

    mock_lever_adapter = AsyncMock()
    mock_lever_adapter.discover_jobs.return_value = [MagicMock()]

    mock_adzuna_adapter = AsyncMock()
    mock_adzuna_adapter.search_by_query.return_value = [MagicMock(), MagicMock()]

    with patch(
        "app.services.jobs.job_ingestion_service.AshbyAdapter",
        return_value=mock_ashby_adapter,
    ) as mock_ashby_cls:
        with patch(
            "app.services.jobs.job_ingestion_service.GreenhouseAdapter",
            return_value=mock_greenhouse_adapter,
        ) as mock_greenhouse_cls:
            with patch(
                "app.services.jobs.job_ingestion_service.SmartRecruitersAdapter",
                return_value=mock_smartrecruiters_adapter,
            ) as mock_smartrecruiters_cls:
                with patch(
                    "app.services.jobs.job_ingestion_service.LeverAdapter",
                    return_value=mock_lever_adapter,
                ) as mock_lever_cls:
                    with patch(
                        "app.services.jobs.job_ingestion_service.AdzunaAdapter",
                        return_value=mock_adzuna_adapter,
                    ) as mock_adzuna_cls:
                        result = await ingestion_service.ingest_all()

    mock_ashby_cls.assert_called_once_with("notion")
    mock_greenhouse_cls.assert_called_once_with("stripe")
    # SmartRecruiters is called for both servicenow and visa
    assert mock_smartrecruiters_cls.call_count == 2
    mock_smartrecruiters_cls.assert_any_call("servicenow")
    mock_smartrecruiters_cls.assert_any_call("visa")
    mock_lever_cls.assert_called_once_with("coupa")
    mock_adzuna_cls.assert_called_once_with()
    mock_ashby_adapter.discover_jobs.assert_awaited_once()
    mock_greenhouse_adapter.discover_jobs.assert_awaited_once()
    assert mock_smartrecruiters_adapter.discover_jobs.await_count == 2
    mock_lever_adapter.discover_jobs.assert_awaited_once()
    # Adzuna: primary query + extra_queries
    assert mock_adzuna_adapter.search_by_query.await_count > 0

    # 1 ashby + 1 greenhouse + 2 smartrecruiters + 1 lever + 1 adzuna = 6 upsert calls
    assert ingestion_service.job_repository.upsert_jobs.call_count == 6

    assert result == {
        "ashby": {"inserted": 1, "updated": 0},
        "greenhouse": {"inserted": 1, "updated": 0},
        "smartrecruiters": {"inserted": 1, "updated": 0},
        "lever": {"inserted": 1, "updated": 0},
        "adzuna": {"inserted": 1, "updated": 0},
        "smartrecruiters_visa": {"inserted": 1, "updated": 0},
    }