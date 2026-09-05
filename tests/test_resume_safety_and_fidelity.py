"""Adversarial resume corpus checks for grounding, style, and page fit."""

from __future__ import annotations

import fitz
import pytest

from app.models.resume import BulletItem, ExperienceItem, PersonalInfo, ResumeProfile
from app.services.optimization.semantic_guard import semantic_guard
from app.services.resume_parser.geometry import extract_document_geometry
from app.services.resume_parser.style_extractor import extract_document_style
from app.services.resumes.document_model import ResumeDocumentModel, ExperiencePosition
from app.services.resumes.fit_verifier import fit_verifier
from app.services.resumes.style_model import DocumentStyleModel
from .benchmark_resume_studio import FIXTURES


def _pdf(pages: int) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    result = doc.tobytes()
    doc.close()
    return result


@pytest.mark.parametrize("fixture_name", list(FIXTURES)[:10])
def test_adversarial_fixture_preserves_source_words_and_has_grounded_fallback(fixture_name: str) -> None:
    """Existing corpus covers columns, graphics, unusual fonts, short/dense, and multi-page resumes."""
    source = FIXTURES[fixture_name]()
    document = fitz.open(stream=source, filetype="pdf")
    source_words = set(" ".join(page.get_text() for page in document).lower().split())
    geometry = extract_document_geometry(document).to_dict()
    parsed_words = set(" ".join(block["text"] for page in geometry["pages"] for block in page["blocks"]).lower().split())
    document.close()
    assert source_words <= parsed_words

    source_profile = ResumeProfile(summary=" ".join(source_words))
    _, issues = semantic_guard.audit_tailored_profile(source_profile, {"summary": " ".join(source_words)})
    assert not issues


def test_semantic_guard_blocks_new_skill_scope_and_title() -> None:
    source = ResumeProfile(
        personal=PersonalInfo(full_name="Alex Morgan"),
        skills={"technical": ["Python", "Docker"]},
        experience=[ExperienceItem(role="Backend Engineer", responsibilities=[BulletItem(text="Built APIs with Python")])],
    )
    _, issues = semantic_guard.audit_tailored_profile(
        source,
        {
            "summary": "Backend Engineer proficient in Kubernetes.",
            "skills": {"technical": ["Python", "Kubernetes"]},
            "experience": [{"role": "Engineering Director", "responsibilities": [{"text": "Led a team using Kubernetes."}]}],
        },
    )
    assert any("Kubernetes" in issue for issue in issues)
    assert any("Engineering Director" in issue for issue in issues)
    assert any("led a team" in issue for issue in issues)


def test_span_style_extraction_flows_into_style_model() -> None:
    source = FIXTURES["10_unusual_fonts"]()
    document = fitz.open(stream=source, filetype="pdf")
    style = extract_document_style(document)
    document.close()
    assert style["body_font"]
    assert 10 <= style["body_size_pt"] <= 11.5
    assert len(style["heading_color_hex"]) == 6


def test_fit_verifier_trims_then_returns_single_page() -> None:
    model = ResumeDocumentModel(
        experience=[ExperiencePosition(role="Engineer", bullets=[BulletItem(text="low priority")])],
        style=DocumentStyleModel(body_size_pt=10.5, line_spacing=1.15),
    )

    def compile_pdf(candidate: ResumeDocumentModel) -> bytes:
        return _pdf(2 if candidate.experience[0].bullets else 1)

    result = fit_verifier.fit(model, compile_pdf)
    assert not result.needs_manual_review
    assert result.document.experience[0].bullets == []
    assert "Removed lowest-priority bullet" in result.audit[0]
