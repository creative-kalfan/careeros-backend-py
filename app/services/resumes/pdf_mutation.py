"""PDF Mutation Engine for CareerOS Resume Studio.

Performs precise spatial text redaction and metric-compatible typography replacement
on PDF documents while keeping document geometry and ATS structures synchronized.
"""

from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

import fitz  # PyMuPDF

from app.services.resume_parser.geometry import DocumentGeometryMap, extract_document_geometry

logger = logging.getLogger(__name__)


def map_font_code(font_name: Optional[str], is_bold: bool = False, is_italic: bool = False) -> str:
    """Map human or PDF font names to PyMuPDF metric-compatible Base14 font codes.

    Base families:
    - sans-serif (Arial, Helvetica, Calibri, Inter, etc.) -> 'helv'
    - serif (Times, Times New Roman, Georgia, Garamond) -> 'times'
    - monospace (Courier, Consolas, Monaco, etc.) -> 'couri'

    Modifiers:
    - bold -> 'bo'
    - italic -> 'it'
    - bold-italic -> 'bi'
    """
    fn = (font_name or "helv").lower()

    if any(k in fn for k in ["times", "serif", "georgia", "garamond", "palatino", "cambria", "baskerville"]):
        base = "times"
    elif any(k in fn for k in ["couri", "mono", "consolas", "menlo", "code", "inconsolata"]):
        base = "couri"
    else:
        base = "helv"

    if is_bold and is_italic:
        suffix = "bi"
    elif is_bold:
        suffix = "bo"
    elif is_italic:
        suffix = "it"
    else:
        suffix = ""

    if base == "helv":
        return f"he{suffix}" if suffix else "helv"
    elif base == "times":
        return f"ti{suffix}" if suffix else "times-roman"
    elif base == "couri":
        return f"co{suffix}" if suffix else "cour"
    return "helv"


def parse_color_rgb(color_val: Any) -> Tuple[float, float, float]:
    """Convert integer, hex string, or RGB iterable to PyMuPDF RGB float tuple [0.0, 1.0]."""
    if color_val is None:
        return (0.0, 0.0, 0.0)

    if isinstance(color_val, (list, tuple)) and len(color_val) >= 3:
        vals = [float(v) for v in color_val[:3]]
        if any(v > 1.0 for v in vals):
            return (min(1.0, max(0.0, vals[0] / 255.0)),
                    min(1.0, max(0.0, vals[1] / 255.0)),
                    min(1.0, max(0.0, vals[2] / 255.0)))
        return (min(1.0, max(0.0, vals[0])),
                min(1.0, max(0.0, vals[1])),
                min(1.0, max(0.0, vals[2])))

    if isinstance(color_val, int):
        if color_val <= 0:
            return (0.0, 0.0, 0.0)
        r = ((color_val >> 16) & 0xFF) / 255.0
        g = ((color_val >> 8) & 0xFF) / 255.0
        b = (color_val & 0xFF) / 255.0
        return (r, g, b)

    if isinstance(color_val, str):
        cleaned = color_val.strip().lstrip("#")
        if len(cleaned) == 6:
            try:
                num = int(cleaned, 16)
                r = ((num >> 16) & 0xFF) / 255.0
                g = ((num >> 8) & 0xFF) / 255.0
                b = (num & 0xFF) / 255.0
                return (r, g, b)
            except ValueError:
                pass

    return (0.0, 0.0, 0.0)


