"""Paraphrase and fabrication discrimination suite for SemanticFabricationGuard."""

from __future__ import annotations

import pytest
from app.models.resume import BulletItem, ExperienceItem, PersonalInfo, ResumeProfile
from app.services.optimization.semantic_guard import semantic_guard


# ---------------------------------------------------------------------------
# 5 Legitimate Paraphrase Cases (MUST PASS)
# ---------------------------------------------------------------------------

def test_paraphrase_1_built_rest_apis_to_developed_restful_services() -> None:
    """Source: built REST APIs -> Tailored: developed scalable RESTful web services."""
    source = ResumeProfile(
        personal=PersonalInfo(full_name="Sam Taylor"),
        skills={"technical": ["Python", "FastAPI"]},
        experience=[
            ExperienceItem(
                role="Software Engineer",
                company="Acme Corp",
                responsibilities=[BulletItem(text="Built REST APIs for customer onboarding.")],
            )
        ],
    )
    tailored = {
        "experience": [
            {
                "role": "Software Engineer",
                "responsibilities": [{"text": "Developed scalable RESTful web services for client onboarding."}],
            }
        ]
    }
    _, issues = semantic_guard.audit_tailored_profile(source, tailored)
    assert not issues, f"False positive on legitimate paraphrase: {issues}"


def test_paraphrase_2_synonym_alias_postgres_to_postgresql() -> None:
    """Source: PostgreSQL -> Tailored: postgres."""
    source = ResumeProfile(
        personal=PersonalInfo(full_name="Sam Taylor"),
        skills={"databases": ["PostgreSQL"]},
        experience=[
            ExperienceItem(
                role="Backend Developer",
                company="Beta LLC",
                responsibilities=[BulletItem(text="Maintained database clusters in PostgreSQL.")],
            )
        ],
    )
    tailored = {
        "skills": {"databases": ["Postgres"]},
        "experience": [
            {
                "role": "Backend Developer",
                "responsibilities": [{"text": "Optimized database queries and storage in postgres."}],
            }
        ],
    }
    _, issues = semantic_guard.audit_tailored_profile(source, tailored)
    assert not issues, f"False positive on synonym alias: {issues}"


def test_paraphrase_3_active_to_passive_voice_and_metrics_rephrasing() -> None:
    """Source: Reduced latency by 40% -> Tailored: Improved API response speed by 40%."""
    source = ResumeProfile(
        personal=PersonalInfo(full_name="Sam Taylor"),
        skills={"technical": ["Python", "Redis"]},
        experience=[
            ExperienceItem(
                role="Systems Engineer",
                company="Gamma Inc",
                responsibilities=[BulletItem(text="Reduced p99 latency by 40% using Redis caching.")],
            )
        ],
    )
    tailored = {
        "experience": [
            {
                "role": "Systems Engineer",
                "responsibilities": [{"text": "Enhanced system throughput and improved response speed by 40% utilizing Redis cache layer."}],
            }
        ]
    }
    _, issues = semantic_guard.audit_tailored_profile(source, tailored)
    assert not issues, f"False positive on rephrased metric: {issues}"


def test_paraphrase_4_summary_synthesis_from_experience() -> None:
    """Source has Python, Docker in experience -> Tailored summary references Python and Docker."""
    source = ResumeProfile(
        personal=PersonalInfo(full_name="Sam Taylor"),
        skills={"tools": ["Docker"]},
        experience=[
            ExperienceItem(
                role="Backend Engineer",
                company="Delta Corp",
                responsibilities=[
                    BulletItem(text="Authored backend services in Python and containerized workloads with Docker.")
                ],
            )
        ],
    )
    tailored = {
        "summary": "Backend Engineer with extensive background architecting Python microservices containerized with Docker."
    }
    _, issues = semantic_guard.audit_tailored_profile(source, tailored)
    assert not issues, f"False positive on summary synthesis: {issues}"


def test_paraphrase_5_word_reordering_and_bullet_consolidation() -> None:
    """Source: Implemented CI/CD pipelines with GitHub Actions and automated unit testing."""
    source = ResumeProfile(
        personal=PersonalInfo(full_name="Sam Taylor"),
        skills={"cicd": ["Git", "GitHub Actions"]},
        experience=[
            ExperienceItem(
                role="DevOps Engineer",
                company="Epsilon Tech",
                responsibilities=[
                    BulletItem(text="Automated test execution and release workflows using Git."),
                ],
            )
        ],
    )
    tailored = {
        "experience": [
            {
                "role": "DevOps Engineer",
                "responsibilities": [
                    {"text": "Streamlined automated test execution pipelines and version controlled release cycles with Git."}
                ],
            }
        ]
    }
    _, issues = semantic_guard.audit_tailored_profile(source, tailored)
    assert not issues, f"False positive on reordered wording: {issues}"


