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


def detect_columns(
    blocks: List[DocumentBlock],
    page_width: float,
    page_height: Optional[float] = None,
) -> List[Column]:
    """
    Detect column boundaries from block positions.

    Hardened against:
    - Spanning headers/full-width blocks (width > 0.65 * page_width)
    - Right-aligned dates and narrow contact pills
    - False positives requiring >= 2 blocks spanning > 20% vertical space
    """
    if not blocks:
        return []

    effective_height = page_height or max((b.y1 for b in blocks), default=792.0)
    spanning_threshold = 0.65 * page_width

    # Filter out spanning blocks from defining columns
    non_spanning_blocks = [b for b in blocks if (b.x1 - b.x0) <= spanning_threshold]

    # Filter out narrow pills (dates, tags, single-line short snippets)
    # A block is considered defining if it has multi-line content or substantial width/text
    def is_defining_block(b: DocumentBlock) -> bool:
        width = b.x1 - b.x0
        if len(b.lines) >= 2:
            return True
        if width > 0.15 * page_width and len(b.text.strip()) > 20:
            return True
        return False

    defining_blocks = [b for b in non_spanning_blocks if is_defining_block(b)]

    # If we don't have enough defining blocks for multiple columns (at least 2 per col)
    if len(defining_blocks) < 4:
        min_x0 = min(b.x0 for b in blocks)
        max_x1 = max(b.x1 for b in blocks)
        return [Column(x0=max(0.0, min_x0 - 10), x1=min(page_width, max_x1 + 10))]

    # Cluster x-positions (using block left edges x0 with fallback to centers)
    x0_positions = sorted(set(round(b.x0, 1) for b in defining_blocks))
    clusters = []
    curr = [x0_positions[0]]
    for i in range(1, len(x0_positions)):
        gap = x0_positions[i] - x0_positions[i - 1]
        if gap > 60:
            clusters.append(curr)
            curr = [x0_positions[i]]
        else:
            curr.append(x0_positions[i])
    if curr:
        clusters.append(curr)

    # Fallback to center-x clustering if x0 clustering produced only 1 cluster
    if len(clusters) < 2:
        centers = sorted(set(round((b.x0 + b.x1) / 2, 1) for b in defining_blocks))
        clusters = []
        curr = [centers[0]]
        for i in range(1, len(centers)):
            gap = centers[i] - centers[i - 1]
            if gap > 60:
                clusters.append(curr)
                curr = [centers[i]]
            else:
                curr.append(centers[i])
        if curr:
            clusters.append(curr)

    if len(clusters) < 2:
        min_x0 = min(b.x0 for b in blocks)
        max_x1 = max(b.x1 for b in blocks)
        return [Column(x0=max(0.0, min_x0 - 10), x1=min(page_width, max_x1 + 10))]

    # Validate candidate columns: require >= 2 blocks spanning > 20% vertical space
    candidate_cols = []
    for cluster in clusters:
        cluster_blocks = [
            b for b in defining_blocks
            if round(b.x0, 1) in cluster or round((b.x0 + b.x1) / 2, 1) in cluster
        ]
        if not cluster_blocks:
            continue
        col_x0 = max(0.0, min(b.x0 for b in cluster_blocks) - 10)
        col_x1 = min(page_width, max(b.x1 for b in cluster_blocks) + 10)
        v_span = max(b.y1 for b in cluster_blocks) - min(b.y0 for b in cluster_blocks)

        if len(cluster_blocks) >= 2 and v_span >= 0.20 * effective_height and (col_x1 - col_x0) > 80:
            candidate_cols.append(Column(x0=col_x0, x1=col_x1))

    # Multi-column classification requires at least 2 valid columns
    if len(candidate_cols) >= 2:
        candidate_cols.sort(key=lambda c: c.x0)
        return candidate_cols

    # Fallback to single column
    min_x0 = min(b.x0 for b in blocks)
    max_x1 = max(b.x1 for b in blocks)
    return [Column(x0=max(0.0, min_x0 - 10), x1=min(page_width, max_x1 + 10))]


