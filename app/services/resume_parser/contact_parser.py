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

    # Focus on actual header blocks (top of first page, strictly above any section headers)
    from .header_lexicon import match_section_header
    first_page_blocks = [b for b in blocks if b.page == 0] or blocks[:5]
    first_page_blocks.sort(key=lambda b: b.y0)
    top_blocks = []
    for b in first_page_blocks:
        if b.lines and match_section_header(b.lines[0].text.strip()):
            break
        if b.y0 < 120:
            top_blocks.append(b)
    if not top_blocks:
        top_blocks = first_page_blocks[:1]

    # Combine text from top header blocks only
    header_text = "\n".join(b.text for b in top_blocks)

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
    candidate_blocks = top_blocks if top_blocks else first_page_blocks[:3]
    for block in candidate_blocks:
        for line in block.lines:
            line_text = line.text.strip()
            if not line_text:
                continue
            
            # Never treat section headers as names
            if match_section_header(line_text):
                continue

            # Skip lines with contact info
            if (EMAIL_RE.search(line_text) or PHONE_RE.search(line_text) or
                LINKEDIN_RE.search(line_text) or GITHUB_RE.search(line_text) or
                URL_RE.search(line_text)):
                continue
            
            # Check if line or prefix before delimiter (e.g. "NAME — TITLE") looks like a name
            name_candidate_text = None
            if is_likely_name(line_text):
                name_candidate_text = line_text
            else:
                parts = re.split(r"\s*[—–\-|]\s*", line_text)
                if parts and is_likely_name(parts[0]):
                    name_candidate_text = parts[0]

            if name_candidate_text:
                # Higher confidence for larger font, bold, top position
                conf = 0.5
                if line.font_size > 14:
                    conf += 0.2
                if line.bold:
                    conf += 0.2
                if block.y0 < 100:  # Near top
                    conf += 0.1
                name_candidates.append((name_candidate_text, conf, block))

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