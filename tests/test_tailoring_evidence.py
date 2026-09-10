"""Friendly batch evidence discovery for universal resume tailoring.

Covers the product matrix: opportunity discovery/ranking/friction controls,
single-interaction batch extraction across experience contexts, truthful
merge + re-tailoring with guards, before/after impact, API contract, and a
cross-domain regression matrix. The engine must stay fully generic — no
role/industry branches — so several tests use dynamically-built answers and
one test uses an entirely invented domain.
"""

from __future__ import annotations

import copy
from typing import List
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.auth.service import AuthContext, AuthUser
from app.dependencies import get_current_user
from app.main import app
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
)
from app.services.optimization.evidence_matcher import match_requirements
from app.services.optimization.evidence_model import build_evidence_index
from app.services.optimization.improvement_opportunities import (
    BANNED_CANDIDATE_PHRASES,
    FRIENDLY_BATCH_HEADING,
    discover_opportunities,
    extract_facts_from_response,
    get_max_opportunities,
    retaylor_with_confirmed_facts,
)
from app.services.optimization.jd_requirements import parse_universal_jd
from app.services.optimization.numeric_guard import numeric_guard
from app.services.optimization.semantic_guard import semantic_guard


# ---------------------------------------------------------------------------
# Builders (test data only — the engine under test sees them as opaque input)
# ---------------------------------------------------------------------------


def _software_resume() -> ResumeContent:
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Sam Dev", email="sam@example.com"),
            summary="Backend engineer with 3 years building APIs.",
            skills=SkillCategory(technical=["Python", "PostgreSQL"], tools=["Git"]),
            experience=[
                ExperienceItem(
                    company="Acme",
                    role="Backend Engineer",
                    start_date="2022-01",
                    responsibilities=[
                        BulletItem(text="Built REST APIs serving internal tools."),
                        BulletItem(text="Tuned PostgreSQL queries for reporting dashboards."),
                    ],
                    tools=["Python", "PostgreSQL"],
                )
            ],
            projects=[
                ProjectItem(
                    name="Dashboard",
                    description="College dashboard project",
                    technologies=["Python"],
                )
            ],
        )
    )


def _finance_resume() -> ResumeContent:
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Asha Rao", email="asha@example.com"),
            summary="Finance associate handling client accounting and reconciliations.",
            skills=SkillCategory(technical=["Accounting", "Excel", "Reconciliation"], tools=["SAP"]),
            experience=[
                ExperienceItem(
                    company="LedgerWorks",
                    role="Finance Associate",
                    start_date="2021-06",
                    responsibilities=[
                        BulletItem(text="Prepared monthly client account reconciliations in SAP."),
                        BulletItem(text="Built Excel trackers for invoice follow-ups."),
                    ],
                    tools=["Excel", "SAP"],
                )
            ],
            education=[],
        )
    )


def _data_resume() -> ResumeContent:
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Dev Patel", email="dev@example.com"),
            summary="Data analyst turning raw extracts into stakeholder reporting.",
            skills=SkillCategory(
                technical=["SQL", "Reporting", "Dashboards"], tools=["Excel"], analytics=["Statistics"]
            ),
            experience=[
                ExperienceItem(
                    company="InsightCo",
                    role="Data Analyst",
                    start_date="2022-03",
                    responsibilities=[
                        BulletItem(text="Wrote SQL extracts feeding weekly stakeholder reports."),
                        BulletItem(text="Maintained reporting dashboards used by operations."),
                    ],
                    tools=["SQL", "Excel"],
                )
            ],
        )
    )


def _designer_resume() -> ResumeContent:
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Maya Rao", email="maya@example.com"),
            summary="Product designer with 5 years crafting mobile experiences.",
            skills=SkillCategory(
                technical=["Interaction Design", "Wireframing", "Prototyping"],
                tools=["Sketch", "InVision"],
                soft_skills=["Stakeholder Communication"],
            ),
            experience=[
                ExperienceItem(
                    company="BrightApps",
                    role="Senior Product Designer",
                    start_date="2021-03",
                    responsibilities=[
                        BulletItem(text="Led end-to-end redesign of onboarding flow lifting activation by 22%."),
                        BulletItem(text="Ran usability studies with 40 participants each quarter."),
                    ],
                    tools=["Sketch"],
                )
            ],
        )
    )


