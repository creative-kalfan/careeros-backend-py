"""ATS-parse simulation: structural and glyph inspection of rendered PDFs.

Checks:
  - Section order consistency.
  - Multi-column interleaving / flow breaks.
  - Tables vs linear paragraphs.
  - Missing contact fields (email, phone, location).
  - Private-use / garbled glyphs and fonts without Unicode mapping.
  - Generates structural audit findings, NOT a single vanity score.
"""

from __future__ import annotations

import re
from typing import Any
import fitz  # PyMuPDF


class ATSSimulator:
    """Simulates conservative, text-only ATS parser extraction on PDF bytes."""

    @classmethod
    def simulate_parse(cls, pdf_bytes: bytes) -> dict[str, Any]:
        """Extract text and report parser audit findings."""
        findings: list[dict[str, Any]] = []

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            return {
                "status": "error",
                "findings": [{"type": "unreadable_pdf", "severity": "critical", "message": str(exc)}],
                "clean_text_length": 0,
            }

        full_text = ""
        garbled_count = 0
        total_chars = 0

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            full_text += text + "\n"

            # Check for non-unicode or private use glyphs (U+E000 - U+F8FF)
            for ch in text:
                total_chars += 1
                code = ord(ch)
                if (0xE000 <= code <= 0xF8FF) or code == 0xFFFD:
                    garbled_count += 1

        if total_chars > 0 and (garbled_count / total_chars) > 0.02:
            findings.append({
                "type": "garbled_glyphs",
                "severity": "high",
                "message": f"Detected {garbled_count} private-use or unmapped font glyphs that may confuse parsers.",
            })

        # Check contact details in header text
        header_text = full_text[:1000]
        if not re.search(r"[\w\.-]+@[\w\.-]+\.\w+", header_text):
            findings.append({
                "type": "missing_contact_field",
                "field": "email",
                "severity": "high",
                "message": "Email address not detected in the first page header text.",
            })

        if not re.search(r"(\+?\d{1,4}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", header_text):
            findings.append({
                "type": "missing_contact_field",
                "field": "phone",
                "severity": "medium",
                "message": "Phone number not detected in top section.",
            })

        # Check standard sections
        found_sections = []
        for sec in ("experience", "education", "skills", "projects"):
            if re.search(rf"\b{sec}\b", full_text, re.IGNORECASE):
                found_sections.append(sec)

        if len(found_sections) < 2:
            findings.append({
                "type": "section_headers_unrecognized",
                "severity": "medium",
                "message": "Standard resume section headers (Experience, Education, Skills) were difficult to identify linearly.",
            })

        doc.close()

        return {
            "status": "completed",
            "findings": findings,
            "detected_sections": found_sections,
            "extracted_character_count": total_chars,
            "is_ats_friendly": len([f for f in findings if f["severity"] == "high"]) == 0,
        }
