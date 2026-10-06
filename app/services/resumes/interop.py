"""JSON Resume (v1.0.0) standard interoperability and Plaintext/LinkedIn exports.

Maps:
  - JSON Resume v1.0.0 <-> CareerOS ResumeProfile
  - Stores provenance metadata in `x-careeros` extension.
  - Plaintext formatted rendering.
  - LinkedIn-paste clean block formatting.
"""

from __future__ import annotations

import json
from typing import Any

from app.models.resume import ResumeProfile


def resume_profile_to_json_resume(profile: ResumeProfile) -> dict[str, Any]:
    """Export CareerOS ResumeProfile to JSON Resume v1.0.0 format."""
    p = profile.personal
    basics = {
        "name": p.full_name or "",
        "label": profile.summary or "",
        "email": p.email or "",
        "phone": p.phone or "",
        "url": p.website or "",
        "summary": profile.summary or "",
        "location": {
            "city": p.location or "",
        },
        "profiles": [],
    }

    if p.linkedin:
        basics["profiles"].append({"network": "LinkedIn", "url": p.linkedin})
    if p.github:
        basics["profiles"].append({"network": "GitHub", "url": p.github})

    work = []
    for exp in (profile.experience or []):
        work.append({
            "name": exp.company or "",
            "position": exp.role or "",
            "startDate": exp.start_date or "",
            "endDate": exp.end_date or "",
            "summary": "",
            "highlights": exp.get_responsibility_texts() if hasattr(exp, "get_responsibility_texts") else [],
        })

    education = []
    for edu in (profile.education or []):
        education.append({
            "institution": edu.institution or "",
            "area": edu.field or "",
            "studyType": edu.degree or "",
            "startDate": edu.start_date or "",
            "endDate": edu.end_date or "",
            "score": edu.gpa or "",
        })

    all_skills = (
        profile.skills.technical
        + profile.skills.tools
        + profile.skills.languages
        + profile.skills.databases
        + profile.skills.analytics
        + profile.skills.soft_skills
    )
    skills = [{"name": s, "keywords": []} for s in all_skills]

    projects = []
    for proj in (profile.projects or []):
        projects.append({
            "name": proj.name or "",
            "description": proj.description or "",
            "highlights": [b.text for b in proj.responsibilities] if hasattr(proj, "responsibilities") else [],
            "keywords": proj.technologies or [],
            "url": proj.url or "",
        })

    return {
        "$schema": "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json",
        "basics": basics,
        "work": work,
        "education": education,
        "skills": skills,
        "projects": projects,
        "x-careeros": {
            "version": "1.0",
            "source": "CareerOS",
            "certifications": [c.model_dump() for c in (profile.certifications or [])],
        },
    }


def json_resume_to_resume_profile(data: dict[str, Any]) -> ResumeProfile:
    """Import JSON Resume v1.0.0 format into CareerOS ResumeProfile."""
    from app.models.resume import PersonalInfo, ExperienceItem, EducationItem, ProjectItem, SkillCategory, BulletItem

    basics = data.get("basics") or {}
    personal = PersonalInfo(
        full_name=basics.get("name") or "",
        email=basics.get("email") or "",
        phone=basics.get("phone") or "",
        location=(basics.get("location") or {}).get("city") or "",
    )
    for p in basics.get("profiles", []):
        net = (p.get("network") or "").lower()
        if "linkedin" in net:
            personal.linkedin = p.get("url")
        elif "github" in net:
            personal.github = p.get("url")

    experience = []
    for w in data.get("work", []):
        bullets = [BulletItem(text=h) for h in (w.get("highlights") or [])]
        experience.append(ExperienceItem(
            company=w.get("name") or "",
            role=w.get("position") or "",
            start_date=w.get("startDate") or "",
            end_date=w.get("endDate") or "",
            responsibilities=bullets,
        ))

    education = []
    for e in data.get("education", []):
        education.append(EducationItem(
            institution=e.get("institution") or "",
            degree=e.get("studyType") or "",
            field=e.get("area") or "",
            start_date=e.get("startDate") or "",
            end_date=e.get("endDate") or "",
            gpa=e.get("score") or "",
        ))

    skill_names = [s.get("name") for s in data.get("skills", []) if s.get("name")]
    skills = SkillCategory(technical=skill_names)

    projects = []
    for pr in data.get("projects", []):
        projects.append(ProjectItem(
            name=pr.get("name") or "",
            description=pr.get("description") or "",
            responsibilities=[BulletItem(text=h) for h in (pr.get("highlights") or [])],
            technologies=pr.get("keywords") or [],
            url=pr.get("url") or "",
        ))

    return ResumeProfile(
        personal=personal,
        summary=basics.get("summary") or basics.get("label") or "",
        experience=experience,
        education=education,
        skills=skills,
        projects=projects,
    )


def export_plain_text(profile: ResumeProfile) -> str:
    """Render a clean, plain-text format for direct clipboard or terminal use."""
    lines = []
    p = profile.personal
    lines.append((p.full_name or "").upper())
    contact_parts = [
        p.email,
        p.phone,
        p.location,
        p.linkedin,
    ]
    lines.append(" | ".join([cp for cp in contact_parts if cp]))
    lines.append("")

    if profile.summary:
        lines.append("PROFESSIONAL SUMMARY")
        lines.append("--------------------")
        lines.append(profile.summary)
        lines.append("")

    all_skills = (
        profile.skills.technical
        + profile.skills.tools
        + profile.skills.languages
        + profile.skills.databases
        + profile.skills.analytics
        + profile.skills.soft_skills
    )
    if all_skills:
        lines.append("SKILLS")
        lines.append("------")
        lines.append(", ".join(all_skills))
        lines.append("")

    if profile.experience:
        lines.append("EXPERIENCE")
        lines.append("----------")
        for exp in profile.experience:
            lines.append(f"{exp.role or ''} at {exp.company or ''} ({exp.start_date or ''} - {exp.end_date or 'Present'})")
            for b in exp.get_responsibility_texts():
                lines.append(f"  • {b}")
            lines.append("")

    if profile.education:
        lines.append("EDUCATION")
        lines.append("---------")
        for edu in profile.education:
            lines.append(f"{edu.degree or ''} in {edu.field or ''} - {edu.institution or ''} ({edu.end_date or ''})")
        lines.append("")

    return "\n".join(lines).strip()
