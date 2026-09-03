"""Contact information extraction from resume header."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from .models import DocumentBlock, ParsedContact
from .text_utils import (
    EMAIL_RE, PHONE_RE, LINKEDIN_RE, GITHUB_RE, URL_RE,
    extract_emails, extract_phones, extract_linkedin, extract_github, extract_urls,
    is_likely_name, normalize_whitespace,
)


@dataclass
class ContactCandidate:
    """A candidate for contact information."""

    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    website: Optional[str] = None
    source_block: Optional[DocumentBlock] = None
    confidence: float = 0.0


def extract_contact_from_blocks(blocks: List[DocumentBlock]) -> ParsedContact:
    """
    Extract contact information from header blocks.
    Uses the top portion of the first page.
    """
    if not blocks:
        return ParsedContact()

    # Focus on first page, top 30% of content
    first_page_blocks = [b for b in blocks if b.page == 0]
    if not first_page_blocks:
        first_page_blocks = blocks[:5]

    # Sort by y-position (top to bottom)
    first_page_blocks.sort(key=lambda b: b.y0)

    # Combine text from top blocks
    header_text = "\n".join(b.text for b in first_page_blocks[:8])

    contact = ParsedContact()

    # Extract email
    emails = extract_emails(header_text)
    if emails:
        contact.email = emails[0]

    # Extract phone
    phones = extract_phones(header_text)
    if phones:
        contact.phone = phones[0]

    # Extract LinkedIn
    linkedin_urls = extract_linkedin(header_text)
    if linkedin_urls:
        contact.linkedin = linkedin_urls[0]
        if not contact.linkedin.startswith("http"):
            contact.linkedin = "https://" + contact.linkedin

    # Extract GitHub
    github_urls = extract_github(header_text)
    if github_urls:
        contact.github = github_urls[0]
        if not contact.github.startswith("http"):
            contact.github = "https://" + contact.github

    # Extract website (other URLs)
    urls = extract_urls(header_text)
    for url in urls:
        if "linkedin.com" not in url and "github.com" not in url:
            contact.website = url
            break

    # Extract name - strongest candidate from first few lines
    name_candidates = []
    for block in first_page_blocks[:5]:
        for line in block.lines:
            line_text = line.text.strip()
            if not line_text:
                continue
            
            # Skip lines with contact info
            if (EMAIL_RE.search(line_text) or PHONE_RE.search(line_text) or
                LINKEDIN_RE.search(line_text) or GITHUB_RE.search(line_text) or
                URL_RE.search(line_text)):
                continue
            
            # Check if looks like a name
            if is_likely_name(line_text):
                # Higher confidence for larger font, bold, top position
                conf = 0.5
                if line.font_size > 14:
                    conf += 0.2
                if line.bold:
                    conf += 0.2
                if block.y0 < 100:  # Near top
                    conf += 0.1
                name_candidates.append((line_text, conf, block))

    if name_candidates:
        # Sort by confidence, take highest
        name_candidates.sort(key=lambda x: x[1], reverse=True)
        contact.name = name_candidates[0][0]

    # Extract location - look for city, state patterns in header
    # Common patterns: "City, State", "City, Country", "City"
    location_patterns = [
        r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*[A-Z]{2}\b",  # City, ST
        r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*[A-Z][a-z]+\b",  # City, State
        r"\bRemote\b",
        r"\bHybrid\b",
    ]
    
    for pattern in location_patterns:
        match = re.search(pattern, header_text)
        if match:
            contact.location = match.group(0)
            break

    return contact