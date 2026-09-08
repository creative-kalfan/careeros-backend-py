"""Tests for the Typst PDF compilation engine.

Covers: markup rendering from the document model (no binary needed),
binary availability detection, end-to-end compilation to real PDF bytes
(``%PDF-`` magic), error mapping, the single-page budget, the canonical
``modern.typ`` template, and the PdfCompiler / export-service integration.

Binary-dependent tests skip cleanly when the ``typst`` CLI is absent so CI
without the Docker image still passes; the Docker build itself installs the
binary (see Dockerfile).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.resume import (
    BulletItem,
    ExperienceItem,
    PersonalInfo,
    ResumeContent,
    ResumeProfile,
    SkillCategory,
)
from app.services.pdf.typst_compiler import (
    TypstCompileError,
    TypstNotAvailableError,
    TypstPageBudgetExceeded,
    acompile_typst_to_pdf,
    compile_typst_to_pdf,
    is_typst_available,
    render_document_model_to_typst,
)
from app.services.resumes.document_model import build_document_model

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "templates" / "typst" / "modern.typ"
)

needs_typst = pytest.mark.skipif(
    shutil.which("typst") is None, reason="typst CLI not installed"
)


def _sample_content() -> ResumeContent:
    profile = ResumeProfile(
        personal=PersonalInfo(
            full_name="Asha Engineer",
            email="asha.engineer@example.com",
            phone="+91 98765 43210",
            location="Bengaluru, IN",
            headline="Backend Engineer",
        ),
        summary="Backend engineer building payment APIs with Python and FastAPI.",
        experience=[
            ExperienceItem(
                company="Finscale",
                role="Backend Engineer",
                location="Bengaluru, IN",
                start_date="2022",
                end_date="Present",
                responsibilities=[
                    BulletItem(text="Built ingestion microservices with Python/FastAPI."),
                    # Hostile markup characters must survive as literal text.
                    BulletItem(text="= Lead #platform *growth* @scale: +35% throughput, $2M volume."),
                ],
                achievements=["Cut P99 latency by 35%."],
            )
        ],
        skills=SkillCategory(technical=["Python", "FastAPI"], tools=["Redis"]),
    )
    return ResumeContent(profile=profile)


# ---------------------------------------------------------------------------
# Renderer unit tests (no binary needed)
# ---------------------------------------------------------------------------


class TestRenderDocumentModelToTypst:
    def test_embeds_identity_and_sections(self):
        markup = render_document_model_to_typst(build_document_model(_sample_content(), None))
        assert "Asha Engineer" in markup
        assert "EXPERIENCE" in markup
        assert "SKILLS" in markup
        assert "Finscale" in markup
        assert "margin: (x: 1.2cm, y: 1.2cm)" in markup

    def test_user_markup_is_literal_not_syntax(self):
        markup = render_document_model_to_typst(build_document_model(_sample_content(), None))
        # Hostile text travels inside string literals via #t("...").
        assert '#t("= Lead #platform *growth* @scale: +35% throughput, $2M volume.")' in markup
        # …and never leaks as bare Typst syntax.
        assert "\n= Lead" not in markup

    def test_empty_model_renders_header_only(self):
        markup = render_document_model_to_typst(
            build_document_model(ResumeContent(), None)
        )
        assert "#align(center)" in markup
        assert "#rsec" not in markup


# ---------------------------------------------------------------------------
# Availability / error mapping
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_missing_binary_raises_typed_error(self):
        with patch("app.services.pdf.typst_compiler.shutil.which", return_value=None):
            assert is_typst_available() is False
            with pytest.raises(TypstNotAvailableError):
                compile_typst_to_pdf("#t(\"hi\")")

    def test_empty_markup_rejected_without_subprocess(self):
        with pytest.raises(TypstCompileError):
            compile_typst_to_pdf("   ")


# ---------------------------------------------------------------------------
# End-to-end compilation (needs the typst binary)
# ---------------------------------------------------------------------------


class TestCompileTypstToPdf:
    @needs_typst
    def test_sample_markup_produces_pdf_magic_bytes(self):
        pdf = compile_typst_to_pdf(
            '#set page(paper: "a4", margin: (x: 1.5cm, y: 1.5cm))\nHello Typst\n'
        )
        assert pdf.startswith(b"%PDF-")

    @needs_typst
    def test_rendered_resume_compiles_to_single_page_pdf(self):
        markup = render_document_model_to_typst(build_document_model(_sample_content(), None))
        pdf = compile_typst_to_pdf(markup)
        assert pdf.startswith(b"%PDF-")
        import fitz

        with fitz.open(stream=pdf, filetype="pdf") as doc:
            assert doc.page_count == 1
            text = doc[0].get_text()
        # Selectable, ATS-friendly text survives compilation.
        assert "Asha Engineer" in text
        assert "Finscale" in text

    @needs_typst
    def test_canonical_template_compiles(self):
        assert TEMPLATE_PATH.is_file()
        pdf = compile_typst_to_pdf(TEMPLATE_PATH.read_text(encoding="utf-8"))
        assert pdf.startswith(b"%PDF-")

    @needs_typst
    def test_invalid_markup_raises_typed_error(self):
        with pytest.raises(TypstCompileError):
            compile_typst_to_pdf("#set page(")

    @needs_typst
    def test_page_budget_exceeded(self):
        long_markup = (
            '#set page(paper: "a4", margin: (x: 1.2cm, y: 1.2cm))\n'
            + "#lorem(1200)\n"
        )
        with pytest.raises(TypstPageBudgetExceeded):
            compile_typst_to_pdf(long_markup)
        relaxed = compile_typst_to_pdf(long_markup, enforce_single_page=False)
        assert relaxed.startswith(b"%PDF-")

    @needs_typst
    @pytest.mark.asyncio
    async def test_async_entrypoint(self):
        pdf = await acompile_typst_to_pdf("Async Typst\n")
        assert pdf.startswith(b"%PDF-")


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


class TestTypstPipelineIntegration:
    @needs_typst
    def test_pdf_compiler_prefers_typst(self):
        from app.services.resumes.pdf_compiler import pdf_compiler

        doc_model = build_document_model(_sample_content(), None)
        pdf_bytes, ver_result = pdf_compiler.compile(doc_model)
        assert pdf_bytes.startswith(b"%PDF-")
        assert ver_result is not None

    @needs_typst
    def test_export_service_pdf(self):
        from app.services.export_service import export_service

        pdf_bytes = export_service.export_pdf(_sample_content(), "minimal")
        assert pdf_bytes.startswith(b"%PDF-")
