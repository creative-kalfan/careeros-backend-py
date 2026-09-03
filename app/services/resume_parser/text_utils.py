"""Text utilities for resume parsing."""

from __future__ import annotations

import re
from typing import List, Optional


# Email regex - robust
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


# Phone regex - supports multiple formats
# +91 98765 43210, +91-9876543210, 9876543210, (080) 1234 5678, etc.
PHONE_RE = re.compile(
    r"""
    (?:
        (?:\+?\d{1,3}[-.\s]?)?     # optional country code
        \(?\d{3,4}\)?               # area code
        [-.\s]?
        \d{3,4}                     # first part
        [-.\s]?
        \d{4}                       # last part
    )
    """,
    re.VERBOSE,
)


# LinkedIn URL regex
LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-/%]+",
    re.IGNORECASE,
)

# GitHub URL regex
GITHUB_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/[\w\-/%]+",
    re.IGNORECASE,
)

# General URL regex
URL_RE = re.compile(
    r"https?://[\w\-._~:/?#\[\]@!$&'()*+,;=%]+",
)

# Date patterns
DATE_RE = re.compile(
    r"""
    (
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}   # Jan 2024, January 2024
        |\d{1,2}/\d{4}                                                         # 01/2024
        |\d{4}                                                                  # 2024
        |(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}\s*[-–—]\s*
          (?:Present|Current|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}|\d{4})
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Simple date pattern for start/end extraction
SIMPLE_DATE_RE = re.compile(
    r"""
    (
        (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}
        |\d{1,2}/\d{4}
        |\d{4}
        |Present
        |Current
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# GPA pattern
GPA_RE = re.compile(
    r"(?:GPA|CGPA|Percentage)[:\s]*([\d.]+)(?:\s*/\s*[\d.]+)?",
    re.IGNORECASE,
)

# Bullet point markers
BULLET_MARKERS = ("•", "▪", "◦", "‣", "·", "-", "*", "▸", "►", "→")

# Common degree patterns
DEGREE_PATTERNS = [
    r"\bB\.?Tech\b",
    r"\bB\.?E\.\b",
    r"\bBachelor of (?:Technology|Engineering|Science|Arts|Commerce|Business Administration)\b",
    r"\bB\.?S[.\s]?C?\b",
    r"\bB\.?A\.\b",
    r"\bB\.?Com\b",
    r"\bB\.?B\.?A\.\b",
    r"\bM\.?Tech\b",
    r"\bM\.?E\.\b",
    r"\bMaster of (?:Technology|Engineering|Science|Arts|Commerce|Business Administration)\b",
    r"\bM\.?S[.\s]?C?\b",
    r"\bM\.?A\.\b",
    r"\bM\.?Com\b",
    r"\bMBA\b",
    r"\bMCA\b",
    r"\bPh\.?D\.\b",
    r"\bDoctor of Philosophy\b",
    r"\b12th\b",
    r"\bHigher Secondary\b",
    r"\bSenior Secondary\b",
    r"\bDiploma\b",
    r"\bAssociate\b",
]

DEGREE_RE = re.compile("|".join(DEGREE_PATTERNS), re.IGNORECASE)

# Institution patterns (universities, colleges, institutes)
INSTITUTION_KEYWORDS = [
    "university",
    "college",
    "institute",
    "school",
    "academy",
    "polytechnic",
    "iit",
    "iim",
    "nit",
    "bits",
    "iiit",
    "iiser",
]


def extract_emails(text: str) -> List[str]:
    """Extract all email addresses from text."""
    return EMAIL_RE.findall(text)


def extract_phones(text: str) -> List[str]:
    """Extract all phone numbers from text."""
    matches = PHONE_RE.findall(text)
    # Clean up matches
    cleaned = []
    for m in matches:
        # Remove extra spaces
        m = re.sub(r"\s+", " ", m).strip()
        if m and m not in cleaned:
            cleaned.append(m)
    return cleaned


def extract_linkedin(text: str) -> List[str]:
    """Extract LinkedIn URLs from text."""
    return LINKEDIN_RE.findall(text)


def extract_github(text: str) -> List[str]:
    """Extract GitHub URLs from text."""
    return GITHUB_RE.findall(text)


def extract_urls(text: str) -> List[str]:
    """Extract all URLs from text."""
    return URL_RE.findall(text)


def extract_dates(text: str) -> List[str]:
    """Extract date-like strings from text."""
    return DATE_RE.findall(text)


def extract_simple_dates(text: str) -> List[str]:
    """Extract simple date components."""
    return SIMPLE_DATE_RE.findall(text)


def extract_gpa(text: str) -> Optional[str]:
    """Extract GPA from text."""
    m = GPA_RE.search(text)
    return m.group(1) if m else None


def is_bullet_line(text: str) -> bool:
    """Check if a line starts with a bullet marker."""
    stripped = text.strip()
    return any(stripped.startswith(marker) for marker in BULLET_MARKERS)


def strip_bullet(text: str) -> str:
    """Remove bullet marker from line start."""
    stripped = text.strip()
    for marker in BULLET_MARKERS:
        if stripped.startswith(marker):
            return stripped[len(marker):].strip()
    return stripped


def looks_like_degree(text: str) -> bool:
    """Check if text looks like a degree."""
    return bool(DEGREE_RE.search(text))


def looks_like_institution(text: str) -> bool:
    """Check if text looks like an institution name."""
    lower = text.lower()
    return any(kw in lower for kw in INSTITUTION_KEYWORDS)


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text."""
    return re.sub(r"\s+", " ", text).strip()


def split_skills_line(line: str) -> List[str]:
    """Split a skills line into individual skills."""
    # Split by common delimiters
    # Order matters: try more specific delimiters first
    skills = []
    
    # First split by semicolons
    parts = re.split(r";", line)
    for part in parts:
        # Then split by pipes
        subparts = re.split(r"\|", part)
        for subpart in subparts:
            # Then split by commas
            skills_list = [s.strip() for s in subpart.split(",")]
            skills.extend([s for s in skills_list if s])
    
    # Also handle bullet points
    if not skills or len(skills) == 1:
        # Try splitting by newlines if it was a multi-line input
        lines = line.split("\n")
        if len(lines) > 1:
            skills = []
            for l in lines:
                l = strip_bullet(l)
                if l:
                    skills.append(l)
    
    return skills


def is_likely_name(text: str) -> bool:
    """Heuristic to check if text looks like a person's name."""
    stripped = text.strip()
    if not stripped:
        return False
    
    words = stripped.split()
    # 2-4 words, each capitalized, no special chars
    if not (2 <= len(words) <= 4):
        return False
    
    # Check each word
    for word in words:
        if not word[0].isupper():
            return False
        if not re.match(r"^[A-Za-z.'-]+$", word):
            return False
    
    # Exclude common non-names
    lower = stripped.lower()
    exclude = {"resume", "cv", "curriculum", "vitae", "profile", "summary", "objective"}
    if any(w in lower for w in exclude):
        return False
    
    return True


def clean_text(text: str) -> str:
    """Clean text for processing."""
    # Remove zero-width characters
    text = text.replace("\u200b", "").replace("\ufeff", "")
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text