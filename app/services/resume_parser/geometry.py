"""PDF Document Geometry Engine for CareerOS Resume Studio.

Extracts physical page dimensions, columns, blocks, lines, text spans, fonts,
styles, and semantic section tags without mutating or replacing the original PDF bytes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    import fitz

from .layout import Column, DocumentBlock, DocumentLine, DocumentSpan, PageLayout
from .section_detector import DetectedSection


def _r(val: float) -> float:
    """Round float to 2 decimal places deterministically."""
    return round(float(val), 2)


def _r_bbox(coords: list[float] | tuple[float, ...]) -> list[float]:
    """Round bounding box coordinates [x0, y0, x1, y1] to 2 decimal places."""
    return [_r(c) for c in coords]


@dataclass
class GeometrySpan:
    """A text span within a line with typography and coordinate attributes."""

    text: str
    bbox: list[float]
    font: str
    size: float
    flags: int = 0
    bold: bool = False
    italic: bool = False
    color: int = 0
    origin: Optional[list[float]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": _r_bbox(self.bbox),
            "font": self.font,
            "size": _r(self.size),
            "flags": int(self.flags),
            "bold": bool(self.bold),
            "italic": bool(self.italic),
            "color": int(self.color),
            "origin": [_r(c) for c in self.origin] if self.origin is not None else None,
        }


@dataclass
class GeometryLine:
    """A rendered line of text composed of text spans."""

    id: str
    bbox: list[float]
    baseline_y: Optional[float] = None
    spans: list[GeometrySpan] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "bbox": _r_bbox(self.bbox),
            "baseline_y": _r(self.baseline_y) if self.baseline_y is not None else None,
            "spans": [s.to_dict() for s in self.spans],
        }


@dataclass
class GeometryStyle:
    """Dominant typography and styling attributes for a geometry block."""

    font_name: str
    font_size: float
    line_height: float
    color: int = 0
    bold: bool = False
    italic: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "font_name": self.font_name,
            "font_size": _r(self.font_size),
            "line_height": _r(self.line_height),
            "color": int(self.color),
            "bold": bool(self.bold),
            "italic": bool(self.italic),
        }


@dataclass
class GeometryBlock:
    """A paragraph or logical text block with spatial and semantic tags."""

    id: str
    page: int
    column_id: Optional[str] = None
    section: Optional[str] = None
    item_id: Optional[str] = None
    bbox: list[float] = field(default_factory=list)
    text: str = ""
    lines: list[GeometryLine] = field(default_factory=list)
    style: GeometryStyle = field(
        default_factory=lambda: GeometryStyle(
            font_name="Helvetica",
            font_size=10.0,
            line_height=12.0,
        )
    )
    char_limit: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "page": int(self.page),
            "column_id": self.column_id,
            "section": self.section,
            "item_id": self.item_id,
            "bbox": _r_bbox(self.bbox),
            "text": self.text,
            "lines": [l.to_dict() for l in self.lines],
            "style": self.style.to_dict(),
            "char_limit": int(self.char_limit),
        }


@dataclass
class GeometryColumn:
    """A detected vertical layout column on a page."""

    id: str
    x0: float
    x1: float
    y0: float
    y1: float
    width: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "x0": _r(self.x0),
            "x1": _r(self.x1),
            "y0": _r(self.y0),
            "y1": _r(self.y1),
            "width": _r(self.width),
        }


@dataclass
class GeometryPage:
    """Spatial and structural geometry metadata for a single PDF page."""

    page_index: int
    width: float
    height: float
    rotation: int = 0
    is_multi_column: bool = False
    columns: list[GeometryColumn] = field(default_factory=list)
    blocks: list[GeometryBlock] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_index": int(self.page_index),
            "width": _r(self.width),
            "height": _r(self.height),
            "rotation": int(self.rotation),
            "is_multi_column": bool(self.is_multi_column),
            "columns": [c.to_dict() for c in self.columns],
            "blocks": [b.to_dict() for b in self.blocks],
        }


@dataclass
class DocumentGeometryMap:
    """Top-level document geometry map matching the CareerOS Resume Studio specification."""

    document_id: Optional[str] = None
    page_count: int = 0
    pages: list[GeometryPage] = field(default_factory=list)
    sections_detected: list[str] = field(default_factory=list)
    extractor_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "page_count": int(self.page_count),
            "pages": [p.to_dict() for p in self.pages],
            "sections_detected": self.sections_detected,
            "extractor_version": self.extractor_version,
        }


def _compute_block_style(block: DocumentBlock) -> GeometryStyle:
    """Compute dominant typography style across all spans in a block."""
    spans = [s for line in block.lines for s in line.spans]
    if not spans:
        return GeometryStyle(
            font_name="Helvetica",
            font_size=10.0,
            line_height=12.0,
            color=0,
            bold=False,
            italic=False,
        )

    # Dominant font name
    font_counts: dict[str, int] = {}
    for s in spans:
        fn = getattr(s, "font_name", "").strip() or "Helvetica"
        w = max(1, len(s.text.strip()))
        font_counts[fn] = font_counts.get(fn, 0) + w
    dominant_font = max(font_counts.items(), key=lambda x: x[1])[0]

    # Median font size
    sizes = sorted(s.font_size for s in spans if s.font_size > 0)
    font_size = sizes[len(sizes) // 2] if sizes else 10.0

    # Line height
    if len(block.lines) > 1:
        avg_lh = (block.lines[-1].y0 - block.lines[0].y0) / (len(block.lines) - 1)
        line_height = avg_lh if avg_lh > 0 else font_size * 1.2
    else:
        line_height = font_size * 1.2

    # Dominant color
    color_counts: dict[int, int] = {}
    for s in spans:
        c = getattr(s, "color", 0)
        w = max(1, len(s.text.strip()))
        color_counts[c] = color_counts.get(c, 0) + w
    dominant_color = max(color_counts.items(), key=lambda x: x[1])[0] if color_counts else 0

    # Dominant bold / italic
    bold_chars = sum(len(s.text) for s in spans if s.bold)
    italic_chars = sum(len(s.text) for s in spans if getattr(s, "italic", False))
    total_chars = max(1, sum(len(s.text) for s in spans))

    bold = bold_chars >= (total_chars / 2)
    italic = italic_chars >= (total_chars / 2)

    return GeometryStyle(
        font_name=dominant_font,
        font_size=_r(font_size),
        line_height=_r(line_height),
        color=dominant_color,
        bold=bold,
        italic=italic,
    )


def _compute_char_limit(block: DocumentBlock, style: GeometryStyle) -> int:
    """Calculate character capacity for a block given its bounds and typography."""
    font_sz = style.font_size if style.font_size > 0 else 10.0
    lh = style.line_height if style.line_height > 0 else font_sz * 1.2
    bw = max(1.0, block.x1 - block.x0)
    bh = max(1.0, block.y1 - block.y0)
    char_w = max(1.0, font_sz * 0.5)
    chars_per_line = max(1, int(bw / char_w))
    max_lines = max(len(block.lines), int(round(bh / lh)))
    return max(len(block.text), chars_per_line * max_lines)


def extract_document_geometry(
    doc: Any,  # fitz.Document
    all_blocks: Optional[List[DocumentBlock]] = None,
    page_layouts: Optional[List[PageLayout]] = None,
    detected_sections: Optional[List[DetectedSection]] = None,
) -> DocumentGeometryMap:
    """Extract full document geometry map from parsed document and layout structures.

    Args:
        doc: PyMuPDF Document instance.
        all_blocks: Flattened list of DocumentBlock instances across all pages (optional).
        page_layouts: List of PageLayout instances for each page (optional).
        detected_sections: List of DetectedSection instances from section detector (optional).

    Returns:
        DocumentGeometryMap containing pages, columns, blocks, lines, spans, styles.
    """
    if all_blocks is None or page_layouts is None:
        from .layout import detect_page_layout, extract_blocks_from_pdf_page, reconstruct_reading_order

        all_blocks = []
        page_layouts = []
        if doc is not None:
            for page in doc:
                _, blocks = extract_blocks_from_pdf_page(page)
                layout = detect_page_layout(
                    blocks,
                    page_num=page.number,
                    page_width=page.rect.width,
                    page_height=page.rect.height,
                )
                page_layouts.append(layout)
                ordered_blocks = reconstruct_reading_order(layout)
                all_blocks.extend(ordered_blocks)

    if detected_sections is None:
        from .section_detector import detect_sections

        detected_sections, _ = detect_sections(all_blocks, page_layouts)

    # 1. Map blocks to detected sections
    block_section_map: Dict[int, str] = {}
    for sec in detected_sections:
        # For low-confidence synthetic fallbacks (confidence <= 0.5), only assign if text matches
        if sec.confidence <= 0.5:
            for b in sec.blocks:
                b_text_lower = b.text.lower()
                if "@" in b.text or any(k in b_text_lower for k in ["linkedin.com", "github.com", "phone", "tel:"]):
                    block_section_map[id(b)] = "contact"
                elif any(
                    k in b_text_lower
                    for k in [
                        "summary",
                        "profile",
                        "experienced",
                        "professional with",
                        "results-driven",
                        "years of experience",
                    ]
                ):
                    block_section_map[id(b)] = sec.section_key
                # Ambiguous / uncertain blocks default to None
        else:
            for b in sec.blocks:
                block_section_map[id(b)] = sec.section_key

    # Track sections detected (confidence > 0.5 or actually matched)
    sections_detected = list(
        dict.fromkeys(
            s.section_key
            for s in detected_sections
            if s.section_key and (s.confidence > 0.5 or any(block_section_map.get(id(b)) == s.section_key for b in s.blocks))
        )
    )

    # Find earliest confident section vertical start on page 0
    first_sec_y0 = float("inf")
    for sec in detected_sections:
        if sec.confidence > 0.5 and sec.blocks:
            for b in sec.blocks:
                if b.page == 0 and b.y0 < first_sec_y0:
                    first_sec_y0 = b.y0

    page_count = len(doc) if doc is not None else len(page_layouts)
    pages: List[GeometryPage] = []

    for page_idx in range(page_count):
        # Fetch page metrics from PyMuPDF if available
        if doc is not None and page_idx < len(doc):
            fitz_page = doc[page_idx]
            page_width = float(fitz_page.rect.width)
            page_height = float(fitz_page.rect.height)
            rotation = int(fitz_page.rotation)
        elif page_idx < len(page_layouts):
            layout = page_layouts[page_idx]
            page_width = layout.page_width
            page_height = layout.page_height
            rotation = 0
        else:
            page_width = 612.0
            page_height = 792.0
            rotation = 0

        layout = page_layouts[page_idx] if page_idx < len(page_layouts) else None
        is_multi_col = layout.is_multi_column if layout else False

        # Build GeometryColumn list
        geom_columns: List[GeometryColumn] = []
        block_col_map: Dict[int, str] = {}

        if layout and layout.columns:
            for col_idx, col in enumerate(layout.columns):
                col_id = f"p{page_idx}_col{col_idx}"
                if col.blocks:
                    col_y0 = min(b.y0 for b in col.blocks)
                    col_y1 = max(b.y1 for b in col.blocks)
                    for b in col.blocks:
                        block_col_map[id(b)] = col_id
                else:
                    col_y0 = 0.0
                    col_y1 = page_height

                geom_columns.append(
                    GeometryColumn(
                        id=col_id,
                        x0=_r(col.x0),
                        x1=_r(col.x1),
                        y0=_r(col_y0),
                        y1=_r(col_y1),
                        width=_r(col.width),
                    )
                )

        # Collect blocks for this page in reading order
        page_blocks = [b for b in all_blocks if b.page == page_idx]

        geom_blocks: List[GeometryBlock] = []
        for b_idx, block in enumerate(page_blocks):
            block_id = f"p{page_idx}_b{b_idx}"

            # Correlate column
            col_id = block_col_map.get(id(block))
            if col_id is None and geom_columns:
                # Find matching or nearest column by center x
                center_x = (block.x0 + block.x1) / 2
                best_col = None
                best_dist = float("inf")
                for c in geom_columns:
                    if c.x0 <= center_x <= c.x1:
                        best_col = c
                        break
                    dist = min(abs(center_x - c.x0), abs(center_x - c.x1))
                    if dist < best_dist:
                        best_dist = dist
                        best_col = c
                col_id = best_col.id if best_col else geom_columns[0].id

            # Correlate section
            sec_name = block_section_map.get(id(block))
            if sec_name is None:
                b_text_lower = block.text.lower()
                is_contact = (
                    "@" in block.text
                    or any(k in b_text_lower for k in ["linkedin.com", "github.com", "phone", "tel:"])
                    or (page_idx == 0 and block.y0 < min(120.0, first_sec_y0) and len(block.lines) <= 2)
                )
                if is_contact:
                    sec_name = "contact"
                else:
                    sec_name = None

            # Compute style & char limit
            style = _compute_block_style(block)
            char_limit = _compute_char_limit(block, style)

            # Build lines & spans
            geom_lines: List[GeometryLine] = []
            for l_idx, line in enumerate(block.lines):
                line_id = f"p{page_idx}_b{b_idx}_l{l_idx}"

                baseline_y = None
                geom_spans: List[GeometrySpan] = []
                for span in line.spans:
                    span_origin = getattr(span, "origin", None)
                    if baseline_y is None and span_origin is not None and len(span_origin) >= 2:
                        baseline_y = float(span_origin[1])

                    geom_spans.append(
                        GeometrySpan(
                            text=span.text,
                            bbox=[_r(span.x0), _r(span.y0), _r(span.x1), _r(span.y1)],
                            font=getattr(span, "font_name", "") or "Helvetica",
                            size=_r(span.font_size),
                            flags=getattr(span, "flags", 0),
                            bold=bool(span.bold),
                            italic=bool(getattr(span, "italic", False)),
                            color=int(getattr(span, "color", 0)),
                            origin=[_r(c) for c in span_origin] if span_origin else None,
                        )
                    )

                if baseline_y is None:
                    # Approximation: baseline at ~80% down the line height
                    baseline_y = line.y1 - (line.y1 - line.y0) * 0.2

                geom_lines.append(
                    GeometryLine(
                        id=line_id,
                        bbox=[_r(line.x0), _r(line.y0), _r(line.x1), _r(line.y1)],
                        baseline_y=_r(baseline_y),
                        spans=geom_spans,
                    )
                )

            geom_blocks.append(
                GeometryBlock(
                    id=block_id,
                    page=page_idx,
                    column_id=col_id,
                    section=sec_name,
                    item_id=None,
                    bbox=[_r(block.x0), _r(block.y0), _r(block.x1), _r(block.y1)],
                    text=block.text,
                    lines=geom_lines,
                    style=style,
                    char_limit=char_limit,
                )
            )

        pages.append(
            GeometryPage(
                page_index=page_idx,
                width=_r(page_width),
                height=_r(page_height),
                rotation=rotation,
                is_multi_column=is_multi_col,
                columns=geom_columns,
                blocks=geom_blocks,
            )
        )

    return DocumentGeometryMap(
        document_id=None,
        page_count=page_count,
        pages=pages,
        sections_detected=sections_detected,
        extractor_version="1.0.0",
    )
