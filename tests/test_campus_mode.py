"""Tests for Campus Mode and Public Profiles (Phase 6.8)."""

import pytest
from app.models.profile import UserProfile
from app.schemas.profile import ProfileUpdate, ProfileResponse


def test_user_profile_career_stage_and_graduating_year():
    row = {
        "id": "u-123",
        "current_role": "CS Student",
        "career_stage": "student",
        "graduating_year": 2026,
    }
    profile = UserProfile.from_db_row(row)
    assert profile is not None
    assert profile.career_stage == "student"
    assert profile.graduating_year == 2026

    # Test schemas
    update = ProfileUpdate(career_stage="fresher", graduating_year=2025)
    assert update.career_stage == "fresher"
    assert update.graduating_year == 2025

    resp = ProfileResponse(
        id="u-123",
        career_stage="fresher",
        graduating_year=2025,
    )
    assert resp.career_stage == "fresher"
    assert resp.graduating_year == 2025
