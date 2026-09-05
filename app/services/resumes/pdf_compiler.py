"""PDF Compilation and DOCX-to-PDF Conversion Engine for CareerOS.

Coordinates converting native DOCX to PDF (via headless LibreOffice when available,
or high-fidelity PyMuPDF layout rendering fallback) and runs visual verification.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from typing import Optional, Tuple

import fitz  # PyMuPDF

from .document_model import ResumeDocumentModel
from .docx_compiler import docx_compiler
from .style_model import DocumentStyleModel
from .visual_verification import VisualVerificationEngine, VisualVerificationResult

logger = logging.getLogger(__name__)


def _find_libreoffice_binary() -> Optional[str]:
    """Locate headless LibreOffice executable across Linux and Windows systems."""
    for cmd in ("soffice", "libreoffice"):
        path = shutil.which(cmd)
        if path:
            return path

    # Common standard paths
    standard_paths = [
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/usr/local/bin/soffice",
        "/opt/libreoffice/program/soffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for p in standard_paths:
        if os.path.isfile(p):
            return p
    return None


def _render_document_model_to_html(doc_model: ResumeDocumentModel) -> str:
    """Render canonical ResumeDocumentModel into clean HTML for PyMuPDF Story pagination."""
    style = doc_model.style or DocumentStyleModel()
    hdr = doc_model.header

    sections_html = []

    # Header
    name_html = f'<h1 class="header-name">{hdr.full_name}</h1>' if hdr.full_name else ""
    headline_html = f'<div class="header-headline">{hdr.headline}</div>' if hdr.headline else ""
    contact_html = f'<div class="header-contact">{hdr.contact_line()}</div>' if hdr.contact_line() else ""
    sections_html.append(f'<div class="header-block">{name_html}{headline_html}{contact_html}</div>')

    for sec in doc_model.section_order:
        if sec == "summary" and doc_model.summary and doc_model.summary.text.strip():
            sections_html.append(
                f'<div class="section">'
                f'<div class="section-title">PROFESSIONAL SUMMARY</div>'
                f'<p class="summary-p">{doc_model.summary.text.strip()}</p>'
                f'</div>'
            )

        elif sec == "experience" and doc_model.experience:
            items = []
            for exp in doc_model.experience:
                date_loc = " | ".join(filter(None, [exp.date_range, exp.location]))
                bullets = "".join(f'<li>{b.text.strip()}</li>' for b in exp.bullets if b.text.strip())
                items.append(
                    f'<div class="entry">'
                    f'<table class="entry-header-table"><tr>'
                    f'<td class="entry-left"><strong>{exp.role}</strong>' + (f' | {exp.company}' if exp.company else '') + f'</td>'
                    f'<td class="entry-right">{date_loc}</td>'
                    f'</tr></table>'
                    + (f'<ul class="bullet-list">{bullets}</ul>' if bullets else '') +
                    f'</div>'
                )
            sections_html.append(f'<div class="section"><div class="section-title">EXPERIENCE</div>{"".join(items)}</div>')

        elif sec == "internships" and doc_model.internships:
            items = []
            for exp in doc_model.internships:
                date_loc = " | ".join(filter(None, [exp.date_range, exp.location]))
                bullets = "".join(f'<li>{b.text.strip()}</li>' for b in exp.bullets if b.text.strip())
                items.append(
                    f'<div class="entry">'
                    f'<table class="entry-header-table"><tr>'
                    f'<td class="entry-left"><strong>{exp.role}</strong>' + (f' | {exp.company}' if exp.company else '') + f'</td>'
                    f'<td class="entry-right">{date_loc}</td>'
                    f'</tr></table>'
                    + (f'<ul class="bullet-list">{bullets}</ul>' if bullets else '') +
                    f'</div>'
                )
            sections_html.append(f'<div class="section"><div class="section-title">INTERNSHIPS</div>{"".join(items)}</div>')

        elif sec == "projects" and doc_model.projects:
            items = []
            for prj in doc_model.projects:
                tech_str = f' <em>({", ".join(prj.technologies)})</em>' if prj.technologies else ""
                bullets_content = []
                if prj.description:
                    bullets_content.append(f'<li>{prj.description}</li>')
                for b in prj.bullets:
                    if b.text.strip() != prj.description.strip():
                        bullets_content.append(f'<li>{b.text.strip()}</li>')
                b_html = f'<ul class="bullet-list">{"".join(bullets_content)}</ul>' if bullets_content else ""
                items.append(
                    f'<div class="entry">'
                    f'<div class="entry-title-line"><strong>{prj.name}</strong>{tech_str}</div>'
                    f'{b_html}'
                    f'</div>'
                )
            sections_html.append(f'<div class="section"><div class="section-title">PROJECTS</div>{"".join(items)}</div>')

        elif sec == "education" and doc_model.education:
            items = []
            for edu in doc_model.education:
                f_study = getattr(edu, "field_of_study", getattr(edu, "field", ""))
                deg = " in ".join(filter(None, [edu.degree, f_study])) or "Degree"
                inst = f" — {edu.institution}" if edu.institution else ""
                cw_html = f'<p class="edu-cw">Coursework: {", ".join(edu.coursework)}</p>' if edu.coursework else ""
                items.append(
                    f'<div class="entry">'
                    f'<table class="entry-header-table"><tr>'
                    f'<td class="entry-left"><strong>{deg}</strong>{inst}</td>'
                    f'<td class="entry-right">{edu.date_range}</td>'
                    f'</tr></table>'
                    f'{cw_html}'
                    f'</div>'
                )
            sections_html.append(f'<div class="section"><div class="section-title">EDUCATION</div>{"".join(items)}</div>')

        elif sec == "skills" and doc_model.skills:
            rows = []
            for grp in doc_model.skills:
                if grp.skills:
                    rows.append(f'<div class="skill-row"><strong>{grp.category}:</strong> {", ".join(grp.skills)}</div>')
            sections_html.append(f'<div class="section"><div class="section-title">SKILLS</div>{"".join(rows)}</div>')

        elif sec == "certifications" and doc_model.certifications:
            lis = "".join(f'<li>{c.text}</li>' for c in doc_model.certifications)
            sections_html.append(f'<div class="section"><div class="section-title">CERTIFICATIONS</div><ul class="bullet-list">{lis}</ul></div>')

    css = f"""
