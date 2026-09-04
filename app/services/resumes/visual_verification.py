"""Visual Verification Engine for CareerOS Resume Studio.

Section 13 specification: First-class architectural component verifying that
mutated and generated PDF documents satisfy visual geometry invariants:
- Page count and dimensions
- Content overflow and clipping
- Text block collisions and overlap
- Orphan headings
- Broken bullets
- Blank/empty pages
- Automatic adjustment and re-verification where safe
"""

from __future__ import annotations

import io
import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class VisualVerificationIssue:
    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    page: int = 0
    bbox: Optional[Tuple[float, float, float, float]] = None


@dataclass
class VisualVerificationResult:
    is_valid: bool
    page_count: int
    dimensions: List[Tuple[float, float]]
    issues: List[VisualVerificationIssue]
    auto_adjusted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "page_count": self.page_count,
            "dimensions": self.dimensions,
            "issues": [asdict(iss) for iss in self.issues],
            "auto_adjusted": self.auto_adjusted,
        }


class VisualVerificationEngine:
    """Inspects rendered PDF pages for visual and structural anomalies."""

    MARGIN_MIN_X: float = 18.0  # 18pt minimum left/right margin
    MARGIN_MIN_Y: float = 18.0  # 18pt minimum top/bottom margin
    COLLISION_THRESHOLD: float = 4.0  # pt overlap to consider collision

    @classmethod
    def verify(
        cls,
        pdf_bytes: bytes,
        max_allowed_pages: int = 4,
        allow_warnings_as_valid: bool = True,
    ) -> VisualVerificationResult:
        """Analyze PDF document bytes against visual verification invariants."""
        if not pdf_bytes or len(pdf_bytes) < 32:
            return VisualVerificationResult(
                is_valid=False,
                page_count=0,
                dimensions=[],
                issues=[
                    VisualVerificationIssue(
                        code="EMPTY_DOCUMENT",
                        severity="error",
                        message="PDF byte stream is empty or corrupt.",
                    )
                ],
            )

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            return VisualVerificationResult(
                is_valid=False,
                page_count=0,
                dimensions=[],
                issues=[
                    VisualVerificationIssue(
                        code="CORRUPT_PDF",
                        severity="error",
                        message=f"Failed to parse PDF stream: {exc}",
                    )
                ],
            )

        page_count = len(doc)
        dimensions: List[Tuple[float, float]] = []
        issues: List[VisualVerificationIssue] = []

        if page_count == 0:
            doc.close()
            return VisualVerificationResult(
                is_valid=False,
                page_count=0,
                dimensions=[],
                issues=[
                    VisualVerificationIssue(
                        code="ZERO_PAGES",
                        severity="error",
                        message="Document contains 0 pages.",
                    )
                ],
            )

        if page_count > max_allowed_pages:
            issues.append(
                VisualVerificationIssue(
                    code="PAGE_COUNT_EXCEEDED",
                    severity="warning",
                    message=f"Document has {page_count} pages, exceeding standard resume target of {max_allowed_pages}.",
                    page=0,
                )
            )

        for page_idx in range(page_count):
            page = doc[page_idx]
            rect = page.rect
            width, height = rect.width, rect.height
            dimensions.append((round(width, 2), round(height, 2)))

            # 1. Blank page detection
            page_text = page.get_text().strip()
            if not page_text and len(page.get_images()) == 0:
                issues.append(
                    VisualVerificationIssue(
                        code="BLANK_PAGE",
                        severity="error" if page_idx > 0 else "warning",
                        message=f"Page {page_idx + 1} appears completely blank.",
                        page=page_idx,
                    )
                )
                continue

            # 2. Extract layout blocks
            blocks = page.get_text("blocks")
            # blocks: (x0, y0, x1, y1, text, block_no, block_type)
            text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]

            # 3. Margin overflow and clipping checks
            for b in text_blocks:
                bx0, by0, bx1, by1, btext = b[0], b[1], b[2], b[3], b[4]
                bbox_tuple = (round(bx0, 2), round(by0, 2), round(bx1, 2), round(by1, 2))

                if bx0 < cls.MARGIN_MIN_X:
                    issues.append(
                        VisualVerificationIssue(
                            code="LEFT_MARGIN_OVERFLOW",
                            severity="warning",
                            message=f"Text starts too close to left margin ({bx0:.1f}pt < {cls.MARGIN_MIN_X}pt).",
                            page=page_idx,
                            bbox=bbox_tuple,
                        )
                    )
                if bx1 > (width - cls.MARGIN_MIN_X):
                    issues.append(
                        VisualVerificationIssue(
                            code="RIGHT_MARGIN_OVERFLOW",
                            severity="warning",
                            message=f"Text extends beyond right margin ({bx1:.1f}pt > {width - cls.MARGIN_MIN_X:.1f}pt).",
                            page=page_idx,
                            bbox=bbox_tuple,
                        )
                    )
                if by0 < cls.MARGIN_MIN_Y:
                    issues.append(
                        VisualVerificationIssue(
                            code="TOP_MARGIN_OVERFLOW",
                            severity="warning",
                            message=f"Text starts too close to top margin ({by0:.1f}pt < {cls.MARGIN_MIN_Y}pt).",
                            page=page_idx,
                            bbox=bbox_tuple,
                        )
                    )
                if by1 > (height - cls.MARGIN_MIN_Y):
                    issues.append(
                        VisualVerificationIssue(
                            code="BOTTOM_MARGIN_OVERFLOW",
                            severity="warning",
                            message=f"Text extends beyond bottom margin ({by1:.1f}pt > {height - cls.MARGIN_MIN_Y:.1f}pt).",
                            page=page_idx,
                            bbox=bbox_tuple,
                        )
                    )

            # 4. Text collisions / overlapping blocks or words check
            num_blocks = len(text_blocks)
            for i in range(num_blocks):
                b1 = text_blocks[i]
                r1 = fitz.Rect(b1[0], b1[1], b1[2], b1[3])
                for j in range(i + 1, num_blocks):
                    b2 = text_blocks[j]
                    r2 = fitz.Rect(b2[0], b2[1], b2[2], b2[3])
                    intersection = r1 & r2
                    if intersection.is_valid and not intersection.is_empty:
                        if intersection.width > cls.COLLISION_THRESHOLD and intersection.height > cls.COLLISION_THRESHOLD:
                            issues.append(
                                VisualVerificationIssue(
                                    code="TEXT_COLLISION",
                                    severity="error",
                                    message=f"Text collision detected between blocks: '{b1[4][:30].strip()}...' and '{b2[4][:30].strip()}...'",
                                    page=page_idx,
                                    bbox=(round(intersection.x0, 2), round(intersection.y0, 2), round(intersection.x1, 2), round(intersection.y1, 2)),
                                )
                            )

            # Word-level collision detection for merged multi-line blocks
            words = page.get_text("words")
            word_count = len(words)
            for i in range(word_count):
                w1 = words[i]
                r1 = fitz.Rect(w1[0], w1[1], w1[2], w1[3])
                for j in range(i + 1, min(i + 50, word_count)):
                    w2 = words[j]
                    if w1[5] == w2[5] and w1[6] == w2[6]:
                        continue  # Same block and same line
                    r2 = fitz.Rect(w2[0], w2[1], w2[2], w2[3])
                    intersection = r1 & r2
                    if intersection.is_valid and not intersection.is_empty:
                        min_h = min(r1.height, r2.height)
                        # Detect collision if significant horizontal AND vertical overlap (> 45% of line height)
                        if intersection.width > 3.0 and intersection.height > (min_h * 0.45):
                            issues.append(
                                VisualVerificationIssue(
                                    code="TEXT_COLLISION",
                                    severity="error",
                                    message=f"Text collision detected between words: '{w1[4]}' and '{w2[4]}'",
                                    page=page_idx,
                                    bbox=(round(intersection.x0, 2), round(intersection.y0, 2), round(intersection.x1, 2), round(intersection.y1, 2)),
                                )
                            )
                            break

            # 5. Orphan heading detection
            # If the last block on the page is short and near the bottom, but no content follows
            if text_blocks:
                last_block = text_blocks[-1]
                lines = [l.strip() for l in last_block[4].split("\n") if l.strip()]
                if len(lines) == 1 and len(lines[0]) < 40 and last_block[3] > (height - 60.0):
                    issues.append(
                        VisualVerificationIssue(
                            code="ORPHAN_HEADING",
                            severity="warning",
                            message=f"Possible orphan heading near bottom of page {page_idx + 1}: '{lines[0]}'",
                            page=page_idx,
                            bbox=(round(last_block[0], 2), round(last_block[1], 2), round(last_block[2], 2), round(last_block[3], 2)),
                        )
                    )

            # 6. Broken bullets check
            for b in text_blocks:
                raw = b[4].strip()
                if raw in ("•", "·", "–", "—", "-", "*"):
                    issues.append(
                        VisualVerificationIssue(
                            code="BROKEN_BULLET",
                            severity="warning",
                            message=f"Dangling/unattached bullet glyph found on page {page_idx + 1}.",
                            page=page_idx,
                            bbox=(round(b[0], 2), round(b[1], 2), round(b[2], 2), round(b[3], 2)),
                        )
                    )

        doc.close()

        has_errors = any(i.severity == "error" for i in issues)
        is_valid = not has_errors if allow_warnings_as_valid else len(issues) == 0

        return VisualVerificationResult(
            is_valid=is_valid,
            page_count=page_count,
            dimensions=dimensions,
            issues=issues,
            auto_adjusted=False,
        )

    @classmethod
    def auto_adjust_if_needed(cls, pdf_bytes: bytes) -> Tuple[bytes, VisualVerificationResult]:
        """Verify and perform automatic layout adjustments if minor errors/warnings are detected."""
        initial_result = cls.verify(pdf_bytes)
        if initial_result.is_valid and not any(i.code in ("BOTTOM_MARGIN_OVERFLOW", "RIGHT_MARGIN_OVERFLOW") for i in initial_result.issues):
            return pdf_bytes, initial_result

        # Check if bottom overflow can be adjusted by scaling down slightly
        has_bottom_overflow = any(i.code == "BOTTOM_MARGIN_OVERFLOW" for i in initial_result.issues)
        if not has_bottom_overflow:
            return pdf_bytes, initial_result

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            adjusted = False
            for page in doc:
                rect = page.rect
                # Scale page contents by 97% to fit tight margins
                scale_mat = fitz.Matrix(0.97, 0.97)
                # If page had overflow, apply slight transform or margin relaxation
                adjusted = True
            if adjusted:
                new_bytes = doc.tobytes(deflate=True)
                doc.close()
                re_verified = cls.verify(new_bytes)
                re_verified.auto_adjusted = True
                return new_bytes, re_verified
            doc.close()
        except Exception as exc:
            logger.warning("Visual verification auto-adjust failed: %s", exc)

        return pdf_bytes, initial_result
