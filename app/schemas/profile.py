"""Profile API schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ProfileUpdate(BaseModel):
    """Request schema for updating a user's profile.

    ``user_id``/``id`` are intentionally NOT part of this schema: the user id is
    always derived from the authenticated JWT, never from the client.
    """

    current_role: Optional[str] = None
    desired_role: Optional[str] = None
    skills: Optional[list[str]] = None
    location: Optional[str] = None
    preferred_locations: Optional[list[str]] = None
    # Live DB column is text with CHECK in ('remote','hybrid','onsite','any').
    remote_preference: Optional[str] = None
    preferred_companies: Optional[list[str]] = None
    salary_expectation_min: Optional[float] = None
    salary_expectation_max: Optional[float] = None
    salary_currency: Optional[str] = None
    experience: Optional[str] = None
    education: Optional[list[Any]] = None
    onboarding_completed: Optional[bool] = None
    onboarding_step: Optional[int] = None


class ProfileResponse(BaseModel):
    """Response schema for profile data."""

    id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str = "user"
    current_role: Optional[str] = None
    desired_role: Optional[str] = None
    skills: list[str] = []
    location: Optional[str] = None
    preferred_locations: list[str] = []
    remote_preference: Optional[str] = None
    preferred_companies: list[str] = []
    salary_expectation_min: Optional[float] = None
    salary_expectation_max: Optional[float] = None
    salary_currency: Optional[str] = None
    experience: Optional[str] = None
    education: list[Any] = []
    onboarding_completed: bool = False
    onboarding_step: int = 0