body {{
    font-family: "{style.body_font}", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    font-size: {style.body_size_pt}pt;
    line-height: {style.line_spacing};
    color: #{style.body_color_hex};
    margin: 0;
    padding: 0;
}}
.header-block {{
    text-align: center;
    margin-bottom: {style.section_after_pt}pt;
}}
.header-name {{
    font-family: "{style.heading_font}", sans-serif;
    font-size: {style.name_size_pt}pt;
    font-weight: bold;
    color: #{style.heading_color_hex};
    margin: 0 0 2pt 0;
}}
.header-headline {{
    font-size: {style.headline_size_pt}pt;
    font-weight: bold;
    color: #{style.accent_color_hex};
    margin: 0 0 2pt 0;
}}
.header-contact {{
    font-size: {style.meta_size_pt}pt;
    color: #{style.meta_color_hex};
    margin: 0;
}}
.section {{
    margin-top: {style.section_before_pt}pt;
    margin-bottom: {style.section_after_pt}pt;
}}
.section-title {{
    font-family: "{style.heading_font}", sans-serif;
    font-size: {style.section_heading_size_pt}pt;
    font-weight: bold;
    color: #{style.heading_color_hex};
    border-bottom: {style.divider_thickness_pt}pt solid #{style.divider_color_hex};
    padding-bottom: 1.5pt;
    margin-bottom: {style.paragraph_after_pt}pt;
    letter-spacing: 0.05em;
}}
.summary-p {{
    margin: 0 0 {style.paragraph_after_pt}pt 0;
    font-size: {style.body_size_pt}pt;
}}
.entry {{
    margin-bottom: 4pt;
}}
.entry-header-table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 1.5pt;
}}
.entry-left {{
    text-align: left;
    font-size: {style.subheading_size_pt}pt;
    color: #{style.heading_color_hex};
    padding: 0;
}}
.entry-right {{
    text-align: right;
    font-size: {style.meta_size_pt}pt;
    color: #{style.meta_color_hex};
    padding: 0;
}}
.entry-title-line {{
    font-size: {style.subheading_size_pt}pt;
    color: #{style.heading_color_hex};
    margin-bottom: 1.5pt;
}}
.bullet-list {{
    margin: 1.5pt 0 3pt 0;
    padding-left: {style.bullet_indent_pt}pt;
}}
.bullet-list li {{
    font-size: {style.body_size_pt}pt;
    color: #{style.body_color_hex};
    margin-bottom: 1.5pt;
}}
.skill-row {{
    font-size: {style.body_size_pt}pt;
    margin-bottom: 2pt;
}}
.edu-cw {{
    font-size: {style.meta_size_pt}pt;
    color: #{style.meta_color_hex};
    margin: 1.5pt 0 0 0;
}}
"""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>{css}</style></head>
<body>{"".join(sections_html)}</body>
</html>"""


