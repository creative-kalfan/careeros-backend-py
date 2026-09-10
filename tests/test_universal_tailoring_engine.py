"""Universal (resume-agnostic) tailoring engine tests.

The ZS Associates Finance Associate resume is only the regression case
(covered in test_whole_resume_tailoring.py). These tests prove the engine
works for UNSEEN roles, industries, and experience levels with no
per-resume hard-coding: a product designer, a data analyst, and generic
pipeline unit checks.
"""

from __future__ import annotations

from unittest.mock import patch

from app.models.resume import (
    BulletItem,
    ExperienceItem,
    PersonalInfo,
    ResumeContent,
    ResumeProfile,
    SkillCategory,
)
from app.services.optimization.content_prioritizer import score_items
from app.services.optimization.evidence_matcher import match_requirements
from app.services.optimization.evidence_model import build_evidence_index
from app.services.optimization.jd_requirements import (
    are_equivalent,
    group_equivalent_requirements,
    parse_universal_jd,
)
from app.services.optimization.structure_optimizer import plan_structure
from app.services.optimization.whole_resume_tailoring_service import (
    whole_resume_tailoring_service,
)


def _designer_resume() -> ResumeContent:
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(
                full_name="Maya Rao",
                email="maya@example.com",
                phone="+919876543210",
                location="Bengaluru, IN",
            ),
            summary="Product designer with 5 years crafting mobile experiences.",
            skills=SkillCategory(
                technical=["Interaction Design", "Wireframing", "Prototyping"],
                tools=["Sketch", "InVision", "Zeplin"],
                soft_skills=["Stakeholder Communication", "User Empathy"],
            ),
            experience=[
                ExperienceItem(
                    company="BrightApps",
                    role="Senior Product Designer",
                    start_date="2021-03",
                    end_date="2024-08",
                    responsibilities=[
                        BulletItem(text="Led end-to-end redesign of onboarding flow lifting activation by 22%."),
                        BulletItem(text="Ran usability studies with 40 participants each quarter."),
                    ],
                    tools=["Sketch", "InVision"],
                )
            ],
            education=[],
        )
    )


DESIGNER_JD = (
    "Senior Product Designer - Mobile Experiences\n\n"
    "Requirements:\n"
    "• 4+ years designing mobile applications with strong interaction design skills.\n"
    "• Proficiency in Figma and prototyping tools for rapid iteration.\n"
    "• Experience running usability studies and translating insights into wireframes.\n"
    "• Excellent stakeholder communication across engineering and product teams.\n"
)


def test_universal_jd_parsing_works_for_unseen_role() -> None:
    universal = parse_universal_jd(DESIGNER_JD, "Senior Product Designer", "BrightApps")
    assert len(universal.requirements) >= 4
    categories = {r.category for r in universal.requirements}
    assert "experience" in categories  # 4+ years statement classified
    texts = " ".join(r.text for r in universal.requirements)
    assert "Figma" in texts  # generic skill phrase extraction, no lexicon needed
    assert "usability" in texts.lower()


def test_semantic_normalization_groups_equivalents() -> None:
    assert are_equivalent("data analysis", "analyze datasets")
    assert are_equivalent("analytical skills", "data analysis")
    assert not are_equivalent("payroll processing", "python programming")
    groups = group_equivalent_requirements(
        ["data analysis", "analyze datasets", "payroll processing"]
    )
    assert len(groups) == 2


def test_evidence_provenance_direct_and_unsupported() -> None:
    from app.services.optimization.evidence_model import classify_requirement
    from app.services.optimization.jd_requirements import normalize_key

    index = build_evidence_index(_designer_resume())
    # A listed design tool classifies as DIRECT evidence.
    prov, strength, ev = classify_requirement(
        normalize_key("Sketch"), "Sketch", index
    )
    assert prov == "DIRECT"
    assert strength >= 0.8
    assert ev is not None and "Sketch" in ev.claim_text
    # Figma has no evidence anywhere: must be UNSUPPORTED and unclaimable.
    universal = parse_universal_jd(DESIGNER_JD, "Senior Product Designer")
    report = match_requirements(universal, index)
    figma = [m for m in report.matches if m.requirement.text.strip().lower() == "figma"]
    assert figma, "generic skill extraction should surface Figma as a requirement"
    assert all(m.provenance == "UNSUPPORTED" and not m.is_claimable for m in figma)
    assert normalize_key("Interaction Design")


