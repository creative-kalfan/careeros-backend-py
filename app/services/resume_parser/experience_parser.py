"""Experience entry parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .entry_detector import (
    detect_experience_entries,
    extract_bullets_from_blocks,
    parse_date_range,
    split_company_role_location,
)
from .models import DocumentBlock, ParsedExperience
from .text_utils import is_bullet_line, strip_bullet


@dataclass
class ExperienceParseResult:
    experience: List[ParsedExperience]
    parse_notes: List[str]


def parse_experience_section(blocks: List[DocumentBlock]) -> ExperienceParseResult:
    """Parse experience blocks into structured entries."""
    parse_notes = []
    
    if not blocks:
        return ExperienceParseResult(experience=[], parse_notes=parse_notes)

    # Detect entry boundaries (only skip first line if it's an explicit section header)
    from .header_lexicon import match_section_header
    has_section_hdr = bool(blocks and blocks[0].lines and match_section_header(blocks[0].lines[0].text.strip()))
    boundaries = detect_experience_entries(blocks, skip_first_line=has_section_hdr)
    parse_notes.append(f"Detected {len(boundaries)} experience entries")

    experiences = []
    
    for start_idx, end_idx in boundaries:
        entry_blocks = blocks[start_idx:end_idx + 1]
        if not entry_blocks:
            continue

        exp = ParsedExperience()
        header_block = entry_blocks[0]
        
        # Determine which line to use as header
        # For first block of section, skip the section header line if present
        line_idx = 1 if (has_section_hdr and start_idx == 0 and len(header_block.lines) > 1) else 0
        if line_idx >= len(header_block.lines):
            line_idx = 0
        first_line = header_block.lines[line_idx].text.strip()
        
        # Combine all text from entry blocks for date extraction
        full_entry_text = "\n".join(b.text for b in entry_blocks)
        
        # Extract company, role, location
        company, role, location = split_company_role_location(first_line)
        exp.company = company or ""
        exp.title = role or ""
        exp.location = location

        # Extract dates from full entry text
        start_date, end_date = parse_date_range(full_entry_text)
        exp.start_date = start_date
        exp.end_date = end_date

        # Check for "Present"/"Current" in entry text
        if "present" in full_entry_text.lower() or "current" in full_entry_text.lower():
            exp.end_date = "Present"

        # Extract bullets from remaining blocks + remaining lines of first block
        content_blocks = entry_blocks[1:] if len(entry_blocks) > 1 else []
        bullets = extract_bullets_from_blocks(content_blocks)
        
        # Also extract bullets from remaining lines of first block
        for line in header_block.lines[line_idx + 1:]:
            if is_bullet_line(line.text):
                bullets.append(strip_bullet(line.text))
            elif line.text.strip() and len(line.text.strip()) > 20:
                bullets.append(line.text.strip())
        
        exp.bullets = bullets

        # Determine confidence
        confidence = "medium"
        if company and role and (start_date or end_date):
            confidence = "high"
        elif company or role:
            confidence = "medium"
        else:
            confidence = "low"
        
        exp.confidence = confidence

        if confidence == "low":
            parse_notes.append(f"Low confidence experience entry: '{header_block.text[:50]}'")

        experiences.append(exp)

    return ExperienceParseResult(experience=experiences, parse_notes=parse_notes)