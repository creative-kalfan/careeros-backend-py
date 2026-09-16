"""10-job fixture tests for CareerOS job relevance scoring.

Validates:
1. Target role exact/direct variants outrank related roles.
2. Related roles outrank sibling data roles.
3. Sibling data roles outrank unrelated engineering roles.
4. Hyderabad Data Analyst outranks Bangalore Backend Engineer despite location advantage.
5. Software Engineering Senior Analyst is role-demoted for Data Analyst candidate.
6. Skill match contribution is gated when role is a mismatch.
"""

import pytest
from app.models.job import NormalizedJob
from app.models.profile import UserProfile
from app.services.jobs.personalized_job_service import PersonalizedJobService


@pytest.fixture
def service():
    return PersonalizedJobService()


@pytest.fixture
def data_analyst_profile():
    return UserProfile(
        id="candidate-1",
        desired_role="Data Analyst",
        skills=["Python", "SQL", "Excel", "Power BI"],
        location="Bangalore, India",
        experience="3 years",
    )


@pytest.fixture
def ten_fixture_jobs():
    return {
        "A": NormalizedJob(
            external_job_id="job-A",
            title="Senior Data Analyst",
            company="DataCorp",
            location="Bangalore, India",
            skills=["Python", "SQL", "Tableau"],
            experience_level="Senior",
            role_category="Data & Analytics",
        ),
        "B": NormalizedJob(
            external_job_id="job-B",
            title="Data Analyst",
            company="Analytix",
            location="Hyderabad, India",
            skills=["Python", "SQL", "Power BI", "Excel"],
            experience_level="Mid",
            role_category="Data & Analytics",
        ),
        "C": NormalizedJob(
            external_job_id="job-C",
            title="BI Analyst",
            company="InfoMetrics",
            location="Bangalore, India",
            skills=["SQL", "Power BI", "Excel"],
            experience_level="Mid",
            role_category="Data & Analytics",
        ),
        "D": NormalizedJob(
            external_job_id="job-D",
            title="Product Analyst",
            company="AppLogic",
            location="Bangalore, India",
            skills=["SQL", "Python", "Mixpanel"],
            experience_level="Mid",
            role_category="Data & Analytics",
        ),
        "E": NormalizedJob(
            external_job_id="job-E",
            title="Data Scientist",
            company="AI Labs",
            location="Bangalore, India",
            skills=["Python", "Machine Learning", "SQL", "PyTorch"],
            experience_level="Mid",
            role_category="Data & Analytics",
        ),
        "F": NormalizedJob(
            external_job_id="job-F",
            title="Data Engineer",
            company="Pipeline Inc",
            location="Bangalore, India",
            skills=["Python", "SQL", "Spark", "Airflow"],
            experience_level="Mid",
            role_category="Data & Analytics",
        ),
        "G": NormalizedJob(
            external_job_id="job-G",
            title="Backend Engineer",
            company="ServerHub",
            location="Bangalore, India",
            skills=["Python", "SQL", "Django", "AWS"],
            experience_level="Mid",
            role_category="Software Engineering",
        ),
        "H": NormalizedJob(
            external_job_id="job-H",
            title="Software Engineer",
            company="DevWorks",
            location="Bangalore, India",
            skills=["Python", "React", "PostgreSQL"],
            experience_level="Mid",
            role_category="Software Engineering",
        ),
        "I": NormalizedJob(
            external_job_id="job-I",
            title="Frontend Developer",
            company="WebCraft",
            location="Bangalore, India",
            skills=["React", "TypeScript", "CSS"],
            experience_level="Mid",
            role_category="Software Engineering",
        ),
        "J": NormalizedJob(
            external_job_id="job-J",
            title="DevOps Engineer",
            company="CloudOps",
            location="Bangalore, India",
            skills=["Docker", "Kubernetes", "AWS", "Terraform"],
            experience_level="Mid",
            role_category="Software Engineering",
        ),
    }


def test_tier_separation_and_relevance_hierarchy(service, data_analyst_profile, ten_fixture_jobs):
    scores = {k: service.calculate_match_score(job, data_analyst_profile) for k, job in ten_fixture_jobs.items()}

    # Tier 1: Exact / direct variants (Senior Data Analyst, Data Analyst)
    assert scores["A"]["role_match"] >= 95
    assert scores["B"]["role_match"] >= 95

    # Tier 2: Closely related analyst roles (BI Analyst, Product Analyst)
    assert 80 <= scores["C"]["role_match"] <= 95
    assert 80 <= scores["D"]["role_match"] <= 95

    # Tier 3: Distinct data family roles (Data Scientist, Data Engineer)
    assert 60 <= scores["E"]["role_match"] <= 75
    assert 60 <= scores["F"]["role_match"] <= 75

    # Tier 4: Unrelated engineering roles
    for key in ("G", "H", "I", "J"):
        assert scores[key]["role_match"] <= 15, f"Job {key} role_match={scores[key]['role_match']} must be <= 15"

    # Hierarchy ranking assertions:
    # Tier 1 outranks Tier 3 and Tier 4
    assert scores["A"]["overall"] > scores["E"]["overall"]
    assert scores["A"]["overall"] > scores["F"]["overall"]
    assert scores["B"]["overall"] > scores["E"]["overall"]
    assert scores["B"]["overall"] > scores["F"]["overall"]

    # Tier 2 outranks Tier 3 and Tier 4
    assert scores["C"]["overall"] > scores["E"]["overall"]
    assert scores["C"]["overall"] > scores["F"]["overall"]
    assert scores["D"]["overall"] > scores["E"]["overall"]
    assert scores["D"]["overall"] > scores["F"]["overall"]

    # Tier 3 outranks Tier 4
    for tier3_key in ("E", "F"):
        for tier4_key in ("G", "H", "I", "J"):
            assert scores[tier3_key]["overall"] > scores[tier4_key]["overall"]


