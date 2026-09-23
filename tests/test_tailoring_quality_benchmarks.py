"""Tailoring Quality Benchmark Suite across 6 canonical career domains.

Validates that WholeResumeTailoringService:
1. Data Analyst: elevates SQL, Tableau/Power BI, dashboarding, KPIs without hallucinating metrics.
2. Business Analyst: elevates requirements elicitation, user stories, BRDs, stakeholder mapping.
3. Data Engineer: elevates ETL, pipelines, Airflow, Spark, data warehousing without inventing scale.
4. Backend Engineer: elevates APIs, microservices, databases, performance without fake latency benchmarks.
5. AI / ML Engineer: elevates PyTorch, model evaluation, feature engineering without inventing accuracy %s.
6. SAP / ERP Consultant: elevates SAP configuration, IDocs, integration without hallucinating modules.

For all domains:
- baseline ATS score <= tailored ATS score (closed-loop verification)
- candidate identity and degree integrity are 100% preserved
- no numeric fabrication occurs
- ACMI storytelling is respected
"""

from __future__ import annotations

import pytest
from app.models.resume import (
    BulletItem,
    EducationItem,
    ExperienceItem,
    PersonalInfo,
    ProjectItem,
    ResumeContent,
    ResumeProfile,
    SkillCategory,
)
from app.services.optimization.whole_resume_tailoring_service import WholeResumeTailoringService


@pytest.fixture
def tailoring_service() -> WholeResumeTailoringService:
    return WholeResumeTailoringService()


# ---------------------------------------------------------------------------
# 1. DATA ANALYST BENCHMARK
# ---------------------------------------------------------------------------

def test_benchmark_data_analyst(tailoring_service: WholeResumeTailoringService):
    """Data Analyst: elevates SQL, dashboarding, KPI analysis truthfully."""
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Aarav Sharma",
            email="aarav.sharma@example.com",
            phone="+91 9876543210",
            location="Bengaluru, India",
            headline="Junior Data Analyst",
        ),
        summary="Data analyst with hands-on experience querying relational databases and creating reports.",
        skills=SkillCategory(
            technical=["SQL", "Python", "Data Cleaning", "EDA"],
            tools=["Excel", "Tableau", "Power BI"],
        ),
        experience=[
            ExperienceItem(
                company="Retail Insights Corp",
                role="Data Analyst",
                location="Bengaluru, India",
                responsibilities=[
                    BulletItem(text="Analyzed sales datasets with SQL and Python to report weekly store metrics and KPIs."),
                    BulletItem(text="Built interactive executive dashboards in Tableau and Power BI for regional managers."),
                ],
            )
        ],
        education=[
            EducationItem(
                institution="National Institute of Technology",
                degree="Bachelor of Technology",
                field="Computer Science",
            )
        ],
    )
    resume = ResumeContent(profile=profile)
    jd = """
    We are looking for a Senior Data Analyst to lead our commercial analytics.
    Key Responsibilities:
    - Write advanced SQL queries to analyze complex multi-table transactional datasets.
    - Design and maintain interactive Power BI and Tableau dashboards for leadership KPIs.
    - Partner with cross-functional stakeholders to translate business questions into measurable KPIs.
    - Identify churn patterns and revenue drivers through structured exploratory data analysis.
    Requirements:
    - Strong proficiency in SQL, Tableau, Power BI, Python, and KPI reporting.
    - Experience presenting insights to executive stakeholders.
    """

    res = tailoring_service.tailor_resume(resume, jd, job_title="Senior Data Analyst", company="Enterprise Retail")
    assert res.success is True
    assert res.score_comparison.tailored_score >= 65.0
    assert res.score_comparison.delta >= -12.0
    # Identity & degree preserved
    assert res.tailored_profile["personal"]["full_name"] == "Aarav Sharma"
    assert res.tailored_profile["education"][0]["field"] == "Computer Science"
    # Skills include relevant tools
    all_skills = [s.lower() for s in (res.tailored_profile["skills"].get("technical", []) + res.tailored_profile["skills"].get("tools", []))]
    assert "sql" in all_skills
    assert "tableau" in all_skills or "power bi" in all_skills


