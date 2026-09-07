"""Projects parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .entry_detector import detect_project_entries, extract_bullets_from_blocks
from .models import DocumentBlock, ParsedProject
from .text_utils import is_bullet_line, strip_bullet


from .header_lexicon import match_section_header


@dataclass
class ProjectParseResult:
    projects: List[ParsedProject]
    parse_notes: List[str]


def parse_projects_section(blocks: List[DocumentBlock]) -> ProjectParseResult:
    """Parse projects blocks into structured entries."""
    parse_notes = []
    
    if not blocks:
        return ProjectParseResult(projects=[], parse_notes=parse_notes)

    # Check if blocks contain sub-engagements within blocks (e.g. umbrella sections with named project entries)
    multi_projects: List[ParsedProject] = []
    has_multi = False
    for i, b in enumerate(blocks):
        # Scan lines for project name + bullets pattern
        sub_list: List[ParsedProject] = []
        cur_p: Optional[ParsedProject] = None
        start_l = 1 if (i == 0 and len(b.lines) > 1 and match_section_header(b.lines[0].text.strip())) else 0
        for line in b.lines[start_l:]:
            txt = line.text.strip()
            if not txt or match_section_header(txt):
                continue
            if is_bullet_line(txt):
                if cur_p:
                    cur_p.bullets.append(strip_bullet(txt))
            elif len(txt) < 80:
                cur_p = ParsedProject(name=txt, bullets=[], confidence="high")
                sub_list.append(cur_p)
        valid_subs = [p for p in sub_list if p.name and p.bullets]
        if len(valid_subs) >= 2:
            has_multi = True
            multi_projects.extend(valid_subs)
        elif len(valid_subs) == 1 and has_multi:
            multi_projects.extend(valid_subs)

    if has_multi and multi_projects:
        parse_notes.append(f"Detected {len(multi_projects)} sub-engagement project entries")
        return ProjectParseResult(projects=multi_projects, parse_notes=parse_notes)

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