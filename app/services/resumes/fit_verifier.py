"""Coordinated content + layout fit loop for compiled resume artifacts.

Stage coordination (NOT a single heuristic):
- CONTENT decisions (what to trim) come from universal content-value scoring
  (jd relevance, evidence strength, impact, recency, uniqueness, redundancy).
  Without external scores, a generic intrinsic-value fallback ranks bullets
  by specificity, metrics, and delivery strength — never by hard-coded
  skills, sections, or resume identity.
- PRESENTATION decisions (margins, spacing, type) are delegated to
  LayoutOptimizer, which searches within readability floors.
- VALIDATION is geometric (real page counts from compiled PDFs).

Supports any page constraint (1-page default preserved for backward
compatibility). Every visible content/layout tradeoff is recorded in audit.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, Dict, List, Optional, Tuple

import fitz

from .document_model import ResumeDocumentModel


@dataclass
class PageLayoutMetrics:
    page_count: int
    content_bbox: Tuple[float, float, float, float]
    vertical_occupancy: float
    vertical_distribution: List[float]  # 4-quadrant vertical distribution
    vertical_utilization: float
    horizontal_utilization: float
    bottom_whitespace_pt: float
    clipping: bool
    overflow: bool
    overlap: bool
    orphan_headings: List[str]
    has_issues: bool


def measure_pdf_layout(
    pdf_bytes: bytes,
    page_index: int = 0,
    style: Optional[Any] = None,
) -> PageLayoutMetrics:
    """Measure structural and visual density layout metrics from compiled PDF bytes."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return PageLayoutMetrics(
            page_count=0,
            content_bbox=(0.0, 0.0, 0.0, 0.0),
            vertical_occupancy=0.0,
            vertical_distribution=[0.0, 0.0, 0.0, 0.0],
            vertical_utilization=0.0,
            horizontal_utilization=0.0,
            bottom_whitespace_pt=0.0,
            clipping=False,
            overflow=True,
            overlap=False,
            orphan_headings=[],
            has_issues=True,
        )

    try:
        page_count = len(doc)
        if page_count == 0:
            return PageLayoutMetrics(
                page_count=0,
                content_bbox=(0.0, 0.0, 0.0, 0.0),
                vertical_occupancy=0.0,
                vertical_distribution=[0.0, 0.0, 0.0, 0.0],
                vertical_utilization=0.0,
                horizontal_utilization=0.0,
                bottom_whitespace_pt=0.0,
                clipping=False,
                overflow=False,
                overlap=False,
                orphan_headings=[],
                has_issues=True,
            )

        idx = max(0, min(page_index, page_count - 1))
        page = doc[idx]
        page_width = float(page.rect.width)
        page_height = float(page.rect.height)

        blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
        if not blocks:
            return PageLayoutMetrics(
                page_count=page_count,
                content_bbox=(0.0, 0.0, 0.0, 0.0),
                vertical_occupancy=0.0,
                vertical_distribution=[0.0, 0.0, 0.0, 0.0],
                vertical_utilization=0.0,
                horizontal_utilization=0.0,
                bottom_whitespace_pt=page_height,
                clipping=False,
                overflow=page_count > 1,
                overlap=False,
                orphan_headings=[],
                has_issues=page_count > 1,
            )

        min_x0 = min(b[0] for b in blocks)
        min_y0 = min(b[1] for b in blocks)
        max_x1 = max(b[2] for b in blocks)
        max_y1 = max(b[3] for b in blocks)
        content_bbox = (round(min_x0, 2), round(min_y0, 2), round(max_x1, 2), round(max_y1, 2))

        top_margin = float(getattr(style, "margin_top_pt", 36.0)) if style else 36.0
        bottom_margin = float(getattr(style, "margin_bottom_pt", 36.0)) if style else 36.0
        left_margin = float(getattr(style, "margin_left_pt", 40.0)) if style else 40.0
        right_margin = float(getattr(style, "margin_right_pt", 40.0)) if style else 40.0

        usable_height = max(1.0, page_height - top_margin - bottom_margin)
        usable_width = max(1.0, page_width - left_margin - right_margin)

        content_height = max_y1 - min_y0
        content_width = max_x1 - min_x0

        vertical_occupancy = round(max(0.0, min(content_height / usable_height, 1.0)), 3)
        vertical_utilization = round(max(0.0, min(content_height / usable_height, 1.0)), 3)
        horizontal_utilization = round(max(0.0, min(content_width / usable_width, 1.0)), 3)
        bottom_whitespace_pt = round(max(0.0, (page_height - bottom_margin) - max_y1), 2)

        q_h = usable_height / 4.0
        quadrants = [0.0, 0.0, 0.0, 0.0]
        for b in blocks:
            b_top = b[1]
            b_bot = b[3]
            for q_idx in range(4):
                q_top = top_margin + q_idx * q_h
                q_bot = q_top + q_h
                overlap_h = max(0.0, min(b_bot, q_bot) - max(b_top, q_top))
                quadrants[q_idx] += overlap_h

        total_q = sum(quadrants)
        if total_q > 0:
            vertical_distribution = [round(q / total_q, 3) for q in quadrants]
        else:
            vertical_distribution = [0.25, 0.25, 0.25, 0.25]

        clipping = any(
            b[0] < -1.0 or b[1] < -1.0 or b[2] > page_width + 1.0 or b[3] > page_height + 1.0
            for b in blocks
        )
        overflow = (page_count > 1) or (max_y1 > page_height - 10.0)

        overlap = False
        n_blocks = len(blocks)
        for i in range(n_blocks):
            b1 = blocks[i]
            for j in range(i + 1, n_blocks):
                b2 = blocks[j]
                x_overlap = min(b1[2], b2[2]) - max(b1[0], b2[0])
                y_overlap = min(b1[3], b2[3]) - max(b1[1], b2[1])
                if x_overlap > 8.0 and y_overlap > 6.0:
                    overlap = True
                    break
            if overlap:
                break

        orphan_headings: List[str] = []
        heading_keywords = {
            "summary", "skills", "experience", "projects", "education",
            "certifications", "internships", "key sub-engagements", "key engagements",
        }
        for b in blocks:
            text_lines = [line.strip() for line in b[4].splitlines() if line.strip()]
            if len(text_lines) == 1:
                cleaned = text_lines[0].lower().rstrip(":")
                if cleaned in heading_keywords:
                    if b[3] > (page_height - bottom_margin - 30.0):
                        orphan_headings.append(text_lines[0])

        has_issues = clipping or overflow or overlap or bool(orphan_headings)

        return PageLayoutMetrics(
            page_count=page_count,
            content_bbox=content_bbox,
            vertical_occupancy=vertical_occupancy,
            vertical_distribution=vertical_distribution,
            vertical_utilization=vertical_utilization,
            horizontal_utilization=horizontal_utilization,
            bottom_whitespace_pt=bottom_whitespace_pt,
            clipping=clipping,
            overflow=overflow,
            overlap=overlap,
            orphan_headings=orphan_headings,
            has_issues=has_issues,
        )
    finally:
        doc.close()