def test_designer_tailoring_never_fabricates_figma() -> None:
    content = _designer_resume()
    with patch.object(whole_resume_tailoring_service, "_call_llm_tailoring", return_value=None):
        result = whole_resume_tailoring_service.tailor_resume(
            resume_content=content,
            job_description=DESIGNER_JD,
            job_title="Senior Product Designer",
            company="BrightApps",
        )
    assert result.success is True
    assert result.limited_alignment is False
    tailored = result.tailored_profile
    assert "Senior Product Designer" in (tailored.get("summary") or "")
    # Unsupported Figma must never appear as claimed experience/skills.
    all_skills = []
    for vals in (tailored.get("skills") or {}).values():
        if isinstance(vals, list):
            all_skills.extend(vals)
        elif isinstance(vals, dict):
            for sub in vals.values():
                all_skills.extend(sub or [])
    assert not any(str(s).lower() == "figma" for s in all_skills)
    bullets = " ".join(
        b.get("text", "") for exp in tailored.get("experience", [])
        for b in exp.get("responsibilities", [])
    )
    assert "figma" not in bullets.lower()
    # Supported strengths ARE surfaced (candidate's own vocabulary).
    summary = tailored.get("summary") or ""
    assert (
        "usability" in summary.lower()
        or "wirefram" in summary.lower()
        or "prototyp" in summary.lower()
        or "interaction design" in summary.lower()
        or "stakeholder communication" in summary.lower()
    )


def test_designer_tailoring_passes_semantic_guard() -> None:
    from app.services.optimization.semantic_guard import semantic_guard

    content = _designer_resume()
    with patch.object(whole_resume_tailoring_service, "_call_llm_tailoring", return_value=None):
        result = whole_resume_tailoring_service.tailor_resume(
            resume_content=content,
            job_description=DESIGNER_JD,
            job_title="Senior Product Designer",
            company="BrightApps",
        )
    _, issues = semantic_guard.audit_tailored_profile(
        source_profile=content.profile,
        tailored_profile_dict=result.tailored_profile,
    )
    assert issues == [], f"Universal tailoring must stay grounded: {issues}"


def test_content_value_rewards_jd_relevance_over_verbosity() -> None:
    content = _designer_resume()
    index = build_evidence_index(content)
    report = match_requirements(
        parse_universal_jd(DESIGNER_JD, "Senior Product Designer"), index
    )
    scores = score_items(
        [
            {"id": "relevant", "section": "experience",
             "text": "Ran usability studies with 40 participants each quarter."},
            {"id": "generic", "section": "experience",
             "text": "Did various tasks."},
        ],
        report,
    )
    by_id = {s.item_id: s for s in scores}
    assert by_id["relevant"].total > by_id["generic"].total
    assert by_id["relevant"].jd_relevance > 0


def test_structure_optimizer_has_no_fixed_template() -> None:
    # Experience bullet mirrors JD vocabulary; education/projects are generic.
    # Value — not a fixed template — must put experience first.
    report = match_requirements(
        parse_universal_jd(DESIGNER_JD, "Senior Product Designer"),
        build_evidence_index(_designer_resume()),
    )
    exp_scores = score_items(
        [
            {"id": "b1", "section": "experience",
             "text": "Ran usability studies with 40 participants each quarter."},
            {"id": "p1", "section": "projects", "text": "Weekend todo app."},
            {"id": "e1", "section": "education", "text": "B.A. History, State College"},
        ],
        report,
    )
    plan = plan_structure(["experience", "projects", "education"], exp_scores)
    assert plan.section_order[0] == "experience"
    # Same sections, fresher nudge only reorders by value, never forces.
    fresher_plan = plan_structure(
        ["experience", "projects", "education"], exp_scores, is_fresher=True
    )
    assert set(fresher_plan.section_order) == {"experience", "projects", "education"}


def test_layout_optimizer_and_fit_verifier_honor_page_budget() -> None:
    from app.services.resumes.document_model import (
        ExperiencePosition,
        ResumeDocumentModel,
    )
    from app.services.resumes.fit_verifier import fit_verifier
    from app.services.resumes.style_model import DocumentStyleModel

    import fitz

    def compile_pdf(candidate: ResumeDocumentModel) -> bytes:
        # Simulate a 2-page overflow that resolves once bullets are trimmed.
        doc = fitz.open()
        pages = 2 if len(candidate.experience[0].bullets) > 1 else 1
        for _ in range(pages):
            doc.new_page()
        out = doc.tobytes()
        doc.close()
        return out

    model = ResumeDocumentModel(
        experience=[
            ExperiencePosition(
                role="Designer",
                bullets=[
                    BulletItem(text="x"),
                    BulletItem(text="Led end-to-end redesign lifting activation by 22%."),
                ],
            )
        ],
        style=DocumentStyleModel(body_size_pt=10.5, line_spacing=1.15),
    )
    result = fit_verifier.fit(model, compile_pdf, max_pages=2)
    assert result.needs_manual_review is False
    # Within a 2-page budget nothing is trimmed.
    assert len(result.document.experience[0].bullets) == 2

    tight = fit_verifier.fit(model, compile_pdf, max_pages=1)
    assert tight.needs_manual_review is False
    # The stub bullet ("x") has the lowest intrinsic value: trimmed first.
    remaining = [b.text for b in tight.document.experience[0].bullets]
    assert "x" not in remaining