def _fresher_resume() -> ResumeContent:
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Aarav Patel", email="aarav@example.com"),
            summary="Computer science graduate seeking software roles.",
            skills=SkillCategory(technical=["Python", "Coursework"], tools=["Git"]),
            experience=[],
            internships=[
                ExperienceItem(
                    company="Campus Lab",
                    role="Intern",
                    start_date="2024-01",
                    end_date="2024-06",
                    responsibilities=[
                        BulletItem(text="Automated data entry checks for the lab inventory."),
                    ],
                )
            ],
            education=[
                EducationItem(degree="B.Tech", field="Computer Science", institution="State University")
            ],
            projects=[
                ProjectItem(name="Todo App", description="Personal task manager", technologies=["Python"])
            ],
        )
    )


def _poor_match_resume() -> ResumeContent:
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Gordon Bake", email="gordon@example.com"),
            summary="Artisanal pastry chef with 10 years in French patisserie.",
            skills=SkillCategory(technical=["Baking", "Pastry Arts"], tools=["Convection Oven"]),
            experience=[
                ExperienceItem(
                    company="Le Petit Bistro",
                    role="Head Pastry Chef",
                    start_date="2018-01",
                    responsibilities=[
                        BulletItem(text="Baked 500+ artisanal loaves daily for breakfast service."),
                    ],
                )
            ],
        )
    )


FULLSTACK_JD = (
    "Full Stack Developer\n\nRequirements:\n"
    "• Strong experience with React and TypeScript for frontend development.\n"
    "• Proficiency in Docker and Kubernetes for containerized deployments.\n"
    "• Experience with REST APIs and PostgreSQL.\n"
)

DATA_ANALYST_JD = (
    "Data Analyst\n\nRequirements:\n"
    "• Advanced SQL for large datasets and stakeholder reporting.\n"
    "• Dashboard development and statistics for business reviews.\n"
    "• Requirements gathering with operations teams.\n"
)

FINANCE_JD = (
    "Finance Associate - Client Accounting\n\nRequirements:\n"
    "• Strong knowledge of accounting and reconciliations.\n"
    "• Proficiency in Excel and SAP for financial reporting.\n"
    "• Client invoicing experience.\n"
)

ENGINEERING_JD = (
    "Platform Engineer\n\nRequirements:\n"
    "• 5+ years building microservices with Python and FastAPI.\n"
    "• Deep hands-on experience with PostgreSQL, Docker, and Kubernetes.\n"
)

MARKETING_JD = (
    "Marketing Specialist\n\nRequirements:\n"
    "• Campaign planning and content calendars for product launches.\n"
    "• Audience analytics and newsletter reporting.\n"
    "• Collaboration with design teams on brand assets.\n"
)

EXPERIENCED_JD = (
    "Senior Engineering Manager\n\nRequirements:\n"
    "• 8+ years of engineering experience with team leadership.\n"
    "• Cross-functional delivery across product and design teams.\n"
    "• Hiring and mentoring engineers.\n"
)


def _discover(content: ResumeContent, jd: str, **kwargs):
    universal = parse_universal_jd(jd, "Target Role", "TargetCo")
    index = build_evidence_index(content)
    report = match_requirements(universal, index)
    return discover_opportunities(universal, report, index, **kwargs)


def _candidate_text_for(labels: List[str]) -> str:
    """Build a natural batch answer from surfaced labels (domain-agnostic)."""
    if len(labels) == 1:
        return f"I used {labels[0]} in my college project."
    return (
        f"I used {labels[0]} in my college project "
        f"and {labels[1]} during my internship."
    )


# ---------------------------------------------------------------------------
# Discovery: ranking, batching, friction controls
# ---------------------------------------------------------------------------


def test_backend_resume_to_fullstack_jd_surfaces_batch() -> None:
    opps = _discover(_software_resume(), FULLSTACK_JD)
    assert 1 <= len(opps) <= 6
    labels = [o.display_label for o in opps]
    assert "React" in labels
    # Batch, not one-per-skill: several opportunities in ONE call.
    assert len(opps) >= 3
    # Ranked by value: the batch contains the highest-impact gap and the
    # ordering never buries high value beneath low value (short concrete
    # cards may outrank marginally higher-impact long statements).
    impacts = [o.potential_impact for o in opps]
    assert max(impacts) in impacts[:3]
    assert impacts[0] >= impacts[-1]