def fit_font_size(
    rect: fitz.Rect,
    text: str,
    initial_font_size: float,
    font_code: str,
    max_y1: Optional[float] = None,
) -> Tuple[float, fitz.Rect]:
    """Iteratively scale down font_size by 0.5pt down to max(6.5, font_size * 0.75) if text overflows.

    If text still overflows at the soft limit, continues scaling down to 6.5pt.
    If it still overflows at 6.5pt, expands rect height into available whitespace up to max_y1 without overlapping obstacles.
    Returns (fitted_font_size, effective_rect).
    """
    if not text.strip():
        return max(6.5, initial_font_size), rect

    font_size = float(initial_font_size) if initial_font_size and initial_font_size > 0 else 10.0
    hard_min = 6.5
    soft_min = max(hard_min, font_size * 0.75)

    tmp_doc = fitz.open()
    try:
        tmp_page = tmp_doc.new_page(width=rect.width + 100, height=rect.height + 400)

        # Phase 1: Try scaling down to soft_min (75% of original font size)
        curr = font_size
        while curr >= soft_min:
            rc = tmp_page.insert_textbox(rect, text, fontsize=curr, fontname=font_code)
            if rc >= 0:
                return round(curr, 2), rect
            curr -= 0.5

        # Phase 2: If still overflows, continue scaling down to hard min (6.5pt)
        while curr >= hard_min:
            rc = tmp_page.insert_textbox(rect, text, fontsize=curr, fontname=font_code)
            if rc >= 0:
                return round(curr, 2), rect
            curr -= 0.5

        # Phase 3: At 6.5pt, expand rect height into available whitespace up to max_y1 if needed
        rc = tmp_page.insert_textbox(rect, text, fontsize=hard_min, fontname=font_code)
        if rc < 0:
            desired_y1 = rect.y1 + abs(rc) + 4.0
            expanded_y1 = min(desired_y1, max_y1) if max_y1 is not None else desired_y1
            effective_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, max(rect.y1, expanded_y1))
        else:
            effective_rect = rect
        return hard_min, effective_rect
    finally:
        tmp_doc.close()


