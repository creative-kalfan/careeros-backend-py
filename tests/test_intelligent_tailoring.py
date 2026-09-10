"""Comprehensive test suite for Intelligent Skill Grouping & Context-Aware Resume Reconstruction.

Covers:
1. Requirement classification (soft skills, office tools, languages, ecosystem libs, specializations).
2. Multi-ecosystem skill relationships (Python, JavaScript, Java, C#, SQL).
3. Question suppression / friction controls (soft skills never questioned, office tools grouped,
   reconstructable ecosystem skills resolved without questions).
4. Truthful resume reconstruction (Problem -> Action -> Tech -> Outcome, real metrics preserved,
   qualitative outcomes without fabrication, candidate memory / recall handling).
5. Cross-domain matrix (Backend->FullStack, Data->Finance, Finance->Data, Operations->Finance,
   Designer->ProductDesigner, Developer->DevOps, Analyst->ProductAnalyst, Fresher->SpecializedAnalyst).
"""

from __future__ import annotations

import copy
from typing import List

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
from app.models.tailoring_evidence import (
    CandidateExperienceResponse,
    ExperienceContext,
    OpportunityType,
    TailoringImprovementOpportunity,
)
from app.services.optimization.evidence_matcher import match_requirements
from app.services.optimization.evidence_model import build_evidence_index
from app.services.optimization.improvement_opportunities import (
    discover_opportunities,
    extract_facts_from_response,
    retaylor_with_confirmed_facts,
)
from app.services.optimization.jd_requirements import parse_universal_jd
from app.services.optimization.resume_reconstruction import (
    extract_real_metrics,
    reconstruct_bullet,
    reconstruct_profile_projects_and_experience,
)
from app.services.optimization.skill_relationships import (
    RequirementCategory,
    RelationshipStrength,
    classify_requirement_type,
    skill_relationship_engine,
)


# ===========================================================================
# 1. Requirement Classification Tests
# ===========================================================================

def test_classify_soft_and_behavioral_skills() -> None:
    soft_phrases = [
        "Strong communication skills",
        "Teamwork and collaboration across teams",
        "Leadership and mentoring junior engineers",
        "Problem solving and analytical thinking",
        "Adaptability in fast-paced environments",
        "Time management and prioritization",
        "Meticulous attention to detail",
        "Stakeholder management and negotiation",
    ]
    for phrase in soft_phrases:
        cat, _ = classify_requirement_type(phrase)
        assert cat == RequirementCategory.SOFT_SKILL, f"Failed for {phrase}: got {cat}"


def test_classify_productivity_and_office_tools() -> None:
    office_phrases = [
        "Proficiency in Microsoft Office suite",
        "Advanced Excel spreadsheets and modeling",
        "Word and PowerPoint presentations",
        "Google Workspace docs and sheets",
        "Outlook calendar and email management",
        "Documentation tools and Confluence",
    ]
    for phrase in office_phrases:
        cat, _ = classify_requirement_type(phrase)
        assert cat == RequirementCategory.PRODUCTIVITY_OFFICE, f"Failed for {phrase}: got {cat}"


def test_classify_programming_languages_and_ecosystem_tools() -> None:
    cases = [
        ("Python programming", RequirementCategory.PROGRAMMING_LANGUAGE),
        ("JavaScript development", RequirementCategory.PROGRAMMING_LANGUAGE),
        ("TypeScript frontend", RequirementCategory.PROGRAMMING_LANGUAGE),
        ("Java enterprise services", RequirementCategory.PROGRAMMING_LANGUAGE),
        ("C# backend development", RequirementCategory.PROGRAMMING_LANGUAGE),
        ("SQL queries and data extracts", RequirementCategory.DATABASE),
        ("Pandas data manipulation", RequirementCategory.ECOSYSTEM_CORE),
        ("NumPy array computation", RequirementCategory.ECOSYSTEM_CORE),
        ("React component architecture", RequirementCategory.ECOSYSTEM_ASSOCIATED),
        ("Spring Boot microservices", RequirementCategory.ECOSYSTEM_CORE),
        ("ASP.NET Core web apis", RequirementCategory.ECOSYSTEM_CORE),
        ("PostgreSQL database", RequirementCategory.ECOSYSTEM_ASSOCIATED),
    ]
    for phrase, expected in cases:
        cat, _ = classify_requirement_type(phrase)
        assert cat == expected, f"Failed for {phrase}: expected {expected}, got {cat}"


