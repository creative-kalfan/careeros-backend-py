"""Tests for the expanded role taxonomy and classifier."""

from __future__ import annotations

import pytest

from app.parsing.role_classifier import classify, classify_many, get_all_categories
from app.parsing.role_taxonomy import normalize_role, get_all_canonical_roles


class TestRoleClassifier:
    """Verify role classification across the broad taxonomy."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            # Software Engineering
            ("Software Engineer", "Software Engineering"),
            ("SOFTWARE ENGINEER", "Software Engineering"),
            ("Senior Backend Engineer", "Software Engineering"),
            ("Staff Software Engineer", "Software Engineering"),
            ("Full Stack Developer", "Software Engineering"),
            ("senior software eng", "Software Engineering"),
            ("Support Engineer", "Software Engineering"),
            ("Enterprise Technical Support Engineer", "Software Engineering"),
            # Product & Business
            ("Product Manager", "Product & Business"),
            ("Product Owner", "Product & Business"),
            ("Senior PM at fintech", "Product & Business"),
            # Data & Analytics
            ("Data Scientist", "Data & Analytics"),
            ("ML Engineer", "Data & Analytics"),
            ("Machine Learning Engineer", "Data & Analytics"),
            ("Data Engineer", "Data & Analytics"),
            ("Data Engineer, People Analytics", "Data & Analytics"),
            # Software Engineering (DevOps/SRE/Mobile mapped here)
            ("DEVOPS ENGINEER", "Software Engineering"),
            ("DevOps Engineer", "Software Engineering"),
            ("SRE", "Software Engineering"),
            ("Platform Engineer", "Software Engineering"),
            ("QA Engineer", "Software Engineering"),
            ("Test Engineer", "Software Engineering"),
            ("QA Manager", "Software Engineering"),
            ("iOS Engineer", "Software Engineering"),
            ("Android Engineer", "Software Engineering"),
            # Design & Creative
            ("UX Designer", "Design & Creative"),
            ("User Researcher", "Design & Creative"),
            ("Rapid User Researcher", "Design & Creative"),
            # Security (mapped to Software Engineering)
            ("Security Engineer", "Software Engineering"),
            ("Security Engineer, Detection and Response", "Software Engineering"),
            ("Security Analyst", "Software Engineering"),
            ("AppSec Engineer", "Software Engineering"),
            # Developer Relations (mapped to Software Engineering)
            ("Developer Advocate", "Software Engineering"),
            ("DevRel Manager", "Software Engineering"),
            ("Technical Evangelist", "Software Engineering"),
            # Management
            ("Engineering Manager", "Management"),
            ("Tech Lead", "Management"),
            # Other
            ("xyzzy qwerty", "Other"),
            ("", "Other"),
            (None, "Other"),
            ("Forward Deployed Engineer", "Other"),
            ("AI Applications Engineer", "Other"),
            ("Model Behavior Engineer", "Other"),
            ("backend dev at startup", "Other"),
        ],
    )
    def test_classify(self, text, expected):
        assert classify(text) == expected


class TestDataAnalystClassification:
    """Verify Data Analyst and related roles are properly classified."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Data Analyst", "Data & Analytics"),
            ("data analyst", "Data & Analytics"),
            ("DATA ANALYST", "Data & Analytics"),
            ("Senior Data Analyst", "Data & Analytics"),
            ("Junior Data Analyst", "Data & Analytics"),
            ("Data Analyst II", "Data & Analytics"),
            ("Data Analyst III", "Data & Analytics"),
            ("Analytics Analyst", "Data & Analytics"),
            ("Reporting Analyst", "Data & Analytics"),
            ("BI Analyst", "Data & Analytics"),
            ("Business Intelligence Analyst", "Data & Analytics"),
            ("Product Data Analyst", "Data & Analytics"),
            ("Marketing Data Analyst", "Data & Analytics"),
            ("Financial Data Analyst", "Data & Analytics"),
            ("Data Visualization Analyst", "Data & Analytics"),
            ("MIS Analyst", "Data & Analytics"),
            ("MIS Executive", "Data & Analytics"),
            # Related but distinct
            ("Business Analyst", "Product & Business"),
            ("BI Developer", "Data & Analytics"),
            ("Data Scientist", "Data & Analytics"),
            ("Data Engineer", "Data & Analytics"),
            ("Analytics Engineer", "Data & Analytics"),
        ],
    )
    def test_data_analyst_family(self, text, expected):
        assert classify(text) == expected


class TestRoleNormalization:
    """Verify role normalization maps aliases to canonical roles."""

    @pytest.mark.parametrize(
        ("text", "expected_canonical"),
        [
            ("Data Analyst", "Data Analyst"),
            ("data analyst", "Data Analyst"),
            ("DATA ANALYST", "Data Analyst"),
            ("Senior Data Analyst", "Data Analyst"),
            ("Junior Data Analyst", "Data Analyst"),
            ("Data Analyst II", "Data Analyst"),
            ("Data Analyst III", "Data Analyst"),
            ("Analytics Analyst", "Data Analyst"),
            ("Reporting Analyst", "Data Analyst"),
            ("BI Analyst", "Data Analyst"),
            ("Business Intelligence Analyst", "Data Analyst"),
            ("Software Engineer", "Software Engineer"),
            ("software engineer", "Software Engineer"),
            ("Backend Developer", "Backend Developer"),
            ("backend developer", "Backend Developer"),
            ("Product Manager", "Product Manager"),
            ("product manager", "Product Manager"),
            ("DevOps Engineer", "DevOps Engineer"),
            ("devops engineer", "DevOps Engineer"),
            ("QA Engineer", "QA Engineer"),
            ("qa engineer", "QA Engineer"),
            ("UX Designer", "UX Designer"),
            ("ux designer", "UX Designer"),
            ("Data Scientist", "Data Scientist"),
            ("data scientist", "Data Scientist"),
            ("Machine Learning Engineer", "Machine Learning Engineer"),
            ("ml engineer", "Machine Learning Engineer"),
        ],
    )
    def test_normalize_role(self, text, expected_canonical):
        assert normalize_role(text) == expected_canonical


def test_classify_many_deduplicated():
    categories = classify_many(
        ["Software Engineer", "Backend Engineer", "Product Manager", "Data Scientist"]
    )
    assert "Software Engineering" in categories
    assert "Product & Business" in categories
    assert "Data & Analytics" in categories


def test_classify_many_empty():
    assert classify_many([]) == []


def test_get_all_categories_count():
    categories = get_all_categories()
    assert len(categories) == 12
    for c in [
        "Software Engineering",
        "Product & Business",
        "Data & Analytics",
        "Finance & BFSI",
        "Sales & Marketing",
        "HR & People",
        "Design & Creative",
        "Customer & Operations",
        "Supply Chain & Logistics",
        "Engineering (Core)",
        "Healthcare, Science & Other Professional",
        "Other",
    ]:
        assert c in categories


def test_get_all_canonical_roles():
    roles = get_all_canonical_roles()
    assert "Data Analyst" in roles
    assert "Software Engineer" in roles
    assert "Product Manager" in roles
    assert "Financial Analyst" in roles
    assert "Recruiter" in roles
    assert "UX Designer" in roles
    assert "Supply Chain Analyst" in roles
    assert "Civil Engineer" in roles
