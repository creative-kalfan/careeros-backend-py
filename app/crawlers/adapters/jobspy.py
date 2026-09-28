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
DEFAULT_COUNTRY_INDEED = "India"


def _is_rate_limited_message(exc: BaseException) -> bool:
    """Local 429 check (kept in the crawler layer to avoid a services import)."""
    haystack = f"{exc.__class__.__name__} {exc}".lower()
    return (
        "429" in haystack
        or "rate limit" in haystack
        or "ratelimit" in haystack
        or "too many requests" in haystack
        or "http 406" in haystack
    )


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
    """Bounded JobSpy discovery for broad job-board coverage.

    Per-site parameters follow the pinned ``python-jobspy==1.1.82`` contract
    (see ``app.services.jobs.jobspy_strategy``): hours_old is requested only
    for indeed/glassdoor/linkedin; country_indeed only for indeed/glassdoor;
    naukri receives search_term/location/results_wanted only. ``last_error``
    / ``last_outcome`` surface the provider result so orchestration can do
    provider-aware throttling and circuit breaking (the job list itself
    stays [] on failure — isolation is preserved).
    """

    def __init__(
        self,
        query: str = DEFAULT_QUERY,
        location: str = DEFAULT_LOCATION,
        results_wanted: int = DEFAULT_RESULTS_WANTED,
        site_names: Optional[list[str]] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        fetch_fn: Optional[Callable[..., Awaitable[list[dict[str, Any]]]]] = None,
        hours_old: Optional[int] = None,
        country_indeed: str = DEFAULT_COUNTRY_INDEED,
        job_type: Optional[str] = None,
        is_remote: Optional[bool] = None,
    ) -> None:
        self.query = query
        self.location = location
        self.results_wanted = max(1, min(int(results_wanted), 200))
        self.site_names = site_names or ["naukri", "linkedin"]
        self.timeout_seconds = timeout_seconds
        self._fetch_fn = fetch_fn
        self.hours_old = hours_old
        self.country_indeed = country_indeed
        self.job_type = job_type
        self.is_remote = is_remote
        self.last_error: Optional[BaseException] = None
        self.last_outcome: str = "not_run"

    async def discover_jobs(self) -> list[CrawledJob]:
        """Scrape one bounded query; failures isolate to [] (never raise)."""
        self.last_error = None
        self.last_outcome = "success"
        try:
            if self._fetch_fn is not None:
                raw_jobs = await asyncio.wait_for(
                    self._fetch_fn(
                        query=self.query,
                        location=self.location,
                        results_wanted=self.results_wanted,
                        site_names=self.site_names,
                        hours_old=self.hours_old,
                        country_indeed=self.country_indeed,
                    ),
                    timeout=self.timeout_seconds,
                )
            else:
                raw_jobs = await asyncio.wait_for(
                    asyncio.to_thread(self._scrape_sync),
                    timeout=self.timeout_seconds,
                )
        except Exception as exc:
            self.last_error = exc
            self.last_outcome = (
                "rate_limited" if _is_rate_limited_message(exc) else "transient"
            )
            logger.warning("JobSpy discovery failed (isolated): %s", exc)
            return []
        if self._scrape_missing_dependency:
            self.last_outcome = "config"
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

    _scrape_missing_dependency = False

    def _scrape_sync(self) -> list[dict[str, Any]]:
        """Synchronous JobSpy call (runs in a worker thread).

        Sites are grouped by supported parameters and scraped per group so
        one group's failure (e.g. Naukri bot-gating) never aborts the other
        providers' results.
        """
        try:
            from jobspy import scrape_jobs  # type: ignore[import-not-found]
        except Exception:
            self._scrape_missing_dependency = True
            logger.info("JobSpy not installed; skipping (pip install python-jobspy to enable)")
            return []
        self._scrape_missing_dependency = False
        groups = self._site_groups()
        records: list[dict[str, Any]] = []
        for group_sites, extra in groups:
            try:
                frame = scrape_jobs(
                    site_name=group_sites,
                    search_term=self.query,
                    location=self.location,
                    results_wanted=self.results_wanted,
                    verbose=0,
                    description_format="markdown",
                    linkedin_fetch_description=False,
                    **extra,
                )
                if frame is None or getattr(frame, "empty", True):
                    continue
                batch = frame.to_dict(orient="records")
                if isinstance(batch, list):
                    records.extend(r for r in batch if isinstance(r, dict))
            except Exception as exc:
                self.last_error = exc
                if _is_rate_limited_message(exc):
                    self.last_outcome = "rate_limited"
                elif self.last_outcome == "success":
                    self.last_outcome = "transient"
                logger.warning(
                    "JobSpy scrape failed (isolated) sites=%s: %s", group_sites, exc
                )
        return records

    def _site_groups(self) -> list[tuple[list[str], dict[str, Any]]]:
        """Group configured sites by supported scrape parameters."""
        indeed_like = [s for s in self.site_names if s in ("indeed", "glassdoor")]
        linkedin = [s for s in self.site_names if s == "linkedin"]
        others = [s for s in self.site_names if s not in ("indeed", "glassdoor", "linkedin")]
        groups: list[tuple[list[str], dict[str, Any]]] = []
        if indeed_like:
            # Indeed limitation: only one of hours_old / (job_type &
            # is_remote) / easy_apply per search — hours_old wins for
            # freshness buckets; job_type/is_remote stay unset.
            extra: dict[str, Any] = {"country_indeed": self.country_indeed}
            if self.hours_old is not None:
                extra["hours_old"] = int(self.hours_old)
            groups.append((indeed_like, extra))
        if linkedin:
            extra = {}
            if self.hours_old is not None:
                extra["hours_old"] = int(self.hours_old)
            groups.append((linkedin, extra))
        if others:
            # Naukri and unverified boards: search_term/location only.
            groups.append((others, {}))
        if not groups:
            groups.append((list(self.site_names), {}))
        return groups
