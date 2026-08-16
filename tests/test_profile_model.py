"""Tests for UserProfile model validation and normalization."""

from app.models.profile import UserProfile


def test_profile_from_db_row_with_valid_data():
    """Test that a valid database row creates a proper UserProfile."""
    row = {
        "id": "user-123",
        "email": "test@example.com",
        "full_name": "Test User",
        "role": "user",
        "current_role": "Software Engineer",
        "desired_role": "Senior Engineer",
        "skills": ["Python", "JavaScript"],
        "location": "San Francisco",
        "preferred_locations": ["SF", "NYC"],
        "remote_preference": "remote",
        "preferred_companies": ["Google", "Meta"],
        "salary_expectation_min": 150000,
        "salary_expectation_max": 200000,
        "salary_currency": "USD",
        "experience": "mid",
    }
    
    profile = UserProfile.from_db_row(row)
    
    assert profile is not None
    assert profile.id == "user-123"
    assert profile.current_role == "Software Engineer"
    assert profile.desired_role == "Senior Engineer"
    assert profile.skills == ["Python", "JavaScript"]
    assert profile.experience == "mid"


def test_profile_from_db_row_with_none_experience():
    """Test that None experience is handled correctly."""
    row = {
        "id": "user-456",
        "experience": None,
    }
    
    profile = UserProfile.from_db_row(row)
    
    assert profile is not None
    assert profile.id == "user-456"
    assert profile.experience is None


def test_profile_from_db_row_with_empty_list_experience():
    """Test that empty list [] for experience is normalized to None.
    
    This is a regression test for the bug where the database contained []
    for the experience field, causing a Pydantic validation error.
    """
    row = {
        "id": "user-789",
        "experience": [],
    }
    
    # This should not raise a ValidationError
    profile = UserProfile.from_db_row(row)
    
    assert profile is not None
    assert profile.id == "user-789"
    assert profile.experience is None  # Empty list should be normalized to None


def test_profile_from_db_row_with_missing_experience():
    """Test that missing experience field is handled correctly."""
    row = {
        "id": "user-999",
    }
    
    profile = UserProfile.from_db_row(row)
    
    assert profile is not None
    assert profile.id == "user-999"
    assert profile.experience is None


def test_profile_from_db_row_with_empty_lists():
    """Test that empty lists for array fields are normalized to empty lists."""
    row = {
        "id": "user-abc",
        "skills": [],
        "preferred_locations": [],
        "preferred_companies": [],
        "experience": "entry",
    }
    
    profile = UserProfile.from_db_row(row)
    
    assert profile is not None
    assert profile.id == "user-abc"
    assert profile.skills == []
    assert profile.preferred_locations == []
    assert profile.preferred_companies == []
    assert profile.experience == "entry"


def test_profile_from_db_row_none_input():
    """Test that None input returns None."""
    profile = UserProfile.from_db_row(None)
    assert profile is None


def test_profile_from_db_row_empty_dict():
    """Test that empty dict input returns None (no id field)."""
    profile = UserProfile.from_db_row({})
    
    # Empty dict has no 'id', so from_db_row returns None
    assert profile is None