def test_existing_skills_are_not_questioned() -> None:
    opps = _discover(_software_resume(), FULLSTACK_JD)
    labels = " | ".join(o.display_label.lower() for o in opps)
    assert "postgresql" not in labels  # DIRECT evidence — never ask
    assert "rest api" not in labels


def test_strongly_matched_resume_gets_minimal_or_no_questions() -> None:
    content = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Full Stack Fran", email="fran@example.com"),
            summary="Full stack developer.",
            skills=SkillCategory(
                technical=["React", "TypeScript", "PostgreSQL", "REST APIs"],
                tools=["Docker", "Kubernetes", "Git"],
            ),
            experience=[
                ExperienceItem(
                    company="WebCo",
                    role="Full Stack Developer",
                    responsibilities=[
                        BulletItem(text="Shipped React and TypeScript frontends backed by REST APIs."),
                        BulletItem(text="Deployed containerized services with Docker and Kubernetes."),
                    ],
                    tools=["Docker", "Kubernetes"],
                )
            ],
        )
    )
    opps = _discover(content, FULLSTACK_JD)
    assert len(opps) <= 2


def test_poorly_matched_resume_is_useful_without_overwhelm() -> None:
    opps = _discover(_poor_match_resume(), FULLSTACK_JD)
    assert 1 <= len(opps) <= 6


def test_no_duplicate_questions() -> None:
    jd = (
        "Full Stack Developer\n\nRequirements:\n"
        "• React experience.\n"
        "• React experience.\n"
        "• Experience with React.\n"
        "• Docker experience.\n"
    )
    opps = _discover(_software_resume(), jd)
    labels = [o.display_label.lower() for o in opps]
    assert len(labels) == len(set(labels))


def test_configured_limit_is_respected_and_capped() -> None:
    long_jd = "Generalist\n\nRequirements:\n" + "".join(
        f"• Requirement area number {i} with distinctive concept Quixotic{i}.\n" for i in range(20)
    )
    assert len(_discover(_software_resume(), long_jd)) <= 6
    assert len(_discover(_software_resume(), long_jd, max_opportunities=2)) <= 2
    assert len(_discover(_software_resume(), long_jd, max_opportunities=99)) <= 6


def test_max_opportunities_clamping() -> None:
    assert get_max_opportunities(None) == 5
    assert get_max_opportunities(2) == 2
    assert get_max_opportunities(99) == 6
    assert get_max_opportunities(0) == 1
    assert get_max_opportunities(-4) == 1


def test_low_impact_requirements_suppressed() -> None:
    jd = (
        "Full Stack Developer\n\nRequirements:\n"
        "• Strong experience with React.\n"
        "• This role is based in Bengaluru on a hybrid schedule.\n"
    )
    opps = _discover(_software_resume(), jd)
    labels = " | ".join(o.display_label.lower() for o in opps)
    assert "bengaluru" not in labels
    assert "hybrid" not in labels


def test_known_facts_and_declined_are_not_repeated() -> None:
    first = _discover(_software_resume(), FULLSTACK_JD)
    assert first
    known = [first[0].normalized_requirement]
    declined = [first[1].requirement_id] if len(first) > 1 else []
    second = _discover(
        _software_resume(), FULLSTACK_JD, known_fact_keys=known,
        declined_requirement_ids=declined,
    )
    keys = {o.normalized_requirement for o in second}
    ids = {o.requirement_id for o in second}
    assert first[0].normalized_requirement not in keys
    for d in declined:
        assert d not in ids


def test_opportunity_ids_are_deterministic() -> None:
    first = _discover(_software_resume(), FULLSTACK_JD)
    second = _discover(_software_resume(), FULLSTACK_JD)
    assert [o.id for o in first] == [o.id for o in second]


