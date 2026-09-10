"""Typst PDF compilation engine for CareerOS.

Replaces the legacy LibreOffice DOCX-to-PDF subprocess conversion with instant
Typst rendering: structured resume markup is compiled by the standalone
``typst`` CLI (temporary ``.typ`` file in, ``.pdf`` bytes out), producing
selectable-text, ATS-friendly PDFs with no JRE and no office suite.

Pipeline position: :class:`PdfCompiler` (``app.services.resumes.pdf_compiler``)
and :class:`ExportService` (``app.services.export_service``) render a
``ResumeDocumentModel`` to Typst markup via :func:`render_document_model_to_typst`
and compile it here. When the binary is unavailable or compilation fails,
callers fall back to the PyMuPDF layout engine — Typst never hard-breaks
the export path.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

# Per-compile budget. Typst renders a resume in milliseconds; the bound only
# guards against a hung subprocess, mapping it to a typed, retryable error
# instead of a stalled request.
TYPST_COMPILE_TIMEOUT_SECONDS = 25.0

# Strict single-page budget for the canonical one-page resume. Callers may
# opt out for legitimately longer documents.
TYPST_MAX_PAGES = 1

# Stderr tail kept in error logs (never the markup itself — it holds PII).
_STDERR_LOG_LIMIT = 2000

if TYPE_CHECKING:  # pragma: no cover
    from app.services.resumes.document_model import ResumeDocumentModel


class TypstNotAvailableError(RuntimeError):
    """The ``typst`` CLI binary is not on PATH."""


class TypstCompileError(RuntimeError):
    """Typst compilation failed (bad markup, timeout, or empty output)."""


class TypstPageBudgetExceeded(RuntimeError):
    """Compiled PDF exceeded the single-page budget."""


def is_typst_available() -> bool:
    """Return True when the ``typst`` CLI binary resolves on PATH."""
    return shutil.which("typst") is not None


async def acompile_typst_to_pdf(
    typst_markup: str,
    *,
    timeout_seconds: float = TYPST_COMPILE_TIMEOUT_SECONDS,
    enforce_single_page: bool = True,
) -> bytes:
    """Compile Typst markup to PDF bytes.

    Markup is written to a temporary ``.typ`` file and compiled to a sibling
    ``.pdf`` (format inferred from the extension — supported by every Typst
    release, unlike stdout output which needs 0.12+). The temp directory is
    always cleaned up. Raises :class:`TypstNotAvailableError` when the binary
    is missing, :class:`TypstCompileError` on bad markup / timeout / empty
    output, and :class:`TypstPageBudgetExceeded` when the result exceeds the
    single-page budget.
    """
    if not (typst_markup or "").strip():
        raise TypstCompileError("Typst markup must not be empty")
    if not is_typst_available():
        raise TypstNotAvailableError(
            "The 'typst' CLI binary was not found on PATH. "
            "Install it (see Dockerfile) to enable Typst PDF compilation."
        )

    with tempfile.TemporaryDirectory(prefix="typst-") as tmpdir:
        in_path = os.path.join(tmpdir, "resume.typ")
        out_path = os.path.join(tmpdir, "resume.pdf")
        with open(in_path, "w", encoding="utf-8") as f:
            f.write(typst_markup)

        try:
            proc = await asyncio.create_subprocess_exec(
                "typst",
                "compile",
                in_path,
                out_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise TypstNotAvailableError("The 'typst' CLI binary was not found on PATH.") from exc
        except OSError as exc:
            raise TypstCompileError(f"Could not launch the Typst subprocess: {exc}") from exc

        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            try:
                proc.kill()
                await proc.wait()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
            raise TypstCompileError(
                f"Typst compilation timed out after {timeout_seconds}s"
            ) from exc

        if proc.returncode != 0:
            detail = (stderr or b"").decode("utf-8", errors="replace").strip()
            logger.warning(
                "Typst compilation failed (exit=%s, markup=%d chars): %s",
                proc.returncode,
                len(typst_markup),
                detail[:_STDERR_LOG_LIMIT],
            )
            raise TypstCompileError(f"Typst compilation failed: {detail[:500]}")

        if stderr:
            # Warnings (e.g. unknown font fallback) never fail the build, but are
            # worth a breadcrumb for operators.
            logger.debug(
                "Typst warnings (markup=%d chars): %s",
                len(typst_markup),
                stderr.decode("utf-8", errors="replace").strip()[:_STDERR_LOG_LIMIT],
            )

        try:
            with open(out_path, "rb") as f:
                pdf_bytes = f.read()
        except OSError as exc:
            raise TypstCompileError(f"Typst produced no PDF output: {exc}") from exc

    if not pdf_bytes.startswith(b"%PDF-"):
        raise TypstCompileError("Typst produced no PDF output")

    if enforce_single_page:
        _enforce_page_budget(pdf_bytes)

    logger.info("Compiled PDF via Typst (%d bytes)", len(pdf_bytes))
    return pdf_bytes


def _enforce_page_budget(pdf_bytes: bytes) -> None:
    """Raise :class:`TypstPageBudgetExceeded` when the PDF has >1 pages."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.debug("PyMuPDF unavailable; skipping Typst page-budget check")
        return
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            page_count = doc.page_count
    except Exception as exc:  # noqa: BLE001 — unreadable output is a compile failure
        raise TypstCompileError(f"Typst output is not a readable PDF: {exc}") from exc
    if page_count > TYPST_MAX_PAGES:
        raise TypstPageBudgetExceeded(
            f"Typst output has {page_count} pages (budget: {TYPST_MAX_PAGES}). "
            "Trim content or disable the single-page budget."
        )


