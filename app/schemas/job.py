"""Job API schema (response DTOs)."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class JobOut(BaseModel):
    """A job as returned by the Jobs API."""

    id: Optional[str] = None
    external_job_id: Optional[str] = None
    source_platform: Optional[str] = None
    source: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    apply_url: Optional[str] = None
    posted_at: Optional[str] = None
    posted_date: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    role_category: Optional[str] = None
    application_deadline: Optional[str] = None
    expires_date: Optional[str] = None
    is_active: Optional[bool] = None
    remote: Optional[bool] = None
    workplace_type: Optional[str] = None
    employment_type: Optional[str] = None
    salary: Optional[str] = None
    skills: Optional[list[str]] = None
    requirements: Optional[list[str]] = None
    responsibilities: Optional[list[str]] = None
    experience_level: Optional[str] = None
    match: Optional[dict[str, Any]] = None
    ats_score: Optional[float] = None
    raw: Optional[dict[str, Any]] = None

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "JobOut":
        """Build a JobOut from a Supabase ``jobs`` row.

        Preserves both snake_case (source) and camelCase (frontend-friendly
        SDK aliases) fields so the response can be consumed by either the
        existing TypeScript callers or new Python clients.
        """
        return cls(
            id=row.get("id") or row.get("external_job_id"),
            external_job_id=row.get("external_job_id"),
            source_platform=row.get("source_platform"),
            source=row.get("source") or row.get("source_platform"),
            title=row.get("title"),
            company=row.get("company"),
            company_name=row.get("company") or row.get("company_name"),
            location=row.get("location"),
            description=row.get("description"),
            url=row.get("url"),
            apply_url=row.get("url") or row.get("apply_url"),
            posted_at=row.get("posted_at"),
            posted_date=row.get("posted_at") or row.get("posted_date"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            role_category=row.get("role_category"),
            application_deadline=row.get("application_deadline"),
            expires_date=row.get("application_deadline"),
            is_active=row.get("is_active"),
            remote=row.get("remote"),
            workplace_type=row.get("workplace_type"),
            employment_type=row.get("employment_type"),
            salary=row.get("salary"),
            skills=row.get("skills") or [],
            requirements=row.get("requirements") or [],
            responsibilities=row.get("responsibilities") or [],
            experience_level=row.get("experience_level"),
            match=row.get("match"),
            ats_score=row.get("ats_score") if row.get("ats_score") else None,
            raw=row.get("raw"),
        )