class PDFMutationEngine:
    """Performs spatial redaction and metric-compatible typography replacement on PDF bytes."""

    @classmethod
    def mutate(
        cls,
        pdf_bytes: Union[bytes, io.BytesIO],
        page_index: int = 0,
        bbox: Optional[Union[List[float], Tuple[float, ...]]] = None,
        block_id: Optional[str] = None,
        replacement_text: str = "",
        geometry_map: Optional[Union[Dict[str, Any], DocumentGeometryMap]] = None,
        font_name: Optional[str] = None,
        font_size: Optional[float] = None,
        is_bold: Optional[bool] = None,
        is_italic: Optional[bool] = None,
        text_color: Optional[Any] = None,
    ) -> Tuple[bytes, Dict[str, Any]]:
        """Mutate PDF by replacing the target bounding box or block with replacement_text.

        Args:
            pdf_bytes: Source PDF binary bytes or byte stream.
            page_index: 0-indexed page number (defaults to 0 or block's page).
            bbox: Bounding box [x0, y0, x1, y1].
            block_id: Target block id (e.g. 'p0_b2'). If provided, looks up in geometry_map.
            replacement_text: New text content to insert in place of redacted area.
            geometry_map: Optional DocumentGeometryMap or dict.
            font_name: Explicit font family override.
            font_size: Explicit font size override.
            is_bold: Explicit bold override.
            is_italic: Explicit italic override.
            text_color: Explicit text color override.

        Returns:
            Tuple of (mutated_pdf_bytes, updated_geometry_map_dict).
        """
        raw_bytes = pdf_bytes.getvalue() if isinstance(pdf_bytes, io.BytesIO) else pdf_bytes
        doc = fitz.open(stream=raw_bytes, filetype="pdf")

        # Resolve block from geometry map if block_id provided
        if block_id:
            geom_dict: Optional[Dict[str, Any]] = (
                geometry_map.to_dict()
                if isinstance(geometry_map, DocumentGeometryMap)
                else geometry_map
            )
            if not geom_dict:
                # Fallback: extract geometry from source doc directly
                geom_dict = extract_document_geometry(doc).to_dict()

            matched_block = None
            for p in geom_dict.get("pages", []):
                for b in p.get("blocks", []):
                    if b.get("id") == block_id:
                        matched_block = b
                        if "page" in b and page_index == 0:
                            page_index = b["page"]
                        break
                if matched_block:
                    break

            if matched_block:
                if bbox is None:
                    bbox = matched_block.get("bbox")
                style = matched_block.get("style", {})
                if font_name is None:
                    font_name = style.get("font_name")
                if font_size is None:
                    font_size = style.get("font_size")
                if is_bold is None:
                    is_bold = style.get("bold", False)
                if is_italic is None:
                    is_italic = style.get("italic", False)
                if text_color is None:
                    text_color = style.get("color", 0)

        if not bbox or len(bbox) < 4:
            doc.close()
            raise ValueError(f"Invalid or missing bounding box for mutation (block_id={block_id}, bbox={bbox})")

        total_pages = len(doc)
        if page_index < 0 or page_index >= total_pages:
            doc.close()
            raise IndexError(f"Page index {page_index} out of range [0, {total_pages - 1}]")

        page = doc[page_index]
        rect = fitz.Rect(bbox[0], bbox[1], bbox[2], bbox[3])

        # Find next obstacle block below target rect in the same column to prevent overlap
        page_blocks = page.get_text("blocks")
        obstacles_below = [
            b[1]
            for b in page_blocks
            if b[1] >= rect.y1 - 1.0
            and min(b[2], rect.x1) - max(b[0], rect.x0) > 10.0
        ]
        max_allowed_y1 = min(obstacles_below) - 2.0 if obstacles_below else (page.rect.height - 36.0)
        max_allowed_y1 = max(rect.y1, max_allowed_y1)

        # 2. Map font & color
        effective_font_name = font_name or "Helvetica"
        effective_font_size = float(font_size) if font_size and font_size > 0 else 10.0
        effective_bold = bool(is_bold)
        effective_italic = bool(is_italic)

        font_code = map_font_code(effective_font_name, effective_bold, effective_italic)
        text_color_rgb = parse_color_rgb(text_color)

        # 3. Dynamic typography fitting and insertion
        if replacement_text and replacement_text.strip():
            fitted_font_size, target_rect = fit_font_size(
                rect, replacement_text, effective_font_size, font_code, max_y1=max_allowed_y1
            )
            # Redact the full target_rect area
            page.add_redact_annot(target_rect, fill=(1.0, 1.0, 1.0))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

            rc = page.insert_textbox(
                target_rect,
                replacement_text,
                fontsize=fitted_font_size,
                fontname=font_code,
                color=text_color_rgb,
                align=fitz.TEXT_ALIGN_LEFT,
            )
            # If text overflows even at hard minimum (rc < 0), insert maximum fitting prefix
            if rc < 0:
                words = replacement_text.split()
                low, high = 1, len(words)
                best_text = ""
                while low <= high:
                    mid = (low + high) // 2
                    cand = " ".join(words[:mid])
                    tmp = fitz.open()
                    tp = tmp.new_page(width=target_rect.width + 100, height=target_rect.height + 100)
                    c_rc = tp.insert_textbox(target_rect, cand, fontsize=fitted_font_size, fontname=font_code)
                    tmp.close()
                    if c_rc >= 0:
                        best_text = cand
                        low = mid + 1
                    else:
                        high = mid - 1
                if best_text:
                    page.insert_textbox(
                        target_rect,
                        best_text,
                        fontsize=fitted_font_size,
                        fontname=font_code,
                        color=text_color_rgb,
                        align=fitz.TEXT_ALIGN_LEFT,
                    )
        else:
            # Empty or whitespace: redact the original rect
            page.add_redact_annot(rect, fill=(1.0, 1.0, 1.0))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        # 4. Re-extract updated geometry map
        updated_geometry = extract_document_geometry(doc)
        mutated_pdf_bytes = doc.tobytes(deflate=True)
        doc.close()

        return mutated_pdf_bytes, updated_geometry.to_dict()