def compile_typst_to_pdf(
    typst_markup: str,
    *,
    timeout_seconds: float = TYPST_COMPILE_TIMEOUT_SECONDS,
    enforce_single_page: bool = True,
) -> bytes:
    """Synchronous wrapper around :func:`acompile_typst_to_pdf`.

    Uses :func:`run_coro_sync` (not ``asyncio.run``): callers are synchronous
    services invoked from ``async`` FastAPI handlers, where ``asyncio.run()``
    raises ``RuntimeError``.
    """
    from app.llm.sync_bridge import run_coro_sync

    return run_coro_sync(
        acompile_typst_to_pdf(
            typst_markup,
            timeout_seconds=timeout_seconds,
            enforce_single_page=enforce_single_page,
        ),
        timeout_seconds=timeout_seconds,
    )


# ---------------------------------------------------------------------------
# ResumeDocumentModel -> Typst markup renderer
# ---------------------------------------------------------------------------


def _lit(value: Any) -> str:
    """Emit *value* as a Typst string literal.

    All user content flows through string variables (``#t("...")``) rather
    than raw markup, so leading ``=``/``-``/``@`` characters, ``#`` tags, or
    ``*`` emphasis in resume text can never be parsed as Typst syntax.
    """
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = "".join(ch for ch in text if ch == "\n" or ord(ch) >= 32)
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + text + '"'


def _paras(text: str) -> list[str]:
    """Split text into `#t("...")` paragraph literals (blank-line separated)."""
    return [_lit(p) for p in (text or "").split("\n") if p.strip()]