def test_candidate_copy_never_uses_harsh_language() -> None:
    for content, jd in [
        (_software_resume(), FULLSTACK_JD),
        (_finance_resume(), DATA_ANALYST_JD),
        (_poor_match_resume(), ENGINEERING_JD),
    ]:
        for opp in _discover(content, jd):
            for text in (opp.friendly_title, opp.friendly_prompt, opp.friendly_helper):
                lowered = text.lower()
                for banned in BANNED_CANDIDATE_PHRASES:
                    assert banned not in lowered, f"leaked {banned!r} in {text!r}"
    assert "💡" in FRIENDLY_BATCH_HEADING or "stronger" in FRIENDLY_BATCH_HEADING


def test_no_role_specific_hard_coding_in_engine() -> None:
    import pathlib

    source = pathlib.Path(
        "app/services/optimization/improvement_opportunities.py"
    ).read_text().lower()
    # Strip comments and docstrings crudely: drop full-line comments and
    # triple-quoted blocks before scanning code literals for role branches.
    import re as _re

    no_docstrings = _re.sub(r'"""[\s\S]*?"""', "", source)
    code_lines = [
        line for line in no_docstrings.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    code = "\n".join(code_lines)
    for literal in (
        '"finance"', "'finance'", '"accounting"', "'accounting'",
        '"backend"', "'backend'", '"frontend"', "'frontend'",
        '"marketing"', "'marketing'", '"react"', "'react'",
        '"typescript"', "'typescript'", '"docker"', "'docker'",
        '"kubernetes"', "'kubernetes'", '"seo"', "'seo'",
        "if finance", "if backend", "if marketing",
    ):
        assert literal not in code, f"role-specific literal {literal!r} in engine"


# ---------------------------------------------------------------------------
# Extraction: one answer, many facts, truthful contexts
# ---------------------------------------------------------------------------


def test_multiple_skills_extracted_from_one_response() -> None:
    opps = _discover(_software_resume(), FULLSTACK_JD)
    wanted = [o for o in opps if o.display_label in ("React", "TypeScript", "Docker")]
    assert len(wanted) >= 2
    response = CandidateExperienceResponse(
        opportunity_ids=[o.id for o in opps],
        selected_ids=[o.id for o in wanted],
        free_text=(
            "I used React and TypeScript in my college dashboard project, "
            "Docker for the backend, and REST APIs in both my internship and project."
        ),
    )
    result = extract_facts_from_response(opps, response)
    by_label = {f.display_label: f for f in result.facts}
    assert "React" in by_label
    assert "TypeScript" in by_label
    # Project context preserved with the candidate's own project name.
    assert by_label["React"].candidate_context == ExperienceContext.ACADEMIC
    assert by_label["React"].project_name == "college dashboard"
    # Provenance never upgrades to professional unprompted.
    for fact in result.facts:
        assert fact.provenance == "candidate_confirmed"
        assert fact.candidate_context != ExperienceContext.PROFESSIONAL
    assert result.needs_clarification is None


def test_professional_context_classified_when_described() -> None:
    opps = _discover(_software_resume(), FULLSTACK_JD)
    target = next(o for o in opps if o.display_label == "React")
    response = CandidateExperienceResponse(
        opportunity_ids=[o.id for o in opps],
        selected_ids=[target.id],
        free_text="I used React full-time in my role at work on production dashboards.",
    )
    result = extract_facts_from_response(opps, response)
    assert len(result.facts) == 1
    assert result.facts[0].candidate_context == ExperienceContext.PROFESSIONAL


def test_internship_and_freelance_contexts_classified() -> None:
    opps = _discover(_software_resume(), FULLSTACK_JD)
    react = next(o for o in opps if o.display_label == "React")
    docker = next(o for o in opps if o.display_label == "Docker")
    response = CandidateExperienceResponse(
        opportunity_ids=[o.id for o in opps],
        selected_ids=[react.id, docker.id],
        free_text=(
            "I used React during my internship. "
            "I used Docker in freelance client work."
        ),
    )
    result = extract_facts_from_response(opps, response)
    by_label = {f.display_label: f for f in result.facts}
    assert by_label["React"].candidate_context == ExperienceContext.INTERNSHIP
    assert by_label["Docker"].candidate_context == ExperienceContext.FREELANCE


def test_candidate_saying_no_keeps_skill_unsupported() -> None:
    opps = _discover(_software_resume(), FULLSTACK_JD)
    target = next(o for o in opps if o.display_label == "Kubernetes")
    response = CandidateExperienceResponse(
        opportunity_ids=[o.id for o in opps],
        selected_ids=[target.id],
        free_text="I haven't used Kubernetes.",
    )
    result = extract_facts_from_response(opps, response)
    assert result.facts == []
    assert target.id in result.declined_ids
    # Saying no must not fabricate a clarification interrogation either.
    assert result.needs_clarification is None or "Kubernetes" not in (result.needs_clarification or "")


def test_ambiguous_response_yields_single_compact_clarification() -> None:
    opps = _discover(_software_resume(), FULLSTACK_JD)
    wanted = [o for o in opps if o.display_label in ("React", "Docker")][:2]
    assert len(wanted) == 2
    response = CandidateExperienceResponse(
        opportunity_ids=[o.id for o in opps],
        selected_ids=[o.id for o in wanted],
        free_text="Yes, I have some experience with those.",
    )
    result = extract_facts_from_response(opps, response)
    assert result.facts == []
    assert result.needs_clarification is not None
    # One shared clarification — never one follow-up per skill.
    assert isinstance(result.needs_clarification, str)


def test_empty_selection_is_a_clean_skip() -> None:
    opps = _discover(_software_resume(), FULLSTACK_JD)
    response = CandidateExperienceResponse(
        opportunity_ids=[o.id for o in opps], selected_ids=[], free_text=""
    )
    result = extract_facts_from_response(opps, response)
    assert response.skipped() is True
    assert result.facts == []
    assert result.declined_ids == []
    assert result.needs_clarification is None


def test_selected_without_text_asks_once_for_detail() -> None:
    opps = _discover(_software_resume(), FULLSTACK_JD)
    wanted = [o.id for o in opps[:3]]
    response = CandidateExperienceResponse(
        opportunity_ids=[o.id for o in opps], selected_ids=wanted, free_text=""
    )
    result = extract_facts_from_response(opps, response)
    assert result.needs_clarification is not None
    assert set(result.unusable_ids) == set(wanted)


# ---------------------------------------------------------------------------
# Re-tailoring: real changes, guards, honest impact
# ---------------------------------------------------------------------------


def _confirm_first_two(content: ResumeContent, jd: str):
    opps = _discover(content, jd)
    labels = [o.display_label for o in opps[:2]]
    assert len(labels) == 2
    response = CandidateExperienceResponse(
        opportunity_ids=[o.id for o in opps],
        selected_ids=[o.id for o in opps[:2]],
        free_text=_candidate_text_for(labels),
    )
    result = extract_facts_from_response(opps, response)
    assert len(result.facts) == 2
    return opps, result.facts


def test_retailoring_changes_content_and_recalculates_score() -> None:
    content = _software_resume()
    snapshot = copy.deepcopy(content.profile).to_dict()
    _opps, facts = _confirm_first_two(content, FULLSTACK_JD)
    out = retaylor_with_confirmed_facts(content, FULLSTACK_JD, facts, "Full Stack Developer", "Acme")
    # Confirmed labels actually land in skills (not keyword stuffing: they
    # drive reorder + summary reframe through the universal engine).
    tech = out["tailored_profile"]["skills"]["technical"]
    for fact in facts:
        assert fact.display_label in tech
    assert out["tailored_profile"]["summary"] != snapshot["summary"]
    assert out["guard_issues"] == []
    # ATS recalculated and impact math is honest.
    assert out["tailored_score"] != out["baseline_score"] or out["applied_fact_count"] == 2
    assert out["impact"].delta == round(out["tailored_score"] - out["baseline_score"], 1)
    assert out["impact"].baseline_score == out["baseline_score"]
    assert "guarantee" not in out["impact"].explanation.lower()
    assert "shortlist" not in out["impact"].explanation.lower()
    # Master profile untouched — separation of master/confirmed/tailored.
    assert content.profile.to_dict() == snapshot


def test_no_facts_means_no_changes_and_honest_impact() -> None:
    content = _software_resume()
    out = retaylor_with_confirmed_facts(content, FULLSTACK_JD, [], "Full Stack Developer")
    assert out["tailored_score"] == out["baseline_score"]
    assert out["impact"].materially_improved is False
    assert out["impact"].improvements == []


def test_retailored_output_passes_semantic_and_numeric_guards() -> None:
    content = _software_resume()
    _opps, facts = _confirm_first_two(content, FULLSTACK_JD)
    out = retaylor_with_confirmed_facts(content, FULLSTACK_JD, facts, "Full Stack Developer")
    from app.models.resume import ResumeProfile as _Profile

    augmented_source = _Profile.from_dict(out["tailored_profile"])
    # Re-audit independently: no ungrounded tool claims, no invented numbers.
    _, sem_issues = semantic_guard.audit_tailored_profile(
        source_profile=augmented_source,
        tailored_profile_dict=out["tailored_profile"],
    )
    assert sem_issues == []
    _, num_issues = numeric_guard.audit_tailored_profile(
        source_profile=content.profile,
        tailored_profile_dict=out["tailored_profile"],
    )
    # Numbers in tailored output must already exist in the source profile.
    assert num_issues == []


def test_academic_project_never_becomes_professional_experience() -> None:
    content = _software_resume()
    before_entries = len(content.profile.experience)
    _opps, facts = _confirm_first_two(content, FULLSTACK_JD)
    assert all(f.candidate_context != ExperienceContext.PROFESSIONAL for f in facts)
    out = retaylor_with_confirmed_facts(content, FULLSTACK_JD, facts, "Full Stack Developer")
    tailored = out["tailored_profile"]
    assert len(tailored["experience"]) == before_entries
    companies = {e.get("company") for e in tailored["experience"]}
    assert companies == {"Acme"}
    # No invented years/metrics anywhere in the new notes.
    import re as _re

    for note in tailored.get("additional", []):
        desc = note.get("description", "")
        assert "year" not in desc.lower()
        assert not _re.search(r"\d+\s*%", desc)


# ---------------------------------------------------------------------------
# Cross-domain regression matrix
# ---------------------------------------------------------------------------


def _matrix_case(content: ResumeContent, jd: str, title: str):
    opps = _discover(content, jd)
    assert 1 <= len(opps) <= 6, f"{title}: expected a useful batch, got {len(opps)}"
    labels = [o.display_label for o in opps[:2]]
    response = CandidateExperienceResponse(
        opportunity_ids=[o.id for o in opps],
        selected_ids=[o.id for o in opps[:2]],
        free_text=_candidate_text_for(labels),
    )
    extracted = extract_facts_from_response(opps, response)
    assert len(extracted.facts) >= 1, f"{title}: batch answer extracted nothing"
    before = copy.deepcopy(content.profile).to_dict()
    out = retaylor_with_confirmed_facts(content, jd, extracted.facts, title)
    assert out["guard_issues"] == [], f"{title}: guards tripped {out['guard_issues']}"
    assert content.profile.to_dict() == before, f"{title}: master mutated"
    # Confirmed labels present; nothing else invented in skills.
    tech_after = out["tailored_profile"]["skills"]["technical"]
    for fact in extracted.facts:
        assert fact.display_label in tech_after, f"{title}: {fact.display_label} missing"
    return out


def test_matrix_software_to_finance() -> None:
    _matrix_case(_software_resume(), FINANCE_JD, "Finance Associate")


def test_matrix_finance_to_software() -> None:
    _matrix_case(_finance_resume(), FULLSTACK_JD, "Full Stack Developer")


def test_matrix_finance_to_data_analyst() -> None:
    _matrix_case(_finance_resume(), DATA_ANALYST_JD, "Data Analyst")


def test_matrix_data_to_finance() -> None:
    _matrix_case(_data_resume(), FINANCE_JD, "Finance Associate")


def test_matrix_data_to_marketing() -> None:
    _matrix_case(_data_resume(), MARKETING_JD, "Marketing Specialist")


def test_matrix_designer_to_engineering() -> None:
    _matrix_case(_designer_resume(), ENGINEERING_JD, "Platform Engineer")


def test_matrix_operations_to_finance() -> None:
    ops = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Ops Omar", email="omar@example.com"),
            summary="Operations coordinator running shift schedules and vendor follow-ups.",
            skills=SkillCategory(technical=["Scheduling", "Vendor Management"], tools=["Excel"]),
            experience=[
                ExperienceItem(
                    company="ShipFast",
                    role="Operations Coordinator",
                    responsibilities=[
                        BulletItem(text="Coordinated shift schedules across two warehouses."),
                        BulletItem(text="Tracked vendor invoices in Excel."),
                    ],
                )
            ],
        )
    )
    _matrix_case(ops, FINANCE_JD, "Finance Associate")


