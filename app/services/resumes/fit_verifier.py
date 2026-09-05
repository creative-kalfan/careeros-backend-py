"""Bounded one-page fit loop for compiled resume artifacts."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

import fitz

from .document_model import ResumeDocumentModel


@dataclass
class FitResult:
    document: ResumeDocumentModel
    pdf_bytes: bytes
    needs_manual_review: bool
    audit: list[str] = field(default_factory=list)


class FitVerifier:
    """Try one content trim, tighter spacing, then readability-safe type reduction."""

    max_bullet_trims = 10
    min_body_size = 10.0
    min_line_spacing = 1.05

    @staticmethod
    def _page_count(pdf_bytes: bytes) -> int:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            return len(document)
        finally:
            document.close()

    def fit(self, document: ResumeDocumentModel, compile_pdf: Callable[[ResumeDocumentModel], bytes]) -> FitResult:
        candidate = copy.deepcopy(document)
        pdf_bytes = compile_pdf(candidate)
        audit: list[str] = []
        if self._page_count(pdf_bytes) <= 1:
            return FitResult(candidate, pdf_bytes, False, audit)

        # 1. Content trimming loop: remove lowest-priority bullet, re-measure, repeat
        trims_done = 0
        while self._page_count(pdf_bytes) > 1 and trims_done < self.max_bullet_trims:
            if not self._drop_lowest_priority_bullet(candidate, audit):
                break
            trims_done += 1
            pdf_bytes = compile_pdf(candidate)
            if self._page_count(pdf_bytes) <= 1:
                return FitResult(candidate, pdf_bytes, False, audit)

        # 2. Spacing tightening: conservative reduction if still overflowing
        if self._page_count(pdf_bytes) > 1 and candidate.style.line_spacing > self.min_line_spacing:
            candidate.style.line_spacing = self.min_line_spacing
            audit.append(f"Tightened line spacing to {self.min_line_spacing} for one-page fit.")
            pdf_bytes = compile_pdf(candidate)
            if self._page_count(pdf_bytes) <= 1:
                return FitResult(candidate, pdf_bytes, False, audit)

        # 3. Typography scaling floor: conservative reduction if still overflowing
        if self._page_count(pdf_bytes) > 1 and candidate.style.body_size_pt > self.min_body_size:
            candidate.style.body_size_pt = self.min_body_size
            candidate.style.subheading_size_pt = max(candidate.style.subheading_size_pt, 10.5)
            audit.append("Reduced body text to 10pt readability floor for one-page fit.")
            pdf_bytes = compile_pdf(candidate)
            if self._page_count(pdf_bytes) <= 1:
                return FitResult(candidate, pdf_bytes, False, audit)

        if self._page_count(pdf_bytes) > 1:
            audit.append("Could not fit one page within readability limits; manual review required.")
            return FitResult(candidate, pdf_bytes, True, audit)

        return FitResult(candidate, pdf_bytes, False, audit)

    @staticmethod
    def _drop_lowest_priority_bullet(document: ResumeDocumentModel, audit: list[str]) -> bool:
        for entry in reversed(document.experience + document.internships):
            if entry.bullets:
                removed = entry.bullets.pop()
                audit.append(f"Removed lowest-priority bullet for one-page fit: {removed.text}")
                return True
        return False


fit_verifier = FitVerifier()
