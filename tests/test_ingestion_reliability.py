"""Focused tests for ingestion reliability.

Covers: race-safe upsert fallback (duplicate-key -> update), stale-source
deactivation semantics, the adzuna crawl branch, and JobIngested event
publication on successful crawls only.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from postgrest.exceptions import APIError

from app.models.job import NormalizedJob
from app.repositories.job_repository import JobRepository

DUPLICATE_KEY_ERROR = APIError(
    {"message": "duplicate key value violates unique constraint", "code": "23505"}
)


def _make_client() -> MagicMock:
    """Chained-mock Supabase client: every builder method returns itself."""
    client = MagicMock()
    client.table.return_value = client
    for method in (
        "select", "eq", "lt", "update", "insert", "neq", "gte", "lte",
        "ilike", "order", "range", "delete", "upsert", "in_", "or_",
    ):
        setattr(client, method, MagicMock(return_value=client))
    return client


def _make_job(external_id: str = "ext-1", source: str = "ashby") -> NormalizedJob:
    return NormalizedJob(
        title="Engineer",
        company="Co",
        external_job_id=external_id,
        source_platform=source,
    )


class TestUpsertRaceFallback:
    def test_duplicate_key_insert_falls_back_to_update(self) -> None:
        client = _make_client()
        repo = JobRepository(client)
        repo._has_last_seen_at = False

        # Independent update chain so poisoning insert().execute() (shared
        # mock in _make_client) does not affect the fallback update path.
        update_chain = MagicMock()
        client.update = MagicMock(return_value=update_chain)

        winner = {"id": "winner-id", "external_job_id": "ext-1", "source_platform": "ashby"}
        client.insert.return_value.execute.side_effect = DUPLICATE_KEY_ERROR

        with patch.object(
            JobRepository, "_find_by_identity", side_effect=[[], [winner]]
        ) as find_mock:
            result = repo.upsert_jobs([_make_job()])

        # First lookup: no row -> insert -> duplicate key -> second lookup finds winner.
        assert find_mock.call_count == 2
        assert result["updated"] == 1
        assert result["inserted"] == 0
        assert result["deduplicated"] == 0
        # Update targeted the winning row id.
        update_chain.eq.assert_called_once_with("id", "winner-id")

    def test_race_without_winning_row_counts_deduplicated(self) -> None:
        client = _make_client()
        repo = JobRepository(client)
        repo._has_last_seen_at = False
        client.insert.return_value.execute.side_effect = DUPLICATE_KEY_ERROR

        with patch.object(JobRepository, "_find_by_identity", side_effect=[[], []]):
            result = repo.upsert_jobs([_make_job()])

        assert result["deduplicated"] == 1
        assert result["inserted"] == 0

    def test_non_duplicate_api_error_reraises(self) -> None:
        client = _make_client()
        repo = JobRepository(client)
        repo._has_last_seen_at = False
        client.insert.return_value.execute.side_effect = APIError(
            {"message": "connection reset", "code": "0"}
        )

        with patch.object(JobRepository, "_find_by_identity", return_value=[]), pytest.raises(APIError):
            repo.upsert_jobs([_make_job()])


class TestDeactivateStaleJobs:
    def test_no_last_seen_column_returns_zero(self) -> None:
        client = _make_client()
        repo = JobRepository(client)
        repo._has_last_seen_at = False
        assert repo.deactivate_stale_jobs(source_platform="ashby") == 0

    def test_deactivates_scoped_to_source(self) -> None:
        client = _make_client()
        repo = JobRepository(client)
        repo._has_last_seen_at = True
        client.execute.return_value = MagicMock(data=[{"id": "a", "posted_at": "2025-01-01T00:00:00Z"}, {"id": "b", "posted_at": "2025-01-15T00:00:00Z"}])

        count = repo.deactivate_stale_jobs(source_platform="ashby", max_age_days=30)

        assert count == 2

    def test_unscoped_deactivation_when_no_source(self) -> None:
        client = _make_client()
        repo = JobRepository(client)
        repo._has_last_seen_at = True
        client.execute.return_value = MagicMock(data=[{"id": "x", "posted_at": "2024-01-01T00:00:00Z"}])

        count = repo.deactivate_stale_jobs(max_age_days=15)

        assert count == 1
        for c in client.eq.call_args_list:
            assert c.args[0] != "source_platform"

    def test_api_error_swallowed_returns_zero(self) -> None:
        client = _make_client()
        repo = JobRepository(client)
        repo._has_last_seen_at = True
        client.execute.side_effect = APIError({"message": "boom", "code": "500"})

        assert repo.deactivate_stale_jobs(source_platform="ashby") == 0


class TestCrawlJobReliability:
    def _patched_ingestion(self, ingest_result: dict[str, int]) -> MagicMock:
        ingestion = MagicMock()
        ingestion.ingest_adzuna_jobs = AsyncMock(return_value=ingest_result)
        ingestion.job_repository.deactivate_stale_jobs.return_value = 1
        ingestion.job_repository.deactivate_not_seen_since.return_value = 0
        return ingestion

    def test_adzuna_branch_ingests_and_publishes_event(self) -> None:
        from app.workers.jobs import crawl_jobs
        from app.workers.jobs.crawl_jobs import crawl_company_job

        captured: list[tuple[Any, Any]] = []

        class FakeBus:
            async def publish(self, event: Any, context: Any = None) -> Any:
                captured.append((event, context))

                class R:
                    succeeded = True
                    failures: list[Any] = []
                return R()

        ingestion = self._patched_ingestion({"discovered": 5, "inserted": 2})

        with patch.object(crawl_jobs, "JobIngestionService", return_value=ingestion), \
             patch("app.events.get_event_bus", return_value=FakeBus()):
            result = asyncio.run(crawl_company_job({"job_id": "t"}, "adzuna", ""))

        assert result["success"] is True
        assert result["deactivated"] == 1
        # Empty slug falls back to the default query.
        ingestion.ingest_adzuna_jobs.assert_called_once_with("software engineer")
        assert len(captured) == 1
        event, ctx = captured[0]
        assert type(event).__name__ == "JobIngested"
        assert event.source_platform == "adzuna"
        assert event.jobs_processed == 5
        assert ctx is None  # system-scoped: no user context

    def test_failed_crawl_does_not_deactivate_or_publish(self) -> None:
        from app.workers.jobs import crawl_jobs
        from app.workers.jobs.crawl_jobs import crawl_company_job

        ingestion = MagicMock()
        ingestion.ingest_ashby_jobs = AsyncMock(side_effect=RuntimeError("board down"))

        with patch.object(crawl_jobs, "JobIngestionService", return_value=ingestion), \
             patch("app.events.get_event_bus") as bus_mock, pytest.raises(RuntimeError):
            asyncio.run(crawl_company_job({"job_id": "t"}, "ashby", "notion"))

        bus_mock.assert_not_called()
        ingestion.job_repository.deactivate_stale_jobs.assert_not_called()

    def test_event_failure_does_not_fail_crawl(self) -> None:
        from app.workers.jobs import crawl_jobs
        from app.workers.jobs.crawl_jobs import crawl_company_job

        ingestion = self._patched_ingestion({"discovered": 3})
        ingestion.ingest_lever_jobs = AsyncMock(return_value={"discovered": 3})
        ingestion.job_repository.deactivate_stale_jobs.return_value = 0

        with patch.object(crawl_jobs, "JobIngestionService", return_value=ingestion), \
             patch("app.events.get_event_bus", side_effect=RuntimeError("bus down")):
            result = asyncio.run(crawl_company_job({"job_id": "t"}, "lever", "coupa"))

        assert result["success"] is True


class TestScheduledTargets:
    def test_adzuna_is_scheduled(self) -> None:
        from app.services.jobs.scheduled_crawl_runner import CRAWL_TARGETS

        assert ("adzuna", "software engineer") in CRAWL_TARGETS