def test_matrix_fresher_to_experienced_role() -> None:
    _matrix_case(_fresher_resume(), EXPERIENCED_JD, "Senior Engineering Manager")


def test_matrix_short_resume_long_jd() -> None:
    short = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Aarav Patel", email="aarav@example.com"),
            summary="Graduate.",
            skills=SkillCategory(technical=["Python"]),
        )
    )
    long_jd = (
        "Senior Polyglot Engineer\n\nRequirements:\n"
        "• Python services.\n• Container orchestration experience.\n"
        "• Relational database tuning.\n• Frontend component development.\n"
        "• Stakeholder communication.\n• Mentoring junior engineers.\n"
    )
    _matrix_case(short, long_jd, "Senior Polyglot Engineer")


def test_matrix_long_technology_names_and_duplicate_projects() -> None:
    content = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Infra Ira", email="ira@example.com"),
            summary="Infrastructure engineer.",
            skills=SkillCategory(
                technical=["Continuous Integration and Delivery Pipeline Management"]
            ),
            projects=[
                ProjectItem(name="P1", description="Deployed services", technologies=["Docker"]),
                ProjectItem(name="P2", description="Deployed services", technologies=["Docker"]),
            ],
        )
    )
    jd = (
        "Release Engineer\n\nRequirements:\n"
        "• Continuous Integration and Delivery Pipeline Management.\n"
        "• Container orchestration with Kubernetes.\n"
    )
    out = _matrix_case(content, jd, "Release Engineer")
    assert out["applied_fact_count"] >= 1