def test_cross_location_target_role_beats_local_unrelated_role(service, data_analyst_profile, ten_fixture_jobs):
    """Job B (Hyderabad Data Analyst) MUST outrank Job G (Bangalore Backend Engineer)
    despite candidate living in Bangalore. Role target priority dominates location boost.
    """
    score_b = service.calculate_match_score(ten_fixture_jobs["B"], data_analyst_profile)
    score_g = service.calculate_match_score(ten_fixture_jobs["G"], data_analyst_profile)
    score_h = service.calculate_match_score(ten_fixture_jobs["H"], data_analyst_profile)

    assert score_b["role_match"] == 100
    assert score_g["role_match"] <= 15
    assert score_h["role_match"] <= 15

    assert score_b["overall"] > score_g["overall"] + 20, (
        f"Hyderabad Data Analyst ({score_b['overall']}) must substantially outrank "
        f"Bangalore Backend Engineer ({score_g['overall']})"
    )
    assert score_b["overall"] > score_h["overall"] + 20


def test_software_engineering_senior_analyst_not_matched_to_data_analyst(service, data_analyst_profile):
    """Generic role words like 'analyst' must not match 'Software Engineering Senior Analyst'
    to 'Data Analyst'.
    """
    job = NormalizedJob(
        external_job_id="job-se-analyst",
        title="Software Engineering Senior Analyst",
        company="Tech Mahindra",
        location="Bangalore, India",
        skills=["Java", "Spring Boot", "Microservices"],
        role_category="Software Engineering",
    )
    score = service.calculate_match_score(job, data_analyst_profile)
    assert score["role_match"] <= 15, f"Expected role_match <= 15, got {score['role_match']}"
    assert score["overall"] < 40


def test_skill_match_gating_on_unrelated_role(service, data_analyst_profile, ten_fixture_jobs):
    """Even though Backend Engineer requires Python and SQL, the skill match
    contribution must be gated when role_match < 40.
    """
    score_g = service.calculate_match_score(ten_fixture_jobs["G"], data_analyst_profile)
    assert score_g["skill_match"] < 20


def test_software_engineer_candidate_regression(service):
    """Software Engineer candidate should match backend/fullstack/swe roles, not data analyst."""
    swe_profile = UserProfile(
        id="swe-1",
        desired_role="Software Engineer",
        skills=["Python", "TypeScript", "React"],
        location="Bangalore, India",
    )
    job_swe = NormalizedJob(
        external_job_id="swe-swe",
        title="Full Stack Engineer",
        location="Bangalore, India",
        skills=["Python", "React"],
        role_category="Software Engineering",
    )
    job_da = NormalizedJob(
        external_job_id="swe-da",
        title="Data Analyst",
        location="Bangalore, India",
        skills=["SQL", "Excel"],
        role_category="Data & Analytics",
    )
    score_swe = service.calculate_match_score(job_swe, swe_profile)
    score_da = service.calculate_match_score(job_da, swe_profile)

    assert score_swe["role_match"] >= 80
    assert score_da["role_match"] <= 15
    assert score_swe["overall"] > score_da["overall"] + 30


def test_frontend_developer_candidate_regression(service):
    """Frontend Developer candidate should match React/UI roles, not DevOps/Backend."""
    fe_profile = UserProfile(
        id="fe-1",
        desired_role="Frontend Developer",
        skills=["React", "TypeScript", "Tailwind"],
        location="Bangalore, India",
    )
    job_fe = NormalizedJob(
        external_job_id="fe-fe",
        title="React Developer",
        location="Bangalore, India",
        skills=["React", "TypeScript"],
        role_category="Software Engineering",
    )
    job_devops = NormalizedJob(
        external_job_id="fe-devops",
        title="DevOps Engineer",
        location="Bangalore, India",
        skills=["Kubernetes", "Docker"],
        role_category="Software Engineering",
    )
    score_fe = service.calculate_match_score(job_fe, fe_profile)
    score_devops = service.calculate_match_score(job_devops, fe_profile)

    assert score_fe["role_match"] >= 85
    assert score_devops["role_match"] <= 15
    assert score_fe["overall"] > score_devops["overall"]


def test_product_manager_candidate_regression(service):
    """Product Manager candidate should match PM variants, not Software Engineer."""
    pm_profile = UserProfile(
        id="pm-1",
        desired_role="Product Manager",
        skills=["Roadmapping", "SQL", "A/B Testing"],
        location="Bangalore, India",
    )
    job_pm = NormalizedJob(
        external_job_id="pm-pm",
        title="Senior Product Manager",
        location="Bangalore, India",
        skills=["Roadmapping", "A/B Testing"],
        role_category="Product & Business",
    )
    job_swe = NormalizedJob(
        external_job_id="pm-swe",
        title="Software Engineer",
        location="Bangalore, India",
        skills=["Java", "C++"],
        role_category="Software Engineering",
    )
    score_pm = service.calculate_match_score(job_pm, pm_profile)
    score_swe = service.calculate_match_score(job_swe, pm_profile)

    assert score_pm["role_match"] >= 95
    assert score_swe["role_match"] <= 15
    assert score_pm["overall"] > score_swe["overall"] + 30


def test_no_desired_role_profile_handles_gracefully(service):
    """Profile without desired_role should not raise exception and return baseline role_match."""
    empty_profile = UserProfile(id="empty-1", desired_role=None)
    job = NormalizedJob(external_job_id="j-1", title="Data Analyst", location="Bangalore, India")
    score = service.calculate_match_score(job, empty_profile)
    assert score["role_match"] == 50
    assert score["overall"] > 0
