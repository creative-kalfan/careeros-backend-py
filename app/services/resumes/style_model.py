"""Document Style Model for CareerOS Resume Document Compiler.

Extracts typographic hierarchy, colors, margins, spacing, and layout attributes
from parsed document geometry to enable high-fidelity document reconstruction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _int_to_hex_color(val: int) -> str:
    """Convert integer color (0xRRGGBB) to hex string (e.g. '0F172A')."""
    if val <= 0:
        return "000000"
    return f"{val & 0xFFFFFF:06X}".upper()


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Convert hex string (e.g. '0F172A') to (r, g, b) tuple."""
    hex_str = hex_str.lstrip("#").strip()
    if len(hex_str) != 6:
        return (0, 0, 0)
    try:
        return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))
    except ValueError:
        return (0, 0, 0)


@dataclass
class DocumentStyleModel:
    """Canonical style model capturing visual identity of a resume."""

    # Typography
    body_font: str = "Calibri"
    heading_font: str = "Calibri"
    
    # Font sizes in points (Pt)
    name_size_pt: float = 20.0
    headline_size_pt: float = 11.0
    section_heading_size_pt: float = 12.0
    subheading_size_pt: float = 10.5
    body_size_pt: float = 10.0
    meta_size_pt: float = 8.5

    # Weights
    heading_bold: bool = True
    subheading_bold: bool = True

    # Colors (hex strings without #)
    body_color_hex: str = "1E293B"
    heading_color_hex: str = "0F172A"
    accent_color_hex: str = "2563EB"
    meta_color_hex: str = "64748B"

    # Margins in points (1 inch = 72 pt)
    margin_top_pt: float = 36.0
    margin_bottom_pt: float = 36.0
    margin_left_pt: float = 40.0
    margin_right_pt: float = 40.0

    # Spacing in points
    line_spacing: float = 1.15
    paragraph_after_pt: float = 2.5
    section_before_pt: float = 7.0
    section_after_pt: float = 3.5

    # Dividers and Bullets
    heading_has_divider: bool = True
    divider_color_hex: str = "CBD5E1"
    divider_thickness_pt: float = 1.0
    bullet_indent_pt: float = 14.0

    # Layout
    columns: int = 1
    page_width_pt: float = 595.0  # A4
    page_height_pt: float = 842.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_font": self.body_font,
            "heading_font": self.heading_font,
            "name_size_pt": self.name_size_pt,
            "headline_size_pt": self.headline_size_pt,
            "section_heading_size_pt": self.section_heading_size_pt,
            "subheading_size_pt": self.subheading_size_pt,
            "body_size_pt": self.body_size_pt,
            "meta_size_pt": self.meta_size_pt,
            "body_color_hex": self.body_color_hex,
            "heading_color_hex": self.heading_color_hex,
            "accent_color_hex": self.accent_color_hex,
            "meta_color_hex": self.meta_color_hex,
            "margin_top_pt": self.margin_top_pt,
            "margin_bottom_pt": self.margin_bottom_pt,
            "margin_left_pt": self.margin_left_pt,
            "margin_right_pt": self.margin_right_pt,
            "line_spacing": self.line_spacing,
            "paragraph_after_pt": self.paragraph_after_pt,
            "section_before_pt": self.section_before_pt,
            "section_after_pt": self.section_after_pt,
            "heading_has_divider": self.heading_has_divider,
            "columns": self.columns,
            "page_width_pt": self.page_width_pt,
            "page_height_pt": self.page_height_pt,
        }


def extract_style_model(geometry_dict: Optional[dict[str, Any]] = None) -> DocumentStyleModel:
    """Extract dominant style properties from DocumentGeometryMap or return clean modern defaults."""
    if not geometry_dict or not isinstance(geometry_dict, dict):
        return DocumentStyleModel()

    pages = geometry_dict.get("pages") or []
    if not pages:
        return DocumentStyleModel()

    first_page = pages[0]
    p_width = float(first_page.get("width") or 595.0)
    p_height = float(first_page.get("height") or 842.0)
    is_multi_column = bool(first_page.get("is_multi_column", False))

    # Aggregate fonts, font sizes, and colors across all blocks
    font_counts: dict[str, int] = {}
    sizes: list[float] = []
    heading_sizes: list[float] = []
    colors: dict[str, int] = {}

    min_x = p_width
    max_x = 0.0
    min_y = p_height
    max_y = 0.0

    for page in pages:
        for block in page.get("blocks", []):
            bbox = block.get("bbox") or []
            if len(bbox) == 4:
                min_x = min(min_x, bbox[0])
                min_y = min(min_y, bbox[1])
                max_x = max(max_x, bbox[2])
                max_y = max(max_y, bbox[3])

            style = block.get("style") or {}
            fn = style.get("font_name", "").strip()
            # Clean font name (e.g. 'ABCDEE+Calibri-Bold' -> 'Calibri')
            if "+" in fn:
                fn = fn.split("+", 1)[1]
            if "-" in fn:
                fn = fn.split("-", 1)[0]
            if fn:
                font_counts[fn] = font_counts.get(fn, 0) + len(block.get("text", ""))

            fs = float(style.get("font_size", 0.0))
            if fs > 0:
                sizes.append(fs)
                if block.get("section") and fs >= 11.0:
                    heading_sizes.append(fs)

            col_val = style.get("color")
            if isinstance(col_val, int) and col_val > 0:
                hex_c = _int_to_hex_color(col_val)
                colors[hex_c] = colors.get(hex_c, 0) + 1

    # Dominant font
    dominant_font = max(font_counts.items(), key=lambda x: x[1])[0] if font_counts else "Calibri"

    # Margins from observed content bounds (clamped to sensible ranges)
    left_m = max(24.0, min(72.0, min_x)) if min_x < p_width else 40.0
    right_m = max(24.0, min(72.0, p_width - max_x)) if max_x > 0 else 40.0
    top_m = max(24.0, min(72.0, min_y)) if min_y < p_height else 36.0
    bottom_m = max(24.0, min(72.0, p_height - max_y)) if max_y > 0 else 36.0

    # Sizes
    body_size = 9.5
    if sizes:
        sizes.sort()
        body_size = sizes[len(sizes) // 2]
        body_size = max(8.5, min(11.5, body_size))

    heading_size = max(11.0, min(14.0, max(heading_sizes) if heading_sizes else body_size + 2.0))

    return DocumentStyleModel(
        body_font=dominant_font,
        heading_font=dominant_font,
        name_size_pt=max(18.0, heading_size + 6.0),
        section_heading_size_pt=heading_size,
        body_size_pt=body_size,
        subheading_size_pt=body_size + 1.0,
        margin_left_pt=round(left_m, 1),
        margin_right_pt=round(right_m, 1),
        margin_top_pt=round(top_m, 1),
        margin_bottom_pt=round(bottom_m, 1),
        columns=2 if is_multi_column else 1,
        page_width_pt=round(p_width, 1),
        page_height_pt=round(p_height, 1),
    )
