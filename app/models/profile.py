"""User profile model for the Job vertical slice."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class UserProfile(BaseModel):
    """A user's profile relevant to job relevance/personalization."""

    id: Optional[str] = None
    current_role: Optional[str] = None
    desired_role: Optional[str] = None
    skills: Optional[list[str]] = None
    location: Optional[str] = None
    preferred_locations: Optional[list[str]] = None
    # The live profiles table stores remote_preference as text with the check
    # constraint ('remote','hybrid','onsite','any') — NOT bool.
    remote_preference: Optional[str] = None
    preferred_companies: Optional[list[str]] = None
    salary_expectation_min: Optional[float] = None
    salary_expectation_max: Optional[float] = None
    salary_currency: Optional[str] = None
    experience: Optional[str] = None
    education: Optional[list[Any]] = None
    onboarding_completed: Optional[bool] = None
    onboarding_step: Optional[int] = None

    @classmethod
    def from_db_row(cls, row: dict[str, Any] | None) -> "UserProfile | None":
        """Build a UserProfile from a Supabase ``profiles`` row (or None).

        Normalizes legacy/empty database values:
        - experience: converts empty list [] to None (string-ish field)
        """
        if not row:
            return None
        # Normalize experience field: database may contain [] for "not set"
        experience = row.get("experience")
        if experience == []:
            experience = None
        return cls(
            id=row.get("id"),
            current_role=row.get("current_role"),
            desired_role=row.get("desired_role"),
            skills=row.get("skills") or [],
            location=row.get("location"),
            preferred_locations=row.get("preferred_locations") or [],
            remote_preference=row.get("remote_preference"),
            preferred_companies=row.get("preferred_companies") or [],
            salary_expectation_min=row.get("salary_expectation_min"),
            salary_expectation_max=row.get("salary_expectation_max"),
            salary_currency=row.get("salary_currency"),
            experience=experience,
            education=row.get("education") or [],
            onboarding_completed=row.get("onboarding_completed") or False,
            onboarding_step=row.get("onboarding_step") or 0,
        )
