"""Projects parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .entry_detector import detect_project_entries, extract_bullets_from_blocks
from .models import DocumentBlock, ParsedProject
from .text_utils import is_bullet_line, strip_bullet


@dataclass
class ProjectParseResult:
    projects: List[ParsedProject]
    parse_notes: List[str]


def parse_projects_section(blocks: List[DocumentBlock]) -> ProjectParseResult:
    """Parse projects blocks into structured entries."""
    parse_notes = []
    
    if not blocks:
        return ProjectParseResult(projects=[], parse_notes=parse_notes)

    boundaries = detect_project_entries(blocks, skip_first_line=True)
    parse_notes.append(f"Detected {len(boundaries)} project entries")

    projects = []
    
    for start_idx, end_idx in boundaries:
        entry_blocks = blocks[start_idx:end_idx + 1]
        if not entry_blocks:
            continue

        proj = ParsedProject()
        
        # First block is usually the project header
        header_block = entry_blocks[0]
        
        # Determine which line to use as project name (skip section header if first block)
        line_idx = 1 if (start_idx == 0 and len(header_block.lines) > 1) else 0
        if line_idx < len(header_block.lines):
            proj.name = header_block.lines[line_idx].text.strip()
        
        # Remaining blocks are description/bullets
        content_blocks = entry_blocks[1:] if len(entry_blocks) > 1 else []
        
        # Extract bullets
        bullets = extract_bullets_from_blocks(content_blocks)
        
        # Also extract bullets from remaining lines of first block
        for line in header_block.lines[line_idx + 1:]:
            if is_bullet_line(line.text):
                bullets.append(strip_bullet(line.text))
            elif line.text.strip() and len(line.text.strip()) > 20:
                bullets.append(line.text.strip())
        
        proj.bullets = bullets
        
        # Combine non-bullet text as description
        description_parts = []
        for block in content_blocks:
            for line in block.lines:
                text = line.text.strip()
                if text and not text.startswith(("•", "▪", "◦", "‣", "·", "-", "*", "▸", "►", "→")):
                    description_parts.append(text)
        
        # Also add non-bullet lines from first block after the name line
        for line in header_block.lines[line_idx + 1:]:
            text = line.text.strip()
            if text and not text.startswith(("•", "▪", "◦", "‣", "·", "-", "*", "▸", "►", "→")):
                description_parts.append(text)
        
        proj.description = " ".join(description_parts)

        # Determine confidence
        confidence = "medium"
        if proj.name and (proj.description or proj.bullets):
            confidence = "high"
        elif proj.name:
            confidence = "medium"
        else:
            confidence = "low"
        
        proj.confidence = confidence

        if confidence == "low":
            parse_notes.append(f"Low confidence project entry")

        projects.append(proj)

    return ProjectParseResult(projects=projects, parse_notes=parse_notes)