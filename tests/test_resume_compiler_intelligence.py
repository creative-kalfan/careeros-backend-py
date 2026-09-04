"""Tests for Resume Intelligence system prompt, Visual Verification, and compiler mutation pipeline."""

from __future__ import annotations

import fitz
import pytest

from app.models.resume import ResumeContent, ResumeProfile, PersonalInfo, ExperienceItem, BulletItem
from app.services.resumes.system_prompt import (
    RESUME_INTELLIGENCE_PROMPT_VERSION,
    RESUME_INTELLIGENCE_SYSTEM_PROMPT,
    get_resume_intelligence_system_prompt,
)
from app.services.resumes.visual_verification import (
    VisualVerificationEngine,
    VisualVerificationResult,
)
from app.services.resumes.pdf_mutation import PDFMutationEngine
from app.services.resume_parser.geometry import extract_document_geometry


def test_system_prompt_version_and_content():
    assert RESUME_INTELLIGENCE_PROMPT_VERSION == "1.0.0"
    assert "CareerOS Resume Intelligence Engine" in RESUME_INTELLIGENCE_SYSTEM_PROMPT
    assert "senior technical recruiter" in RESUME_INTELLIGENCE_SYSTEM_PROMPT
    assert "Never fabricate" in RESUME_INTELLIGENCE_SYSTEM_PROMPT

    prompt = get_resume_intelligence_system_prompt(section="experience", custom_instructions="Test constraint")
    assert "TARGET SECTION: EXPERIENCE" in prompt
    assert "Test constraint" in prompt


def test_visual_verification_valid_pdf():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(54, 54, 540, 120), "Jane Doe\nStaff Software Engineer")
    page.insert_textbox(fitz.Rect(54, 130, 540, 300), "Experience\nLead distributed systems engineer.")
    pdf_bytes = doc.tobytes()
    doc.close()

    result = VisualVerificationEngine.verify(pdf_bytes)
    assert result.is_valid is True
    assert result.page_count == 1
    assert len(result.dimensions) == 1
    assert result.dimensions[0] == (595.0, 842.0)


def test_visual_verification_empty_document():
    result = VisualVerificationEngine.verify(b"")
    assert result.is_valid is False
    assert any(i.code == "EMPTY_DOCUMENT" for i in result.issues)


def test_visual_verification_collision_detection():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Insert two overlapping textboxes at identical coordinates
    rect = fitz.Rect(100, 100, 300, 150)
    page.insert_textbox(rect, "Block One of Text Content")
    page.insert_textbox(rect, "Block Two Overlapping Heavily")
    pdf_bytes = doc.tobytes()
    doc.close()

    result = VisualVerificationEngine.verify(pdf_bytes, allow_warnings_as_valid=False)
    assert any(i.code == "TEXT_COLLISION" for i in result.issues)


def test_pdf_mutation_with_visual_verification():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    rect = fitz.Rect(54, 54, 400, 90)
    page.insert_textbox(rect, "Original Headline Text")
    pdf_bytes = doc.tobytes()
    doc.close()

    mutated_bytes, geom = PDFMutationEngine.mutate(
        pdf_bytes=pdf_bytes,
        page_index=0,
        bbox=[54, 54, 400, 90],
        replacement_text="Staff Infrastructure & AI Platforms Architect",
    )

    assert len(mutated_bytes) > 0
    assert "pages" in geom
    # Verify mutated doc parses cleanly
    check_doc = fitz.open(stream=mutated_bytes, filetype="pdf")
    text = check_doc[0].get_text()
    check_doc.close()
    assert "Staff Infrastructure" in text
