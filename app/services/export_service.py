"""Resume export service for PDF and DOCX generation (Step 6)."""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from typing import Any

from app.models.resume import ResumeContent

logger = logging.getLogger(__name__)


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_\- ]+", "", name)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    return cleaned[:80] or "resume"


def _render_html(content: ResumeContent, template: str = "minimal") -> str:
    profile = content.profile
    personal = profile.personal
    sections: list[str] = []

    sections.append('<div class="header"><h1>{name}</h1><p>{headline}</p></div>'.format(
        name=personal.full_name or "Candidate",
        headline=personal.headline or "",
    ))
    if personal.email or personal.phone or personal.location:
        contact = " | ".join(filter(None, [personal.email, personal.phone, personal.location, personal.website, personal.linkedin, personal.github]))
        sections.append('<div class="contact">{contact}</div>'.format(contact=contact))

    if profile.summary:
        sections.append('<div class="section"><h2>Professional Summary</h2><p>{text}</p></div>'.format(text=profile.summary))

    if profile.experience:
        items = []
        for exp in profile.experience:
            header = "{role} at {company}".format(role=exp.role or "", company=exp.company or "")
            date_range = " — ".join(filter(None, [exp.start_date, exp.end_date if not exp.current else "Present"]))
            bullets = "<br/>".join(exp.get_all_bullet_texts())
            items.append('<div class="item"><h3>{header} <span class="date">{date}</span></h3><p>{bullets}</p></div>'.format(
                header=header, date=date_range, bullets=bullets,
            ))
        sections.append('<div class="section"><h2>Experience</h2>{items}</div>'.format(items="".join(items)))

    if profile.internships:
        items = []
        for exp in profile.internships:
            header = "{role} at {company}".format(role=exp.role or "", company=exp.company or "")
            date_range = " — ".join(filter(None, [exp.start_date, exp.end_date if not exp.current else "Present"]))
            bullets = "<br/>".join(exp.get_all_bullet_texts())
            items.append('<div class="item"><h3>{header} <span class="date">{date}</span></h3><p>{bullets}</p></div>'.format(
                header=header, date=date_range, bullets=bullets,
            ))
        sections.append('<div class="section"><h2>Internships</h2>{items}</div>'.format(items="".join(items)))

    if profile.projects:
        items = []
        for proj in profile.projects:
            header = proj.name or "Project"
            bullets = "<br/>".join(filter(None, [proj.description, proj.problem, proj.contribution, proj.results]))
            if proj.technologies:
                bullets += "<br/><em>Technologies: {tech}</em>".format(tech=", ".join(proj.technologies))
            items.append('<div class="item"><h3>{header}</h3><p>{bullets}</p></div>'.format(header=header, bullets=bullets))
        sections.append('<div class="section"><h2>Projects</h2>{items}</div>'.format(items="".join(items)))

    if profile.education:
        items = []
        for edu in profile.education:
            header = "{degree} in {field}".format(degree=edu.degree or "", field=edu.field or "")
            date_range = " — ".join(filter(None, [edu.start_date, edu.end_date]))
            details = ", ".join(filter(None, [edu.institution, edu.gpa]))
            items.append('<div class="item"><h3>{header} <span class="date">{date}</span></h3><p>{details}</p></div>'.format(
                header=header, date=date_range, details=details,
            ))
        sections.append('<div class="section"><h2>Education</h2>{items}</div>'.format(items="".join(items)))

    if profile.skills and any([profile.skills.technical, profile.skills.tools, profile.skills.languages, profile.skills.databases, profile.skills.analytics, profile.skills.soft_skills]):
        items = []
        for category, label in [
            ("technical", "Technical Skills"),
            ("tools", "Tools"),
            ("languages", "Languages"),
            ("databases", "Databases"),
            ("analytics", "Analytics"),
            ("soft_skills", "Soft Skills"),
        ]:
            values = getattr(profile.skills, category, [])
            if values:
                items.append('<div class="skill-category"><strong>{label}:</strong> {values}</div>'.format(label=label, values=", ".join(values)))
        sections.append('<div class="section"><h2>Skills</h2>{items}</div>'.format(items="".join(items)))

    if profile.certifications:
        items = []
        for cert in profile.certifications:
            header = cert.name or "Certification"
            details = " | ".join(filter(None, [cert.issuer, cert.date]))
            items.append('<div class="item"><h3>{header}</h3><p>{details}</p></div>'.format(header=header, details=details))
        sections.append('<div class="section"><h2>Certifications</h2>{items}</div>'.format(items="".join(items)))

    if profile.achievements:
        items = "<br/>".join(profile.achievements)
        sections.append('<div class="section"><h2>Achievements</h2><p>{items}</p></div>'.format(items=items))

    if profile.leadership:
        items = []
        for lead in profile.leadership:
            header = "{role} — {org}".format(role=lead.role or "", org=lead.organization or "")
            date_range = " — ".join(filter(None, [lead.start_date, lead.end_date]))
            details = lead.description or ""
            items.append('<div class="item"><h3>{header} <span class="date">{date}</span></h3><p>{details}</p></div>'.format(
                header=header, date=date_range, details=details,
            ))
        sections.append('<div class="section"><h2>Leadership</h2>{items}</div>'.format(items="".join(items)))

    if profile.languages:
        items = []
        for lang in profile.languages:
            label = lang.language or ""
            if lang.proficiency:
                label += " ({prof})".format(prof=lang.proficiency)
            items.append(label)
        sections.append('<div class="section"><h2>Languages</h2><p>{items}</p></div>'.format(items=", ".join(items)))

    if profile.links:
        items = []
        for link in profile.links:
            label = link.label or link.url or ""
            items.append('{label}: {url}'.format(label=label, url=link.url or ""))
        sections.append('<div class="section"><h2>Links</h2><p>{items}</p></div>'.format(items="<br/>".join(items)))

    if profile.additional:
        items = []
        for add in profile.additional:
            if add.title:
                items.append('<strong>{title}:</strong> {desc}'.format(title=add.title, desc=add.description or ""))
            elif add.description:
                items.append(add.description)
        sections.append('<div class="section"><h2>Additional Information</h2><p>{items}</p></div>'.format(items="<br/>".join(items)))

    html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: Arial, sans-serif; font-size: 11pt; line-height: 1.4; color: #222; margin: 0; padding: 40px; }}
