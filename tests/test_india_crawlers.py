import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from app.crawlers.adapters.instahyre import InstahyreAdapter
from app.crawlers.adapters.hirist import HiristAdapter
from app.crawlers.adapters.naukri import NaukriAdapter
from app.crawlers.crawl_registry import all_targets


def test_registry_contains_india_targets():
    targets = all_targets()
    sources = {t.source for t in targets}
    assert "instahyre" in sources
    assert "hirist" in sources
    assert "naukri" in sources


@pytest.mark.asyncio
async def test_instahyre_adapter_rate_limit_and_parse():
    with patch("app.crawlers.adapters.instahyre.check_rate_limit", new_callable=AsyncMock) as mock_limit:
        # 1. When rate limited
        mock_limit.return_value = False
        adapter = InstahyreAdapter()
        jobs = await adapter.discover_jobs()
        assert jobs == []

        # 2. When allowed
        mock_limit.return_value = True
        fake_payload = {
            "objects": [
                {
                    "id": 101,
                    "title": "Backend Python Developer",
                    "company_name": "Tech Corp India",
                    "location": "Bengaluru",
                    "description": "Develop high scale backend systems using Python and FastAPI.",
                    "job_url": "/job/101-backend-developer",
                    "skills": "Python, FastAPI, Redis",
                    "is_remote": True,
                }
            ]
        }
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = fake_payload
            mock_get.return_value = mock_resp

            jobs = await adapter.discover_jobs()
            assert len(jobs) == 1
            job = jobs[0]
            assert job.title == "Backend Python Developer"
            assert job.company == "Tech Corp India"
            assert job.location == "Bengaluru"
            assert job.source_platform == "instahyre"
            assert job.remote is True
            assert job.external_job_id == "101"
            assert "Python" in job.skills


@pytest.mark.asyncio
async def test_hirist_adapter_rate_limit_and_parse():
    with patch("app.crawlers.adapters.hirist.check_rate_limit", new_callable=AsyncMock) as mock_limit:
        # Rate limited
        mock_limit.return_value = False
        adapter = HiristAdapter()
        jobs = await adapter.discover_jobs()
        assert jobs == []

        # Allowed
        mock_limit.return_value = True
        fake_payload = {
            "jobs": [
                {
                    "id": "h-202",
                    "title": "Lead Software Engineer",
                    "recruiter_name": "Fintech Solutions",
                    "city": "Hyderabad",
                    "snippet": "Lead team in building modern web apps.",
                    "url": "/job/h-202",
                    "skills": ["Go", "Kubernetes"],
                }
            ]
        }
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = fake_payload
            mock_get.return_value = mock_resp

            jobs = await adapter.discover_jobs()
            assert len(jobs) == 1
            job = jobs[0]
            assert job.title == "Lead Software Engineer"
            assert job.company == "Fintech Solutions"
            assert job.location == "Hyderabad"
            assert job.source_platform == "hirist"
            assert job.external_job_id == "h-202"


@pytest.mark.asyncio
async def test_naukri_adapter_rate_limit_and_fallback():
    with patch("app.crawlers.adapters.naukri.check_rate_limit", new_callable=AsyncMock) as mock_limit:
        # 1. Rate limited
        mock_limit.return_value = False
        adapter = NaukriAdapter()
        jobs = await adapter.discover_jobs()
        assert jobs == []

        # 2. Firecrawl scrape path
        mock_limit.return_value = True
        sample_html = """
        <div class="srp-jobtuple-wrapper">
            <a class="title" href="https://www.naukri.com/job-1">Senior Data Engineer</a>
            <a class="comp-name">Analytics India</a>
            <span class="loc-wrap">Bangalore/Bengaluru</span>
            <span class="job-desc">Experienced with PySpark, SQL, AWS</span>
            <ul class="tags-gt">
                <li>PySpark</li>
                <li>SQL</li>
            </ul>
        </div>
        """
        with patch("app.config.get_settings") as mock_settings:
            mock_settings.return_value.firecrawl_api_key = "test_key"
            with patch("app.crawlers.adapters.naukri.FirecrawlClient") as mock_fc_client:
                mock_instance = AsyncMock()
                mock_instance.scrape.return_value = {"data": {"html": sample_html}}
                mock_fc_client.return_value.__aenter__.return_value = mock_instance

                jobs = await adapter.discover_jobs()
                assert len(jobs) == 1
                job = jobs[0]
                assert job.title == "Senior Data Engineer"
                assert job.company == "Analytics India"
                assert job.location == "Bangalore/Bengaluru"
                assert job.source_platform == "naukri"
                assert "PySpark" in job.skills
