"""Extract conservative document typography from immutable PDF span data."""

from __future__ import annotations

from collections import Counter
from typing import Any


def _clean_font(name: str) -> str:
    name = (name or "").split("+", 1)[-1]
    return name.split("-", 1)[0] or "Calibri"


def _hex_color(value: int) -> str:
    return f"{value & 0xFFFFFF:06X}"


def extract_document_style(doc: Any) -> dict[str, Any]:
    """Return safe style metadata; ambiguous/exotic layouts use compiler defaults."""
    spans: list[dict[str, Any]] = []
    for page in doc:
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                spans.extend(span for span in line.get("spans", []) if span.get("text", "").strip())
    if not spans:
        return {"fallback": True, "reason": "no_text_spans"}

    weighted_fonts = Counter()
    weighted_sizes = Counter()
    colors = Counter()
    heading_spans: list[dict[str, Any]] = []
    for span in spans:
        weight = len(span.get("text", "").strip())
        weighted_fonts[_clean_font(span.get("font", ""))] += weight
        weighted_sizes[round(float(span.get("size", 10.0)), 1)] += weight
        colors[int(span.get("color", 0))] += weight
        if span.get("flags", 0) & 16 or float(span.get("size", 0)) >= 11:
            heading_spans.append(span)
    body_font = weighted_fonts.most_common(1)[0][0]
    body_size = weighted_sizes.most_common(1)[0][0]
    heading_font = _clean_font(heading_spans[0].get("font", body_font)) if heading_spans else body_font
    heading_size = max((float(span.get("size", body_size)) for span in heading_spans), default=body_size + 2)
    accent = next((color for color, _ in colors.most_common() if color not in (0, 0xFFFFFF)), 0x2563EB)
    return {
        "body_font": body_font,
        "body_size_pt": max(10.0, min(11.5, body_size)),
        "heading_font": heading_font,
        "section_heading_size_pt": max(11.0, min(13.0, heading_size)),
        "heading_color_hex": _hex_color(accent),
        "accent_color_hex": _hex_color(accent),
        "fallback": False,
    }
