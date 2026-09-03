"""Layout detection and reading order reconstruction for PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .models import DocumentBlock, DocumentLine, DocumentSpan


@dataclass
class Column:
    """A detected column in a page."""

    x0: float
    x1: float
    blocks: List[DocumentBlock] = None

    def __post_init__(self):
        if self.blocks is None:
            self.blocks = []

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def width(self) -> float:
        return self.x1 - self.x0


@dataclass
class PageLayout:
    """Layout analysis for a single page."""

    page_num: int
    page_width: float
    page_height: float
    columns: List[Column]
    is_multi_column: bool
    body_font_size: float
    parse_notes: List[str] = None

    def __post_init__(self):
        if self.parse_notes is None:
            self.parse_notes = []


def detect_columns(blocks: List[DocumentBlock], page_width: float) -> List[Column]:
    """
    Detect column boundaries from block x-positions.
    
    Uses block center x-positions to identify distinct vertical columns.
    """
    if not blocks:
        return []

    # Collect block center x positions
    x_positions = []
    for block in blocks:
        center_x = (block.x0 + block.x1) / 2
        x_positions.append(center_x)

    if not x_positions:
        return []

    # Cluster x-positions using simple threshold
    # Sort positions
    x_positions = sorted(set(round(x, 1) for x in x_positions))
    
    # Find gaps between clusters
    clusters = []
    current_cluster = [x_positions[0]]
    
    for i in range(1, len(x_positions)):
        gap = x_positions[i] - x_positions[i - 1]
        # If gap is large (> 50 points), it's a new column
        if gap > 50:
            clusters.append(current_cluster)
            current_cluster = [x_positions[i]]
        else:
            current_cluster.append(x_positions[i])
    
    if current_cluster:
        clusters.append(current_cluster)

    # Convert clusters to columns - use min/max of block bounds for column bounds
    columns = []
    for cluster in clusters:
        # Find blocks whose centers fall in this cluster (with rounding)
        cluster_blocks = []
        for b in blocks:
            center_x = round((b.x0 + b.x1) / 2, 1)
            if center_x in cluster:
                cluster_blocks.append(b)
        if not cluster_blocks:
            continue
        x0 = min(b.x0 for b in cluster_blocks)
        x1 = max(b.x1 for b in cluster_blocks)
        # Add some padding
        x0 = max(0, x0 - 10)
        x1 = min(page_width, x1 + 10)
        columns.append(Column(x0=x0, x1=x1))

    # Filter out very narrow columns (likely artifacts)
    columns = [c for c in columns if c.width > 80]

    return columns


def assign_blocks_to_columns(blocks: List[DocumentBlock], columns: List[Column]) -> List[Column]:
    """Assign blocks to their respective columns based on x-position."""
    for block in blocks:
        block_center_x = (block.x0 + block.x1) / 2
        best_column = None
        best_distance = float("inf")

        for col in columns:
            # Check if block center falls within column
            if col.x0 <= block_center_x <= col.x1:
                best_column = col
                break
            # Otherwise find closest column
            dist = min(abs(block_center_x - col.x0), abs(block_center_x - col.x1))
            if dist < best_distance:
                best_distance = dist
                best_column = col

        if best_column:
            best_column.blocks.append(block)

    # Sort blocks within each column by y-position (top to bottom)
    for col in columns:
        col.blocks.sort(key=lambda b: b.y0)

    return columns


def detect_page_layout(
    blocks: List[DocumentBlock],
    page_num: int,
    page_width: float,
    page_height: float,
) -> PageLayout:
    """Analyze a page's layout and detect columns."""
    if not blocks:
        return PageLayout(
            page_num=page_num,
            page_width=page_width,
            page_height=page_height,
            columns=[],
            is_multi_column=False,
            body_font_size=11.0,
        )

    # Calculate body font size (median of all spans)
    font_sizes = []
    for block in blocks:
        for line in block.lines:
            for span in line.spans:
                if span.font_size > 0:
                    font_sizes.append(span.font_size)

    body_font_size = 11.0
    if font_sizes:
        font_sizes.sort()
        body_font_size = font_sizes[len(font_sizes) // 2]

    # Detect columns
    columns = detect_columns(blocks, page_width)
    columns = assign_blocks_to_columns(blocks, columns)

    is_multi_column = len(columns) > 1

    parse_notes = []
    if is_multi_column:
        parse_notes.append(f"Two-column layout detected on page {page_num + 1}")

    return PageLayout(
        page_num=page_num,
        page_width=page_width,
        page_height=page_height,
        columns=columns,
        is_multi_column=is_multi_column,
        body_font_size=body_font_size,
        parse_notes=parse_notes,
    )


def reconstruct_reading_order(page_layout: PageLayout) -> List[DocumentBlock]:
    """
    Reconstruct reading order from page layout.
    
    For single column: simple top-to-bottom.
    For multi-column: process each column top-to-bottom, then concatenate columns left-to-right.
    """
    ordered_blocks = []

    if page_layout.is_multi_column:
        # Sort columns by x-position (left to right)
        sorted_columns = sorted(page_layout.columns, key=lambda c: c.x0)
        for col in sorted_columns:
            ordered_blocks.extend(col.blocks)
    else:
        # Single column: all blocks sorted by y
        all_blocks = []
        for col in page_layout.columns:
            all_blocks.extend(col.blocks)
        all_blocks.sort(key=lambda b: b.y0)
        ordered_blocks = all_blocks

    return ordered_blocks


def extract_spans_from_pdf(page) -> List[DocumentSpan]:
    """Extract spans from a PDF page using get_text('dict')."""
    spans = []
    text_dict = page.get_text("dict")
    
    for block in text_dict.get("blocks", []):
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue
                
                bbox = span.get("bbox", [0, 0, 0, 0])
                font_size = span.get("size", 0)
                flags = span.get("flags", 0)
                font_name = span.get("font", "")
                color = span.get("color", 0)
                
                # Check bold flag (bit 16 = 2^4 = 16)
                bold = bool(flags & 16)
                # Check italic flag (bit 2 = 2^1 = 2) 
                italic = bool(flags & 2)
                
                spans.append(DocumentSpan(
                    text=text,
                    page=page.number,
                    x0=bbox[0],
                    y0=bbox[1],
                    x1=bbox[2],
                    y1=bbox[3],
                    font_size=font_size,
                    bold=bold,
                    italic=italic,
                    font_name=font_name,
                    color=color,
                ))
    
    return spans


def group_spans_into_lines(spans: List[DocumentSpan], y_tolerance: float = 3.0) -> List[DocumentLine]:
    """Group spans into lines based on y-position."""
    if not spans:
        return []

    # Sort spans by page, then y, then x
    spans.sort(key=lambda s: (s.page, s.y0, s.x0))

    lines = []
    current_line_spans = [spans[0]]
    current_y = spans[0].y0

    for span in spans[1:]:
        # Check if on same page and similar y-position
        if span.page == current_line_spans[0].page and abs(span.y0 - current_y) <= y_tolerance:
            current_line_spans.append(span)
        else:
            # Finalize current line
            if current_line_spans:
                current_line_spans.sort(key=lambda s: s.x0)
                x0 = min(s.x0 for s in current_line_spans)
                y0 = min(s.y0 for s in current_line_spans)
                x1 = max(s.x1 for s in current_line_spans)
                y1 = max(s.y1 for s in current_line_spans)
                lines.append(DocumentLine(
                    spans=current_line_spans,
                    page=current_line_spans[0].page,
                    x0=x0, y0=y0, x1=x1, y1=y1,
                ))
            # Start new line
            current_line_spans = [span]
            current_y = span.y0

    # Don't forget the last line
    if current_line_spans:
        current_line_spans.sort(key=lambda s: s.x0)
        x0 = min(s.x0 for s in current_line_spans)
        y0 = min(s.y0 for s in current_line_spans)
        x1 = max(s.x1 for s in current_line_spans)
        y1 = max(s.y1 for s in current_line_spans)
        lines.append(DocumentLine(
            spans=current_line_spans,
            page=current_line_spans[0].page,
            x0=x0, y0=y0, x1=x1, y1=y1,
        ))

    return lines


def group_lines_into_blocks(lines: List[DocumentLine], y_gap_threshold: float = 10.0) -> List[DocumentBlock]:
    """Group lines into blocks (paragraphs) based on vertical gaps."""
    if not lines:
        return []

    blocks = []
    current_block_lines = [lines[0]]

    for line in lines[1:]:
        # Check if same page and close vertically
        prev_line = current_block_lines[-1]
        if (line.page == prev_line.page and 
            line.y0 - prev_line.y1 <= y_gap_threshold):
            current_block_lines.append(line)
        else:
            # Finalize current block
            if current_block_lines:
                x0 = min(l.x0 for l in current_block_lines)
                y0 = min(l.y0 for l in current_block_lines)
                x1 = max(l.x1 for l in current_block_lines)
                y1 = max(l.y1 for l in current_block_lines)
                blocks.append(DocumentBlock(
                    lines=current_block_lines,
                    page=current_block_lines[0].page,
                    x0=x0, y0=y0, x1=x1, y1=y1,
                ))
            current_block_lines = [line]

    # Last block
    if current_block_lines:
        x0 = min(l.x0 for l in current_block_lines)
        y0 = min(l.y0 for l in current_block_lines)
        x1 = max(l.x1 for l in current_block_lines)
        y1 = max(l.y1 for l in current_block_lines)
        blocks.append(DocumentBlock(
            lines=current_block_lines,
            page=current_block_lines[0].page,
            x0=x0, y0=y0, x1=x1, y1=y1,
        ))

    return blocks