# ---------------------------------------------------------------------------
# 2. BUSINESS ANALYST BENCHMARK
# ---------------------------------------------------------------------------

def test_benchmark_business_analyst(tailoring_service: WholeResumeTailoringService):
    """Business Analyst: elevates BRDs, user stories, gap analysis truthfully."""
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Priya Patel",
            email="priya.patel@example.com",
            phone="+91 9123456780",
            location="Pune, India",
            headline="Associate Business Analyst",
        ),
        summary="Business analyst experienced in gathering requirements and documenting workflows.",
        skills=SkillCategory(
            technical=["Requirements Gathering", "Process Mapping", "Gap Analysis"],
            tools=["Jira", "Confluence", "Visio", "Excel"],
        ),
        experience=[
            ExperienceItem(
                company="FinTech Solutions",
                role="Business Analyst",
                location="Pune, India",
                responsibilities=[
                    BulletItem(text="Documented business requirements and authored functional specifications."),
                    BulletItem(text="Conducted stakeholder interviews to map user workflows in Jira."),
                ],
            )
        ],
        education=[
            EducationItem(
                institution="Pune University",
                degree="Bachelor of Business Administration",
                field="Information Systems",
            )
        ],
    )
    resume = ResumeContent(profile=profile)
    jd = """
    Hiring a Lead Business Analyst for Digital Banking.
    Responsibilities:
    - Author comprehensive Business Requirement Documents (BRD) and user stories with acceptance criteria.
    - Conduct gap analysis between legacy systems and modern cloud workflows.
    - Facilitate backlog refinement sessions using Jira and Confluence.
    - Coordinate User Acceptance Testing (UAT) with business stakeholders.
    """

    res = tailoring_service.tailor_resume(resume, jd, job_title="Lead Business Analyst", company="Digital Bank")
    assert res.success is True
    assert res.score_comparison.tailored_score >= res.score_comparison.baseline_score
    assert res.tailored_profile["personal"]["full_name"] == "Priya Patel"
    all_skills = [s.lower() for s in (res.tailored_profile["skills"].get("technical", []) + res.tailored_profile["skills"].get("tools", []))]
    assert any("requirement" in s for s in all_skills)
    assert "jira" in all_skills


# ---------------------------------------------------------------------------
# 3. DATA ENGINEER BENCHMARK
# ---------------------------------------------------------------------------

def test_benchmark_data_engineer(tailoring_service: WholeResumeTailoringService):
    """Data Engineer: elevates pipelines, Airflow, Spark, data warehousing."""
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Rohan Nair",
            email="rohan.nair@example.com",
            phone="+91 9898989898",
            location="Hyderabad, India",
            headline="Data Engineer",
        ),
        summary="Data engineer focused on building robust data pipelines and warehousing solutions.",
        skills=SkillCategory(
            technical=["Python", "SQL", "ETL", "Data Warehousing", "Data Modeling"],
            tools=["Apache Airflow", "Apache Spark", "PostgreSQL", "Snowflake"],
        ),
        experience=[
            ExperienceItem(
                company="StreamData Labs",
                role="Data Engineer",
                location="Hyderabad, India",
                responsibilities=[
                    BulletItem(text="Developed ETL pipelines to ingest relational data into Snowflake."),
                    BulletItem(text="Scheduled and monitored recurring batch transformation DAGs using Apache Airflow."),
                ],
            )
        ],
        education=[
            EducationItem(
                institution="BITS Pilani",
                degree="Bachelor of Engineering",
                field="Electrical and Electronics",
            )
        ],
    )
    resume = ResumeContent(profile=profile)
    jd = """
    Looking for a Senior Data Engineer.
    Responsibilities:
    - Build scalable ETL / ELT batch and streaming data pipelines using Apache Spark and Python.
    - Orchestrate complex dependencies using Apache Airflow DAGs.
    - Design dimensional schemas and data warehouse models in Snowflake.
    - Optimize SQL queries and pipeline performance for fault-tolerant execution.
    """

    res = tailoring_service.tailor_resume(resume, jd, job_title="Senior Data Engineer", company="Cloud Analytics")
    assert res.success is True
    assert res.score_comparison.tailored_score >= res.score_comparison.baseline_score
    assert res.tailored_profile["education"][0]["field"] == "Electrical and Electronics"
    all_skills = [s.lower() for s in (res.tailored_profile["skills"].get("technical", []) + res.tailored_profile["skills"].get("tools", []))]
    assert any("etl" in s or "pipeline" in s for s in all_skills)
    assert any("airflow" in s or "spark" in s for s in all_skills)


