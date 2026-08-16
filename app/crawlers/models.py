"""Shared data models for the crawler framework.

``CrawledJob`` mirrors the TypeScript ``CrawledJob`` interface from
``careeros-backend/services/crawlers/BaseCrawler.ts`` exactly.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CrawledJob(BaseModel):
    """A normalized job posting shared by all ATS adapters."""

    title: str
    company: str
    description: str
    responsibilities: Optional[list[str]] = None
    requirements: Optional[list[str]] = None
    skills: Optional[list[str]] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    salary: Optional[str] = None
    apply_url: Optional[str] = None
    remote: Optional[bool] = None
    posted_date: Optional[str] = None
    expires_date: Optional[str] = None
    external_job_id: Optional[str] = None
    source_platform: Optional[str] = None
    workplace_type: Optional[str] = None
    experience_level: Optional[str] = None
    salary_currency: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    raw: Optional[dict[str, Any]] = Field(default=None)