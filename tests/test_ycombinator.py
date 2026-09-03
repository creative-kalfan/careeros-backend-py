"""Tests for Y Combinator jobs adapter."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.crawlers.adapters.ycombinator import YCAdapter, _fnv1a_32, _deterministic_external_id


# --- _fnv1a_32 tests ---


def test_fnv1a_32_deterministic():
    """Same input must always produce the same hash."""
    result = _fnv1a_32("test input")
    assert isinstance(result, str)
    assert len(result) == 8
    # Call again and verify equality
    assert _fnv1a_32("test input") == result


def test_fnv1a_32_different_inputs():
    """Different inputs must produce different hashes (with high probability)."""
    r1 = _fnv1a_32("alpha")
    r2 = _fnv1a_32("beta")
    assert r1 != r2


def test_fnv1a_32_title_company_fallback():
    """Fallback hash when apply_url is None uses title+company."""
    result = _fnv1a_32("Software Engineer" + "Test Company")
    assert isinstance(result, str)
    assert len(result) == 8


# --- _deterministic_external_id tests ---


def test_deterministic_external_id_with_apply_url():
    """When apply_url is provided, ID is derived from apply_url."""
    result = _deterministic_external_id("https://yc.app/job/123", "Engineer", "Startup")
    assert isinstance(result, str)
    assert len(result) == 8


def test_deterministic_external_id_without_apply_url():
    """When apply_url is None, ID is derived from title+company."""
    result = _deterministic_external_id(None, "Engineer", "Startup")
    assert isinstance(result, str)
    assert len(result) == 8


def test_deterministic_external_id_consistency():
    """Same inputs always produce the same ID."""
    r1 = _deterministic_external_id("https://yc.app/job/123", "Engineer", "Startup")
    r2 = _deterministic_external_id("https://yc.app/job/123", "Engineer", "Startup")
    assert r1 == r2


def test_deterministic_external_id_different_urls():
    """Different apply URLs produce different IDs."""
    r1 = _deterministic_external_id("https://yc.app/job/123", "Eng", "Co")
    r2 = _deterministic_external_id("https://yc.app/job/456", "Eng", "Co")
    assert r1 != r2


def test_deterministic_external_id_different_company():
    """Different companies produce different IDs even with same title."""
    r1 = _deterministic_external_id(None, "Eng", "Acme")
    r2 = _deterministic_external_id(None, "Eng", "Beta")
    assert r1 != r2


# --- YCAdapter tests (mocked) ---


@pytest.fixture
def mock_client():
    """Provide a mocked httpx AsyncClient."""
    client = AsyncMock()
    client.get.return_value.status_code = 200
    client.get.return_value.text = "<html><body></body></html>"
    return client


@pytest.fixture
def mock_adapter(mock_client):
    """Provide YCAdapter with mocked client."""
    with patch("app.crawlers.adapters.ycombinator.httpx.AsyncClient", return_value=mock_client):
        adapter = YCAdapter()
        yield adapter


@pytest.mark.asyncio
async def test_yc_adapter_discover_jobs_basic(mock_adapter, mock_client):
    """Test that discover_jobs returns a list of CrawledJob objects."""
    jobs = await mock_adapter.discover_jobs()
    assert isinstance(jobs, list)
    # If the HTML is empty, may return zero jobs — that's acceptable.


@pytest.mark.asyncio
async def test_yc_adapter_discover_jobs_has_identity(mock_adapter):
    """Test that jobs have source_platform and external_job_id set."""
    jobs = await mock_adapter.discover_jobs()
    for job in jobs:
        assert job.source_platform == "ycombinator"
        assert job.external_job_id, f"Job {job.title} missing external_job_id"


@pytest.mark.asyncio
async def test_yc_adapter_source_platform(mock_adapter):
    """All jobs must have source_platform = ycombinator."""
    jobs = await mock_adapter.discover_jobs()
    for job in jobs:
        assert job.source_platform == "ycombinator"


# ---------------------------------------------------------------------------
# Canonical ingestion path tests (JobIngestionService.ingest_ycombinator_jobs)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_ycombinator_jobs_uses_canonical_pipeline():
    """YC ingestion must go through JobIngestionService → normalize → upsert."""
    import asyncio

    from app.crawlers.models import CrawledJob
    from app.services.jobs.job_ingestion_service import JobIngestionService

    sample = CrawledJob(
        title="Senior Engineer",
        company="Acme YC Startup",
        description="Build things",
        apply_url="https://www.ycombinator.com/jobs/abc",
        external_job_id=_deterministic_external_id(
            "https://www.ycombinator.com/jobs/abc", "Senior Engineer", "Acme YC Startup"
        ),
        source_platform="ycombinator",
    )

    with patch(
        "app.services.jobs.job_ingestion_service.JobRepository"
    ) as repo_cls:
        import app.crawlers.adapters.ycombinator

        # Construct INSIDE the patch so the service uses the mocked repository.
        service = JobIngestionService()

        fake_adapter = MagicMock()
        fake_adapter.discover_jobs = AsyncMock(return_value=[sample])
        fake_adapter.__aenter__ = AsyncMock(return_value=fake_adapter)
        fake_adapter.__aexit__ = AsyncMock(return_value=False)

        # The service imports YCAdapter locally; patch it at the source module
        # so the function-local `from ... import YCAdapter` resolves to the fake.
        with patch.object(
            app.crawlers.adapters.ycombinator, "YCAdapter", return_value=fake_adapter
        ), patch.object(
            service.job_service,
            "normalize_and_classify",
            MagicMock(side_effect=lambda j: j),
        ):
            repo_cls.return_value.upsert_jobs.return_value = {
                "discovered": 1, "inserted": 1,
            }

            result = await asyncio.wait_for(
                service.ingest_ycombinator_jobs(), timeout=5
            )

            assert result == {"discovered": 1, "inserted": 1}
            # Normalize ran through the shared JobService, not a duplicate path.
            service.job_service.normalize_and_classify.assert_called_once_with(sample)  # type: ignore[attr-defined]
            # Repository upsert received the crawled jobs (sync call, not awaited).
            repo_cls.return_value.upsert_jobs.assert_called_once()
            args = repo_cls.return_value.upsert_jobs.call_args[0][0]
            assert args == [sample]
            assert args[0].source_platform == "ycombinator"
            assert args[0].external_job_id


@pytest.mark.asyncio
async def test_worker_ycombinator_path_delegates_to_service():
    """The worker's ingest_yc_jobs wrapper must delegate to the canonical method."""
    from app.crawlers.adapters import ycombinator as yc_module

    with patch(
        "app.services.jobs.job_ingestion_service.JobIngestionService"
    ) as svc_cls:
        instance = svc_cls.return_value
        instance.ingest_ycombinator_jobs = AsyncMock(return_value={"discovered": 5})

        result = await yc_module.ingest_yc_jobs()

        assert result == {"discovered": 5}
        instance.ingest_ycombinator_jobs.assert_awaited_once()


def test_ingest_wrapper_has_no_type_ignore_or_direct_repo_access():
    """Guard: the YC wrapper must not bypass the canonical service layer."""
    import inspect

    from app.crawlers.adapters import ycombinator as yc_module

    source = inspect.getsource(yc_module.ingest_yc_jobs)
    assert "type: ignore" not in source
    # Must not touch the repository directly — only via the service method.
    assert "job_repository" not in source


# Run these if invoked directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])