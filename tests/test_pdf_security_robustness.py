"""Security, bounds-checking, and malformed payload robustness tests for PDFMutationEngine."""

import fitz
import pytest

from app.services.resumes.pdf_mutation import PDFMutationEngine


def _make_valid_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(fitz.Rect(50, 50, 400, 100), "Safe content block", fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class TestPDFSecurityAndRobustness:
    def test_empty_bytes_rejected(self):
        with pytest.raises(Exception):
            PDFMutationEngine.mutate(b"", page_index=0, bbox=[50, 50, 200, 100], replacement_text="New text")

    def test_corrupted_bytes_rejected(self):
        corrupted = b"%PDF-1.4\n" + b"\x00\xff\xee\xdd" * 50
        with pytest.raises(Exception):
            PDFMutationEngine.mutate(corrupted, page_index=0, bbox=[50, 50, 200, 100], replacement_text="New text")

    def test_out_of_bounds_page_index_raises_index_error(self):
        valid = _make_valid_pdf()
        with pytest.raises(IndexError, match="out of range"):
            PDFMutationEngine.mutate(valid, page_index=99, bbox=[50, 50, 200, 100], replacement_text="New text")

    def test_negative_page_index_raises_index_error(self):
        valid = _make_valid_pdf()
        with pytest.raises(IndexError, match="out of range"):
            PDFMutationEngine.mutate(valid, page_index=-1, bbox=[50, 50, 200, 100], replacement_text="New text")

    def test_missing_or_invalid_bbox_rejected(self):
        valid = _make_valid_pdf()
        with pytest.raises(ValueError, match="Invalid or missing bounding box"):
            PDFMutationEngine.mutate(valid, page_index=0, bbox=[], replacement_text="New text")

        with pytest.raises(ValueError, match="Invalid or missing bounding box"):
            PDFMutationEngine.mutate(valid, page_index=0, bbox=[10, 20], replacement_text="New text")

    def test_encrypted_pdf_handling(self):
        doc = fitz.open()
        p = doc.new_page()
        p.insert_text((50, 50), "Encrypted content")
        # Save with user password
        buf = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret")
        doc.close()

        # Mutating encrypted PDF without password should raise error
        with pytest.raises(Exception):
            PDFMutationEngine.mutate(buf, page_index=0, bbox=[50, 50, 200, 100], replacement_text="Hacked")
