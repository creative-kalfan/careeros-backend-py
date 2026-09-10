"""JobSpy discovery adapter (Naukri/LinkedIn coverage).

Isolated behind BaseCrawler. Never writes to the DB — returns CrawledJob
records into the canonical JobIngestionService pipeline only.

``python-jobspy`` is an OPTIONAL dependency: when it is not installed (or a
crawl fails / times out), discovery logs and returns [] so one provider can
never break ingestion. Tests inject ``fetch_fn`` / ``client`` instead of the
real scraper.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from app.crawlers.base import BaseCrawler
from app.crawlers.models import CrawledJob
from app.crawlers.source_quality import stable_hash

logger = logging.getLogger(__name__)

DEFAULT_QUERY = "data analyst India"
DEFAULT_LOCATION = "India"
DEFAULT_RESULTS_WANTED = 50
DEFAULT_TIMEOUT_SECONDS = 60.0


def _str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def map_jobspy_record(raw: dict[str, Any]) -> CrawledJob:
    """Map one JobSpy-shaped record (Naukri/LinkedIn columns) to CrawledJob."""
    title = _str(raw.get("title"))
    company = _str(raw.get("company"))
    location = _str(raw.get("location"))
    description = _str(raw.get("description") or raw.get("job_text") or "")
    job_url = _str(raw.get("job_url") or raw.get("apply_url") or raw.get("redirect_url"))
    external_id = _str(raw.get("id") or raw.get("job_id") or raw.get("external_job_id"))
    if not external_id:
        # Deterministic fallback identity (stable across processes).
        external_id = f"jobspy-{stable_hash((job_url + '|' + title + '|' + company).lower())}"
    site = _str(raw.get("site") or raw.get("source") or "").lower()
    raw = {**raw, "jobspy_site": site or "jobspy"}
    skills = raw.get("skills") if isinstance(raw.get("skills"), list) else None
    return CrawledJob(
        title=title,
        company=company,
        description=description,
        location=location or None,
        employment_type=_str(raw.get("job_type") or raw.get("employment_type")) or None,
        apply_url=job_url or None,
        remote=("remote" in location.lower()) if location else None,
        external_job_id=external_id,
        source_platform="jobspy",
        posted_date=_str(raw.get("date_posted") or raw.get("posted_date")) or None,
        skills=skills,
        raw=raw if isinstance(raw, dict) else {"jobspy_site": site or "jobspy"},
    )


class JobSpyAdapter(BaseCrawler):
    """Bounded JobSpy discovery for Naukri/LinkedIn coverage."""

    def __init__(
        self,
        query: str = DEFAULT_QUERY,
        location: str = DEFAULT_LOCATION,
        results_wanted: int = DEFAULT_RESULTS_WANTED,
        site_names: Optional[list[str]] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        fetch_fn: Optional[Callable[..., Awaitable[list[dict[str, Any]]]]] = None,
    ) -> None:
        self.query = query
        self.location = location
        self.results_wanted = max(1, min(int(results_wanted), 200))
        self.site_names = site_names or ["naukri", "linkedin"]
        self.timeout_seconds = timeout_seconds
        self._fetch_fn = fetch_fn

    async def discover_jobs(self) -> list[CrawledJob]:
        """Scrape one bounded query; failures isolate to [] (never raise)."""
        try:
            if self._fetch_fn is not None:
                raw_jobs = await asyncio.wait_for(
                    self._fetch_fn(
                        query=self.query,
                        location=self.location,
                        results_wanted=self.results_wanted,
                        site_names=self.site_names,
                    ),
                    timeout=self.timeout_seconds,
                )
            else:
                raw_jobs = await asyncio.wait_for(
                    asyncio.to_thread(self._scrape_sync),
                    timeout=self.timeout_seconds,
                )
        except Exception as exc:
            logger.warning("JobSpy discovery failed (isolated): %s", exc)
            return []
        if not isinstance(raw_jobs, list):
            return []
        jobs: list[CrawledJob] = []
        for raw in raw_jobs[: self.results_wanted]:
            if not isinstance(raw, dict):
                continue
            try:
                job = map_jobspy_record(raw)
                if job.title:
                    jobs.append(job)
            except Exception as exc:
                logger.warning("JobSpy record skipped: %s", exc)
        return jobs

    def _scrape_sync(self) -> list[dict[str, Any]]:
        """Synchronous JobSpy call (runs in a worker thread)."""
        try:
            from jobspy import scrape_jobs  # type: ignore[import-not-found]
        except Exception:
            logger.info("JobSpy not installed; skipping (pip install python-jobspy to enable)")
            return []
        try:
            frame = scrape_jobs(
                site_name=self.site_names,
                search_term=self.query,
                location=self.location,
                results_wanted=self.results_wanted,
            )
            if frame is None or getattr(frame, "empty", True):
                return []
            return frame.to_dict(orient="records")  # type: ignore[no-any-return]
        except Exception as exc:
            logger.warning("JobSpy scrape failed (isolated): %s", exc)
            return []