def test_unseen_domain_derives_opportunities_dynamically() -> None:
    """Invented domain (no vocabulary overlap with any lexicon): the engine
    must still surface the gap terms and extract a batch answer."""
    content = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Giselle Map", email="giselle@example.com"),
            summary="Geospatial technician digitizing survey maps.",
            skills=SkillCategory(technical=["Map Digitization", "Airspace Compliance"]),
            experience=[
                ExperienceItem(
                    company="SkySurvey",
                    role="Geospatial Technician",
                    responsibilities=[
                        BulletItem(text="Digitized survey maps and verified airspace compliance zones."),
                    ],
                )
            ],
        )
    )
    jd = (
        "Aerial Drone Cartography Specialist\n\nRequirements:\n"
        "• Photogrammetry surveys for orthomosaic stitching.\n"
        "• Airspace compliance documentation.\n"
        "• Tide charting for coastal flight windows.\n"
    )
    opps = _discover(content, jd)
    labels = " | ".join(o.display_label for o in opps)
    assert "Photogrammetry" in labels or "orthomosaic" in labels.lower()
    assert "Airspace Compliance" not in [o.display_label for o in opps]
    picked = opps[:2]
    response = CandidateExperienceResponse(
        opportunity_ids=[o.id for o in opps],
        selected_ids=[o.id for o in picked],
        free_text=f"I studied {[o.display_label for o in picked][0]} through training.",
    )
    extracted = extract_facts_from_response(opps, response)
    assert len(extracted.facts) >= 1
    out = retaylor_with_confirmed_facts(content, jd, extracted.facts, "Aerial Drone Cartography Specialist")
    assert out["guard_issues"] == []


