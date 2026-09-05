"""Education entry parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from .entry_detector import detect_education_entries, extract_bullets_from_blocks, parse_date_range
from .models import DocumentBlock, ParsedEducation
from .text_utils import extract_gpa, looks_like_degree, looks_like_institution


@dataclass
class EducationParseResult:
    education: List[ParsedEducation]
    parse_notes: List[str]


DEGREE_NORMALIZATION = {
    r"b\.?tech": "B.Tech",
    r"b\.?e\.": "B.E.",
    r"bachelor of technology": "B.Tech",
    r"bachelor of engineering": "B.E.",
    r"b\.?s[.\s]?c?": "B.Sc",
    r"bachelor of science": "B.Sc",
    r"b\.?a\.": "B.A.",
    r"bachelor of arts": "B.A.",
    r"b\.?com": "B.Com",
    r"bachelor of commerce": "B.Com",
    r"b\.?b\.?a\.": "BBA",
    r"m\.?tech": "M.Tech",
    r"m\.?e\.": "M.E.",
    r"master of technology": "M.Tech",
    r"master of engineering": "M.E.",
    r"m\.?s[.\s]?c?": "M.Sc",
    r"master of science": "M.Sc",
    r"m\.?a\.": "M.A.",
    r"master of arts": "M.A.",
    r"m\.?com": "M.Com",
    r"master of commerce": "M.Com",
    r"mba": "MBA",
    r"master of business administration": "MBA",
    r"mca": "MCA",
    r"master of computer applications": "MCA",
    r"ph\.?d\.": "Ph.D.",
    r"doctor of philosophy": "Ph.D.",
    r"12th": "12th Grade",
    r"higher secondary": "Higher Secondary",
    r"senior secondary": "Senior Secondary",
    r"diploma": "Diploma",
    r"associate": "Associate Degree",
}


def normalize_degree(text: str) -> str:
    """Normalize degree string to standard format."""
    lower = text.lower().strip()
    
    for pattern, normalized in DEGREE_NORMALIZATION.items():
        if re.search(pattern, lower):
            return normalized
    
    # Return original if no match, but title-cased
    return text.strip().title()


def parse_education_section(blocks: List[DocumentBlock]) -> EducationParseResult:
    """Parse education blocks into structured entries."""
    parse_notes = []
    
    if not blocks:
        return EducationParseResult(education=[], parse_notes=parse_notes)

    boundaries = detect_education_entries(blocks, skip_first_line=True)
    parse_notes.append(f"Detected {len(boundaries)} education entries via entry detector")

    # If entry detector fails to find good boundaries, fall back to treating all blocks as one entry
    if len(boundaries) == 0 or (len(boundaries) == 1 and boundaries[0][0] > 1):
        # Entry detector missed some blocks (e.g., institution in separate block)
        # Fall back: treat all blocks as a single education entry
        boundaries = [(0, len(blocks) - 1)]
        parse_notes.append("Entry detector missed blocks, falling back to single entry")

    education = []
    
    for start_idx, end_idx in boundaries:
        entry_blocks = blocks[start_idx:end_idx + 1]
        if not entry_blocks:
            continue

        edu = ParsedEducation()
        
        # Combine all text for this entry
        full_text = "\n".join(b.text for b in entry_blocks)
        
        # Extract degree
        degree_match = None
        for block in entry_blocks:
            for line in block.lines:
                if looks_like_degree(line.text):
                    degree_match = line.text.strip()
                    break
            if degree_match:
                break
        
        if degree_match:
            edu.degree = normalize_degree(degree_match)
        
        # Extract institution
        institution_match = None
        for block in entry_blocks:
            for line in block.lines:
                if looks_like_institution(line.text):
                    institution_match = line.text.strip()
                    break
            if institution_match:
                break
        
        if institution_match:
            # Clean up institution name
            parts = [p.strip() for p in re.split(r"[,|]", institution_match) if p.strip()]
            inst_part = next((p for p in parts if looks_like_institution(p)), parts[0])
            edu.institution = re.sub(r"\s*\(\d{4}\)$", "", inst_part).strip()
        else:
            # Fallback: find line that isn't degree, date, or GPA
            for block in entry_blocks:
                for line in block.lines:
                    txt = line.text.strip()
                    if (
                        txt
                        and not looks_like_degree(txt)
                        and not extract_gpa(txt)
                        and not parse_date_range(txt)[0]
                        and not any(c in txt.lower() for c in ("cgpa", "percentage", "%"))
                        and len(txt) > 3
                    ):
                        edu.institution = re.split(r"[,|]", txt)[0].strip()
                        break
                if edu.institution:
                    break

        # If no degree found but institution found, check first relevant line
        if not degree_match and entry_blocks[0].lines:
            line_idx = 1 if (start_idx == 0 and len(entry_blocks[0].lines) > 1) else 0
            if line_idx < len(entry_blocks[0].lines):
                first_line = entry_blocks[0].lines[line_idx].text.strip()
                if looks_like_degree(first_line):
                    edu.degree = normalize_degree(first_line)
                elif looks_like_institution(first_line):
                    edu.institution = re.split(r"[,|]", first_line)[0].strip()
        
        # Extract dates
        start_date, end_date = parse_date_range(full_text)
        if start_date and end_date and start_date == end_date:
            end_date = None
        edu.start_date = start_date
        edu.end_date = end_date

        # Extract GPA
        gpa = extract_gpa(full_text)
        if gpa:
            edu.gpa = gpa

        # Determine confidence
        confidence = "medium"
        if edu.degree and edu.institution:
            confidence = "high"
        elif edu.degree or edu.institution:
            confidence = "medium"
        else:
            confidence = "low"
        
        edu.confidence = confidence

        if confidence == "low":
            parse_notes.append(f"Low confidence education entry")

        education.append(edu)

    return EducationParseResult(education=education, parse_notes=parse_notes)