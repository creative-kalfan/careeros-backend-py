"""Validation layer for parsed resume output."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from .models import ParsedExperience, ParsedEducation, ParsedProject, ParsedResume

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validation."""

    is_valid: bool
    errors: List[str]
    warnings: List[str]


def validate_parsed_resume(parsed: ParsedResume) -> ValidationResult:
    """Validate the parsed resume output."""
    errors = []
    warnings = []

    # Check contact object exists
    if not parsed.contact:
        errors.append("Contact object is missing")
    else:
        # Check at least one contact field is present
        contact_fields = [
            parsed.contact.name,
            parsed.contact.email,
            parsed.contact.phone,
            parsed.contact.linkedin,
        ]
        if not any(contact_fields):
            warnings.append("No contact information found")

    # Validate experience entries
    for i, exp in enumerate(parsed.experience):
        if not isinstance(exp, ParsedExperience):
            errors.append(f"Experience entry {i} is not a ParsedExperience object")
            continue

        # Check required fields
        if not exp.title and not exp.company:
            warnings.append(f"Experience entry {i} missing both title and company")

        # Check confidence is valid
        if exp.confidence not in ("high", "medium", "low"):
            errors.append(f"Experience entry {i} has invalid confidence: {exp.confidence}")

        # Check bullets is a list
        if not isinstance(exp.bullets, list):
            errors.append(f"Experience entry {i} bullets is not a list")

        # Check no nested strings accidentally
        for bullet in exp.bullets:
            if not isinstance(bullet, str):
                errors.append(f"Experience entry {i} contains non-string bullet")

    # Validate education entries
    for i, edu in enumerate(parsed.education):
        if not isinstance(edu, ParsedEducation):
            errors.append(f"Education entry {i} is not a ParsedEducation object")
            continue

        if not edu.degree and not edu.institution:
            warnings.append(f"Education entry {i} missing both degree and institution")

        if edu.confidence not in ("high", "medium", "low"):
            errors.append(f"Education entry {i} has invalid confidence: {edu.confidence}")

    # Validate skills
    if not isinstance(parsed.skills, list):
        errors.append("Skills is not a list")
    else:
        for skill in parsed.skills:
            if not isinstance(skill, str):
                errors.append("Skills contains non-string element")

    # Validate projects
    for i, proj in enumerate(parsed.projects):
        if not isinstance(proj, ParsedProject):
            errors.append(f"Project entry {i} is not a ParsedProject object")
            continue

        if proj.confidence not in ("high", "medium", "low"):
            errors.append(f"Project entry {i} has invalid confidence: {proj.confidence}")

        if not isinstance(proj.bullets, list):
            errors.append(f"Project entry {i} bullets is not a list")

    # Validate other arrays
    for field_name in ["certifications", "achievements", "languages", "links"]:
        field_val = getattr(parsed, field_name)
        if not isinstance(field_val, list):
            errors.append(f"{field_name} is not a list")
        else:
            for item in field_val:
                if not isinstance(item, str):
                    errors.append(f"{field_name} contains non-string element")

    # Check parse_notes
    if not isinstance(parsed.parse_notes, list):
        errors.append("parse_notes is not a list")

    # Check for the specific corruption pattern mentioned in requirements
    # "fullNameemailphonelocationlinkedin" type corruption
    contact_dict = {
        "name": parsed.contact.name,
        "email": parsed.contact.email,
        "phone": parsed.contact.phone,
        "location": parsed.contact.location,
        "linkedin": parsed.contact.linkedin,
    }
    for key, val in contact_dict.items():
        if val and isinstance(val, str):
            # Check if multiple fields concatenated
            other_fields = [k for k in contact_dict if k != key and contact_dict[k]]
            for other in other_fields:
                if other in val:
                    errors.append(
                        f"Contact field '{key}' appears to contain concatenated "
                        f"data from '{other}': {val[:100]}"
                    )

    is_valid = len(errors) == 0

    if errors:
        logger.warning("Validation errors: %s", errors)
    if warnings:
        logger.info("Validation warnings: %s", warnings)

    return ValidationResult(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
    )


def sanitize_parsed_resume(parsed: ParsedResume) -> ParsedResume:
    """Sanitize parsed resume - fix common issues."""
    # Ensure all lists are lists
    if not isinstance(parsed.experience, list):
        parsed.experience = []
    if not isinstance(parsed.education, list):
        parsed.education = []
    if not isinstance(parsed.skills, list):
        parsed.skills = []
    if not isinstance(parsed.projects, list):
        parsed.projects = []
    if not isinstance(parsed.certifications, list):
        parsed.certifications = []
    if not isinstance(parsed.achievements, list):
        parsed.achievements = []
    if not isinstance(parsed.languages, list):
        parsed.languages = []
    if not isinstance(parsed.links, list):
        parsed.links = []
    if not isinstance(parsed.parse_notes, list):
        parsed.parse_notes = []

    # Fix confidence values
    for exp in parsed.experience:
        if exp.confidence not in ("high", "medium", "low"):
            exp.confidence = "medium"
    
    for edu in parsed.education:
        if edu.confidence not in ("high", "medium", "low"):
            edu.confidence = "medium"
    
    for proj in parsed.projects:
        if proj.confidence not in ("high", "medium", "low"):
            proj.confidence = "medium"

    return parsed