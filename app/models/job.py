"""Normalized job model shared across the Job vertical slice.

This is the single CareerOS representation of a job after normalization.
All source formats (Ashby, Adzuna, SmartRecruiters, Lever, Greenhouse, etc.)
are converted into this model before being persisted or returned by the API.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

# Jobs older than this many days are considered stale and hidden from results.
STALE_JOB_DAYS = 30


class NormalizedJob(BaseModel):
    """A job normalized into the CareerOS representation."""

    # Persisted identity
    id: Optional[str] = None
    external_job_id: Optional[str] = None
    source_platform: Optional[str] = None

    # Core content
    title: str
    company: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None

    # Work/employment metadata (only set when the source provides it)
    remote: Optional[bool] = None
    workplace_type: Optional[str] = None
    employment_type: Optional[str] = None
    salary: Optional[str] = None
    salary_currency: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    apply_url: Optional[str] = None
    # DB column is "url"; expose as "url" for DB round-trip, alias to apply_url
    url: Optional[str] = None
    posted_date: Optional[str] = None
    expires_date: Optional[str] = None
    experience_level: Optional[str] = None

    # Classification / enrichment
    role_category: Optional[str] = None
    skills: Optional[list[str]] = None
    requirements: Optional[list[str]] = None
    responsibilities: Optional[list[str]] = None
    match: Optional[dict[str, float]] = None
    ats_score: Optional[float] = None

    # Source provenance / quality (see app.crawlers.source_quality)
    source_tier: Optional[int] = None
    source_provider: Optional[str] = None
    canonical_url: Optional[str] = None
    source_verified: Optional[bool] = None
    source_confidence: Optional[float] = None
    company_website: Optional[str] = None
    careers_url: Optional[str] = None
    logo_url: Optional[str] = None

    # Original source payload (for debugging/audit)
    raw: Optional[dict[str, Any]] = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _sync_url_apply_url(self) -> "NormalizedJob":
        """Keep url and apply_url in sync for DB round-trip."""
        if self.url is not None and self.apply_url is None:
            self.apply_url = self.url
        elif self.apply_url is not None and self.url is None:
            self.url = self.apply_url
        return self

    def _is_stale(self) -> bool:
        """Return True if the job's posted_date is older than STALE_JOB_DAYS.

        Jobs with no posted_date are treated as fresh (not stale) so we never
        hide a job just because the source omitted a date.
        """
        if not self.posted_date:
            return False
        try:
            posted = self.posted_date
            if isinstance(posted, str):
                posted_dt = datetime.fromisoformat(posted.replace("Z", "+00:00"))
            else:
                posted_dt = posted
            if posted_dt.tzinfo is None:
                posted_dt = posted_dt.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - posted_dt).total_seconds() / 86400
            return age_days > STALE_JOB_DAYS
        except Exception:
            return False

    # Whitelist of columns that actually exist in the Supabase ``jobs`` table.
    # ``to_db_row`` only emits these so inserts/updates never fail with a
    # "column not found" error for fields that live only on the model.
    _DB_COLUMNS = frozenset(
        {
            "title",
            "company",
            "location",
            "description",
            "url",
            "source",
            "posted_at",
            "role_category",
            "application_deadline",
            "is_active",
            "source_platform",
            "external_job_id",
            "source_tier",
            "source_provider",
            "canonical_url",
            "source_verified",
            "source_confidence",
            "company_website",
            "careers_url",
            "logo_url",
        }
    )

    def to_db_row(self) -> dict[str, Any]:
        """Map to the Supabase ``jobs`` table column names.

        ``is_active`` is derived from the posted date: jobs older than
        ``STALE_JOB_DAYS`` are inserted/updated with ``is_active=False`` so
        they are hidden from results at ingestion time (30-day cutoff).

        Only columns that exist in the ``jobs`` table are emitted (see
        ``_DB_COLUMNS``) so ingestion never fails on a schema mismatch.
        """
        row = {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "description": self.description,
            "url": self.apply_url,
            "source": self.source_platform,
            "posted_at": self.posted_date,
            "role_category": self.role_category,
            "application_deadline": self.expires_date,
            "is_active": not self._is_stale(),
            "source_platform": self.source_platform,
            "external_job_id": self.external_job_id,
            "remote": self.remote,
            "workplace_type": self.workplace_type,
            "employment_type": self.employment_type,
            "salary": self.salary,
            "salary_currency": self.salary_currency,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "skills": self.skills or [],
            "requirements": self.requirements or [],
            "responsibilities": self.responsibilities or [],
            "experience_level": self.experience_level,
            "ats_score": self.ats_score,
            "source_tier": self.source_tier,
            "source_provider": self.source_provider or self.source_platform,
            "canonical_url": self.canonical_url or self.apply_url,
            "source_verified": self.source_verified,
            "source_confidence": self.source_confidence,
            "company_website": self.company_website,
            "careers_url": self.careers_url,
            "logo_url": self.logo_url,
        }
        return {k: v for k, v in row.items() if k in self._DB_COLUMNS and v is not None}