def test_classify_specialized_technologies() -> None:
    specializations = [
        "TensorFlow deep learning models",
        "PyTorch neural networks",
        "PostgreSQL administration and DBA tuning",
        "VBA macro development in Excel",
        "Blazor web development in .NET",
    ]
    for phrase in specializations:
        cat, _ = classify_requirement_type(phrase)
        assert cat == RequirementCategory.SPECIALIZED_TECH, f"Failed for {phrase}: got {cat}"


# ===========================================================================
# 2. Multi-Ecosystem Skill Relationship Tests (Generic Architecture)
# ===========================================================================

def test_python_ecosystem_relationships() -> None:
    candidate_skills = {"Python"}
    # Core ecosystem
    strength, root, fam = skill_relationship_engine.evaluate_relationship(candidate_skills, "Pandas")
    assert strength == RelationshipStrength.STRONG_ECOSYSTEM
    assert root == "Python"
    assert fam is not None and fam.id == "python"

    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "NumPy")
    assert strength == RelationshipStrength.STRONG_ECOSYSTEM

    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "Matplotlib")
    assert strength == RelationshipStrength.STRONG_ECOSYSTEM

    # Commonly associated
    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "Scikit-Learn")
    assert strength == RelationshipStrength.COMMONLY_ASSOCIATED

    # Specialization: must NOT be auto-inferred as strong ecosystem
    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "TensorFlow")
    assert strength == RelationshipStrength.SPECIALIZATION

    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "PyTorch")
    assert strength == RelationshipStrength.SPECIALIZATION


def test_javascript_ecosystem_relationships() -> None:
    candidate_skills = {"JavaScript"}
    # Core ecosystem
    strength, _, fam = skill_relationship_engine.evaluate_relationship(candidate_skills, "Node.js")
    assert strength == RelationshipStrength.STRONG_ECOSYSTEM
    assert fam is not None and fam.id == "javascript"

    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "TypeScript")
    assert strength == RelationshipStrength.STRONG_ECOSYSTEM

    # Associated framework
    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "React")
    assert strength == RelationshipStrength.COMMONLY_ASSOCIATED

    # Specialization: cannot auto-infer React Native or Electron without evidence
    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "React Native")
    assert strength == RelationshipStrength.SPECIALIZATION


def test_java_ecosystem_relationships() -> None:
    candidate_skills = {"Java"}
    strength, root, fam = skill_relationship_engine.evaluate_relationship(candidate_skills, "Spring Boot")
    assert strength == RelationshipStrength.STRONG_ECOSYSTEM
    assert fam is not None and fam.id == "java"

    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "Hibernate")
    assert strength == RelationshipStrength.STRONG_ECOSYSTEM

    # Specialization
    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "Hadoop")
    assert strength == RelationshipStrength.SPECIALIZATION


def test_csharp_ecosystem_relationships() -> None:
    candidate_skills = {"C#"}
    strength, root, fam = skill_relationship_engine.evaluate_relationship(candidate_skills, ".NET")
    assert strength == RelationshipStrength.STRONG_ECOSYSTEM
    assert fam is not None and fam.id == "csharp"

    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "ASP.NET Core")
    assert strength == RelationshipStrength.STRONG_ECOSYSTEM

    # Specialization
    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "Unity")
    assert strength == RelationshipStrength.SPECIALIZATION


def test_sql_ecosystem_relationships() -> None:
    candidate_skills = {"SQL"}
    strength, root, fam = skill_relationship_engine.evaluate_relationship(candidate_skills, "database querying")
    assert strength == RelationshipStrength.STRONG_ECOSYSTEM

    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "PostgreSQL")
    assert strength == RelationshipStrength.COMMONLY_ASSOCIATED

    # Specialization: DBA / administration must NOT be auto-inferred
    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "PostgreSQL administration")
    assert strength == RelationshipStrength.SPECIALIZATION

    strength, _, _ = skill_relationship_engine.evaluate_relationship(candidate_skills, "Database Administration")
    assert strength == RelationshipStrength.SPECIALIZATION