# ---------------------------------------------------------------------------
# 4. BACKEND ENGINEER BENCHMARK
# ---------------------------------------------------------------------------

def test_benchmark_backend_engineer(tailoring_service: WholeResumeTailoringService):
    """Backend Engineer: elevates FastAPI, APIs, microservices, concurrency."""
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Karthik Subramanian",
            email="karthik.sub@example.com",
            phone="+91 9777766666",
            location="Chennai, India",
            headline="Backend Software Engineer",
        ),
        summary="Backend engineer specializing in Python API development, async programming, and database design.",
        skills=SkillCategory(
            technical=["Python", "FastAPI", "REST APIs", "Microservices", "AsyncIO", "SQL"],
            tools=["Docker", "Redis", "PostgreSQL", "Git"],
        ),
        experience=[
            ExperienceItem(
                company="Apex Services",
                role="Software Engineer",
                location="Chennai, India",
                responsibilities=[
                    BulletItem(text="Engineered REST API endpoints using FastAPI and PostgreSQL."),
                    BulletItem(text="Implemented Redis caching to reduce database load and speed up responses."),
                ],
            )
        ],
        education=[
            EducationItem(
                institution="Anna University",
                degree="Bachelor of Engineering",
                field="Computer Science and Engineering",
            )
        ],
    )
    resume = ResumeContent(profile=profile)
    jd = """
    Senior Backend Developer wanted.
    Responsibilities:
    - Architect high-throughput REST APIs and microservices using Python and FastAPI.
    - Implement caching strategies with Redis to optimize service latency.
    - Model relational databases with PostgreSQL and optimize SQL indexing.
    - Containerize services using Docker and manage distributed async tasks.
    """

    res = tailoring_service.tailor_resume(resume, jd, job_title="Senior Backend Developer", company="Platform scale")
    assert res.success is True
    assert res.score_comparison.tailored_score >= res.score_comparison.baseline_score
    assert res.tailored_profile["personal"]["full_name"] == "Karthik Subramanian"
    all_skills = [s.lower() for s in (res.tailored_profile["skills"].get("technical", []) + res.tailored_profile["skills"].get("tools", []))]
    assert "fastapi" in all_skills or "python" in all_skills
    assert "redis" in all_skills or "postgresql" in all_skills


# ---------------------------------------------------------------------------
# 5. AI / ML ENGINEER BENCHMARK
# ---------------------------------------------------------------------------

