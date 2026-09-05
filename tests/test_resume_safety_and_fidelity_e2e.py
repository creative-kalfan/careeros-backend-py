"""Real end-to-end rendering and artifact generation tests for style extraction and fit loop."""

from __future__ import annotations

import json
import os
from pathlib import Path
import fitz
import pytest
from PIL import Image

from app.models.resume import BulletItem, ExperienceItem, PersonalInfo, ResumeContent, ResumeProfile, SkillCategory
from app.services.resume_parser.adapters import parsed_resume_to_resume_content
from app.services.resume_parser.pdf_parser import PDFParser
from app.services.resume_parser.style_extractor import extract_document_style
from app.services.resumes.document_model import build_document_model
from app.services.resumes.docx_compiler import docx_compiler
from app.services.resumes.fit_verifier import fit_verifier
from app.services.resumes.pdf_compiler import pdf_compiler
from app.services.resumes.style_model import DocumentStyleModel
from .benchmark_resume_studio import FIXTURES


ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
STYLE_ARTIFACTS = ARTIFACTS_DIR / "style_extraction"
FIT_ARTIFACTS = ARTIFACTS_DIR / "fit_loop"


@pytest.fixture(scope="session", autouse=True)
def ensure_artifact_directories() -> None:
    STYLE_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    FIT_ARTIFACTS.mkdir(parents=True, exist_ok=True)


def _render_pdf_to_image(pdf_bytes: bytes, page_idx: int = 0, dpi: int = 150) -> Image.Image:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_idx]
    pix = page.get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    return img