# ===========================================================================
# 3. Automatic Handling & Question Suppression Tests
# ===========================================================================

def test_soft_skills_never_create_candidate_questions() -> None:
    content = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Alex Ray", email="alex@example.com"),
            summary="Engineer who coordinated with operations and resolved incidents.",
            skills=SkillCategory(technical=["Python"]),
            experience=[
                ExperienceItem(
                    company="Acme",
                    role="Software Engineer",
                    responsibilities=[
                        BulletItem(text="Coordinated with development and operations teams to resolve production incidents."),
                    ],
                )
            ],
        )
    )
    jd = (
        "Software Engineer\n\nRequirements:\n"
        "• Strong communication skills and cross-functional collaboration.\n"
        "• Proven teamwork and problem solving abilities.\n"
        "• Attention to detail and time management.\n"
        "• React and Docker experience.\n"
    )
    universal = parse_universal_jd(jd, "Software Engineer", "Acme")
    index = build_evidence_index(content)
    report = match_requirements(universal, index)
    opps = discover_opportunities(universal, report, index)

    labels = [o.display_label.lower() for o in opps]
    # Soft skills must NEVER appear in the candidate question cards!
    assert not any("communication" in l for l in labels)
    assert not any("teamwork" in l for l in labels)
    assert not any("collaboration" in l for l in labels)
    assert not any("problem solving" in l for l in labels)
    assert not any("attention to detail" in l for l in labels)
    assert not any("time management" in l for l in labels)
    # Only genuine unresolved technical gaps (React, Docker) surface
    assert any("react" in l for l in labels)


def test_office_skills_handled_as_family_no_individual_questions() -> None:
    # Candidate already has Excel and reporting
    content = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Sam Analyst", email="sam@example.com"),
            summary="Analyst building trackers and reporting.",
            skills=SkillCategory(technical=["Excel", "Reporting"]),
            experience=[
                ExperienceItem(
                    company="Corp",
                    role="Analyst",
                    responsibilities=[
                        BulletItem(text="Maintained spreadsheets and monthly reporting trackers."),
                    ],
                    tools=["Excel"],
                )
            ],
        )
    )
    jd = (
        "Operations Associate\n\nRequirements:\n"
        "• Microsoft Office, Word, Excel, PowerPoint, and Outlook.\n"
        "• Salesforce CRM experience.\n"
    )
    universal = parse_universal_jd(jd, "Operations Associate", "Corp")
    index = build_evidence_index(content)
    report = match_requirements(universal, index)
    opps = discover_opportunities(universal, report, index)

    labels = [o.display_label.lower() for o in opps]
    # Candidate already has office/spreadsheet evidence -> DO NOT ask about Word, PPT, Outlook!
    assert not any("word" in l for l in labels)
    assert not any("powerpoint" in l for l in labels)
    assert not any("outlook" in l for l in labels)
    assert not any("office" in l for l in labels)
    # Salesforce CRM is genuinely unresolved, so it can surface
    assert any("salesforce" in l for l in labels)


def test_python_and_project_context_suppresses_pandas_numpy_questions() -> None:
    # Candidate has Python and a Customer Churn Analysis project
    content = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Karan Dev", email="karan@example.com"),
            summary="Backend engineer with Python experience.",
            skills=SkillCategory(technical=["Python", "SQL", "Git"]),
            projects=[
                ProjectItem(
                    name="Customer Analytics Dashboard",
                    description="Analyzed customer churn data and identified behavioral patterns.",
                    technologies=["Python"],
                )
            ],
            experience=[
                ExperienceItem(
                    company="DataCorp",
                    role="Backend Developer",
                    responsibilities=[
                        BulletItem(text="Built Python data extraction scripts feeding SQL pipelines."),
                    ],
                    tools=["Python", "SQL"],
                )
            ],
        )
    )
    # JD asks for Python, Pandas, NumPy, Matplotlib, Docker, React, Communication
    jd = (
        "Full Stack Developer\n\nRequirements:\n"
        "• Python, Pandas, NumPy, and Matplotlib for data processing.\n"
        "• Docker and React for application development.\n"
        "• Strong communication and teamwork.\n"
    )
    universal = parse_universal_jd(jd, "Full Stack Developer", "TechCo")
    index = build_evidence_index(content)
    report = match_requirements(universal, index)
    opps = discover_opportunities(universal, report, index)

    labels = [o.display_label.lower() for o in opps]
    # Python is already known
    assert not any("python" == l for l in labels)
    # Soft skills never questioned
    assert not any("communication" in l for l in labels)
    assert not any("teamwork" in l for l in labels)
    # Pandas, NumPy, Matplotlib: candidate has Python + customer churn/analytics context!
    # They should NOT be interrogated as separate questions!
    assert not any("pandas" in l for l in labels)
    assert not any("numpy" in l for l in labels)
    assert not any("matplotlib" in l for l in labels)
    # Only unresolved external areas (Docker, React) surface in the batch!
    assert any("react" in l for l in labels)
    assert any("docker" in l for l in labels)


