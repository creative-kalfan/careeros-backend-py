"""Real end-to-end rendering and artifact generation tests for style extraction and fit loop."""

from __future__ import annotations

import json
import os
from pathlib import Path
import fitz
import pytest
from PIL import Image

from app.models.resume import BulletItem, ExperienceItem, PersonalInfo, ResumeContent, ResumeProfile
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
        ("10_unusual_fonts", "times"),
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

    # 3. Compile through real document model & compiler
    content = parsed_resume_to_resume_content(parse_result.parsed)
    doc_model = build_document_model(content, parse_result.geometry)
    docx_bytes = docx_compiler.compile(doc_model)
    compiled_pdf, ver_result = pdf_compiler.compile(doc_model, docx_bytes)
    assert len(compiled_pdf) > 0

    # 4. Save full page screenshot
    screenshot = _render_pdf_to_image(compiled_pdf, page_idx=0, dpi=150)
    screenshot_path = STYLE_ARTIFACTS / f"{fixture_name}.png"
    screenshot.save(screenshot_path)
    assert screenshot_path.is_file()
    assert os.path.getsize(screenshot_path) > 1000

    # 5. Programmatically assert extracted DocumentStyle values
    assert extracted_style["body_font"]
    assert 10.0 <= extracted_style["body_size_pt"] <= 11.5
    assert len(extracted_style["heading_color_hex"]) == 6
    assert parse_result.geometry["document_style"]["body_font"] == extracted_style["body_font"]


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