def assign_blocks_to_columns(blocks: List[DocumentBlock], columns: List[Column]) -> List[Column]:
    """Assign blocks to their respective columns based on position."""
    if not columns:
        return []

    # Reset existing blocks
    for col in columns:
        col.blocks = []

    # If single column, assign all blocks sorted top-to-bottom
    if len(columns) == 1:
        columns[0].blocks = sorted(blocks, key=lambda b: (b.y0, b.x0))
        return columns

    # Multi-column: assign each block to best column
    for block in blocks:
        block_width = block.x1 - block.x0
        block_center_x = (block.x0 + block.x1) / 2

        # Spanning blocks assigned to first column so they remain at top/proper order
        if block_width > 0.65 * (columns[-1].x1 - columns[0].x0):
            columns[0].blocks.append(block)
            continue

        best_column = None
        best_distance = float("inf")

        for col in columns:
            if col.x0 <= block_center_x <= col.x1:
                best_column = col
                break
            dist = min(abs(block_center_x - col.x0), abs(block_center_x - col.x1))
            if dist < best_distance:
                best_distance = dist
                best_column = col

        if best_column:
            best_column.blocks.append(block)

    # Sort blocks within each column by y-position (top to bottom)
    for col in columns:
        col.blocks.sort(key=lambda b: (b.y0, b.x0))

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

    # Detect columns with hardened vertical space checks
    columns = detect_columns(blocks, page_width, page_height)
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


def extract_blocks_from_pdf_page(page) -> Tuple[List[DocumentSpan], List[DocumentBlock]]:
    """Extract spans and structured blocks directly from PyMuPDF's get_text('dict')."""
    spans: List[DocumentSpan] = []
    blocks: List[DocumentBlock] = []
    text_dict = page.get_text("dict")

    for b_dict in text_dict.get("blocks", []):
        if "lines" not in b_dict:
            continue
        block_lines: List[DocumentLine] = []
        for l_dict in b_dict["lines"]:
            line_spans: List[DocumentSpan] = []
            for s_dict in l_dict.get("spans", []):
                text = s_dict.get("text", "")
                if not text.strip():
                    continue
                bbox = s_dict.get("bbox", [0, 0, 0, 0])
                flags = s_dict.get("flags", 0)
                origin = s_dict.get("origin", None)
                span = DocumentSpan(
                    text=text,
                    page=page.number,
                    x0=bbox[0],
                    y0=bbox[1],
                    x1=bbox[2],
                    y1=bbox[3],
                    font_size=s_dict.get("size", 0),
                    bold=bool(flags & 16),
                    italic=bool(flags & 2),
                    font_name=s_dict.get("font", ""),
                    color=s_dict.get("color", 0),
                    flags=flags,
                    origin=list(origin) if origin else None,
                )
                line_spans.append(span)
                spans.append(span)

            if line_spans:
                line_spans.sort(key=lambda s: s.x0)
                block_lines.append(
                    DocumentLine(
                        spans=line_spans,
                        page=page.number,
                        x0=min(s.x0 for s in line_spans),
                        y0=min(s.y0 for s in line_spans),
                        x1=max(s.x1 for s in line_spans),
                        y1=max(s.y1 for s in line_spans),
                    )
                )

        if block_lines:
            block_lines.sort(key=lambda l: l.y0)
            blocks.append(
                DocumentBlock(
                    lines=block_lines,
                    page=page.number,
                    x0=min(l.x0 for l in block_lines),
                    y0=min(l.y0 for l in block_lines),
                    x1=max(l.x1 for l in block_lines),
                    y1=max(l.y1 for l in block_lines),
                )
            )

    return spans, blocks


def extract_spans_from_pdf(page) -> List[DocumentSpan]:
    """Extract spans from a PDF page using get_text('dict')."""
    spans, _ = extract_blocks_from_pdf_page(page)
    return spans


def group_spans_into_lines(spans: List[DocumentSpan], y_tolerance: float = 3.0) -> List[DocumentLine]:
    """Group spans into lines based on y-position and horizontal continuity."""
    if not spans:
        return []

    # Sort spans by page, then y, then x
    spans.sort(key=lambda s: (s.page, s.y0, s.x0))

    lines = []
    current_line_spans = [spans[0]]
    current_y = spans[0].y0

    for span in spans[1:]:
        h_gap = span.x0 - current_line_spans[-1].x1
        # Same line requires same page, close vertical position, and reasonable horizontal continuity
        if (
            span.page == current_line_spans[0].page
            and abs(span.y0 - current_y) <= y_tolerance
            and -2.0 <= h_gap <= 25.0
        ):
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