# ===========================================================================
# 4. Resume Reconstruction & Truthfulness Tests
# ===========================================================================

def test_bullet_reconstruction_problem_action_tech_outcome() -> None:
    # Weak bullet: "Worked on customer churn analysis using Python."
    weak_bullet = "Worked on customer churn analysis using Python."
    rebuilt = reconstruct_bullet(weak_bullet, {"Python"}, {"Python", "Pandas"})
    # Better: "Analyzed customer churn data using Python to identify behavioral patterns and support customer segmentation."
    assert "Analyzed" in rebuilt
    assert "Python" in rebuilt
    assert "identify behavioral patterns" in rebuilt
    # No invented numbers or metrics
    assert not extract_real_metrics(rebuilt)


def test_bullet_reconstruction_preserves_existing_real_metric() -> None:
    # Real metric already present in candidate bullet: "50,000+ customer records"
    metric_bullet = "Cleaned and analyzed 50,000+ customer records using Python and Pandas."
    rebuilt = reconstruct_bullet(metric_bullet, {"Python", "Pandas"}, {"Python"})
    assert "50,000+" in rebuilt
    assert "Python" in rebuilt


def test_reconstruction_never_invents_metrics_when_absent() -> None:
    raw_desc = "Analyzed customer data and identified churn patterns."
    rebuilt = reconstruct_bullet(raw_desc, {"Python"}, {"Python", "Pandas"})
    assert "Python" in rebuilt
    # No invented %, $, or numbers
    assert not extract_real_metrics(rebuilt)
    assert "50,000" not in rebuilt
    assert "%" not in rebuilt


def test_candidate_uncertain_recall_does_not_decline_or_weaken_resume() -> None:
    opps = [
        TailoringImprovementOpportunity(
            id="opp-react",
            requirement_id="React",
            normalized_requirement="react",
            display_label="React",
            opportunity_type=OpportunityType.TOOL_EXPOSURE,
        ),
        TailoringImprovementOpportunity(
            id="opp-docker",
            requirement_id="Docker",
            normalized_requirement="docker",
            display_label="Docker",
            opportunity_type=OpportunityType.TOOL_EXPOSURE,
        ),
    ]
    # Candidate says: "I used Docker at work, but I don't remember where I used React."
    resp = CandidateExperienceResponse(
        selected_ids=["opp-react", "opp-docker"],
        free_text="I used Docker at work, but I don't remember where I used React.",
    )
    result = extract_facts_from_response(opps, resp)
    # Docker confirmed
    confirmed_labels = [f.display_label for f in result.facts]
    assert "Docker" in confirmed_labels
    # React: candidate could not recall specific project -> MUST NOT be in declined_ids!
    assert "opp-react" not in result.declined_ids
    # React confirmed as background familiarity without false project attribution
    assert "React" in confirmed_labels


# ===========================================================================
# 5. Cross-Domain Matrix Tests
# ===========================================================================

def _make_resume(role: str, summary: str, skills: List[str], tools: List[str], bullets: List[str]) -> ResumeContent:
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Candidate", email="cand@example.com"),
            summary=summary,
            skills=SkillCategory(technical=skills, tools=tools),
            experience=[
                ExperienceItem(
                    company="PastCo",
                    role=role,
                    responsibilities=[BulletItem(text=b) for b in bullets],
                    tools=tools,
                )
            ],
        )
    )


