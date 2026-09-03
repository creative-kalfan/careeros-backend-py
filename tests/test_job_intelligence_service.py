"""Tests for the JobIntelligenceService and extraction utilities."""

from __future__ import annotations

import pytest

from app.models.job import NormalizedJob
from app.models.job_intelligence import (
    CertificationInfo,
    EducationInfo,
    JobIntelligence,
    RequirementInfo,
    SeniorityInfo,
    SkillInfo,
    WorkArrangement,
)
from app.services.jobs.job_intelligence_service import JobIntelligenceService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _job(**kwargs: object) -> NormalizedJob:
    """Build a minimal NormalizedJob for testing."""
    defaults: dict[str, object] = {
        "title": "Test Engineer",
        "company": "Acme Corp",
        "description": "",
        "location": "Remote",
        "url": "https://example.com",
        "source_platform": "test",
        "external_job_id": "test-1",
    }
    defaults.update(kwargs)
    return NormalizedJob(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Skill extraction
# ---------------------------------------------------------------------------

class TestSkillExtraction:
    def test_extracts_known_skills(self) -> None:
        jd = "We are looking for a Python developer with SQL and Docker experience."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        names = {s.normalized_name for s in result.skills}
        assert "Python" in names
        assert "SQL" in names
        assert "docker" in names

    def test_skill_normalization(self) -> None:
        jd = "Experience with PostgreSQL, Power BI, and Python3 required."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        normalized = {s.normalized_name for s in result.skills}
        assert "postgresql" in normalized
        assert "power bi" in normalized
        assert "python" in normalized

    def test_skill_importance_required(self) -> None:
        jd = "Python and SQL are required for this role."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        for skill in result.skills:
            if skill.normalized_name in ("Python", "SQL"):
                assert skill.importance == "required"
                assert skill.confidence == "high"

    def test_skill_importance_preferred(self) -> None:
        jd = "Experience with Kubernetes is preferred."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        for skill in result.skills:
            if skill.normalized_name == "kubernetes":
                assert skill.importance == "preferred"
                assert skill.confidence == "high"

    def test_skill_evidence_preserved(self) -> None:
        jd = "You must know Python for backend development."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        python_skill = next((s for s in result.skills if s.normalized_name == "Python"), None)
        assert python_skill is not None
        assert len(python_skill.evidence) > 0

    def test_no_fabrication_on_vague_text(self) -> None:
        jd = "We need someone with modern data technologies."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert len(result.skills) == 0


# ---------------------------------------------------------------------------
# Experience extraction
# ---------------------------------------------------------------------------

class TestExperienceExtraction:
    def test_single_year(self) -> None:
        jd = "2+ years of experience required."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert result.seniority.years_min == 2.0
        assert result.seniority.years_max is None

    def test_year_range(self) -> None:
        jd = "3-5 years of experience in software engineering."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert result.seniority.years_min == 3.0
        assert result.seniority.years_max == 5.0

    def test_senior_title(self) -> None:
        jd = "Senior Data Analyst role."
        job = _job(description=jd, title="Senior Data Analyst")
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert result.seniority.level == "senior"
        assert result.seniority.confidence in ("high", "medium")

    def test_entry_level(self) -> None:
        jd = "Entry-level position for recent graduates."
        job = _job(description=jd, title="Entry Level Engineer")
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert result.seniority.level == "entry"
        assert result.seniority.confidence in ("high", "medium")

    def test_no_years_returns_none(self) -> None:
        jd = "We are looking for a developer."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert result.seniority.years_min is None
        assert result.seniority.years_max is None


# ---------------------------------------------------------------------------
# Education extraction
# ---------------------------------------------------------------------------

class TestEducationExtraction:
    def test_bachelor_degree(self) -> None:
        jd = "Bachelor's degree in Computer Science required."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        degrees = [e.degree for e in result.education]
        assert "bachelor" in degrees

    def test_mba_detection(self) -> None:
        jd = "MBA preferred."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        degrees = [e.degree for e in result.education]
        assert "mba" in degrees

    def test_phd_detection(self) -> None:
        jd = "PhD in a technical field."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        degrees = [e.degree for e in result.education]
        assert "phd" in degrees

    def test_required_flag(self) -> None:
        jd = "Bachelor's degree required."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        bachelor = next((e for e in result.education if e.degree == "bachelor"), None)
        assert bachelor is not None
        assert bachelor.required is True

    def test_no_education_statement(self) -> None:
        jd = "We need a skilled developer."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert len(result.education) == 0


# ---------------------------------------------------------------------------
# Certification extraction
# ---------------------------------------------------------------------------

class TestCertificationExtraction:
    def test_aws_certified(self) -> None:
        jd = "AWS Certified Solutions Architect preferred."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        names = [c.name for c in result.certifications]
        assert "aws certified" in names

    def test_pmp(self) -> None:
        jd = "PMP certification is a plus."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        names = [c.name for c in result.certifications]
        assert "pmp" in names

    def test_no_certifications(self) -> None:
        jd = "We need a software engineer."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert len(result.certifications) == 0


# ---------------------------------------------------------------------------
# Responsibility extraction
# ---------------------------------------------------------------------------

class TestResponsibilityExtraction:
    def test_responsibilities_section(self) -> None:
        jd = """
        Responsibilities
        - Write clean code
        - Review pull requests
        - Mentor junior engineers
        """
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert len(result.responsibilities) >= 2
        assert any("pull" in r.lower() for r in result.responsibilities)

    def test_what_you_will_do(self) -> None:
        jd = """
        What you'll do
        - Build scalable systems
        - Collaborate with teams
        """
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert len(result.responsibilities) >= 1


# ---------------------------------------------------------------------------
# Requirement extraction
# ---------------------------------------------------------------------------

class TestRequirementExtraction:
    def test_requirements_section(self) -> None:
        jd = """
        Requirements:
        - 5+ years of experience
        - Strong Python skills
        """
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert len(result.requirements) >= 1

    def test_preferred_qualifications(self) -> None:
        jd = """
        Preferred qualifications:
        - Experience with React
        - Knowledge of GraphQL
        """
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert len(result.requirements) >= 1
        for req in result.requirements:
            if req.text in ["Experience with React", "Knowledge of GraphQL"]:
                assert req.type == "preferred"


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

class TestKeywordExtraction:
    def test_keywords_extracted(self) -> None:
        jd = "Python developer with SQL and Docker experience."
        job = _job(description=jd, title="")
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert len(result.keywords) > 0

    def test_stop_words_filtered(self) -> None:
        jd = "The and or of to in a an for with on at by."
        job = _job(description=jd, title="")
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert len(result.keywords) == 0


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_all_items_have_confidence(self) -> None:
        jd = "Python and SQL required. Bachelor's degree required."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        for skill in result.skills:
            assert skill.confidence in ("high", "medium", "low")
        for edu in result.education:
            assert edu.confidence in ("high", "medium", "low")
        for cert in result.certifications:
            assert cert.confidence in ("high", "medium", "low")

    def test_no_fabrication(self) -> None:
        jd = "We are looking for a modern data engineer."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert len(result.skills) == 0
        assert len(result.certifications) == 0


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------

class TestMalformedInput:
    def test_empty_description(self) -> None:
        job = _job(description="", title="")
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert result.job_id == "test-1"
        assert result.skills == []
        assert result.keywords == []

    def test_none_description(self) -> None:
        job = _job(description=None)  # type: ignore[arg-type]
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert result.skills == []


# ---------------------------------------------------------------------------
# Work arrangement
# ---------------------------------------------------------------------------

class TestWorkArrangement:
    def test_remote_detected(self) -> None:
        jd = "This is a remote position."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert result.work_arrangement.type == "remote"

    def test_hybrid_detected(self) -> None:
        jd = "Hybrid work model with 2 days in office."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert result.work_arrangement.type == "hybrid"

    def test_onsite_detected(self) -> None:
        jd = "On-site position in Bangalore."
        job = _job(description=jd)
        result = JobIntelligenceService().analyze_job(job, job_id="test-1")
        assert result.work_arrangement.type == "onsite"


# ---------------------------------------------------------------------------
# Idempotency / version
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_same_input_produces_same_structure(self) -> None:
        jd = "Python developer with SQL and Docker. Bachelor's degree required."
        job = _job(description=jd)
        service = JobIntelligenceService()
        r1 = service.analyze_job(job, job_id="test-1")
        r2 = service.analyze_job(job, job_id="test-1")
        assert r1.intelligence_version == r2.intelligence_version == "1.0"
        assert len(r1.skills) == len(r2.skills)
