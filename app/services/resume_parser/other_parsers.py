"""Parsers for certifications, achievements, languages, and links."""

from __future__ import annotations

import re
from typing import List

from .models import DocumentBlock
from .text_utils import is_bullet_line, strip_bullet, extract_urls, extract_linkedin, extract_github


def parse_certifications(blocks: List[DocumentBlock]) -> List[str]:
    """Extract certifications from blocks."""
    certs = []
    
    for i, block in enumerate(blocks):
        start_line = 1 if (i == 0 and len(block.lines) > 1) else 0
        for line in block.lines[start_line:]:
            text = line.text.strip()
            if not text:
                continue
            
            # Skip bullet markers, take the content
            if is_bullet_line(text):
                text = strip_bullet(text)
            
            # Filter out very short or very long lines
            if 3 <= len(text) <= 200:
                certs.append(text)
    
    return certs


def parse_achievements(blocks: List[DocumentBlock]) -> List[str]:
    """Extract achievements from blocks."""
    achievements = []
    
    for i, block in enumerate(blocks):
        start_line = 1 if (i == 0 and len(block.lines) > 1) else 0
        for line in block.lines[start_line:]:
            text = line.text.strip()
            if not text:
                continue
            
            if is_bullet_line(text):
                text = strip_bullet(text)
            
            if 5 <= len(text) <= 500:
                achievements.append(text)
    
    return achievements


def parse_languages(blocks: List[DocumentBlock]) -> List[str]:
    """Extract languages from blocks."""
    languages = []
    
    for i, block in enumerate(blocks):
        start_line = 1 if (i == 0 and len(block.lines) > 1) else 0
        for line in block.lines[start_line:]:
            text = line.text.strip()
            if not text:
                continue
            
            if is_bullet_line(text):
                text = strip_bullet(text)
            
            # Try to parse "Language - Proficiency" format
            if " - " in text or " – " in text or ":" in text:
                languages.append(text)
            else:
                languages.append(text)
    
    return languages


def parse_links(blocks: List[DocumentBlock]) -> List[str]:
    """Extract links from blocks."""
    links = []
    
    for block in blocks:
        text = block.text
        urls = extract_urls(text)
        linkedin = extract_linkedin(text)
        github = extract_github(text)
        
        for url in urls + linkedin + github:
            if url not in links:
                links.append(url)
    
    return links


def parse_summary(blocks: List[DocumentBlock]) -> str:
    """Extract summary from blocks."""
    if not blocks:
        return ""
    
    # Combine all text, excluding very short fragments
    parts = []
    for i, block in enumerate(blocks):
        start_line = 1 if (i == 0 and len(block.lines) > 1) else 0
        for line in block.lines[start_line:]:
            text = line.text.strip()
            if len(text) > 20:  # Skip very short lines
                parts.append(text)
    
    return " ".join(parts)