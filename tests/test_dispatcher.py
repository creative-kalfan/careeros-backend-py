"""Tests for the CareerOS background-job dispatcher and registry."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.dispatcher import enqueue, enqueue_crawl_company, enqueue_resume_parse
from app.workers.registry import JobDefinition, clear_registry, get_job_definition, get_registered_jobs, register_job


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    clear_registry()
    # Force re-execution of module code to trigger @register_job decorators
    # after clearing the registry.
    import importlib

    from app.workers import functions
    from app.workers.jobs import crawl_jobs

    importlib.reload(functions)
    importlib.reload(crawl_jobs)
    yield
    clear_registry()


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_register_and_retrieve(self) -> None:
        @register_job("test_job", timeout=60, max_tries=1, retry=False, description="Test job")
        async def _test_job(ctx: dict[str, Any]) -> dict[str, str]:
            return {"status": "ok"}

        definition = get_job_definition("test_job")
        assert definition.name == "test_job"
        assert definition.timeout == 60
        assert definition.max_tries == 1
        assert definition.retry is False
        assert definition.description == "Test job"

    def test_get_registered_jobs(self) -> None:
        @register_job("job_a", timeout=10)
        async def _job_a(ctx: dict[str, Any]) -> dict[str, str]:
            return {}

        @register_job("job_b", timeout=20)
        async def _job_b(ctx: dict[str, Any]) -> dict[str, str]:
            return {}

        jobs = get_registered_jobs()
        names = {j.name for j in jobs}
        assert "job_a" in names
        assert "job_b" in names

    def test_unknown_job_raises(self) -> None:
        with pytest.raises(KeyError, match="Unknown job: nonexistent"):
            get_job_definition("nonexistent")

    def test_registry_imports_register_known_jobs(self) -> None:
        """Verify that importing the worker modules registers all expected jobs."""
        import importlib

        from app.workers import functions
        from app.workers.jobs import crawl_jobs

        # Force re-execution of module code to trigger @register_job decorators
        # after the autouse fixture cleared the registry.
        importlib.reload(functions)
        importlib.reload(crawl_jobs)

        jobs = get_registered_jobs()
        names = {j.name for j in jobs}
        assert "careeros_worker_health" in names
        assert "parse_resume_job" in names
        assert "crawl_company_job" in names


# ---------------------------------------------------------------------------
# Dispatcher tests
# ---------------------------------------------------------------------------

class TestDispatcher:
    @pytest.mark.asyncio
    async def test_enqueue_unknown_job_raises(self) -> None:
        with pytest.raises(KeyError, match="Unknown job: nonexistent"):
            await enqueue("nonexistent")

    @pytest.mark.asyncio
    async def test_enqueue_returns_job_id(self) -> None:
        mock_job = MagicMock()
        mock_job.job_id = "test-job-id-123"

        mock_redis = AsyncMock()
        mock_redis.enqueue_job = AsyncMock(return_value=mock_job)
        mock_redis.aclose = AsyncMock()

        with patch("app.workers.dispatcher._get_redis", return_value=mock_redis):
            job_id = await enqueue("careeros_worker_health")
            assert job_id == "test-job-id-123"

    @pytest.mark.asyncio
    async def test_enqueue_none_returns_none(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.enqueue_job = AsyncMock(return_value=None)
        mock_redis.aclose = AsyncMock()

        with patch("app.workers.dispatcher._get_redis", return_value=mock_redis):
            job_id = await enqueue("careeros_worker_health")
            assert job_id is None

    @pytest.mark.asyncio
    async def test_enqueue_resume_parse_helper(self) -> None:
        mock_job = MagicMock()
        mock_job.job_id = "resume-job-id"

        mock_redis = AsyncMock()
        mock_redis.enqueue_job = AsyncMock(return_value=mock_job)
        mock_redis.aclose = AsyncMock()

        with patch("app.workers.dispatcher._get_redis", return_value=mock_redis):
            job_id = await enqueue_resume_parse("resume-123", "user-456", "path/to/file.pdf")
            assert job_id == "resume-job-id"
            mock_redis.enqueue_job.assert_called_once_with(
                "parse_resume_job", "resume-123", "user-456", "path/to/file.pdf"
            )

    @pytest.mark.asyncio
    async def test_enqueue_crawl_company_with_lock(self) -> None:
        mock_job = MagicMock()
        mock_job.job_id = "crawl-job-id"

        mock_redis = AsyncMock()
        mock_redis.enqueue_job = AsyncMock(return_value=mock_job)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        with patch("app.workers.dispatcher._get_redis", return_value=mock_redis):
            job_id = await enqueue_crawl_company("greenhouse", "stripe")
            assert job_id == "crawl-job-id"
            mock_redis.set.assert_called_once()
            mock_redis.enqueue_job.assert_called_once_with("crawl_company_job", "greenhouse", "stripe")

    @pytest.mark.asyncio
    async def test_enqueue_crawl_company_lock_held(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=False)
        mock_redis.aclose = AsyncMock()

        with patch("app.workers.dispatcher._get_redis", return_value=mock_redis):
            job_id = await enqueue_crawl_company("greenhouse", "stripe")
            assert job_id is None
            mock_redis.enqueue_job.assert_not_called()
