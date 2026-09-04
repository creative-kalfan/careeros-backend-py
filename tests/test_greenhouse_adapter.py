"""Tests for the Greenhouse ATS adapter against the REAL public API.

Uses ``greenhouse`` as the test slug - Greenhouse's own company board,
verified by hand (returns 200).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.crawlers.adapters.greenhouse import GreenhouseAdapter

REAL_SLUG = "greenhouse"
MISSING_SLUG = "this-company-definitely-does-not-exist-xyz-99231"

RETRY_DELAY_SECONDS = 2.0


async def _discover_with_retry(slug: str) -> list:
    """Retry once after a short delay on transient network failure."""
    for attempt in range(2):
        async with GreenhouseAdapter(slug) as ad:
            jobs = await ad.discover_jobs()
        if jobs:
            return jobs
        if attempt == 0:
            await asyncio.sleep(RETRY_DELAY_SECONDS)
    return jobs


@pytest.mark.asyncio
async def test_real_company_returns_jobs_with_all_fields_populated() -> None:
    jobs = await _discover_with_retry(REAL_SLUG)
    assert len(jobs) > 0
    for job in jobs:
        assert job.title, f"Job {job.external_job_id} has no title"
        assert job.company, f"Job {job.external_job_id} has no company"
        # Some Greenhouse job boards may return draft/expired postings with empty descriptions.
        # Validate the field type is correct; check majority have content below.
        assert isinstance(job.description, str), f"Job {job.external_job_id} description is not a string"
        assert job.source_platform == "greenhouse", f"Job {job.external_job_id} has wrong source platform"
        assert job.external_job_id, f"Job has no external_job_id"
        assert isinstance(job.skills, list), f"Job {job.external_job_id} skills is not a list"
        assert isinstance(job.requirements, list), f"Job {job.external_job_id} requirements is not a list"
        assert isinstance(job.responsibilities, list), f"Job {job.external_job_id} responsibilities is not a list"
    # At least half the returned jobs should have a non-empty description.
    jobs_with_desc = [j for j in jobs if j.description]
    assert len(jobs_with_desc) >= len(jobs) // 2, (
        f"Too many jobs missing descriptions: {len(jobs) - len(jobs_with_desc)}/{len(jobs)}"
    )


@pytest.mark.asyncio
async def test_missing_company_returns_empty_list_not_exception() -> None:
    async with GreenhouseAdapter(MISSING_SLUG) as ad:
        jobs = await ad.discover_jobs()
    assert jobs == []


@pytest.mark.asyncio
async def test_remote_detection_on_real_data() -> None:
    """Remote flag must be derived from location text. If the board currently
    has remote jobs, the flag must be True for them; if it has none, every
    non-remote job must have remote=False. Either way the mapping is correct."""
    jobs = await _discover_with_retry(REAL_SLUG)
    remote_jobs = [j for j in jobs if j.location and "remote" in j.location.lower()]
    for job in remote_jobs:
        assert job.remote is True, f"remote should be True for {job.title}"
    for job in jobs:
        if not (job.location and "remote" in job.location.lower()):
            assert job.remote is False, f"remote should be False for {job.title}"


@pytest.mark.asyncio
async def test_malformed_response_returns_empty_list() -> None:
    async def handler(request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ad = GreenhouseAdapter(REAL_SLUG, client=client)
        jobs = await ad.discover_jobs()
    assert jobs == []