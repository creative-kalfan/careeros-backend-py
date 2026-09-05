"""Entry detection and grouping for experience, education, projects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .models import DocumentBlock, DocumentLine
from .text_utils import (
    DATE_RE, SIMPLE_DATE_RE, extract_simple_dates, is_bullet_line, 
    looks_like_degree, looks_like_institution, strip_bullet
)


@dataclass
class EntryBoundary:
    """Represents a detected entry boundary."""

    block: DocumentBlock
    entry_type: str  # "experience", "education", "project"
    confidence: float
    signals: List[str]


# Experience patterns
COMPANY_SUFFIXES = [
    "inc", "corp", "corporation", "ltd", "limited", "llc", "llp",
    "technologies", "technology", "tech", "solutions", "solution",
    "systems", "system", "services", "service", "labs", "lab",
    "group", "holdings", "ventures", "partners", "partner",
    "associates", "associate", "consulting", "consultants",
    "industries", "industry", "manufacturing", "mfg",
    "international", "intl", "global", "worldwide",
]

ROLE_KEYWORDS = [
    "engineer", "manager", "director", "vp", "vice president",
    "developer", "analyst", "consultant", "designer", "lead",
    "architect", "specialist", "coordinator", "administrator",
    "officer", "president", "ceo", "cto", "cfo", "coo",
    "intern", "trainee", "associate", "assistant", "senior",
    "principal", "staff", "head", "chief", "founder", "co-founder",
    "scientist", "researcher", "data", "product", "project",
    "program", "operations", "sales", "marketing", "hr", "human resources",
    "finance", "accountant", "auditor", "lawyer", "attorney",
    "doctor", "physician", "nurse", "teacher", "professor",
]

LOCATION_INDICATORS = [
    "remote", "hybrid", "onsite", "on-site", "work from home", "wfh",
]


def detect_experience_entries(blocks: List[DocumentBlock], skip_first_line: bool = True) -> List[Tuple[int, int]]:
    """
    Detect experience entry boundaries in blocks.
    Returns list of (start_idx, end_idx) tuples.
    """
    if not blocks:
        return []

    boundaries = []
    in_entry = False
    entry_start = 0

    for i, block in enumerate(blocks):
        text = block.text.strip()
        if not text:
            continue

        # Check first line of block
        line_idx = 1 if (skip_first_line and i == 0 and len(block.lines) > 1) else 0
        if line_idx >= len(block.lines):
            continue
        first_line = block.lines[line_idx].text.strip()
        
        # Skip lines that are ONLY dates (not entry headers)
        dates = extract_simple_dates(first_line)
        is_only_date = len(dates) > 0 and len(first_line) < 40 and not any(c.isalpha() for c in first_line.replace(dates[0], "").replace(dates[1] if len(dates) > 1 else "", ""))
        if is_only_date:
            continue

        # Signal 1: Date pattern in first line (strong indicator of new entry)
        has_date = len(dates) > 0

        # Signal 2: Company-like name (has suffix)
        has_company_suffix = any(
            suffix in first_line.lower() for suffix in COMPANY_SUFFIXES
        )

        # Signal 3: Role keyword in first line
        has_role = any(
            role in first_line.lower() for role in ROLE_KEYWORDS
        )

        # Signal 4: Bold + short (typographic header)
        is_bold_short = (
            block.lines and block.lines[line_idx].bold and len(first_line) < 80
        )

        # Signal 5: Pipe-separated format (Company | Role | Location)
        has_pipe_format = "|" in first_line and first_line.count("|") >= 1

        # Signal 6: "Role at Company" format
        has_at_format = " at " in first_line.lower()

        # Signal 7: Multiple lines with bullets following (entry content)
        has_bullets_following = False
        if i + 1 < len(blocks):
            next_block = blocks[i + 1]
            if next_block.lines and is_bullet_line(next_block.lines[0].text):
                has_bullets_following = True

        # Combine signals for entry header detection
        is_header = False
        signals = []
        
        if has_date and (has_company_suffix or has_role or has_pipe_format):
            is_header = True
            signals.append("date_with_company_or_role")
        if has_company_suffix and len(first_line) < 100:
            is_header = True
            signals.append("company_suffix")
        if has_role and has_date:
            is_header = True
            signals.append("role_with_date")
        if has_pipe_format and has_role:
            is_header = True
            signals.append("pipe_format_with_role")
        if has_at_format:
            is_header = True
            signals.append("at_format")
        if is_bold_short and (has_role or has_company_suffix):
            is_header = True
            signals.append("bold_typography")

        if is_header:
            # Close previous entry if any
            if in_entry:
                boundaries.append((entry_start, i - 1))
            # Start new entry
            in_entry = True
            entry_start = i

    # Close last entry
    if in_entry:
        boundaries.append((entry_start, len(blocks) - 1))

    # If no boundaries found but we have blocks, treat all as one entry
    if not boundaries and blocks:
        boundaries = [(0, len(blocks) - 1)]

    return boundaries


def detect_education_entries(blocks: List[DocumentBlock], skip_first_line: bool = True) -> List[Tuple[int, int]]:
    """Detect education entry boundaries."""
    if not blocks:
        return []

    boundaries = []
    in_entry = False
    entry_start = 0

    for i, block in enumerate(blocks):
        text = block.text.strip()
        if not text:
            continue

        # Check ALL lines in the block for entry headers
        # For first block, we need to check lines after the section header
        start_line_idx = 0
        if skip_first_line and i == 0:
            # Find the first line that's not a section header
            for idx, line in enumerate(block.lines):
                line_text = line.text.strip()
                if line_text and not line_text.isupper():  # Section headers are often ALL CAPS
                    start_line_idx = idx
                    break
            else:
                start_line_idx = 0
        
        for line_idx in range(start_line_idx, len(block.lines)):
            first_line = block.lines[line_idx].text.strip()
            if not first_line:
                continue
            
            # Education signals
            has_degree = looks_like_degree(first_line)
            has_institution = looks_like_institution(first_line)
            has_date = len(extract_simple_dates(first_line)) > 0
            is_bold_short = block.lines and block.lines[line_idx].bold and len(first_line) < 80

            is_header = False
            if has_degree and has_institution:
                is_header = True
            elif has_degree and has_date:
                is_header = True
            elif has_institution and has_date:
                is_header = True
            elif has_institution and not has_degree and i > 0:
                # Institution-only line after first entry - likely new education entry
                is_header = True
            elif is_bold_short and (has_degree or has_institution):
                is_header = True

            if is_header:
                if in_entry:
                    boundaries.append((entry_start, i - 1))
                in_entry = True
                entry_start = i
                break  # Only need one header line per block

    if in_entry:
        boundaries.append((entry_start, len(blocks) - 1))

    if not boundaries and blocks:
        boundaries = [(0, len(blocks) - 1)]

    return boundaries


def detect_project_entries(blocks: List[DocumentBlock], skip_first_line: bool = True) -> List[Tuple[int, int]]:
    """Detect project entry boundaries."""
    if not blocks:
        return []

    boundaries = []
    in_entry = False
    entry_start = 0

    for i, block in enumerate(blocks):
        text = block.text.strip()
        if not text:
            continue

        # Check ALL lines in the block for entry headers
        # For first block, we need to check lines after the section header
        start_line_idx = 0
        if skip_first_line and i == 0:
            # Find the first line that's not a section header
            for idx, line in enumerate(block.lines):
                line_text = line.text.strip()
                if line_text and not line_text.isupper():  # Section headers are often ALL CAPS
                    start_line_idx = idx
                    break
            else:
                start_line_idx = 0
        
        for line_idx in range(start_line_idx, len(block.lines)):
            first_line = block.lines[line_idx].text.strip()
            if not first_line:
                continue
            
            # Project signals: short line, no date, project-like keywords
            is_short = len(first_line) < 80
            has_project_kw = any(kw in first_line.lower() for kw in ["project", "app", "system", "platform", "tool", "website", "application"])
            has_date = len(extract_simple_dates(first_line)) > 0
            is_bold_short = block.lines and block.lines[line_idx].bold and is_short
            no_date = not has_date

            # Additional signal: Title-case short line that could be a project name
            # (e.g., "Real-time Analytics Platform" - no "project" keyword but clearly a project name)
            is_title_case_project = (
                is_short and no_date and 
                len(first_line.split()) >= 2 and
                first_line[0].isupper() and
                not any(kw in first_line.lower() for kw in ["education", "experience", "skills", "certification", "language", "link", "summary", "objective"])
            )

            is_header = False
            if is_bold_short and has_project_kw:
                is_header = True
            elif is_short and has_project_kw and no_date:
                is_header = True
            elif is_bold_short and no_date and len(first_line.split()) <= 6:
                is_header = True
            elif is_title_case_project:
                # Title-case project name - allow for first block too
                is_header = True

            if is_header:
                if in_entry:
                    boundaries.append((entry_start, i - 1))
                in_entry = True
                entry_start = i
                break  # Only need one header line per block

    if in_entry:
        boundaries.append((entry_start, len(blocks) - 1))

    if not boundaries and blocks:
        boundaries = [(0, len(blocks) - 1)]

    return boundaries


def extract_bullets_from_blocks(blocks: List[DocumentBlock]) -> List[str]:
    """Extract all bullet points from a list of blocks."""
    bullets = []
    for block in blocks:
        for line in block.lines:
            if is_bullet_line(line.text):
                bullets.append(strip_bullet(line.text))
            elif line.text.strip() and not line.text.strip().isupper():
                # Non-bullet text that might be a responsibility
                # Only include if it's substantial
                if len(line.text.strip()) > 20:
                    bullets.append(line.text.strip())
    return bullets


def parse_date_range(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse start and end dates from text."""
    dates = extract_simple_dates(text)
    if not dates:
        return None, None
    
    start = dates[0] if dates else None
    end = dates[1] if len(dates) > 1 else None
    
    # Normalize "Present"/"Current"
    if end and end.lower() in ("present", "current"):
        end = "Present"
    
    return start, end


