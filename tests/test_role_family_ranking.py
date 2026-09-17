"""Unit and regression tests for role-family classification, seniority guards, and personalized ranking."""
import pytest
from unittest.mock import MagicMock
from app.parsing.role_family import (
    classify_role_family,
    evaluate_role_compatibility,
    RoleFamily,
)
from app.services.jobs.extraction_utils import classify_seniority
from app.models.profile import UserProfile
from app.models.job import NormalizedJob
from app.services.jobs.job_relevance_service import JobRelevanceService
from app.services.jobs.personalized_job_service import PersonalizedJobService


class TestRoleFamilyLayer:
    """Test deterministic role-family classification and cross-role compatibility."""

    def test_sap_vs_software_engineer_mismatch(self):
        compat, factor = evaluate_role_compatibility(
            candidate_role="SAP Consultant",
            job_title="Software Engineer, Product Platform",
            job_description="Build web applications with Python, React, and MongoDB."
        )
        assert compat == "MISMATCH"
        assert factor == 0.05

    def test_data_engineer_vs_software_engineer_mismatch(self):
        compat, factor = evaluate_role_compatibility(
            candidate_role="Data Engineer",
            job_title="Software Engineer, Core Infrastructure",
            job_description="Develop distributed backend microservices in Go and Python."
        )
        assert compat == "MISMATCH"
        assert factor == 0.05

    def test_aiml_vs_generic_software_engineer_mismatch(self):
        compat, factor = evaluate_role_compatibility(
            candidate_role="AI/ML Engineer",
            job_title="Software Engineer, Infrastructure",
            job_description="Maintain Kubernetes clusters and internal cloud tooling."
        )
        assert compat == "MISMATCH"
        assert factor == 0.05

    def test_sap_consultant_strong_match(self):
        compat, factor = evaluate_role_compatibility(
            candidate_role="SAP Consultant",
            job_title="Associate_SAP ABAP Developer",
            job_description="ABAP development, HANA integration, ERP configuration."
        )
        assert compat == "STRONG"
        assert factor == 1.0

    def test_data_analyst_strong_match(self):
        compat, factor = evaluate_role_compatibility(
            candidate_role="Data Analyst",
            job_title="Junior Data Analyst - Business Intelligence",
            job_description="Create Power BI dashboards, write SQL queries, analyze sales metrics."
        )
        assert compat == "STRONG"
        assert factor == 1.0

    def test_backend_vs_swe_compatible(self):
        compat, factor = evaluate_role_compatibility(
            candidate_role="Backend Engineer",
            job_title="Software Engineer - Platform",
            job_description="Build REST APIs and scalable backend services with Python."
        )
        assert compat in ("STRONG", "COMPATIBLE")
        assert factor >= 0.7


class TestSeniorityExtractionGuards:
    """Test numerical levels, mentorship text, and years-of-experience guards."""

    def test_swe3_classified_as_senior(self):
        level, conf = classify_seniority(
            text="Leading development of core database engine.",
            title="Software Engineer 3"
        )
        assert level == "senior"
        assert conf == "high"

    def test_swe2_classified_as_mid(self):
        level, conf = classify_seniority(
            text="Developing new search features.",
            title="Software Engineer 2"
        )
        assert level == "mid"
        assert conf == "high"

    def test_mentor_junior_does_not_trigger_entry(self):
        level, conf = classify_seniority(
            text="Responsible to mentor junior developers and guide team members.",
            title="Senior Software Engineer"
        )
        assert level == "senior"
        assert level != "entry"

    def test_years_min_ge_3_never_entry(self):
        level, conf = classify_seniority(
            text="Candidates must have at least 3 years of experience in Python.",
            title="Software Engineer"
        )
        assert level != "entry"

    def test_accelerator_program_triggers_entry(self):
        level, conf = classify_seniority(
            text="Join our engineering accelerator program for new graduates.",
            title="Graduate Engineer Trainee"
        )
        assert level in ("entry", "trainee", "fresher")


