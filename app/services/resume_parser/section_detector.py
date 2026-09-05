"""Section detection using multiple signals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .header_lexicon import HEADER_LEXICON, match_section_header, normalize_header
from .layout import DocumentBlock, PageLayout
from .models import DocumentLine
from .text_utils import extract_simple_dates, looks_like_degree, looks_like_institution


@dataclass
class SectionCandidate:
    """A candidate section header."""

    block: DocumentBlock
    section_key: str
    confidence: float
    signals: List[str]


@dataclass
class DetectedSection:
    """A detected section with its content blocks."""

    section_key: str
    title: str
    blocks: List[DocumentBlock]
    start_page: int
    end_page: int
    confidence: float


def calculate_body_font_size(blocks: List[DocumentBlock]) -> float:
    """Calculate median font size for body text."""
    font_sizes = []
    for block in blocks:
        for line in block.lines:
            for span in line.spans:
                if span.font_size > 0 and len(span.text.strip()) > 2:
                    font_sizes.append(span.font_size)
    
    if not font_sizes:
        return 11.0
    
    font_sizes.sort()
    return font_sizes[len(font_sizes) // 2]


def detect_sections(
    all_blocks: List[DocumentBlock],
    page_layouts: List[PageLayout],
) -> Tuple[List[DetectedSection], List[str]]:
    """
    Detect sections using multiple signals:
    1. Header lexicon match (strongest)
    2. Font size relative to body
    3. Bold + short text
    4. ALL CAPS
    5. Position (top of page)
    6. Typography consistency
    """
    parse_notes = []
    body_font_size = calculate_body_font_size(all_blocks)
    parse_notes.append(f"Body font size baseline: {body_font_size:.1f}pt")

    # First pass: find all header candidates
    candidates = []
    for block in all_blocks:
        # Check each line in the block
        for line_idx, line in enumerate(block.lines):
            line_text = line.text.strip()
            if not line_text or len(line_text) > 120:
                continue

            # Only consider lines that LOOK like section headers:
            # - First line of block, OR
            # - ALL CAPS, OR  
            # - Larger font than body, OR
            # - Bold + short
            is_potential_header = (
                line_idx == 0 or
                line_text.isupper() or
                line.font_size > body_font_size * 1.15 or
                (line.bold and len(line_text) < 60)
            )
            
            if not is_potential_header:
                continue

            # Signal 1: Header lexicon match
            section_key = match_section_header(line_text)
            if not section_key and line_idx == 0:
                from .entry_detector import ROLE_KEYWORDS, COMPANY_SUFFIXES
                dates = extract_simple_dates(line_text)
                has_role = any(r in line_text.lower() for r in ROLE_KEYWORDS)
                has_company = any(s in line_text.lower() for s in COMPANY_SUFFIXES)
                if dates and (has_role or has_company):
                    section_key = "experience"

            if section_key:
                candidates.append(SectionCandidate(
                    block=block,
                    section_key=section_key,
                    confidence=0.95,
                    signals=["lexicon_match" if match_section_header(line_text) else "entry_header"],
                ))
                continue

            # Signal 2: Font size significantly larger than body
            font_ratio = line.font_size / body_font_size if body_font_size > 0 else 1.0
            is_larger = font_ratio > 1.15

            # Signal 3: Bold + short
            is_bold_short = line.bold and len(line_text) < 60

            # Signal 4: ALL CAPS + short
            is_all_caps = line_text.isupper() and len(line_text) > 2 and len(line_text) < 50

            # Signal 5: Position - near top of page
            is_top = block.y0 < page_layouts[block.page].page_height * 0.15 if block.page < len(page_layouts) else False

            # Combine signals
            signals = []
            confidence = 0.0
            
            if is_larger:
                signals.append("larger_font")
                confidence += 0.3
            if is_bold_short:
                signals.append("bold_short")
                confidence += 0.25
            if is_all_caps:
                signals.append("all_caps")
                confidence += 0.25
            if is_top:
                signals.append("top_position")
                confidence += 0.1

            # Only consider as header if confidence > 0.4
            if confidence > 0.4:
                # Try to infer section from context
                inferred_section = infer_section_from_context(line_text, all_blocks, block)
                if inferred_section:
                    candidates.append(SectionCandidate(
                        block=block,
                        section_key=inferred_section,
                        confidence=confidence,
                        signals=signals,
                    ))

    # Deduplicate candidates - keep best candidate per section per page
    # Prefer candidates that look more like section headers:
    # - First line of block (or only line)
    # - Short text (standalone header)
    # - All caps
    # - Larger font
    seen: Dict[Tuple[int, str], SectionCandidate] = {}
    seen_scores: Dict[Tuple[int, str], float] = {}
    for cand in candidates:
        key = (cand.block.page, cand.section_key)
        
        # Calculate header quality score
        block = cand.block
        # Find which line in the block matched
        matched_line_idx = -1
        for idx, line in enumerate(block.lines):
            if match_section_header(line.text.strip()):
                matched_line_idx = idx
                break
        
        quality_score = 0.0
        if matched_line_idx == 0:
            quality_score += 10  # First line of block
        if matched_line_idx == 0 and len(block.lines) == 1:
            quality_score += 10  # Only line in block
        if block.lines and matched_line_idx >= 0 and block.lines[matched_line_idx].text.strip().isupper():
            quality_score += 5  # All caps
        if block.lines and matched_line_idx >= 0 and block.lines[matched_line_idx].font_size > body_font_size * 1.15:
            quality_score += 5  # Larger font
        if len(block.text.strip()) < 100:
            quality_score += 3  # Short block (likely header only)
        
        total_score = cand.confidence * 100 + quality_score
        
        if key not in seen or total_score > seen_scores[key]:
            seen[key] = cand
            seen_scores[key] = total_score

    unique_candidates = list(seen.values())
    unique_candidates.sort(key=lambda c: (c.block.page, c.block.y0))

    # Build sections from candidates
    sections = []
    used_blocks: Set[int] = set()
    
    for i, cand in enumerate(unique_candidates):
        block_id = id(cand.block)
        if block_id in used_blocks:
            continue

        # Find the end of this section (next header or end of document)
        start_idx = all_blocks.index(cand.block) if cand.block in all_blocks else -1
        if start_idx == -1:
            continue

        # Include the header block itself in the section (parsers will handle header vs content)
        section_blocks = [cand.block]
        used_blocks.add(block_id)
        
        # Collect subsequent blocks until next header
        for j in range(start_idx + 1, len(all_blocks)):
            next_block = all_blocks[j]
            next_id = id(next_block)
            
            # Check if next block is a header candidate
            is_next_header = any(
                id(c.block) == next_id for c in unique_candidates
            )
            
            if is_next_header:
                break
            
            section_blocks.append(next_block)
            used_blocks.add(next_id)

        # Determine end page
        end_page = section_blocks[-1].page if section_blocks else cand.block.page

        sections.append(DetectedSection(
            section_key=cand.section_key,
            title=cand.block.text.strip(),
            blocks=section_blocks,
            start_page=cand.block.page,
            end_page=end_page,
            confidence=cand.confidence,
        ))

        parse_notes.append(
            f"Section '{cand.section_key}' detected at page {cand.block.page + 1} "
            f"({cand.signals}, confidence={cand.confidence:.2f})"
        )

    # Handle blocks before first section (header/contact area)
    first_section_start = min((s.start_page for s in sections), default=len(all_blocks))
    header_blocks = [b for b in all_blocks if b.page < first_section_start or 
                     (b.page == first_section_start and b.y0 < (sections[0].blocks[0].y0 if sections and sections[0].blocks else float('inf')))]
    
    if header_blocks and not any(s.section_key == "summary" for s in sections):
        # Check if there's summary-like content
        header_text = "\n".join(b.text for b in header_blocks)
        if len(header_text) > 50:
            sections.insert(0, DetectedSection(
                section_key="summary",
                title="Professional Summary",
                blocks=header_blocks,
                start_page=header_blocks[0].page,
                end_page=header_blocks[-1].page,
                confidence=0.5,
            ))
            parse_notes.append("Pre-section content treated as summary")

    return sections, parse_notes


def infer_section_from_context(
    text: str,
    all_blocks: List[DocumentBlock],
    current_block: DocumentBlock,
) -> Optional[str]:
    """Infer section type from surrounding context and content patterns."""
    lower = text.lower()
    
    # Check for date patterns (experience/education often have dates)
    dates = extract_simple_dates(text)
    has_dates = len(dates) > 0
    
    # Check for degree/institution patterns
    has_degree = looks_like_degree(text)
    has_institution = looks_like_institution(text)
    
    # Look at following blocks for clues
    idx = all_blocks.index(current_block) if current_block in all_blocks else -1
    following_text = ""
    if idx >= 0:
        for b in all_blocks[idx + 1:idx + 5]:
            following_text += b.text + "\n"
    
    following_lower = following_text.lower()
    
    # Experience indicators
    exp_indicators = ["engineer", "manager", "developer", "analyst", "consultant", 
                      "designer", "lead", "director", "vp", "vice president",
                      "inc", "corp", "ltd", "llc", "technologies", "solutions"]
    
    # Education indicators
    edu_indicators = ["university", "college", "institute", "school", "b.tech", 
                      "m.tech", "b.sc", "m.sc", "mba", "ph.d", "bachelor", "master"]
    
    # Skills indicators
    skills_indicators = ["python", "java", "javascript", "sql", "aws", "docker",
                         "kubernetes", "react", "angular", "vue", "node"]
    
    # Count matches
    exp_score = sum(1 for kw in exp_indicators if kw in following_lower)
    edu_score = sum(1 for kw in edu_indicators if kw in following_lower)
    skills_score = sum(1 for kw in skills_indicators if kw in following_lower)
    
    if has_degree or has_institution or edu_score > exp_score and edu_score > skills_score:
        return "education"
    if has_dates and (exp_score > edu_score and exp_score > skills_score):
        return "experience"
    if skills_score > exp_score and skills_score > edu_score:
        return "skills"
    
    # Check header lexicon partial matches
    for section, keywords in HEADER_LEXICON.items():
        for kw in keywords:
            if kw in lower:
                return section
    
    return None


def get_section_blocks(
    sections: List[DetectedSection],
    section_key: str,
) -> List[DocumentBlock]:
    """Get all blocks belonging to a section."""
    for section in sections:
        if section.section_key == section_key:
            return section.blocks
    return []