_STRONG_OPENERS = frozenset(
    {
        "architected", "spearheaded", "engineered", "developed", "designed",
        "implemented", "optimized", "delivered", "automated", "scaled",
        "streamlined", "orchestrated", "accelerated", "pioneered", "built",
        "led", "created", "reduced", "increased", "transformed", "established",
        "drove", "launched", "standardized", "managed", "directed",
    }
)


def _bullet_intrinsic_value(text: str) -> float:
    """Generic value proxy: specificity + evidence + delivery (no vocabulary)."""
    t = (text or "").strip()
    if not t:
        return 0.0
    tokens = re.findall(r"[A-Za-z0-9+#./-]+", t)
    value = min(len(tokens) / 18.0, 1.0)  # substantive detail wins
    if re.search(r"\d", t):
        value += 0.5  # quantified impact
    first = re.sub(r"[^a-zA-Z]", "", t.split()[0]).lower() if t.split() else ""
    if first in _STRONG_OPENERS:
        value += 0.3
    if len(t) < 24:
        value -= 0.4  # stub/generic fragments go first
    return round(value, 3)


@dataclass
class FitResult:
    document: ResumeDocumentModel
    pdf_bytes: bytes
    needs_manual_review: bool
    audit: List[str] = field(default_factory=list)


class FitVerifier:
    """Coordinate value-aware content trimming + layout optimization."""

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

    @staticmethod
    def _last_page_fill(pdf_bytes: bytes) -> float:
        """Fraction of the last page's content height covered by text blocks."""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            try:
                if len(doc) == 0:
                    return 0.0
                page = doc[len(doc) - 1]
                blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
                if not blocks:
                    return 0.0
                top = min(b[1] for b in blocks)
                bottom = max(b[3] for b in blocks)
                usable = page.rect.height - 72.0  # approx margins
                return round(max(0.0, min((bottom - top) / max(usable, 1.0), 1.0)), 3)
            finally:
                doc.close()
        except Exception:
            return 1.0

    def fit(
        self,
        document: ResumeDocumentModel,
        compile_pdf: Callable[[ResumeDocumentModel], bytes],
        max_pages: int = 1,
        value_scores: Optional[Dict[str, float]] = None,
    ) -> FitResult:
        candidate = copy.deepcopy(document)
        pdf_bytes = compile_pdf(candidate)
        audit: List[str] = []

        # 1. Content trimming loop: if overflowing, remove lowest-value bullet, re-measure.
        trims_done = 0
        while self._page_count(pdf_bytes) > max_pages and trims_done < self.max_bullet_trims:
            if not self._drop_lowest_value_bullet(candidate, audit, value_scores):
                break
            trims_done += 1
            pdf_bytes = compile_pdf(candidate)

        # 2. Presentation optimization (delegated — no content decisions here).
        # Always run layout optimizer so underfilled resumes get expanded density
        # and dense resumes get compacted presentation.
        from .layout_optimizer import LayoutConstraints, LayoutOptimizer

        optimizer = LayoutOptimizer(
            LayoutConstraints(
                max_pages=max_pages,
                min_body_pt=self.min_body_size,
                min_line_spacing=self.min_line_spacing,
            )
        )
        layout_result = optimizer.optimize(
            candidate, compile_pdf, last_page_fill_fn=self._last_page_fill
        )
        candidate = layout_result.document
        audit.extend(layout_result.audit)
        pdf_bytes = compile_pdf(candidate)

        # 3. If still overflowing after presentation compaction, try further trimming
        while self._page_count(pdf_bytes) > max_pages and trims_done < self.max_bullet_trims:
            if not self._drop_lowest_value_bullet(candidate, audit, value_scores):
                break
            trims_done += 1
            layout_result = optimizer.optimize(
                candidate, compile_pdf, last_page_fill_fn=self._last_page_fill
            )
            candidate = layout_result.document
            audit.extend(layout_result.audit)
            pdf_bytes = compile_pdf(candidate)

        if self._page_count(pdf_bytes) > max_pages:
            audit.append(
                f"Could not fit {max_pages} page(s) within readability limits; "
                "manual review required."
            )
            return FitResult(candidate, pdf_bytes, True, audit)

        return FitResult(candidate, pdf_bytes, False, audit)

    @classmethod
    def _drop_lowest_value_bullet(
        cls,
        document: ResumeDocumentModel,
        audit: List[str],
        value_scores: Optional[Dict[str, float]] = None,
    ) -> bool:
        """Remove the single lowest-value bullet across sections.

        Search order is value-driven, not position-driven: every remaining
        bullet is ranked (external value_scores by bullet id win; otherwise
        intrinsic value), and only the minimum is removed. Ties break toward
        later sections/entries so recent, high-context roles are preserved.
        """
        candidates: List[tuple[float, int, int, str, Any, Any]] = []

        def consider(section_rank: int, entry_idx: int, bullet: Any, container: Any) -> None:
            text = getattr(bullet, "text", str(bullet))
            bid = getattr(bullet, "id", "")
            if value_scores is not None and bid in value_scores:
                value = float(value_scores[bid])
            else:
                value = _bullet_intrinsic_value(text)
            # Lower value sorts first; later sections/entries break ties.
            candidates.append((value, -section_rank, -entry_idx, bid, bullet, container))

        for i, entry in enumerate(document.experience):
            for b in list(entry.bullets):
                consider(3, i, b, entry)
        for i, entry in enumerate(document.internships):
            for b in list(entry.bullets):
                consider(2, i, b, entry)
        for i, proj in enumerate(document.projects):
            for b in list(proj.bullets):
                consider(1, i, b, proj)

        if not candidates:
            return False
        candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
        _, _, _, _, bullet, container = candidates[0]
        text = getattr(bullet, "text", str(bullet))
        container.bullets = [b for b in container.bullets if b is not bullet]
        audit.append(f"Removed lowest-priority bullet for page fit: {text}")
        return True

    # Backward-compatible hook retained for direct callers/tests.
    @staticmethod
    def _drop_lowest_priority_bullet(document: ResumeDocumentModel, audit: List[str]) -> bool:
        return FitVerifier._drop_lowest_value_bullet(document, audit, None)


fit_verifier = FitVerifier()