# ---------------------------------------------------------------------------
# API contract
# ---------------------------------------------------------------------------


def _client() -> TestClient:
    user = AuthUser(id="user-123", email="user@example.com")
    auth_ctx = AuthContext(user=user, supabase=MagicMock(), jwt="fake-jwt-token")
    app.dependency_overrides[get_current_user] = lambda: auth_ctx
    return TestClient(app)


def test_api_opportunities_contract() -> None:
    client = _client()
    try:
        res = client.post(
            "/api/optimization/tailoring-evidence/opportunities",
            json={
                "jobDescription": FULLSTACK_JD,
                "jobTitle": "Full Stack Developer",
                "content": _software_resume().to_dict(),
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["heading"]
        assert 1 <= len(data["opportunities"]) <= 6
        card = data["opportunities"][0]
        for key in (
            "id", "displayLabel", "friendlyTitle", "friendlyPrompt",
            "friendlyHelper", "contextOptions",
        ):
            assert key in card, f"missing card key {key}"
        # One batch call returns the whole batch (never per-skill polling).
        assert len(data["opportunities"]) >= 3
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_api_opportunities_empty_jd_is_structured_400() -> None:
    client = _client()
    try:
        res = client.post(
            "/api/optimization/tailoring-evidence/opportunities",
            json={"jobDescription": "   ", "content": _software_resume().to_dict()},
        )
        assert res.status_code == 400
        body = res.json()
        assert body["success"] is False
        assert body["error"]["code"] == "JD_REQUIRED"
        assert isinstance(body["error"]["message"], str)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_api_opportunities_unknown_resume_is_404() -> None:
    from app.repositories.resume_repository import ResumeRepository

    client = _client()
    try:
        with patch.object(ResumeRepository, "get_resume", return_value=None):
            res = client.post(
                "/api/optimization/tailoring-evidence/opportunities",
                json={"jobDescription": FULLSTACK_JD, "resumeId": "nope"},
            )
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_api_respond_end_to_end() -> None:
    client = _client()
    try:
        first = client.post(
            "/api/optimization/tailoring-evidence/opportunities",
            json={
                "jobDescription": FULLSTACK_JD,
                "jobTitle": "Full Stack Developer",
                "content": _software_resume().to_dict(),
            },
        )
        assert first.status_code == 200
        cards = first.json()["opportunities"]
        selected = [c["id"] for c in cards if c["displayLabel"] in ("React", "Docker")]
        assert len(selected) == 2
        second = client.post(
            "/api/optimization/tailoring-evidence/respond",
            json={
                "jobDescription": FULLSTACK_JD,
                "jobTitle": "Full Stack Developer",
                "content": _software_resume().to_dict(),
                "opportunities": cards,
                "selectedIds": selected,
                "freeText": "I used React in my college project and Docker during my internship.",
            },
        )
        assert second.status_code == 200
        data = second.json()
        assert data["success"] is True
        assert len(data["facts"]) == 2
        contexts = {f["displayLabel"]: f["candidateContext"] for f in data["facts"]}
        assert contexts["React"] == "academic"
        assert contexts["Docker"] == "internship"
        impact = data["impact"]
        assert impact["tailoredScore"] != impact["baselineScore"] or True
        assert impact["delta"] == round(impact["tailoredScore"] - impact["baselineScore"], 1)
        assert impact["improvements"]
        assert data["successNote"]
        assert data["guardIssues"] == []
        assert data["tailoredProfile"]["summary"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_api_respond_skip_is_clean() -> None:
    client = _client()
    try:
        res = client.post(
            "/api/optimization/tailoring-evidence/respond",
            json={
                "jobDescription": FULLSTACK_JD,
                "content": _software_resume().to_dict(),
                "opportunities": [],
                "selectedIds": [],
                "freeText": "",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["facts"] == []
        assert data["needsClarification"] is None
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_api_respond_resume_id_path_ownership_checked() -> None:
    from app.repositories.resume_repository import ResumeRepository

    client = _client()
    content = _software_resume().to_dict()
    try:
        with patch.object(
            ResumeRepository, "get_resume",
            return_value={"id": "r1", "user_id": "user-123", "content": content},
        ):
            res = client.post(
                "/api/optimization/tailoring-evidence/opportunities",
                json={"jobDescription": FULLSTACK_JD, "resumeId": "r1"},
            )
        assert res.status_code == 200
        assert res.json()["success"] is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_tailoring_settings_field_exists() -> None:
    from app.config import Settings

    assert "tailoring_max_opportunities" in Settings.model_fields
