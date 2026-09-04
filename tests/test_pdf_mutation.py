"""Unit tests for PDF Mutation Engine and Typography Fitting."""

from __future__ import annotations

import fitz
import pytest

from app.services.resumes.pdf_mutation import (
    PDFMutationEngine,
    fit_font_size,
    map_font_code,
    parse_color_rgb,
)


def _make_sample_pdf() -> bytes:
    """Generate a clean synthetic PDF with two distinct text blocks for testing."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    # Block 1: Header / Name
    page.insert_textbox(
        fitz.Rect(54, 50, 400, 80),
        "ALEX MORGAN\nalex@example.com",
        fontsize=16,
        fontname="helv",
    )

    # Block 2: Experience Item
    page.insert_textbox(
        fitz.Rect(54, 120, 500, 180),
        "Senior Backend Engineer — Acme Corp\n"
        "Architected distributed systems handling 50k requests per second.",
        fontsize=11,
        fontname="helv",
    )

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class TestFontAndColorMapping:
    """Test Base14 font mapping and color conversion."""

    def test_map_font_code_helvetica(self) -> None:
        assert map_font_code("Helvetica", False, False) == "helv"
        assert map_font_code("Arial", True, False) == "hebo"
        assert map_font_code("Calibri", False, True) == "heit"
        assert map_font_code("Inter", True, True) == "hebi"

    def test_map_font_code_times(self) -> None:
        assert map_font_code("Times New Roman", False, False) == "times-roman"
        assert map_font_code("Georgia", True, False) == "tibo"
        assert map_font_code("Garamond", False, True) == "tiit"
        assert map_font_code("Palatino", True, True) == "tibi"

    def test_map_font_code_courier(self) -> None:
        assert map_font_code("Courier", False, False) == "cour"
        assert map_font_code("Consolas", True, False) == "cobo"
        assert map_font_code("Monospace", False, True) == "coit"
        assert map_font_code("Menlo", True, True) == "cobi"

    def test_parse_color_rgb(self) -> None:
        assert parse_color_rgb(0) == (0.0, 0.0, 0.0)
        assert parse_color_rgb(None) == (0.0, 0.0, 0.0)
        # 0xFF0000 = Red
        assert parse_color_rgb(0xFF0000) == (1.0, 0.0, 0.0)
        # Hex string
        assert parse_color_rgb("#00FF00") == (0.0, 1.0, 0.0)
        # 0-255 RGB tuple
        assert parse_color_rgb((0, 0, 255)) == (0.0, 0.0, 1.0)
        # 0.0-1.0 RGB tuple
        assert parse_color_rgb((0.5, 0.5, 0.5)) == (0.5, 0.5, 0.5)


class TestDynamicTypographyFitting:
    """Test dynamic typography fitting under bounding box constraints."""

    def test_short_text_preserves_font_size(self) -> None:
        rect = fitz.Rect(50, 50, 400, 100)
        fitted, _ = fit_font_size(rect, "Short text fits easily", 12.0, "helv")
        assert fitted == 12.0

    def test_overflowing_text_scales_down(self) -> None:
        rect = fitz.Rect(50, 50, 200, 70)  # Very tight 20px high box
        long_text = (
            "This is an extensive multi-sentence bullet point describing system architecture "
            "and database latency optimization across Kubernetes clusters that exceeds initial limits."
        )
        fitted, _ = fit_font_size(rect, long_text, 12.0, "helv")
        # Should scale down towards minimum constraint
        assert fitted < 12.0
        assert fitted >= 6.5


class TestPDFMutationEngine:
    """Test redaction, text insertion, and geometry re-extraction."""

    def test_mutate_with_bbox_redacts_and_replaces(self) -> None:
        sample_pdf = _make_sample_pdf()

        mutated_bytes, updated_geom = PDFMutationEngine.mutate(
            pdf_bytes=sample_pdf,
            page_index=0,
            bbox=[54, 50, 400, 80],
            replacement_text="JORDAN TAYLOR\njordan@tech.io",
            font_name="helv",
            font_size=16.0,
            is_bold=True,
        )

        assert isinstance(mutated_bytes, bytes)
        assert len(mutated_bytes) > 500

        # Verify old text is gone and new text is present
        doc = fitz.open(stream=mutated_bytes, filetype="pdf")
        page_text = doc[0].get_text()
        doc.close()

        assert "JORDAN TAYLOR" in page_text
        assert "jordan@tech.io" in page_text
        assert "ALEX MORGAN" not in page_text

        # Verify geometry map re-extracted
        assert "pages" in updated_geom
        assert len(updated_geom["pages"]) == 1
        blocks = updated_geom["pages"][0]["blocks"]
        assert any("JORDAN TAYLOR" in b["text"] for b in blocks)

    def test_mutate_with_block_id_lookup(self) -> None:
        sample_pdf = _make_sample_pdf()

        # Extract initial geometry
        doc = fitz.open(stream=sample_pdf, filetype="pdf")
        from app.services.resume_parser.geometry import extract_document_geometry
        initial_geom = extract_document_geometry(doc).to_dict()
        doc.close()

        # Find experience block
        exp_block = next(
            b for b in initial_geom["pages"][0]["blocks"]
            if "Acme Corp" in b["text"]
        )
        target_block_id = exp_block["id"]

        new_experience = (
            "Staff Systems Architect — NextGen AI\n"
            "Spearheaded distributed microservices platform processing 1M events per second."
        )

        mutated_bytes, updated_geom = PDFMutationEngine.mutate(
            pdf_bytes=sample_pdf,
            page_index=0,
            block_id=target_block_id,
            geometry_map=initial_geom,
            replacement_text=new_experience,
        )

        doc = fitz.open(stream=mutated_bytes, filetype="pdf")
        page_text = doc[0].get_text()
        doc.close()

        assert "Staff Systems Architect" in page_text
        assert "NextGen AI" in page_text
        assert "Acme Corp" not in page_text

        # Geometry reflects the replacement
        updated_blocks = updated_geom["pages"][0]["blocks"]
        assert any("Staff Systems Architect" in b["text"] for b in updated_blocks)

    def test_successive_mutations(self) -> None:
        """Mutate multiple blocks sequentially and verify full document integrity."""
        pdf1 = _make_sample_pdf()

        # Mutation 1: Name
        pdf2, geom2 = PDFMutationEngine.mutate(
            pdf_bytes=pdf1,
            page_index=0,
            bbox=[54, 50, 400, 80],
            replacement_text="DR. SAMANTHA REED",
            font_name="times",
            font_size=18.0,
            is_bold=True,
        )

        # Mutation 2: Experience
        pdf3, geom3 = PDFMutationEngine.mutate(
            pdf_bytes=pdf2,
            page_index=0,
            bbox=[54, 120, 500, 180],
            replacement_text="Chief Technology Officer — Quantum Innovations\nDirecting AI Research.",
            font_name="helv",
            font_size=11.0,
        )

        doc = fitz.open(stream=pdf3, filetype="pdf")
        final_text = doc[0].get_text()
        doc.close()

        assert "DR. SAMANTHA REED" in final_text
        assert "Chief Technology Officer" in final_text
        assert "Quantum Innovations" in final_text
        assert "ALEX MORGAN" not in final_text
        assert "Acme Corp" not in final_text

    def test_page_index_out_of_range_raises_index_error(self) -> None:
        sample_pdf = _make_sample_pdf()
        with pytest.raises(IndexError, match=r"Page index 5 out of range \[0, 0\]"):
            PDFMutationEngine.mutate(
                pdf_bytes=sample_pdf,
                page_index=5,
                bbox=[54, 50, 400, 80],
                replacement_text="Test Out Of Range",
            )
