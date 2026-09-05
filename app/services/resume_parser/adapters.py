"""Adapter to map ParsedResume to existing ResumeContent schema."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.models.resume import (
    CertificationItem,
    EducationItem,
    ExperienceItem,
    LanguageItem,
    LeadershipItem,
    LinkItem,
    PersonalInfo,
    ProjectItem,
    ResumeContent,
    ResumeMeta,
    ResumeProfile,
    SkillCategory,
)
from .models import ParsedEducation, ParsedExperience, ParsedProject, ParsedResume
from .skills_parser import SKILL_CATEGORIES, is_genuine_soft_skill

# ponytail: single reverse lookup built once from the canonical taxonomy in
# skills_parser — no second keyword list to drift out of sync.
_SKILL_TO_FIELD: dict[str, str] = {}
for _cat, _skills in SKILL_CATEGORIES.items():
    _field = {
        "programming": "technical",
        "frameworks": "technical",
        "cloud": "technical",
        "devops": "technical",
        "ml_ai": "technical",
        "tools": "tools",
        "languages": "languages",
        "databases": "databases",
        "data": "analytics",
    }.get(_cat, "technical")
    for _s in _skills:
        _SKILL_TO_FIELD.setdefault(_s, _field)


def generate_id() -> str:
    """Generate a short unique ID."""
    return uuid.uuid4().hex[:12]


def map_contact(parsed_contact) -> PersonalInfo:
    """Map ParsedContact to PersonalInfo."""
    return PersonalInfo(
        full_name=parsed_contact.name,
        email=parsed_contact.email,
        phone=parsed_contact.phone,
        location=parsed_contact.location,
        headline=None,
        website=parsed_contact.website,
        linkedin=parsed_contact.linkedin,
        github=parsed_contact.github,
    )


def _bullet_id(text: str) -> str:
    """Generate a deterministic ID for a bullet based on its text content.
    
    Uses a simple FNV-1a-like hash to ensure consistent IDs across server restarts.
    """
    h = 0x811c9dc5
    for c in text.encode("utf-8"):
        h ^= c
        h = (h * 0x01000193) & 0xFFFFFFFF
    # Convert to signed 32-bit integer range, then to positive string
    return str(h % (2**31 - 1) + 1)


def map_experience(parsed_exp: List[ParsedExperience]) -> List[ExperienceItem]:
    """Map ParsedExperience to ExperienceItem."""
    from app.models.resume import BulletItem

    items = []
    for exp in parsed_exp:
        # Build bullet items with deterministic IDs based on bullet text
        responsibilities: list[BulletItem] = []
        for b in exp.bullets:
            responsibilities.append(BulletItem(id=_bullet_id(b), text=b))

        item = ExperienceItem(
            id=_bullet_id(f"{exp.company or ''}-{exp.title or ''}-{exp.start_date or ''}-{exp.end_date or ''}"),
            company=exp.company or None,
            role=exp.title or None,
            location=exp.location,
            start_date=exp.start_date,
            end_date=exp.end_date,
            current=exp.end_date is not None and exp.end_date.lower() in ("present", "current"),
            employment_type=None,
            responsibilities=responsibilities,
            achievements=[],  # Separated in our parser
            tools=[],
            metrics=None,
        )
        items.append(item)
    return items


def map_education(parsed_edu: List[ParsedEducation]) -> List[EducationItem]:
    """Map ParsedEducation to EducationItem."""
    items = []
    for edu in parsed_edu:
        item = EducationItem(
            id=generate_id(),
            institution=edu.institution or None,
            degree=edu.degree or None,
            field=None,  # Not directly extracted
            location=None,
            start_date=edu.start_date,
            end_date=edu.end_date,
            gpa=edu.gpa,
            coursework=[],
            achievements=[],
        )
        items.append(item)
    return items


def map_skills(skills: List[str]) -> SkillCategory:
    """Map flat skills list to SkillCategory.

    Only genuine interpersonal attributes land in soft_skills; everything
    unknown defaults to technical so novel stacks never misrender as soft.
    """
    category = SkillCategory()

    for skill in skills:
        lower = skill.lower().strip()
        field = _SKILL_TO_FIELD.get(lower)
        if field == "tools":
            category.tools.append(skill)
        elif field == "languages":
            category.languages.append(skill)
        elif field == "databases":
            category.databases.append(skill)
        elif field == "analytics":
            category.analytics.append(skill)
        elif field == "technical":
            category.technical.append(skill)
        elif is_genuine_soft_skill(skill):
            category.soft_skills.append(skill)
        else:
            category.technical.append(skill)

    return category


def map_projects(parsed_projects: List[ParsedProject]) -> List[ProjectItem]:
    """Map ParsedProject to ProjectItem."""
    items = []
    for proj in parsed_projects:
        item = ProjectItem(
            id=generate_id(),
            name=proj.name or None,
            description=proj.description or None,
            problem=None,
            contribution=None,
            technologies=[],  # Not directly extracted
            methodology=None,
            results=None,
            metrics=None,
            url=None,
        )
        items.append(item)
    return items


def map_certifications(certs: List[str]) -> List[CertificationItem]:
    """Map certification strings to CertificationItem."""
    items = []
    for cert in certs:
        item = CertificationItem(
            id=generate_id(),
            name=cert,
            issuer=None,
            date=None,
            credential_url=None,
        )
        items.append(item)
    return items


def map_languages(langs: List[str]) -> List[LanguageItem]:
    """Map language strings to LanguageItem."""
    items = []
    for lang in langs:
        parts = [p.strip() for p in lang.replace("–", "-").replace(":", "-").split("-", 1)]
        if len(parts) >= 2:
            item = LanguageItem(
                id=generate_id(),
                language=parts[0],
                proficiency=parts[1],
            )
        else:
            item = LanguageItem(
                id=generate_id(),
                language=lang,
                proficiency=None,
            )
        items.append(item)
    return items


def map_links(links: List[str]) -> List[LinkItem]:
    """Map link strings to LinkItem."""
    items = []
    for link in links:
        label = link
        try:
            from urllib.parse import urlparse
            parsed = urlparse(link if link.startswith("http") else f"https://{link}")
            label = parsed.netloc or parsed.path or link
            url = link if link.startswith("http") else f"https://{link}"
        except Exception:
            url = link

        item = LinkItem(
            id=generate_id(),
            label=label,
            url=url,
        )
        items.append(item)
    return items


def map_achievements(achievements: List[str]) -> List[str]:
    """Map achievements - already strings."""
    return achievements


def map_leadership(parsed: ParsedResume) -> List[LeadershipItem]:
    """Map leadership - not directly extracted, return empty."""
    return []


def map_additional(parsed: ParsedResume) -> List[Any]:
    """Map additional - not directly extracted, return empty."""
    return []


def parsed_resume_to_resume_content(parsed: ParsedResume) -> ResumeContent:
    """
    Convert ParsedResume to ResumeContent (existing schema).
    
    This is the main adapter function that maps the new parser output
    to the existing application schema.
    """
    profile = ResumeProfile(
        personal=map_contact(parsed.contact),
        target_role=None,
        summary=parsed.summary,
        experience=map_experience(parsed.experience),
        internships=[],  # Not separated in new parser
        education=map_education(parsed.education),
        skills=map_skills(parsed.skills),
        projects=map_projects(parsed.projects),
        certifications=map_certifications(parsed.certifications),
        achievements=map_achievements(parsed.achievements),
        leadership=map_leadership(parsed),
        languages=map_languages(parsed.languages),
        links=map_links(parsed.links),
        additional=map_additional(parsed),
    )

    # Calculate meta
    has_work = bool(parsed.experience)
    has_education = bool(parsed.education)
    has_skills = bool(parsed.skills)
    has_projects = bool(parsed.projects)

    score = 0.0
    weights = {
        "personal": 20,
        "experience": 25,
        "education": 15,
        "skills": 20,
        "projects": 10,
        "certifications": 5,
        "achievements": 5,
    }

    if parsed.contact.name or parsed.contact.email:
        score += weights["personal"]
    if has_work:
        score += weights["experience"]
    if has_education:
        score += weights["education"]
    if has_skills:
        score += weights["skills"]
    if has_projects:
        score += weights["projects"]
    if parsed.certifications:
        score += weights["certifications"]
    if parsed.achievements:
        score += weights["achievements"]

    is_fresher = not has_work and (has_projects or has_education)
    
    # Guess experience level
    experience_level = "fresher" if is_fresher else "entry"
    if has_work:
        total_years = 0
        for exp in parsed.experience:
            try:
                start = int(exp.start_date[:4]) if exp.start_date and len(exp.start_date) >= 4 else 2020
                end = int(exp.end_date[:4]) if exp.end_date and exp.end_date.lower() != "present" and len(exp.end_date) >= 4 else 2026
                total_years += max(0, end - start)
            except Exception:
                pass
        if total_years >= 8:
            experience_level = "senior"
        elif total_years >= 4:
            experience_level = "mid"
        elif total_years >= 1:
            experience_level = "junior"

    meta = ResumeMeta(
        is_fresher=is_fresher,
        experience_level=experience_level,
        completeness=min(score, 100.0),
        setup_completed=False,
        setup_step=0,
    )

    return ResumeContent(profile=profile, meta=meta)


def resume_content_to_parsed_resume(content: ResumeContent) -> ParsedResume:
    """
    Reverse adapter: Convert ResumeContent to ParsedResume.
    Useful for round-trip testing.
    """
    # This is a best-effort reverse mapping
    # Some information may be lost
    from .models import ParsedContact, ParsedExperience, ParsedEducation, ParsedProject
    
    contact = ParsedContact(
        name=content.profile.personal.full_name,
        email=content.profile.personal.email,
        phone=content.profile.personal.phone,
        location=content.profile.personal.location,
        linkedin=content.profile.personal.linkedin,
        github=content.profile.personal.github,
        website=content.profile.personal.website,
    )

    experience = []
    for exp in content.profile.experience:
        experience.append(ParsedExperience(
            title=exp.role or "",
            company=exp.company or "",
            location=exp.location,
            start_date=exp.start_date,
            end_date=exp.end_date,
            bullets=exp.get_responsibility_texts(),
            confidence="high" if exp.company and exp.role else "medium",
        ))

    education = []
    for edu in content.profile.education:
        education.append(ParsedEducation(
            degree=edu.degree or "",
            institution=edu.institution or "",
            start_date=edu.start_date,
            end_date=edu.end_date,
            gpa=edu.gpa,
            confidence="high" if edu.degree and edu.institution else "medium",
        ))

    skills = []
    for cat_name, cat_skills in content.profile.skills.model_dump().items():
        if isinstance(cat_skills, list):
            skills.extend(cat_skills)

    projects = []
    for proj in content.profile.projects:
        projects.append(ParsedProject(
            name=proj.name or "",
            description=proj.description or "",
            bullets=[],
            confidence="high" if proj.name else "medium",
        ))

    return ParsedResume(
        contact=contact,
        summary=content.profile.summary,
        experience=experience,
        education=education,
        skills=skills,
        projects=projects,
        certifications=[c.name for c in content.profile.certifications if c.name],
        achievements=content.profile.achievements,
        languages=[l.language for l in content.profile.languages if l.language],
        links=[l.url for l in content.profile.links if l.url],
        parse_notes=[],
    )