def render_document_model_to_typst(doc_model: ResumeDocumentModel) -> str:
    """Render a canonical ``ResumeDocumentModel`` to Typst markup.

    Mirrors the canonical ``modern.typ`` template styling: tight A4 margins,
    single-column selectable text, standard section headings — ATS-friendly
    by construction. Never invents content; empty sections are omitted.
    """
    hdr = doc_model.header
    style = getattr(doc_model, "style", None)
    if style is None:
        from app.services.resumes.style_model import DocumentStyleModel
        style = DocumentStyleModel()

    body_pt = getattr(style, "body_size_pt", 9.5)
    sec_heading_pt = getattr(style, "section_heading_size_pt", 10.5)
    subheading_pt = getattr(style, "subheading_size_pt", 10.0)
    name_pt = getattr(style, "name_size_pt", 20.0)
    headline_pt = getattr(style, "headline_size_pt", 11.0)
    meta_pt = getattr(style, "meta_size_pt", 8.5)
    body_color = getattr(style, "body_color_hex", "1e293b")
    heading_color = getattr(style, "heading_color_hex", "0f172a")
    meta_color = getattr(style, "meta_color_hex", "64748b")
    accent_color = getattr(style, "accent_color_hex", "2563eb")
    divider_color = getattr(style, "divider_color_hex", "cbd5e1")
    divider_thick = getattr(style, "divider_thickness_pt", 1.0)
    sec_before = getattr(style, "section_before_pt", 6.0)
    sec_after = getattr(style, "section_after_pt", 3.0)
    bullet_spacing = getattr(style, "bullet_spacing_pt", 2.0)
    header_spacing = getattr(style, "header_spacing_pt", 2.0)
    par_spacing = getattr(style, "paragraph_after_pt", 4.0)
    line_sp = getattr(style, "line_spacing", 1.15)
    leading_em = round(0.45 * (line_sp / 1.15), 2)

    m_left = getattr(style, "margin_left_pt", 40.0)
    m_right = getattr(style, "margin_right_pt", 40.0)
    m_top = getattr(style, "margin_top_pt", 36.0)
    m_bottom = getattr(style, "margin_bottom_pt", 36.0)
    if (
        abs(m_left - 40.0) < 0.1
        and abs(m_right - 40.0) < 0.1
        and abs(m_top - 36.0) < 0.1
        and abs(m_bottom - 36.0) < 0.1
    ):
        margin_str = "margin: (x: 1.2cm, y: 1.2cm)"
    else:
        margin_str = f"margin: (left: {m_left:.1f}pt, right: {m_right:.1f}pt, top: {m_top:.1f}pt, bottom: {m_bottom:.1f}pt)"

    # Keep exactly 9.5pt when body_pt is default 9.5 or 10.0 to match template baseline
    body_size_str = "9.5pt" if abs(body_pt - 9.5) < 0.05 else f"{body_pt:.1f}pt"

    out: list[str] = [
        "// Generated by app/services/pdf/typst_compiler.py — mirrors app/templates/typst/modern.typ",
        f'#set page(paper: "a4", {margin_str})',
        f'#set text(font: ("DejaVu Sans",), size: {body_size_str}, fill: rgb("#{body_color}"))',
        f"#set block(spacing: {par_spacing:.1f}pt)",
        f"#set par(leading: {leading_em:.2f}em)",
        "#let t(it) = [#it]",
        "#let rsec(title) = {",
        f"  v({sec_before:.1f}pt)",
        f'  text(size: {sec_heading_pt:.1f}pt, weight: "bold", fill: rgb("#{heading_color}"), tracking: 0.06em, upper(title))',
        "  v(2pt)",
        f'  line(length: 100%, stroke: {divider_thick:.1f}pt + rgb("#{divider_color}"))',
        f"  v({sec_after:.1f}pt)",
        "}",
        "",
    ]

    # Header
    out.append("#align(center)[")
    if hdr.full_name:
        out.append(f'  #text(size: {name_pt:.1f}pt, weight: "bold", fill: rgb("#{heading_color}"))[#t({_lit(hdr.full_name)})]')
    if hdr.headline:
        out.append(f'  #v({header_spacing:.1f}pt)\n  #text(size: {headline_pt:.1f}pt, weight: "bold", fill: rgb("#{accent_color}"))[#t({_lit(hdr.headline)})]')
    contact = hdr.contact_line()
    if contact:
        out.append(f'  #v({header_spacing:.1f}pt)\n  #text(size: {meta_pt:.1f}pt, fill: rgb("#{meta_color}"))[#t({_lit(contact)})]')
    out.append("]")
    out.append("")

    def _experience_block(positions: Any, heading: str) -> None:
        if not positions:
            return
        out.append(f"#rsec({_lit(heading)})")
        for exp in positions:
            title = " | ".join(p for p in (exp.role, exp.company) if p)
            date_loc = " | ".join(p for p in (exp.date_range, exp.location) if p)
            out.append("#grid(columns: (1fr, auto), gutter: 8pt,")
            out.append(f'  [#text(size: {subheading_pt:.1f}pt, weight: "bold", fill: rgb("#{heading_color}"))[#t({_lit(title)})]],')
            out.append(f'  [#text(size: {meta_pt:.1f}pt, fill: rgb("#{meta_color}"))[#t({_lit(date_loc)})]],')
            out.append(")")
            bullets = [b.text for b in (exp.bullets or []) if (b.text or "").strip()]
            if bullets:
                out.append(f"#list(marker: [•], spacing: {bullet_spacing:.1f}pt, indent: 12pt, body-indent: 6pt,")
                out.extend(f"  [#t({p})]," for p in _paras("\n".join(bullets)))
                out.append(")")
            sub_heading = getattr(exp, "sub_engagements_heading", "Key Sub-Engagements")
            for sub in getattr(exp, "sub_engagements", None) or []:
                if sub_heading:
                    out.append(f'  #text(size: {subheading_pt - 1.0:.1f}pt, weight: "bold", fill: rgb("#{heading_color}"))[#t({_lit(sub_heading)})]')
                    sub_heading = None
                if sub.name:
                    out.append(f'  #pad(left: 12pt)[#text(size: {subheading_pt:.1f}pt, weight: "bold")[#t({_lit(sub.name)})]]')
                if sub.description:
                    out.append(f'  #pad(left: 16pt)[#text(size: {meta_pt:.1f}pt, fill: rgb("#{meta_color}"))[#t({_lit(sub.description)})]]')
                sub_bullets = [b.text for b in (sub.bullets or []) if (b.text or "").strip()]
                if sub_bullets:
                    out.append("  #pad(left: 12pt)[")
                    out.append(f"  #list(marker: [•], spacing: {bullet_spacing:.1f}pt, indent: 12pt, body-indent: 6pt,")
                    out.extend(f"    [#t({p})]," for p in _paras("\n".join(sub_bullets)))
                    out.append("  )]")
            out.append(f"#v({sec_after:.1f}pt)")

    for sec in doc_model.section_order:
        if sec == "summary" and doc_model.summary and (doc_model.summary.text or "").strip():
            out.append(f"#rsec({_lit('PROFESSIONAL SUMMARY')})")
            out.extend(f"#t({p})" for p in _paras(doc_model.summary.text))
        elif sec == "skills" and doc_model.skills:
            rows = [(g.category, g.skills) for g in doc_model.skills if g.skills]
            if rows:
                out.append(f"#rsec({_lit('SKILLS')})")
                for cat, skills in rows:
                    out.append(f'  #text(size: {body_pt:.1f}pt)[#strong[#t({_lit(cat + ":")})] #t({_lit(", ".join(skills))})]')
        elif sec == "experience" and doc_model.experience:
            _experience_block(doc_model.experience, "EXPERIENCE")
        elif sec == "internships" and doc_model.internships:
            _experience_block(doc_model.internships, "INTERNSHIPS")
        elif sec == "projects" and doc_model.projects:
            out.append(f"#rsec({_lit((getattr(doc_model, 'projects_heading', 'Projects') or 'Projects').upper())})")
            for prj in doc_model.projects:
                tech = f" ({', '.join(prj.technologies)})" if prj.technologies else ""
                out.append(f'  #text(size: {subheading_pt:.1f}pt, weight: "bold", fill: rgb("#{heading_color}"))[#t({_lit((prj.name or "Project") + tech)})]')
                if prj.url:
                    out.append(f'  #text(size: {meta_pt:.1f}pt, fill: rgb("#{meta_color}"))[#t({_lit(prj.url)})]')
                bits: list[str] = []
                if prj.description:
                    bits.append(prj.description)
                bits.extend(b.text for b in (prj.bullets or []) if (b.text or "").strip() and b.text.strip() != (prj.description or "").strip())
                if bits:
                    out.append(f"#list(marker: [•], spacing: {bullet_spacing:.1f}pt, indent: 12pt, body-indent: 6pt,")
                    out.extend(f"  [#t({p})]," for p in _paras("\n".join(bits)))
                    out.append(")")
                out.append(f"#v({sec_after:.1f}pt)")
        elif sec == "education" and doc_model.education:
            out.append(f"#rsec({_lit('EDUCATION')})")
            for edu in doc_model.education:
                deg = " in ".join(p for p in (edu.degree, edu.field_of_study) if p) or "Degree"
                left = deg + (f" — {edu.institution}" if edu.institution else "")
                out.append("#grid(columns: (1fr, auto), gutter: 8pt,")
                out.append(f'  [#text(size: {subheading_pt:.1f}pt, weight: "bold", fill: rgb("#{heading_color}"))[#t({_lit(left)})]],')
                out.append(f'  [#text(size: {meta_pt:.1f}pt, fill: rgb("#{meta_color}"))[#t({_lit(edu.date_range)})]],')
                out.append(")")
                meta = " | ".join(p for p in (edu.location, f"GPA: {edu.gpa}" if edu.gpa else "") if p)
                if meta:
                    out.append(f'  #text(size: {meta_pt:.1f}pt, fill: rgb("#{meta_color}"))[#t({_lit(meta)})]')
                if edu.coursework:
                    out.append(f'  #text(size: {meta_pt:.1f}pt, fill: rgb("#{meta_color}"))[#t({_lit("Coursework: " + ", ".join(edu.coursework))})]')
                out.append(f"#v({sec_after:.1f}pt)")
        elif sec == "certifications" and doc_model.certifications:
            items = [c.text for c in doc_model.certifications if (c.text or "").strip()]
            if items:
                out.append(f"#rsec({_lit('CERTIFICATIONS')})")
                out.append(f"#list(marker: [•], spacing: {bullet_spacing:.1f}pt, indent: 12pt, body-indent: 6pt,")
                out.extend(f"  [#t({p})]," for p in _paras("\n".join(items)))
                out.append(")")
        elif sec == "additional" and getattr(doc_model, "additional", None):
            items = [a.text for a in doc_model.additional if (a.text or "").strip()]
            if items:
                out.append(f"#rsec({_lit((getattr(doc_model, 'additional_heading', 'Additional Knowledge') or 'Additional Knowledge').upper())})")
                out.append(f"#list(marker: [•], spacing: {bullet_spacing:.1f}pt, indent: 12pt, body-indent: 6pt,")
                out.extend(f"  [#t({p})]," for p in _paras("\n".join(items)))
                out.append(")")

    return "\n".join(out) + "\n"
