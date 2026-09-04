"""Regression tests for anti-fabrication of numerical claims and metrics in resume tailoring."""

import re
import pytest
from app.models.resume import (
    ResumeContent,
    ResumeProfile,
    PersonalInfo,
    ExperienceItem,
    BulletItem,
    SkillCategory,
)
from app.services.optimization.optimization_service import OptimizationService


def test_no_numeric_metrics_invented_for_unmetriced_bullets():
    """Verify that unmetriced bullets do NOT receive invented percentages (e.g. 30%, 40%, 25%)."""
    profile = ResumeProfile(
        personal=PersonalInfo(full_name="Jordan Reed"),
        experience=[
            ExperienceItem(
                id="exp_1",
                role="Backend Engineer",
                company="TechCorp",
                responsibilities=[
                    BulletItem(id="b1", text="Responsible for developing backend REST APIs with Python and PostgreSQL."),
                    BulletItem(id="b2", text="Helped with frontend React component updates and bug fixes."),
                    BulletItem(id="b3", text="Maintained CI/CD pipelines with Docker."),
                ],
            )
        ],
        skills=SkillCategory(technical=["Python", "PostgreSQL", "React", "Docker"]),
    )
    content = ResumeContent(profile=profile)
    opt = OptimizationService()
    res = opt.optimize_resume(
        resume_content=content,
        job_description="Looking for a Python Backend Engineer with PostgreSQL and Docker experience.",
        job_title="Python Backend Engineer",
    )

    metric_regex = re.compile(r"\b\d+[\d,.]*(?:%|\+|k|m|x| percent)\b", re.I)

    for sug in res.suggestions:
        if sug.get("section") == "experience":
            suggested_text = sug.get("suggestedText") or sug.get("suggested_text") or ""
            # Source bullet had no numeric metric -> rewrite must NOT have invented numeric metric
            assert not metric_regex.search(suggested_text), f"Invented numerical metric found: '{suggested_text}'"


def test_existing_numeric_metrics_are_preserved():
    """Verify that genuine candidate-provided metrics are preserved in rewrites."""
    profile = ResumeProfile(
        personal=PersonalInfo(full_name="Jordan Reed"),
        experience=[
            ExperienceItem(
                id="exp_1",
                role="Backend Engineer",
                company="TechCorp",
                responsibilities=[
                    BulletItem(id="b1", text="Optimized PostgreSQL queries, reducing P99 latency by 35% on high-load endpoints."),
                ],
            )
        ],
        skills=SkillCategory(technical=["Python", "PostgreSQL"]),
    )
    content = ResumeContent(profile=profile)
    opt = OptimizationService()
    res = opt.optimize_resume(
        resume_content=content,
        job_description="Looking for a Python Backend Engineer to optimize database queries.",
        job_title="Python Backend Engineer",
    )

    # Bullet with existing strong metric and verb shouldn't be ruined or replaced with fake numbers
    for sug in res.suggestions:
        if sug.get("childId") == "b1" or sug.get("child_id") == "b1":
            suggested_text = sug.get("suggestedText") or sug.get("suggested_text") or ""
            if "35%" in sug.get("currentText", ""):
                assert "35%" in suggested_text or sug.get("action") == "keep"