@pytest.mark.parametrize(
    "source_role,source_skills,target_jd,expected_surfaced,expected_suppressed",
    [
        # 1. Backend -> Full Stack
        (
            "Backend Engineer",
            ["Python", "SQL", "Git"],
            "Full Stack\n\nRequirements:\n• React and TypeScript.\n• Python and SQL.\n• Teamwork.",
            ["React", "TypeScript"],
            ["Python", "SQL", "Teamwork"],
        ),
        # 2. Data -> Finance
        (
            "Data Analyst",
            ["SQL", "Excel", "Reporting"],
            "Finance Associate\n\nRequirements:\n• Accounting principles and reconciliations.\n• Excel and financial reporting.\n• Client communication.",
            ["Accounting", "reconciliations"],
            ["Excel", "reporting", "communication"],
        ),
        # 3. Finance -> Data
        (
            "Finance Associate",
            ["Accounting", "Excel", "Reconciliation"],
            "Financial Data Analyst\n\nRequirements:\n• Python and SQL for data analysis.\n• Excel financial models.\n• Problem solving.",
            ["Python", "SQL"],
            ["Excel", "Problem solving"],
        ),
        # 4. Operations -> Finance
        (
            "Operations Coordinator",
            ["Process Tracking", "Spreadsheets", "Vendor Follow-ups"],
            "Accounts Payable Specialist\n\nRequirements:\n• SAP ERP invoice processing.\n• Excel spreadsheets.\n• Organization and detail.",
            ["SAP", "invoice"],
            ["spreadsheets", "Organization"],
        ),
        # 5. Designer -> Product Designer
        (
            "Graphic Designer",
            ["Illustrator", "Photoshop", "Typography"],
            "Product Designer\n\nRequirements:\n• Figma and mobile prototyping.\n• Usability testing.\n• Collaboration with engineers.",
            ["Figma", "prototyping"],
            ["Collaboration"],
        ),
        # 6. Developer -> DevOps
        (
            "Software Developer",
            ["Java", "Git", "Linux"],
            "DevOps Engineer\n\nRequirements:\n• Terraform and Kubernetes.\n• Linux and Git.\n• Adaptability and incident response.",
            ["Terraform", "Kubernetes"],
            ["Linux", "Git", "Adaptability"],
        ),
        # 7. Analyst -> Product Analyst
        (
            "Business Analyst",
            ["SQL", "Excel", "Stakeholder Requirements"],
            "Product Analyst\n\nRequirements:\n• Mixpanel product analytics.\n• SQL queries and metrics.\n• Communication.",
            ["Mixpanel"],
            ["SQL", "Communication"],
        ),
        # 8. Fresher -> Specialized Analyst
        (
            "Junior Analyst",
            ["Python", "Statistics"],
            "Healthcare Data Analyst\n\nRequirements:\n• HIPAA compliance and clinical datasets.\n• Python data processing.\n• Teamwork.",
            ["HIPAA"],
            ["Python", "Teamwork"],
        ),
    ],
)
def test_cross_domain_matrix_questioning_and_suppression(
    source_role: str,
    source_skills: List[str],
    target_jd: str,
    expected_surfaced: List[str],
    expected_suppressed: List[str],
) -> None:
    content = _make_resume(
        role=source_role,
        summary=f"{source_role} with experience.",
        skills=source_skills,
        tools=["Git"],
        bullets=[f"Handled core responsibilities for {source_role}."],
    )
    universal = parse_universal_jd(target_jd, "Target Role", "TargetCo")
    index = build_evidence_index(content)
    report = match_requirements(universal, index)
    opps = discover_opportunities(universal, report, index)

    surfaced_text = " ".join(o.display_label.lower() for o in opps)

    for sup in expected_suppressed:
        assert sup.lower() not in surfaced_text, f"Expected '{sup}' to be suppressed, but was surfaced in {surfaced_text}"

    for surf in expected_surfaced:
        assert any(
            surf.lower() in o.display_label.lower() or surf.lower() in o.requirement_id.lower()
            for o in opps
        ), f"Expected '{surf}' to be surfaced, but opportunities were: {[o.display_label for o in opps]}"