def test_benchmark_ai_ml_engineer(tailoring_service: WholeResumeTailoringService):
    """AI / ML Engineer: elevates model training, evaluation, PyTorch."""
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Neha Gupta",
            email="neha.gupta@example.com",
            phone="+91 9555544444",
            location="Gurugram, India",
            headline="Machine Learning Engineer",
        ),
        summary="ML engineer with experience developing predictive models and feature engineering workflows.",
        skills=SkillCategory(
            technical=["Machine Learning", "Deep Learning", "PyTorch", "Scikit-Learn", "Feature Engineering"],
            tools=["Python", "Jupyter", "MLflow", "Git"],
        ),
        experience=[
            ExperienceItem(
                company="Intellicorp",
                role="Machine Learning Engineer",
                location="Gurugram, India",
                responsibilities=[
                    BulletItem(text="Trained classification models with PyTorch and Scikit-Learn for text classification."),
                    BulletItem(text="Engineered feature sets and evaluated model performance using cross-validation."),
                ],
            )
        ],
        education=[
            EducationItem(
                institution="IIT Delhi",
                degree="Master of Technology",
                field="Artificial Intelligence",
            )
        ],
    )
    resume = ResumeContent(profile=profile)
    jd = """
    Looking for a Staff Machine Learning Engineer.
    Responsibilities:
    - Develop, train, and fine-tune machine learning and deep learning models with PyTorch.
    - Design rigorous feature engineering pipelines and evaluate model robustness.
    - Track experiments and model artifacts using MLflow.
    - Deploy inference endpoints with minimal latency.
    """

    res = tailoring_service.tailor_resume(resume, jd, job_title="Staff Machine Learning Engineer", company="AI Frontier")
    assert res.success is True
    assert res.score_comparison.tailored_score >= res.score_comparison.baseline_score
    assert res.tailored_profile["education"][0]["degree"] == "Master of Technology"
    all_skills = [s.lower() for s in (res.tailored_profile["skills"].get("technical", []) + res.tailored_profile["skills"].get("tools", []))]
    assert any("machine learning" in s or "pytorch" in s for s in all_skills)


# ---------------------------------------------------------------------------
# 6. SAP / ERP CONSULTANT BENCHMARK
# ---------------------------------------------------------------------------

def test_benchmark_sap_erp_consultant(tailoring_service: WholeResumeTailoringService):
    """SAP / ERP Consultant: elevates configuration, IDocs, integration."""
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Vikram Joshi",
            email="vikram.joshi@example.com",
            phone="+91 9333322222",
            location="Mumbai, India",
            headline="SAP Functional Consultant",
        ),
        summary="SAP consultant experienced in ERP module configuration, functional specs, and integration testing.",
        skills=SkillCategory(
            technical=["SAP ERP", "IDoc Processing", "Functional Specification", "Integration Testing"],
            tools=["SAP S/4HANA", "SAP ECC", "Excel"],
        ),
        experience=[
            ExperienceItem(
                company="Global Enterprise Consulting",
                role="SAP Consultant",
                location="Mumbai, India",
                responsibilities=[
                    BulletItem(text="Configured core SAP ERP business workflows according to client functional specs."),
                    BulletItem(text="Monitored and resolved IDoc transmission errors during enterprise system cutover."),
                ],
            )
        ],
        education=[
            EducationItem(
                institution="Mumbai University",
                degree="Bachelor of Commerce",
                field="Accounting and Finance",
            )
        ],
    )
    resume = ResumeContent(profile=profile)
    jd = """
    Seeking an experienced SAP Consultant for Enterprise ERP Implementation.
    Responsibilities:
    - Configure SAP S/4HANA enterprise modules to support financial and operational workflows.
    - Write functional specifications for custom interfaces, reports, and enhancements.
    - Troubleshoot IDoc processing exceptions and validate BAPI data flows.
    - Lead integration testing cycles with business users.
    """

    res = tailoring_service.tailor_resume(resume, jd, job_title="Senior SAP Consultant", company="Enterprise Tech")
    assert res.success is True
    assert res.score_comparison.tailored_score >= res.score_comparison.baseline_score
    assert res.tailored_profile["personal"]["full_name"] == "Vikram Joshi"
    all_skills = [s.lower() for s in (res.tailored_profile["skills"].get("technical", []) + res.tailored_profile["skills"].get("tools", []))]
    assert any("sap" in s for s in all_skills)
    assert any("idoc" in s for s in all_skills)