# ---------------------------------------------------------------------------
# 5 Fabrication Cases (MUST FAIL with SEMANTIC_FABRICATION / issue returned)
# ---------------------------------------------------------------------------

def test_fabrication_1_invented_unmentioned_cloud_platform() -> None:
    """Source has Python only -> Tailored adds AWS."""
    source = ResumeProfile(
        personal=PersonalInfo(full_name="Sam Taylor"),
        skills={"languages": ["Python"]},
        experience=[
            ExperienceItem(
                role="Software Engineer",
                company="Acme Corp",
                responsibilities=[BulletItem(text="Built backend services using Python.")],
            )
        ],
    )
    tailored = {
        "summary": "Cloud Architect with deep proficiency deploying scalable services to AWS.",
        "skills": {"languages": ["Python"], "cloud": ["AWS"]},
    }
    _, issues = semantic_guard.audit_tailored_profile(source, tailored)
    assert issues, "Failed to catch ungrounded AWS platform claim"
    assert any("aws" in issue.lower() for issue in issues)


def test_fabrication_2_invented_container_orchestration_tool() -> None:
    """Source has Docker only -> Tailored introduces Kubernetes."""
    source = ResumeProfile(
        personal=PersonalInfo(full_name="Sam Taylor"),
        skills={"containers": ["Docker"]},
        experience=[
            ExperienceItem(
                role="DevOps Engineer",
                company="Beta LLC",
                responsibilities=[BulletItem(text="Packaged services into Docker containers.")],
            )
        ],
    )
    tailored = {
        "experience": [
            {
                "role": "DevOps Engineer",
                "responsibilities": [
                    {"text": "Packaged services into Docker containers and orchestrated production clusters using Kubernetes."}
                ],
            }
        ]
    }
    _, issues = semantic_guard.audit_tailored_profile(source, tailored)
    assert issues, "Failed to catch ungrounded Kubernetes claim"
    assert any("kubernetes" in issue.lower() for issue in issues)


def test_fabrication_3_scope_inflation_led_a_team_when_no_leadership() -> None:
    """Source was Individual Contributor -> Tailored claims 'Led a team'."""
    source = ResumeProfile(
        personal=PersonalInfo(full_name="Sam Taylor"),
        skills={"technical": ["Python", "FastAPI"]},
        experience=[
            ExperienceItem(
                role="Junior Developer",
                company="Gamma Inc",
                responsibilities=[BulletItem(text="Wrote unit tests and fixed API bug tickets.")],
            )
        ],
    )
    tailored = {
        "experience": [
            {
                "role": "Junior Developer",
                "responsibilities": [
                    {"text": "Led a team of engineers building high-throughput microservices."}
                ],
            }
        ]
    }
    _, issues = semantic_guard.audit_tailored_profile(source, tailored)
    assert issues, "Failed to catch scope inflation ('led a team')"
    assert any("led a team" in issue.lower() for issue in issues)


def test_fabrication_4_job_title_elevation() -> None:
    """Source: Junior Developer -> Tailored role: Staff Engineering Director."""
    source = ResumeProfile(
        personal=PersonalInfo(full_name="Sam Taylor"),
        skills={"technical": ["Python"]},
        experience=[
            ExperienceItem(
                role="Junior Developer",
                company="Delta Corp",
                responsibilities=[BulletItem(text="Contributed to Python application code.")],
            )
        ],
    )
    tailored = {
        "experience": [
            {
                "role": "Staff Engineering Director",
                "responsibilities": [{"text": "Contributed to Python application code."}],
            }
        ]
    }
    _, issues = semantic_guard.audit_tailored_profile(source, tailored)
    assert issues, "Failed to catch fabricated job title elevation"
    assert any("Staff Engineering Director" in issue or "Director" in issue for issue in issues)


def test_fabrication_5_unsupported_skills_injected_into_skills_dict() -> None:
    """Source has Python -> Tailored adds Kafka, Terraform, Spark to skills dictionary."""
    source = ResumeProfile(
        personal=PersonalInfo(full_name="Sam Taylor"),
        skills={"languages": ["Python"]},
        experience=[
            ExperienceItem(
                role="Backend Developer",
                company="Epsilon Tech",
                responsibilities=[BulletItem(text="Built backend systems in Python.")],
            )
        ],
    )
    tailored = {
        "skills": {
            "languages": ["Python"],
            "data": ["Kafka", "Spark"],
            "infrastructure": ["Terraform"],
        }
    }
    _, issues = semantic_guard.audit_tailored_profile(source, tailored)
    assert issues, "Failed to catch ungrounded skill dictionary additions"
    assert any("Kafka" in issue for issue in issues)
    assert any("Terraform" in issue for issue in issues)