def split_company_role_location(line: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Split a header line into company, role, location.
    Handles formats like:
    - "Company | Role | Location"
    - "Role — Company (Dates)"
    - "Company - Role - Location"
    - "Role at Company, Location"
    - "Company, Location"
    """
    cleaned = re.sub(r"\s*\([^)]*(?:19|20)\d{2}[^)]*\)\s*", " ", line).strip()
    
    # Check for dash variants (em-dash, en-dash, hyphen, question mark from encoding)
    for sep in ["|", " — ", " – ", " - ", " ? "]:
        if sep in cleaned:
            parts = [p.strip() for p in cleaned.split(sep) if p.strip()]
            if len(parts) >= 2:
                p0_role = any(r in parts[0].lower() for r in ROLE_KEYWORDS)
                p1_role = any(r in parts[1].lower() for r in ROLE_KEYWORDS)
                p0_comp = any(c in parts[0].lower() for c in COMPANY_SUFFIXES)
                p1_comp = any(c in parts[1].lower() for c in COMPANY_SUFFIXES)
                loc = parts[2] if len(parts) >= 3 else None
                if (p0_role and not p1_role) or (p1_comp and not p0_comp):
                    return parts[1], parts[0], loc
                return parts[0], parts[1], loc

    # Try "Role at Company, Location"
    at_match = re.match(r"^(.+?)\s+at\s+(.+?)(?:,\s*(.+))?$", line, re.IGNORECASE)
    if at_match:
        role = at_match.group(1).strip()
        company = at_match.group(2).strip()
        location = at_match.group(3).strip() if at_match.group(3) else None
        return company, role, location

    # Default: assume first part is company
    return line, None, None