.header {{ text-align: center; margin-bottom: 16px; }}
.header h1 {{ font-size: 22pt; margin: 0; }}
.header p {{ font-size: 12pt; color: #555; margin: 4px 0 0; }}
.contact {{ text-align: center; font-size: 10pt; color: #666; margin-bottom: 16px; }}
.section {{ margin-bottom: 14px; }}
.section h2 {{ font-size: 13pt; text-transform: uppercase; border-bottom: 1px solid #ccc; padding-bottom: 2px; margin: 0 0 6px; }}
.item {{ margin-bottom: 8px; }}
.item h3 {{ font-size: 11pt; margin: 0; }}
.item .date {{ font-size: 10pt; color: #666; }}
.item p {{ margin: 2px 0 0; font-size: 10pt; }}
.skill-category {{ margin-bottom: 4px; font-size: 10pt; }}
</style>
</head>
<body>
{content}
</body>
</html>""".format(content="\n".join(sections))
    return html


class ExportService:
    """Export resume versions to PDF and DOCX."""

    def export_pdf(self, content: ResumeContent, template: str = "minimal") -> bytes:
        html = _render_html(content, template)
        try:
            import io
            import fitz  # PyMuPDF
            buf = io.BytesIO()
            # Try Story API for proper pagination
            if hasattr(fitz, 'Story'):
                writer = fitz.DocumentWriter(buf)
                story = fitz.Story(html)
                page_rect = fitz.Rect(0, 0, 595, 842)  # A4
                content_rect = page_rect + (36, 36, -36, -36)  # margins
                more = True
                while more:
                    dev = writer.begin_page(page_rect)
                    more, _ = story.place(content_rect)
                    story.draw(dev)
                    writer.end_page()
                writer.close()
                return buf.getvalue()
            else:
                # Fallback: single tall page (pre-existing behavior)
                doc = fitz.open()
                page = doc.new_page(width=595, height=842 * 3)
                page.insert_htmlbox(page.rect, html)
                pdf_bytes = doc.tobytes()
                doc.close()
                return pdf_bytes
        except Exception as exc:
            logger.error("PDF export failed: %s", exc)
            raise RuntimeError("Unable to generate PDF") from exc

    def export_docx(self, content: ResumeContent, template: str = "minimal") -> bytes:
        try:
            from docx import Document  # type: ignore
            from docx.shared import Pt  # type: ignore
        except ImportError as exc:
            raise RuntimeError("python-docx is not installed") from exc

        doc = Document()
        style = doc.styles["Normal"]
        style.font.name = "Arial"
        style.font.size = Pt(11)

        profile = content.profile
        personal = profile.personal
        doc.add_heading(personal.full_name or "Candidate", level=0)
        if personal.headline:
            doc.add_paragraph(personal.headline)
        contact_parts = filter(None, [personal.email, personal.phone, personal.location, personal.website, personal.linkedin, personal.github])
        contact_line = " | ".join(contact_parts)
        if contact_line:
            doc.add_paragraph(contact_line)

        if profile.summary:
            doc.add_heading("Professional Summary", level=1)
            doc.add_paragraph(profile.summary)

        if profile.experience:
            doc.add_heading("Experience", level=1)
            for exp in profile.experience:
                doc.add_heading("{role} at {company}".format(role=exp.role or "", company=exp.company or ""), level=2)
                date_range = " — ".join(filter(None, [exp.start_date, exp.end_date if not exp.current else "Present"]))
                doc.add_paragraph(date_range)
                for bullet in exp.get_all_bullet_texts():
                    doc.add_paragraph(bullet, style="List Bullet")

        if profile.internships:
            doc.add_heading("Internships", level=1)
            for exp in profile.internships:
                doc.add_heading("{role} at {company}".format(role=exp.role or "", company=exp.company or ""), level=2)
                date_range = " — ".join(filter(None, [exp.start_date, exp.end_date if not exp.current else "Present"]))
                doc.add_paragraph(date_range)
                for bullet in exp.get_all_bullet_texts():
                    doc.add_paragraph(bullet, style="List Bullet")

        if profile.projects:
            doc.add_heading("Projects", level=1)
            for proj in profile.projects:
                doc.add_heading(proj.name or "Project", level=2)
                for detail in filter(None, [proj.description, proj.problem, proj.contribution, proj.results]):
                    doc.add_paragraph(detail, style="List Bullet")

        if profile.education:
            doc.add_heading("Education", level=1)
            for edu in profile.education:
                heading = "{degree} in {field}".format(degree=edu.degree or "", field=edu.field or "")
                if edu.institution:
                    heading += " — {inst}".format(inst=edu.institution)
                doc.add_heading(heading, level=2)
                details = []
                date_range = " — ".join(filter(None, [edu.start_date, edu.end_date]))
                if date_range:
                    details.append(date_range)
                if edu.location:
                    details.append(edu.location)
                if edu.gpa:
                    details.append("GPA: {gpa}".format(gpa=edu.gpa))
                if details:
                    doc.add_paragraph(" | ".join(details))
                if edu.coursework:
                    doc.add_paragraph("Coursework: {cw}".format(cw=", ".join(edu.coursework)))
                if edu.achievements:
                    for ach in edu.achievements:
                        doc.add_paragraph(ach, style="List Bullet")

        if profile.skills and any([profile.skills.technical, profile.skills.tools, profile.skills.languages, profile.skills.databases, profile.skills.analytics, profile.skills.soft_skills]):
            doc.add_heading("Skills", level=1)
            for category, label in [
                ("technical", "Technical"), ("tools", "Tools"), ("languages", "Languages"),
                ("databases", "Databases"), ("analytics", "Analytics"), ("soft_skills", "Soft Skills"),
            ]:
                values = getattr(profile.skills, category, [])
                if values:
                    doc.add_paragraph("{label}: {values}".format(label=label, values=", ".join(values)))

        if profile.certifications:
            doc.add_heading("Certifications", level=1)
            for cert in profile.certifications:
                details = " | ".join(filter(None, [cert.name, cert.issuer, cert.date]))
                doc.add_paragraph(details)

        if profile.achievements:
            doc.add_heading("Achievements", level=1)
            for item in profile.achievements:
                doc.add_paragraph(item, style="List Bullet")

        if profile.leadership:
            doc.add_heading("Leadership", level=1)
            for lead in profile.leadership:
                header = "{role} — {org}".format(role=lead.role or "", org=lead.organization or "")
                doc.add_heading(header, level=2)
                date_range = " — ".join(filter(None, [lead.start_date, lead.end_date]))
                if date_range:
                    doc.add_paragraph(date_range)
                if lead.description:
                    doc.add_paragraph(lead.description)

        if profile.languages:
            doc.add_heading("Languages", level=1)
            items = []
            for lang in profile.languages:
                label = lang.language or ""
                if lang.proficiency:
                    label += " ({prof})".format(prof=lang.proficiency)
                items.append(label)
            doc.add_paragraph(", ".join(items))

        if profile.links:
            doc.add_heading("Links", level=1)
            for link in profile.links:
                label = link.label or link.url or ""
                doc.add_paragraph("{label}: {url}".format(label=label, url=link.url or ""))

        if profile.additional:
            doc.add_heading("Additional Information", level=1)
            for add in profile.additional:
                if add.title:
                    doc.add_paragraph("{title}: {desc}".format(title=add.title, desc=add.description or ""))
                elif add.description:
                    doc.add_paragraph(add.description)

        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()


export_service = ExportService()
