"""Canonical Document Model for CareerOS Resume Document Compiler.

Provides a unified structured representation connecting Semantic Content,
Typographic Style, and Spatial Layout for high-fidelity document generation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.models.resume import (
    BulletItem,
    CertificationItem,
    EducationItem,
    ExperienceItem,
    LeadershipItem,
    PersonalInfo,
    ProjectItem,
    ResumeContent,
    ResumeProfile,
    SkillCategory,
)
from .style_model import DocumentStyleModel, extract_style_model


def _gen_id(prefix: str = "blk") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class DocumentElement:
    """Base semantic document element with attached style and layout."""

    id: str
    semantic_type: str  # e.g., 'header_name', 'summary', 'job_role', 'bullet'
    text: str = ""
    section: Optional[str] = None
    page: int = 0
    column: int = 0
    bbox: Optional[list[float]] = None
    font_name: Optional[str] = None
    font_size: Optional[float] = None
    bold: bool = False
    italic: bool = False
    color_hex: Optional[str] = None
    spacing_after: float = 2.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "semantic_type": self.semantic_type,
            "text": self.text,
            "section": self.section,
            "page": self.page,
            "column": self.column,
            "bbox": self.bbox,
            "font_name": self.font_name,
            "font_size": self.font_size,
            "bold": self.bold,
            "italic": self.italic,
            "color_hex": self.color_hex,
            "spacing_after": self.spacing_after,
        }


@dataclass
class HeaderElement:
    """Header containing candidate identity and contact details."""

    id: str = field(default_factory=lambda: _gen_id("hdr"))
    full_name: str = ""
    headline: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""

    def contact_line(self) -> str:
        parts = filter(None, [self.email, self.phone, self.location, self.linkedin, self.github, self.website])
        return " | ".join(parts)


@dataclass
class BulletElement:
    """Single bullet point with stable ID for precise targeting."""

    id: str = field(default_factory=lambda: _gen_id("blt"))
    text: str = ""


@dataclass
class ExperiencePosition:
    """A role/position inside the experience section."""

    id: str = field(default_factory=lambda: _gen_id("pos"))
    company: str = ""
    role: str = ""
    location: str = ""
    date_range: str = ""
    bullets: list[BulletElement] = field(default_factory=list)


@dataclass
class ProjectEntry:
    """A project entry."""

    id: str = field(default_factory=lambda: _gen_id("prj"))
    name: str = ""
    technologies: list[str] = field(default_factory=list)
    description: str = ""
    url: str = ""
    bullets: list[BulletElement] = field(default_factory=list)


@dataclass
class EducationEntry:
    """An education entry."""

    id: str = field(default_factory=lambda: _gen_id("edu"))
    degree: str = ""
    field_of_study: str = ""
    institution: str = ""
    location: str = ""
    date_range: str = ""
    gpa: str = ""
    coursework: list[str] = field(default_factory=list)


@dataclass
class SkillGroup:
    """Group of skills under a category label."""

    category: str = "Technical Skills"
    skills: list[str] = field(default_factory=list)


@dataclass
class ResumeDocumentModel:
    """Canonical Document Model for CareerOS.

    Represents the complete resume document ready for OOXML DOCX compilation
    or direct spatial rendering.
    """

    document_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    header: HeaderElement = field(default_factory=HeaderElement)
    summary: Optional[DocumentElement] = None
    experience: list[ExperiencePosition] = field(default_factory=list)
    internships: list[ExperiencePosition] = field(default_factory=list)
    projects: list[ProjectEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    skills: list[SkillGroup] = field(default_factory=list)
    certifications: list[DocumentElement] = field(default_factory=list)
    section_order: list[str] = field(
        default_factory=lambda: [
            "summary",
            "experience",
            "projects",
            "education",
            "skills",
            "certifications",
        ]
    )
    style: DocumentStyleModel = field(default_factory=DocumentStyleModel)

    def apply_operation(self, op: dict[str, Any]) -> bool:
        """Apply a validated structured AI operation directly to this document model."""
        operation_type = op.get("operation") or op.get("action")
        target_id = op.get("target") or op.get("target_id")
        child_id = op.get("child_id")
        new_content = op.get("new_content") or op.get("suggestedText") or op.get("suggested_text") or ""

        if not operation_type or not new_content:
            return False

        # 1. Summary replacement
        if operation_type in ("replace_block", "rewrite_summary", "replace"):
            if target_id == "summary" or (self.summary and self.summary.id == target_id) or not target_id:
                if self.summary:
                    self.summary.text = new_content
                else:
                    self.summary = DocumentElement(
                        id=_gen_id("sum"),
                        semantic_type="professional_summary",
                        section="summary",
                        text=new_content,
                    )
                return True

        # 2. Experience bullet rewrite or addition
        for exp in self.experience + self.internships:
            if target_id and exp.id == target_id:
                if operation_type in ("rewrite_bullet", "replace") and child_id:
                    for b in exp.bullets:
                        if b.id == child_id:
                            b.text = new_content
                            return True
                    # Fallback: append if child_id not found
                    exp.bullets.append(BulletElement(id=child_id, text=new_content))
                    return True
                elif operation_type in ("add_bullet", "insert"):
                    exp.bullets.append(BulletElement(text=new_content))
                    return True
                elif operation_type in ("remove_bullet", "delete") and child_id:
                    exp.bullets = [b for b in exp.bullets if b.id != child_id]
                    return True

            # If child_id matches bullet directly without target_id
            if child_id:
                for b in exp.bullets:
                    if b.id == child_id:
                        if operation_type in ("rewrite_bullet", "replace"):
                            b.text = new_content
                            return True
                        elif operation_type in ("remove_bullet", "delete"):
                            exp.bullets.remove(b)
                            return True

        # 3. Project bullet rewrite or addition
        for prj in self.projects:
            if target_id and prj.id == target_id:
                if operation_type in ("rewrite_bullet", "replace") and child_id:
                    for b in prj.bullets:
                        if b.id == child_id:
                            b.text = new_content
                            return True
                    prj.bullets.append(BulletElement(id=child_id, text=new_content))
                    return True
                elif operation_type in ("add_bullet", "insert"):
                    prj.bullets.append(BulletElement(text=new_content))
                    return True
                elif operation_type in ("replace", "replace_block"):
                    prj.description = new_content
                    return True

        # 4. Skills update
        if operation_type in ("update_skill", "insert") or target_id == "skills":
            skills_to_add = [s.strip() for s in new_content.replace("\n", ",").split(",") if s.strip()]
            if self.skills:
                target_group = self.skills[0]
                for s in skills_to_add:
                    if s not in target_group.skills:
                        target_group.skills.append(s)
            else:
                self.skills.append(SkillGroup(category="Technical Skills", skills=skills_to_add))
            return True

        return False

    def to_resume_content(self) -> ResumeContent:
        """Project this document model back into canonical ResumeContent."""
        profile = ResumeProfile(
            personal=PersonalInfo(
                full_name=self.header.full_name,
                headline=self.header.headline,
                email=self.header.email,
                phone=self.header.phone,
                location=self.header.location,
                linkedin=self.header.linkedin,
                github=self.header.github,
                website=self.header.website,
            ),
            summary=self.summary.text if self.summary else None,
            experience=[
                ExperienceItem(
                    id=e.id,
                    company=e.company,
                    role=e.role,
                    location=e.location,
                    start_date=e.date_range.split("—")[0].strip() if "—" in e.date_range else e.date_range,
                    responsibilities=[BulletItem(id=b.id, text=b.text) for b in e.bullets],
                )
                for e in self.experience
            ],
            internships=[
                ExperienceItem(
                    id=e.id,
                    company=e.company,
                    role=e.role,
                    location=e.location,
                    start_date=e.date_range.split("—")[0].strip() if "—" in e.date_range else e.date_range,
                    responsibilities=[BulletItem(id=b.id, text=b.text) for b in e.bullets],
                )
                for e in self.internships
            ],
            projects=[
                ProjectItem(
                    id=p.id,
                    name=p.name,
                    technologies=p.technologies,
                    description=p.description,
                    url=p.url,
                )
                for p in self.projects
            ],
            education=[
                EducationItem(
                    id=edu.id,
                    degree=edu.degree,
                    field=edu.field_of_study,
                    institution=edu.institution,
                    location=edu.location,
                    coursework=edu.coursework,
                )
                for edu in self.education
            ],
            skills=SkillCategory(
                technical=self.skills[0].skills if self.skills else [],
            ),
            certifications=[
                CertificationItem(id=c.id, name=c.text)
                for c in self.certifications
            ],
        )
        return ResumeContent(profile=profile)


def build_document_model(
    content: ResumeContent,
    geometry: Optional[dict[str, Any]] = None,
) -> ResumeDocumentModel:
    """Build a rich ResumeDocumentModel by combining ResumeContent with geometry and styles."""
    style = extract_style_model(geometry)
    profile = content.profile
    p = profile.personal

    header = HeaderElement(
        full_name=p.full_name or "Candidate",
        headline=p.headline or profile.target_role or "",
        email=p.email or "",
        phone=p.phone or "",
        location=p.location or "",
        linkedin=p.linkedin or "",
        github=p.github or "",
        website=p.website or "",
    )

    summary_el = None
    if profile.summary:
        summary_el = DocumentElement(
            id=_gen_id("sum"),
            semantic_type="professional_summary",
            section="summary",
            text=profile.summary,
            font_name=style.body_font,
            font_size=style.body_size_pt,
            color_hex=style.body_color_hex,
        )

    # Build Experience
    experience_positions: list[ExperiencePosition] = []
    for exp in profile.experience:
        bullets = [
            BulletElement(id=b.id, text=b.text)
            for b in exp.responsibilities
            if b.text.strip()
        ]
        dates = " — ".join(filter(None, [exp.start_date, "Present" if exp.current else exp.end_date]))
        experience_positions.append(
            ExperiencePosition(
                id=exp.id,
                company=exp.company or "",
                role=exp.role or "Software Engineer",
                location=exp.location or "",
                date_range=dates,
                bullets=bullets,
            )
        )

    # Build Internships
    internship_positions: list[ExperiencePosition] = []
    for exp in profile.internships:
        bullets = [
            BulletElement(id=b.id, text=b.text)
            for b in exp.responsibilities
            if b.text.strip()
        ]
        dates = " — ".join(filter(None, [exp.start_date, "Present" if exp.current else exp.end_date]))
        internship_positions.append(
            ExperiencePosition(
                id=exp.id,
                company=exp.company or "",
                role=exp.role or "Intern",
                location=exp.location or "",
                date_range=dates,
                bullets=bullets,
            )
        )

    # Build Projects
    projects: list[ProjectEntry] = []
    for proj in profile.projects:
        bullets = []
        if proj.description:
            bullets.append(BulletElement(text=proj.description))
        if proj.results:
            bullets.append(BulletElement(text=f"Results: {proj.results}"))
        projects.append(
            ProjectEntry(
                id=proj.id,
                name=proj.name or "Project",
                technologies=proj.technologies,
                description=proj.description or "",
                url=proj.url or "",
                bullets=bullets,
            )
        )

    # Build Education
    education: list[EducationEntry] = []
    for edu in profile.education:
        dates = " — ".join(filter(None, [edu.start_date, edu.end_date]))
        education.append(
            EducationEntry(
                id=edu.id,
                degree=edu.degree or "",
                field_of_study=edu.field or "",
                institution=edu.institution or "",
                location=edu.location or "",
                date_range=dates,
                gpa=edu.gpa or "",
                coursework=edu.coursework,
            )
        )

    # Build Skills
    skills_groups: list[SkillGroup] = []
    categories = [
        ("technical", "Technical Skills"),
        ("tools", "Tools & Frameworks"),
        ("languages", "Languages"),
        ("databases", "Databases"),
        ("analytics", "Analytics"),
        ("soft_skills", "Soft Skills"),
    ]
    for cat_key, cat_label in categories:
        vals = getattr(profile.skills, cat_key, [])
        if vals:
            skills_groups.append(SkillGroup(category=cat_label, skills=list(vals)))

    if profile.skills.custom:
        for custom_label, custom_vals in profile.skills.custom.items():
            if custom_vals:
                skills_groups.append(SkillGroup(category=custom_label, skills=list(custom_vals)))

    # Build Certifications
    certs: list[DocumentElement] = []
    for c in profile.certifications:
        details = " | ".join(filter(None, [c.name, c.issuer, c.date]))
        certs.append(
            DocumentElement(
                id=c.id,
                semantic_type="certification",
                section="certifications",
                text=details,
            )
        )

    # Determine dynamic section order
    section_order: list[str] = []
    if summary_el:
        section_order.append("summary")
    if experience_positions:
        section_order.append("experience")
    if projects:
        section_order.append("projects")
    if education:
        section_order.append("education")
    if skills_groups:
        section_order.append("skills")
    if internship_positions:
        section_order.append("internships")
    if certs:
        section_order.append("certifications")

    return ResumeDocumentModel(
        header=header,
        summary=summary_el,
        experience=experience_positions,
        internships=internship_positions,
        projects=projects,
        education=education,
        skills=skills_groups,
        certifications=certs,
        section_order=section_order,
        style=style,
    )