class PdfCompiler:
    """Compiles Document Model and native DOCX into visually verified PDF bytes."""

    def compile(
        self,
        doc_model: ResumeDocumentModel,
        docx_bytes: Optional[bytes] = None,
    ) -> tuple[bytes, VisualVerificationResult]:
        """Convert DOCX/DocumentModel to PDF and visually verify output."""
        style = doc_model.style or DocumentStyleModel()
        if not docx_bytes:
            docx_bytes = docx_compiler.compile(doc_model)

        pdf_bytes = None
        soffice_bin = _find_libreoffice_binary()

        # Strategy 1: Headless LibreOffice CLI if available (bounded 15s timeout with resource fallback)
        if soffice_bin:
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    in_path = os.path.join(tmpdir, "resume.docx")
                    with open(in_path, "wb") as f:
                        f.write(docx_bytes)
                    proc = subprocess.run(
                        [
                            soffice_bin,
                            "--headless",
                            "--convert-to",
                            "pdf",
                            "--outdir",
                            tmpdir,
                            in_path,
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=15,
                    )
                    out_path = os.path.join(tmpdir, "resume.pdf")
                    if os.path.isfile(out_path):
                        with open(out_path, "rb") as f:
                            pdf_bytes = f.read()
                        logger.info("Compiled PDF via LibreOffice successfully (%d bytes)", len(pdf_bytes))
                    else:
                        logger.warning("LibreOffice exited without producing output file; falling back to PyMuPDF layout")
            except subprocess.TimeoutExpired:
                logger.warning("LibreOffice conversion timed out after 15s; falling back to PyMuPDF layout engine")
            except Exception as exc:
                logger.warning("LibreOffice conversion failed (%s); falling back to PyMuPDF layout engine", exc)

        # Strategy 2: High-fidelity layout engine using PyMuPDF Story
        if not pdf_bytes:
            html = _render_document_model_to_html(doc_model)
            buf = io.BytesIO()
            writer = fitz.DocumentWriter(buf)
            story = fitz.Story(html)
            page_rect = fitz.Rect(0, 0, style.page_width_pt, style.page_height_pt)
            content_rect = fitz.Rect(
                style.margin_left_pt,
                style.margin_top_pt,
                style.page_width_pt - style.margin_right_pt,
                style.page_height_pt - style.margin_bottom_pt,
            )
            more = True
            while more:
                dev = writer.begin_page(page_rect)
                more, _ = story.place(content_rect)
                story.draw(dev)
                writer.end_page()
            writer.close()
            pdf_bytes = buf.getvalue()
            logger.info("Compiled PDF via PyMuPDF layout engine (%d bytes)", len(pdf_bytes))

        # 3. Visual Verification
        ver_result = VisualVerificationEngine.verify(pdf_bytes)
        if not ver_result.is_valid:
            logger.warning("Visual verification detected issues: %s; running auto-adjust", ver_result.issues)
            pdf_bytes, adjusted = VisualVerificationEngine.auto_adjust_if_needed(pdf_bytes)
            ver_result = VisualVerificationEngine.verify(pdf_bytes)

        return pdf_bytes, ver_result


pdf_compiler = PdfCompiler()
