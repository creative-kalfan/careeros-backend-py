"""PDF parser using PyMuPDF with layout-aware extraction."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

import fitz  # PyMuPDF

from .layout import (
    DocumentBlock,
    PageLayout,
    detect_page_layout,
    extract_blocks_from_pdf_page,
    extract_spans_from_pdf,
    group_lines_into_blocks,
    group_spans_into_lines,
    reconstruct_reading_order,
)
from .models import DocumentLine, DocumentSpan, ParsedResume, ParseResult

logger = logging.getLogger(__name__)


class PDFParser:
    """PDF parser with layout-aware text extraction."""

    def __init__(self, debug: bool = False):
        self.debug = debug
        self.parse_notes: List[str] = []

    def parse(self, file_path: str) -> ParseResult:
        """Parse a PDF file and return structured resume data."""
        self.parse_notes = []
        
        doc = None
        try:
            doc = fitz.open(file_path)
            logger.info("PDF opened: %s pages", len(doc))

            all_blocks: List[DocumentBlock] = []
            page_layouts: List[PageLayout] = []
            raw_text_parts: List[str] = []

            for page in doc:
                # Extract spans and structured blocks with layout awareness
                spans, blocks = extract_blocks_from_pdf_page(page)

                if self.debug:
                    self.parse_notes.append(f"Page {page.number + 1}: extracted {len(spans)} spans")
                    self.parse_notes.append(f"Page {page.number + 1}: {len(blocks)} blocks")

                # Detect page layout
                layout = detect_page_layout(
                    blocks,
                    page_num=page.number,
                    page_width=page.rect.width,
                    page_height=page.rect.height,
                )
                page_layouts.append(layout)
                self.parse_notes.extend(layout.parse_notes)

                # Reconstruct reading order
                ordered_blocks = reconstruct_reading_order(layout)
                all_blocks.extend(ordered_blocks)

                # Also get simple text for fallback
                raw_text_parts.append(page.get_text())

            raw_text = "\n".join(raw_text_parts)

            if not all_blocks:
                return ParseResult(
                    status="failed",
                    error="No text content extracted from PDF",
                    raw_text=raw_text,
                    debug_info={"parse_notes": self.parse_notes} if self.debug else None,
                )

            # Detect sections
            from .geometry import extract_document_geometry
            from .section_detector import detect_sections

            sections, section_notes = detect_sections(all_blocks, page_layouts)
            self.parse_notes.extend(section_notes)

            # Extract document geometry
            geometry_map = extract_document_geometry(
                doc=doc,
                all_blocks=all_blocks,
                page_layouts=page_layouts,
                detected_sections=sections,
            )
            geometry_dict = geometry_map.to_dict()
            from .style_extractor import extract_document_style
            geometry_dict["document_style"] = extract_document_style(doc)

            # Parse structured content
            parsed = self._parse_structured(
                blocks=all_blocks,
                page_layouts=page_layouts,
                raw_text=raw_text,
                sections=sections,
            )

            debug_info = {"parse_notes": self.parse_notes} if self.debug else {}
            debug_info["geometry"] = geometry_dict

            return ParseResult(
                status="completed",
                parsed=parsed,
                raw_text=raw_text,
                debug_info=debug_info,
                geometry=geometry_dict,
            )

        except Exception as e:
            logger.exception("PDF parsing failed")
            return ParseResult(
                status="failed",
                error=f"PDF parsing failed: {str(e)}",
                raw_text="",
                debug_info={"parse_notes": self.parse_notes} if self.debug else None,
            )
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass

    def _parse_structured(
        self,
        blocks: List[DocumentBlock],
        page_layouts: List[PageLayout],
        raw_text: str,
        sections: Optional[List[Any]] = None,
    ) -> ParsedResume:
        """Parse structured content from blocks."""
        from .section_detector import detect_sections, get_section_blocks
        from .contact_parser import extract_contact_from_blocks
        from .experience_parser import parse_experience_section
        from .education_parser import parse_education_section
        from .skills_parser import parse_skills_section
        from .project_parser import parse_projects_section
        from .other_parsers import (
            parse_certifications,
            parse_achievements,
            parse_languages,
            parse_links,
            parse_summary,
        )

        # Detect sections if not already provided
        if sections is None:
            sections, section_notes = detect_sections(blocks, page_layouts)
            self.parse_notes.extend(section_notes)

        # Extract contact from header area (first page, top blocks)
        contact = extract_contact_from_blocks(blocks)

        # Parse each section
        experience_result = parse_experience_section(get_section_blocks(sections, "experience"))
        education_result = parse_education_section(get_section_blocks(sections, "education"))
        skills = parse_skills_section(get_section_blocks(sections, "skills"))
        projects_result = parse_projects_section(get_section_blocks(sections, "projects"))
        certifications = parse_certifications(get_section_blocks(sections, "certifications"))
        achievements = parse_achievements(get_section_blocks(sections, "achievements"))
        languages = parse_languages(get_section_blocks(sections, "languages"))
        links = parse_links(get_section_blocks(sections, "links"))
        summary = parse_summary(get_section_blocks(sections, "summary"))

        self.parse_notes.extend(experience_result.parse_notes)
        self.parse_notes.extend(education_result.parse_notes)
        self.parse_notes.extend(projects_result.parse_notes)

        return ParsedResume(
            contact=contact,
            summary=summary if summary else None,
            experience=experience_result.experience,
            education=education_result.education,
            skills=skills,
            projects=projects_result.projects,
            certifications=certifications,
            achievements=achievements,
            languages=languages,
            links=links,
            parse_notes=self.parse_notes,
        )
