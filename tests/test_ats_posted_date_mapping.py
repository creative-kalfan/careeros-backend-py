"""Regression tests: ATS adapters must map trustworthy posted_date fields.

Never fabricate a date; never use updated_at/updated fields that would
rewrite original posting history on recrawl.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.crawlers.adapters.ashby import AshbyAdapter
from app.crawlers.adapters.greenhouse import GreenhouseAdapter
from app.crawlers.adapters.lever import LeverAdapter, _posted_date_from_epoch_ms
from app.crawlers.adapters.smartrecruiters import SmartRecruitersAdapter


def _resp(payload: dict) -> MagicMock:
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = payload
    return m


async def test_greenhouse_maps_first_published_as_posted_date():
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "Engineer",
                "content": "<p>Build things</p>",
                "first_published": "2026-09-20T00:00:00Z",
                "updated_at": "2026-09-22T00:00:00Z",
                "absolute_url": "https://boards.greenhouse.io/x/jobs/1",
                "location": {"name": "Bengaluru, India"},
            }
        ]
    }
    client = AsyncMock()
    client.get.return_value = _resp(payload)
    ad = GreenhouseAdapter("acme", client=client)
    jobs = await ad.discover_jobs()
    assert len(jobs) == 1
    assert jobs[0].posted_date == "2026-09-20T00:00:00Z"
    # Must NOT prefer updated_at
    assert jobs[0].posted_date != "2026-09-22T00:00:00Z"


async def test_greenhouse_missing_first_published_stays_none():
    payload = {"jobs": [{"id": 1, "title": "Engineer", "content": "x"}]}
    client = AsyncMock()
    client.get.return_value = _resp(payload)
    ad = GreenhouseAdapter("acme", client=client)
    jobs = await ad.discover_jobs()
    assert jobs[0].posted_date is None


async def test_ashby_maps_published_at_as_posted_date():
    payload = {
        "jobs": [
            {
                "id": "j1",
                "title": "Engineer",
                "descriptionHtml": "<p>Build</p>",
                "publishedAt": "2026-09-21T12:00:00Z",
                "lastUpdatedAt": "2026-09-23T00:00:00Z",
                "jobUrl": "https://jobs.ashbyhq.com/acme/j1",
            }
        ]
    }
    client = AsyncMock()
    client.get.return_value = _resp(payload)
    ad = AshbyAdapter("acme", client=client)
    jobs = await ad.discover_jobs()
    assert jobs[0].posted_date == "2026-09-21T12:00:00Z"
    assert jobs[0].posted_date != "2026-09-23T00:00:00Z"


async def test_lever_maps_created_at_epoch_ms_as_posted_date():
    # 2026-09-20T00:00:00Z = 1789996800000-ish; use a known value:
    # 1_767_225_600_000 ms ≈ 2026-01-01T00:00:00Z
    payload = {
        "postings": [
            {
                "id": "1",
                "text": "Engineer",
                "description": "Build",
                "createdAt": 1767225600000,
                "hostedUrl": "https://jobs.lever.co/acme/1",
                "location": {"name": "Bengaluru"},
            }
        ]
    }
    client = AsyncMock()
    # List then detail
    client.get.side_effect = [_resp(payload), _resp(payload["postings"][0])]
    ad = LeverAdapter("acme", client=client)
    jobs = await ad.discover_jobs()
    assert len(jobs) == 1
    assert jobs[0].posted_date is not None
    assert jobs[0].posted_date.startswith("2026-01-01")


def test_lever_epoch_helper_rejects_garbage():
    assert _posted_date_from_epoch_ms(None) is None
    assert _posted_date_from_epoch_ms("") is None
    assert _posted_date_from_epoch_ms("not-a-number") is None
    assert _posted_date_from_epoch_ms(0) is None
    assert _posted_date_from_epoch_ms(-1) is None


async def test_smartrecruiters_maps_released_date_as_posted_date():
    list_payload = {
        "content": [
            {
                "id": "sr1",
                "name": "Engineer",
                "company": {"name": "Acme"},
                "location": {"city": "Bengaluru", "country": "India"},
                "releasedDate": "2026-09-19",
                "applyUrl": "https://jobs.smartrecruiters.com/acme/sr1",
            }
        ]
    }
    detail_payload = {
        **list_payload["content"][0],
        "jobAd": {"sections": {"jobDescription": {"text": "Build products"}}},
    }
    client = AsyncMock()
    client.get.side_effect = [_resp(list_payload), _resp(detail_payload)]
    ad = SmartRecruitersAdapter("acme", client=client)
    jobs = await ad.discover_jobs()
    assert jobs[0].posted_date == "2026-09-19"
