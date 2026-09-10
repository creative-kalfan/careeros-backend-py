"""Adaptive Visual Density Engine and Layout Optimizer (Stage 6 of CareerOS).

Controls presentation-only optimization, strictly separated from semantic content decisions.
Universal and resume-agnostic: adapts visual density based on measurable page utilization
and distribution, ensuring professional presentation regardless of content volume.

- Underfilled resumes: progressively increases body typography, heading typography proportionally,
  line height, section spacing, bullet spacing, and header spacing until visually balanced.
- Normal resumes: maintains normal template typography and spacing.
- Dense resumes: prioritizes content compaction first, then reduces spacing, margins, line height,
  and typography only as a final presentation adjustment.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .document_model import ResumeDocumentModel


@dataclass
class LayoutConstraints:
    max_pages: int = 1
    # Typography bounds (pt)
    min_body_pt: float = 9.5
    max_body_pt: float = 12.0
    ideal_body_pt: float = 10.0

    # Line spacing bounds
    min_line_spacing: float = 1.05
    max_line_spacing: float = 1.35
    ideal_line_spacing: float = 1.15

    # Margin bounds (pt)
    min_margin_pt: float = 28.0
    max_margin_pt: float = 54.0

    # Spacing bounds (pt)
    min_section_before_pt: float = 4.0
    max_section_before_pt: float = 14.0
    min_section_after_pt: float = 2.0
    max_section_after_pt: float = 7.0

    min_bullet_spacing_pt: float = 1.0
    max_bullet_spacing_pt: float = 5.0

    min_header_spacing_pt: float = 1.5
    max_header_spacing_pt: float = 6.0

    min_paragraph_after_pt: float = 1.5
    max_paragraph_after_pt: float = 5.0

    # Target visual vertical utilization (high-80s to mid-90s)
    target_utilization_min: float = 0.82
    target_utilization_max: float = 0.96


@dataclass
class LayoutResult:
    document: ResumeDocumentModel
    audit: List[str] = field(default_factory=list)
    adjustments: List[Dict[str, Any]] = field(default_factory=list)
    quality_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit": self.audit,
            "adjustments": self.adjustments,
            "quality_score": round(self.quality_score, 3),
        }


def update_headings_proportionally(style: Any, body_pt: float) -> None:
    """Proportionally adjust heading sizes based on body font size.

    Preserves clean typographic scale:
    - Section heading: +2.0pt to +2.5pt above body
    - Subheading: +0.5pt to +1.0pt above body
    - Name: +8.0pt to +10.0pt above body
    - Headline: +1.0pt above body
    - Meta: -1.0pt below body (min 8.5pt)
    """
    style.body_size_pt = round(body_pt, 1)
    style.section_heading_size_pt = round(min(14.5, max(11.5, body_pt + 2.0)), 1)
    style.subheading_size_pt = round(min(12.5, max(10.0, body_pt + 0.5)), 1)
    style.name_size_pt = round(min(24.0, max(18.0, body_pt + 9.0)), 1)
    style.headline_size_pt = round(min(13.0, max(10.5, body_pt + 1.0)), 1)
    style.meta_size_pt = round(min(10.0, max(8.5, body_pt - 1.0)), 1)


def score_layout(
    style: Any,
    page_count: int,
    last_page_fill: float,
    constraints: LayoutConstraints,
) -> float:
    """Balance readability / hierarchy / ATS / utilization (0..100)."""
    if page_count > constraints.max_pages:
        return max(0.0, 40.0 - 15.0 * (page_count - constraints.max_pages))
    score = 65.0
    body = float(getattr(style, "body_size_pt", 10.0))
    spacing = float(getattr(style, "line_spacing", 1.15))
    score -= abs(body - constraints.ideal_body_pt) * 4.0
    score -= abs(spacing - constraints.ideal_line_spacing) * 10.0
    if body < constraints.min_body_pt or spacing < constraints.min_line_spacing:
        score -= 20.0

    heading = float(getattr(style, "section_heading_size_pt", 12.0))
    if heading - body < 1.0:
        score -= 8.0

    if int(getattr(style, "columns", 1)) != 1:
        score -= 6.0

    # Reward balanced utilization
    if page_count == constraints.max_pages:
        if 0.80 <= last_page_fill <= 0.96:
            score += 15.0
        elif last_page_fill >= 0.60:
            score += 8.0
        elif last_page_fill < 0.40:
            score -= 10.0
    return round(max(0.0, min(score, 100.0)), 2)


class LayoutOptimizer:
    """Adaptive Visual Density Engine searching presentation adjustments within safety bounds."""

    def __init__(self, constraints: Optional[LayoutConstraints] = None) -> None:
        self.constraints = constraints or LayoutConstraints()

    def optimize(
        self,
        document: ResumeDocumentModel,
        compile_pdf: Callable[[ResumeDocumentModel], bytes],
        last_page_fill_fn: Optional[Callable[[bytes], float]] = None,
    ) -> LayoutResult:
        """Deterministically optimize visual density and layout for page budget.

        For short/underfilled resumes: expands typography and spacing in the strict canonical order:
        1. Body typography
        2. Heading typography proportionally
        3. Line height
        4. Section spacing
        5. Bullet spacing
        6. Header/contact spacing
        7. Re-render and measure

        For dense resumes: compacts presentation in the strict canonical order:
        1. Content prioritization (handled by FitVerifier prior to layout optimization)
        2. Reduce unnecessary spacing
        3. Reduce margins within safe limits
        4. Reduce line height within readability limits
        5. Reduce typography only as final presentation adjustment
        """
        from .fit_verifier import measure_pdf_layout

        c = self.constraints
        candidate = copy.deepcopy(document)
        audit: List[str] = []
        adjustments: List[Dict[str, Any]] = []

        def measure(doc: ResumeDocumentModel) -> Tuple[int, Any, bytes]:
            pdf = compile_pdf(doc)
            metrics = measure_pdf_layout(pdf, style=doc.style)
            return metrics.page_count, metrics, pdf

        pages, metrics, pdf_bytes = measure(candidate)
        fill = last_page_fill_fn(pdf_bytes) if last_page_fill_fn else metrics.vertical_utilization
        best_score = score_layout(candidate.style, pages, fill, c)
        best = copy.deepcopy(candidate)

        # -------------------------------------------------------------------
        # BRANCH A: DENSE RESUME (pages > max_pages)
        # Order: 2. Spacing -> 3. Margins -> 4. Line height -> 5. Typography
        # -------------------------------------------------------------------
        if pages > c.max_pages:
            style = candidate.style

            # Stage 2: Reduce excessive spacing first
            spacing_reduced = False
            if float(style.section_before_pt) > c.min_section_before_pt:
                style.section_before_pt = c.min_section_before_pt
                spacing_reduced = True
            if float(style.section_after_pt) > c.min_section_after_pt:
                style.section_after_pt = c.min_section_after_pt
                spacing_reduced = True
            if float(getattr(style, "bullet_spacing_pt", 2.0)) > c.min_bullet_spacing_pt:
                style.bullet_spacing_pt = c.min_bullet_spacing_pt
                spacing_reduced = True
            if float(getattr(style, "header_spacing_pt", 2.0)) > c.min_header_spacing_pt:
                style.header_spacing_pt = c.min_header_spacing_pt
                spacing_reduced = True
            if float(style.paragraph_after_pt) > c.min_paragraph_after_pt:
                style.paragraph_after_pt = c.min_paragraph_after_pt
                spacing_reduced = True

            if spacing_reduced:
                pages, metrics, pdf_bytes = measure(candidate)
                fill = last_page_fill_fn(pdf_bytes) if last_page_fill_fn else metrics.vertical_utilization
                adjustments.append({"kind": "spacing_reduced", "score": score_layout(candidate.style, pages, fill, c)})
                audit.append("Reduced excessive section, bullet, and paragraph spacing for page fit.")
                if score_layout(candidate.style, pages, fill, c) >= best_score:
                    best, best_score = copy.deepcopy(candidate), score_layout(candidate.style, pages, fill, c)
                if pages <= c.max_pages:
                    return LayoutResult(best, audit, adjustments, best_score)

            # Stage 3: Margin optimization
            margins_tightened = False
            for attr in ("margin_left_pt", "margin_right_pt", "margin_top_pt", "margin_bottom_pt"):
                current = float(getattr(style, attr, 40.0))
                if current > c.min_margin_pt + 1.0:
                    setattr(style, attr, round(max(c.min_margin_pt, current - 6.0), 1))
                    margins_tightened = True
            if margins_tightened:
                pages, metrics, pdf_bytes = measure(candidate)
                fill = last_page_fill_fn(pdf_bytes) if last_page_fill_fn else metrics.vertical_utilization
                adjustments.append({"kind": "margins_optimized", "score": score_layout(candidate.style, pages, fill, c)})
                audit.append("Optimized page margins within ATS-safe bounds for page fit.")
                if score_layout(candidate.style, pages, fill, c) >= best_score:
                    best, best_score = copy.deepcopy(candidate), score_layout(candidate.style, pages, fill, c)
                if pages <= c.max_pages:
                    return LayoutResult(best, audit, adjustments, best_score)

            # Stage 4: Line-height optimization
            if float(style.line_spacing) > c.min_line_spacing:
                style.line_spacing = c.min_line_spacing
                pages, metrics, pdf_bytes = measure(candidate)
                fill = last_page_fill_fn(pdf_bytes) if last_page_fill_fn else metrics.vertical_utilization
                adjustments.append({"kind": "line_spacing_reduced", "score": score_layout(candidate.style, pages, fill, c)})
                audit.append(f"Optimized line spacing to {c.min_line_spacing} within readability limits.")
                if score_layout(candidate.style, pages, fill, c) >= best_score:
                    best, best_score = copy.deepcopy(candidate), score_layout(candidate.style, pages, fill, c)
                if pages <= c.max_pages:
                    return LayoutResult(best, audit, adjustments, best_score)

            # Stage 5: Typography reduction as final step only
            if float(style.body_size_pt) > c.min_body_pt:
                update_headings_proportionally(style, c.min_body_pt)
                pages, metrics, pdf_bytes = measure(candidate)
                fill = last_page_fill_fn(pdf_bytes) if last_page_fill_fn else metrics.vertical_utilization
                adjustments.append({"kind": "typography_reduced", "score": score_layout(candidate.style, pages, fill, c)})
                audit.append(f"Reduced typography to {c.min_body_pt}pt readability floor as final adjustment.")
                if score_layout(candidate.style, pages, fill, c) >= best_score:
                    best, best_score = copy.deepcopy(candidate), score_layout(candidate.style, pages, fill, c)

            return LayoutResult(best, audit, adjustments, best_score)

        # -------------------------------------------------------------------
        # BRANCH B: UNDERFILLED RESUME (pages <= max_pages and utilization < target)
        # Order: 1. Typography -> 2. Headings -> 3. Line height ->
        #        4. Section spacing -> 5. Bullet spacing -> 6. Header spacing
        # -------------------------------------------------------------------
        if pages <= c.max_pages and metrics.vertical_utilization < c.target_utilization_min:
            audit.append(
                f"Detected underfilled layout (utilization={metrics.vertical_utilization:.2f} < {c.target_utilization_min:.2f}); "
                "engaging Adaptive Density Engine."
            )

            # Progressive optimization loop
            max_rounds = 8
            for _ in range(max_rounds):
                pages, metrics, _ = measure(candidate)
                if metrics.vertical_utilization >= c.target_utilization_min or pages > c.max_pages:
                    break

                progress_made = False
                style = candidate.style

                # Step 1 & 2: Increase body typography and headings proportionally
                if float(style.body_size_pt) < c.max_body_pt:
                    checkpoint = copy.deepcopy(candidate)
                    new_body = min(c.max_body_pt, round(float(style.body_size_pt) + 0.5, 1))
                    update_headings_proportionally(style, new_body)
                    test_pages, test_metrics, _ = measure(candidate)
                    if test_pages <= c.max_pages and not test_metrics.clipping and not test_metrics.overlap:
                        best = copy.deepcopy(candidate)
                        progress_made = True
                        adjustments.append({"kind": "increase_typography", "body_size_pt": new_body})
                        audit.append(f"Increased body typography to {new_body}pt and headings proportionally.")
                        if test_metrics.vertical_utilization >= c.target_utilization_min:
                            break
                    else:
                        candidate = checkpoint
                        style = candidate.style

                # Step 3: Increase line height
                if float(style.line_spacing) < c.max_line_spacing:
                    checkpoint = copy.deepcopy(candidate)
                    new_spacing = min(c.max_line_spacing, round(float(style.line_spacing) + 0.05, 2))
                    style.line_spacing = new_spacing
                    test_pages, test_metrics, _ = measure(candidate)
                    if test_pages <= c.max_pages and not test_metrics.clipping and not test_metrics.overlap:
                        best = copy.deepcopy(candidate)
                        progress_made = True
                        adjustments.append({"kind": "increase_line_spacing", "line_spacing": new_spacing})
                        audit.append(f"Increased line height to {new_spacing} for visual comfort.")
                        if test_metrics.vertical_utilization >= c.target_utilization_min:
                            break
                    else:
                        candidate = checkpoint
                        style = candidate.style

                # Step 4: Increase section spacing
                if float(style.section_before_pt) < c.max_section_before_pt or float(style.section_after_pt) < c.max_section_after_pt:
                    checkpoint = copy.deepcopy(candidate)
                    new_before = min(c.max_section_before_pt, round(float(style.section_before_pt) + 1.5, 1))
                    new_after = min(c.max_section_after_pt, round(float(style.section_after_pt) + 0.8, 1))
                    style.section_before_pt = new_before
                    style.section_after_pt = new_after
                    test_pages, test_metrics, _ = measure(candidate)
                    if test_pages <= c.max_pages and not test_metrics.clipping and not test_metrics.overlap:
                        best = copy.deepcopy(candidate)
                        progress_made = True
                        adjustments.append({"kind": "increase_section_spacing", "section_before_pt": new_before, "section_after_pt": new_after})
                        audit.append(f"Increased section spacing ({new_before}pt / {new_after}pt).")
                        if test_metrics.vertical_utilization >= c.target_utilization_min:
                            break
                    else:
                        candidate = checkpoint
                        style = candidate.style

                # Step 5: Increase bullet spacing
                curr_bullet_sp = float(getattr(style, "bullet_spacing_pt", 2.0))
                if curr_bullet_sp < c.max_bullet_spacing_pt:
                    checkpoint = copy.deepcopy(candidate)
                    new_bullet_sp = min(c.max_bullet_spacing_pt, round(curr_bullet_sp + 0.8, 1))
                    style.bullet_spacing_pt = new_bullet_sp
                    test_pages, test_metrics, _ = measure(candidate)
                    if test_pages <= c.max_pages and not test_metrics.clipping and not test_metrics.overlap:
                        best = copy.deepcopy(candidate)
                        progress_made = True
                        adjustments.append({"kind": "increase_bullet_spacing", "bullet_spacing_pt": new_bullet_sp})
                        audit.append(f"Increased bullet spacing to {new_bullet_sp}pt.")
                        if test_metrics.vertical_utilization >= c.target_utilization_min:
                            break
                    else:
                        candidate = checkpoint
                        style = candidate.style

                # Step 6: Increase header/contact spacing
                curr_header_sp = float(getattr(style, "header_spacing_pt", 2.0))
                if curr_header_sp < c.max_header_spacing_pt:
                    checkpoint = copy.deepcopy(candidate)
                    new_header_sp = min(c.max_header_spacing_pt, round(curr_header_sp + 1.0, 1))
                    style.header_spacing_pt = new_header_sp
                    test_pages, test_metrics, _ = measure(candidate)
                    if test_pages <= c.max_pages and not test_metrics.clipping and not test_metrics.overlap:
                        best = copy.deepcopy(candidate)
                        progress_made = True
                        adjustments.append({"kind": "increase_header_spacing", "header_spacing_pt": new_header_sp})
                        audit.append(f"Increased header spacing to {new_header_sp}pt.")
                        if test_metrics.vertical_utilization >= c.target_utilization_min:
                            break
                    else:
                        candidate = checkpoint
                        style = candidate.style

                if not progress_made:
                    break

            final_pages, final_metrics, final_pdf = measure(best)
            fill = last_page_fill_fn(final_pdf) if last_page_fill_fn else final_metrics.vertical_utilization
            best_score = score_layout(best.style, final_pages, fill, c)
            return LayoutResult(best, audit, adjustments, best_score)

        # -------------------------------------------------------------------
        # BRANCH C: NORMAL RESUME (pages <= max_pages and balanced utilization)
        # Maintain template's normal typography and spacing
        # -------------------------------------------------------------------
        return LayoutResult(best, audit, adjustments, best_score)


layout_optimizer = LayoutOptimizer()