# ---------------------------------------------------------------------------
# Step 2: Visual evidence and programmatic assertions for Style Extraction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "fixture_name, expected_font_substring",
    [
        ("9_graphics_and_images", "helv"),
        ("10_unusual_fonts", "Impact"),
        ("2_two_column", "helv"),
    ],
)
def test_style_extraction_e2e_render_and_assert(fixture_name: str, expected_font_substring: str) -> None:
    """Run real parse -> style-extract -> compile -> PDF render, save screenshot, and assert fidelity."""
    source_pdf = FIXTURES[fixture_name]()
    
    # 1. Inspect source PDF with PyMuPDF
    source_doc = fitz.open(stream=source_pdf, filetype="pdf")
    extracted_style = extract_document_style(source_doc)
    source_doc.close()

    # 2. Parse via real parser
    parser = PDFParser()
    parse_result = parser.parse(source_pdf)
    assert parse_result.status == "completed"
    assert parse_result.geometry is not None
    assert "document_style" in parse_result.geometry

    # 3. Content equality and leak assertions for Defect 1 (9_graphics_and_images)
    if fixture_name == "9_graphics_and_images":
        p = parse_result.parsed
        # Exact content assertions per section
        assert p.contact.name == "ELENA ROSTOVA"
        assert p.contact.email == "elena.rostova@design.io"
        assert p.contact.location == "San Francisco, CA"
        assert p.summary == (
            "Senior Product Designer with deep engineering background creating human-centered design systems. "
            "Maintained 100% vector asset consistency across web, mobile, and print mediums."
        )
        assert len(p.experience) == 1
        assert p.experience[0].title == "Lead Product Designer"
        assert p.experience[0].company == "VectorWorks Studio"
        assert p.experience[0].start_date == "2020"
        assert p.experience[0].end_date == "Present"
        assert p.experience[0].bullets == [
            "Spearheaded unified multi-platform component architecture used by 4M active users.",
            "Reduced visual regression incidents by 75% via automated token validation.",
        ]
        assert len(p.education) == 1
        assert p.education[0].degree == "B.Sc"
        assert p.education[0].institution == "Rhode Island School of Design"
        assert p.education[0].start_date == "2018"
        assert p.skills == ["Design Systems", "Figma", "Typography", "Motion Design", "Vector Illustration", "CSS3"]

        # Assert no vector drawing metadata or shape coordinates leaked into parsed content
        all_parsed_text = " ".join([
            p.contact.name, p.contact.email, p.contact.location or "", p.summary,
            " ".join(p.skills), " ".join(p.experience[0].bullets),
        ])
        for drawing_token in ["draw_rect", "draw_circle", "Point(", "Rect(", "0.93", "0.95", "fill=", "rgb"]:
            assert drawing_token not in all_parsed_text

    # 4. Content and font fallback/preservation assertions for Defect 2 (10_unusual_fonts)
    if fixture_name == "10_unusual_fonts":
        p = parse_result.parsed
        assert p.contact.name == "DR. ARLO CHEN"
        assert p.contact.email == "arlo.chen@linguistics.edu"
        assert p.contact.location == "Cambridge, MA"
        assert "Distinguished Academic Researcher" in p.summary
        assert len(p.experience) >= 1
        assert len(p.education) >= 1
        assert p.education[0].institution == "Harvard University"
        assert p.education[0].degree == "Ph.D."
        # Style extractor explicitly detected non-standard font (Impact)
        assert extracted_style["body_font"] == "Impact"
        assert extracted_style["heading_font"] == "Impact"

    # 5. Compile through real document model & compiler
    content = parsed_resume_to_resume_content(parse_result.parsed)
    if fixture_name in ("9_graphics_and_images", "10_unusual_fonts"):
        assert content.profile.skills.soft_skills == [], (
            f"Technical skills misrouted to soft_skills: {content.profile.skills.soft_skills}"
        )
    doc_model = build_document_model(content, parse_result.geometry)
    docx_bytes = docx_compiler.compile(doc_model)
    compiled_pdf, ver_result = pdf_compiler.compile(doc_model, docx_bytes)
    assert len(compiled_pdf) > 0

    # Ensure compiled PDF has no un-rendered glyph substitutions (? for bullets/dashes)
    compiled_doc = fitz.open(stream=compiled_pdf, filetype="pdf")
    compiled_text = compiled_doc[0].get_text()
    compiled_doc.close()
    assert "•" in compiled_text or "\u2022" in compiled_text, "Compiled document must contain bullet glyphs"
    assert "—" in compiled_text or "\u2014" in compiled_text, "Compiled document must contain em-dash glyphs"

    # Skills mislabeling guard: technical stacks must never print as soft skills.
    if fixture_name in ("9_graphics_and_images", "10_unusual_fonts"):
        assert "Soft Skills:" not in compiled_text
        expected_tech = (
            ["Figma", "CSS3", "Typography", "Design Systems"]
            if fixture_name == "9_graphics_and_images"
            else ["PyTorch", "LaTeX", "Natural Language Processing"]
        )
        for tech in expected_tech:
            assert tech in compiled_text, f"{tech} missing from compiled output"

    # 6. Save full page screenshot
    screenshot = _render_pdf_to_image(compiled_pdf, page_idx=0, dpi=150)
    screenshot_path = STYLE_ARTIFACTS / f"{fixture_name}.png"
    screenshot.save(screenshot_path)
    assert screenshot_path.is_file()
    assert os.path.getsize(screenshot_path) > 1000

    # 7. Programmatically assert extracted DocumentStyle values
    assert expected_font_substring.lower() in extracted_style["body_font"].lower()
    assert 10.0 <= extracted_style["body_size_pt"] <= 11.5
    assert len(extracted_style["heading_color_hex"]) == 6
    assert parse_result.geometry["document_style"]["body_font"] == extracted_style["body_font"]


def test_compiler_base14_glyph_rendering_no_corruption() -> None:
    """Verify production compiler path preserves bullets (•) and em-dashes (—) with base-14 font."""
    from app.services.resumes.document_model import (
        HeaderElement, DocumentElement, ExperiencePosition, BulletElement,
    )
    doc_model = build_document_model(
        ResumeContent(
            profile=ResumeProfile(
                personal=PersonalInfo(full_name="Base14 Test", email="base14@test.com"),
                summary="Verifying base-14 em-dash — and bullet • preservation.",
                experience=[
                    ExperienceItem(
                        company="Test Co",
                        role="Staff Engineer",
                        start_date="2020",
                        end_date="Present",
                        responsibilities=[BulletItem(text="Lead initiative — saved $1M with • bullet.")],
                    )
                ],
            )
        )
    )
    # Explicitly force base-14 Helvetica
    doc_model.style.body_font = "Helvetica"
    doc_model.style.heading_font = "Helvetica"

    docx_bytes = docx_compiler.compile(doc_model)
    compiled_pdf, ver_result = pdf_compiler.compile(doc_model, docx_bytes)

    c_doc = fitz.open(stream=compiled_pdf, filetype="pdf")
    extracted_text = c_doc[0].get_text()
    c_doc.close()

    # Programmatic assertion: No '?' substitutions for bullets or em-dashes
    assert "?" not in extracted_text, f"Unexpected '?' substitution found in compiled PDF: {extracted_text}"
    assert "•" in extracted_text, "Bullet glyph • must be present in compiled PDF"
    assert "—" in extracted_text, "Em-dash glyph — must be present in compiled PDF"