class TestRankingPriorityTiers:
    """Test personalized ranking behavior: fresher-first, role isolation, and tier priority."""

    def test_entry_candidate_ranks_relevant_entry_above_relevant_senior(self):
        profile = UserProfile(
            desired_role="Data Analyst",
            skills=["SQL", "Python", "Power BI", "Excel"],
            experience="entry",
            location="Bangalore",
        )

        job_entry = NormalizedJob(
            id="job-entry-da",
            title="Junior Data Analyst",
            company="Analytics Corp",
            location="Bangalore",
            description="Entry level role for fresh graduates with SQL and Python.",
            skills=["SQL", "Python"],
            experience_level="entry",
            is_active=True,
        )

        job_senior = NormalizedJob(
            id="job-senior-da",
            title="Lead Data Analyst",
            company="Enterprise Corp",
            location="Bangalore",
            description="Lead team of analysts. Minimum 7 years experience in SQL and Python.",
            skills=["SQL", "Python"],
            experience_level="senior",
            is_active=True,
        )

        mock_job_repo = MagicMock()
        mock_job_repo.list_jobs.return_value = ([job_senior.model_dump(), job_entry.model_dump()], 2)
        mock_prof_repo = MagicMock()
        mock_prof_repo.get_profile.return_value = profile

        relevance_service = JobRelevanceService(
            job_repository=mock_job_repo,
            profile_repository=mock_prof_repo,
        )
        ranked, total = relevance_service.get_relevant_jobs(
            user_id="user-123",
            page=1,
            page_size=10,
        )

        assert total == 2
        assert ranked[0].id == "job-entry-da"
        assert ranked[1].id == "job-senior-da"

    def test_unrelated_job_pushed_below_relevant_roles(self):
        profile = UserProfile(
            desired_role="SAP Consultant",
            skills=["SAP ABAP", "SAP HANA", "SAP FICO"],
            experience="entry",
            location="Bangalore",
        )

        job_sap_mid = NormalizedJob(
            id="job-sap-mid",
            title="SAP ABAP Consultant",
            company="ERP Solutions",
            location="Bangalore",
            description="Hands on SAP ABAP development on HANA.",
            skills=["SAP ABAP", "SAP HANA"],
            experience_level="mid",
            is_active=True,
        )

        job_swe_entry = NormalizedJob(
            id="job-swe-entry",
            title="Junior Software Engineer",
            company="OpenAI",
            location="Bangalore",
            description="Entry level software engineer. Python and distributed systems.",
            skills=["Python"],
            experience_level="entry",
            is_active=True,
        )

        mock_job_repo = MagicMock()
        mock_job_repo.list_jobs.return_value = ([job_swe_entry.model_dump(), job_sap_mid.model_dump()], 2)
        mock_prof_repo = MagicMock()
        mock_prof_repo.get_profile.return_value = profile

        relevance_service = JobRelevanceService(
            job_repository=mock_job_repo,
            profile_repository=mock_prof_repo,
        )
        ranked, total = relevance_service.get_relevant_jobs(
            user_id="user-123",
            page=1,
            page_size=10,
        )

        assert total == 2
        assert ranked[0].id == "job-sap-mid"
        assert ranked[1].id == "job-swe-entry"

    def test_mass_hiring_cannot_bypass_role_mismatch(self):
        profile = UserProfile(
            desired_role="AI/ML Engineer",
            skills=["PyTorch", "TensorFlow", "NLP", "Python"],
            experience="entry",
            location="Bangalore",
        )

        job_aiml = NormalizedJob(
            id="job-aiml",
            title="Junior Machine Learning Engineer",
            company="AI Labs",
            location="Bangalore",
            description="Build machine learning models with PyTorch.",
            skills=["PyTorch", "Python"],
            experience_level="entry",
            is_active=True,
        )

        job_unrelated_mass_hiring = NormalizedJob(
            id="job-mass-swe",
            title="Software Engineer, Core Backend",
            company="MassTech",
            location="Bangalore",
            description="Mass hiring drive for general software engineers.",
            skills=["Java", "C++"],
            experience_level="entry",
            is_active=True,
            mass_hiring="VERIFIED_MASS_HIRING",
            mass_hiring_status="ACTIVE",
        )

        mock_job_repo = MagicMock()
        mock_job_repo.list_jobs.return_value = ([job_unrelated_mass_hiring.model_dump(), job_aiml.model_dump()], 2)
        mock_prof_repo = MagicMock()
        mock_prof_repo.get_profile.return_value = profile

        relevance_service = JobRelevanceService(
            job_repository=mock_job_repo,
            profile_repository=mock_prof_repo,
        )
        ranked, total = relevance_service.get_relevant_jobs(
            user_id="user-123",
            page=1,
            page_size=10,
        )

        assert total == 2
        assert ranked[0].id == "job-aiml"