def test_legacy_soft_skills_reclassified_at_render_boundary() -> None:
    """Stale profiles with technical terms in soft_skills still compile cleanly."""
    content = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Legacy Case", email="legacy@test.com"),
            skills=SkillCategory(soft_skills=["PyTorch", "CSS3", "Leadership"]),
        )
    )
    doc_model = build_document_model(content)
    cats = {g.category: g.skills for g in doc_model.skills}
    assert "PyTorch" not in cats.get("Soft Skills", [])
    assert "CSS3" not in cats.get("Soft Skills", [])
    assert cats.get("Soft Skills") == ["Leadership"]
    assert "PyTorch" in cats.get("Technical Skills", []) or "PyTorch" in cats.get("Technical & Core Competencies", [])

    compiled_pdf, _ = pdf_compiler.compile(doc_model, docx_compiler.compile(doc_model))
    c_doc = fitz.open(stream=compiled_pdf, filetype="pdf")
    text = c_doc[0].get_text()
    c_doc.close()
    assert "Soft Skills: PyTorch" not in text
    assert "Soft Skills: Leadership" in text or "Leadership" in text


# ---------------------------------------------------------------------------
# Step 3: Visual evidence and audit log for Fit Loop
# ---------------------------------------------------------------------------

def test_fit_loop_e2e_overflow_trim_and_screenshot() -> None:
    """Run dense overflow-prone resume through real fit loop, save final PDF screenshot + audit JSON."""
    fixture_name = "11_dense_overflow_resume"
    bullets = [
        BulletItem(text=f"Spearheaded enterprise infrastructure modernization initiative {i} resulting in 40% reduction in cloud hosting expenses across multi-region environments.")
        for i in range(30)
    ]
    profile = ResumeProfile(
        personal=PersonalInfo(full_name="Samantha Reed", email="samantha@example.com"),
        summary="Principal Architect with 15+ years leading large-scale cloud infrastructure and distributed messaging platforms.",
        experience=[
            ExperienceItem(
                role="Senior Staff Infrastructure Architect",
                company="TechScale Global",
                location="San Francisco, CA",
                start_date="2018",
                end_date="Present",
                responsibilities=bullets,
            )
        ],
    )
    content = ResumeContent(profile=profile)
    doc_model = build_document_model(content)

    # Trigger real fit loop with live pdf_compiler
    fit_result = fit_verifier.fit(
        doc_model,
        lambda model: pdf_compiler.compile(model)[0],
    )

    final_pdf = fit_result.pdf_bytes
    final_doc = fitz.open(stream=final_pdf, filetype="pdf")
    page_count = len(final_doc)
    final_doc.close()

    # Save screenshot of final single page
    screenshot = _render_pdf_to_image(final_pdf, page_idx=0, dpi=150)
    screenshot_path = FIT_ARTIFACTS / f"{fixture_name}.png"
    screenshot.save(screenshot_path)

    # Save audit log JSON
    audit_data = {
        "fixture": fixture_name,
        "final_page_count": page_count,
        "needs_manual_review": fit_result.needs_manual_review,
        "audit_trail": fit_result.audit,
    }
    json_path = FIT_ARTIFACTS / f"{fixture_name}.json"
    json_path.write_text(json.dumps(audit_data, indent=2), encoding="utf-8")

    assert screenshot_path.is_file()
    assert json_path.is_file()
    assert page_count == 1, "Expected fit loop to successfully converge to 1 page"
    assert len(fit_result.audit) > 0, "Expected audit trail of trims"
    assert any("Removed lowest-priority bullet" in a for a in fit_result.audit)
