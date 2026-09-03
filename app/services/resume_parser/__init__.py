"""Main parser orchestrator."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .models import ParseResult, ParsedResume
from .pdf_parser import PDFParser
from .docx_parser import DOCXParser
from .validator import validate_parsed_resume, sanitize_parsed_resume
from .adapters import parsed_resume_to_resume_content
from app.models.resume import ResumeContent

logger = logging.getLogger(__name__)


class ResumeParser:
    """Main entry point for resume parsing."""

    def __init__(self, debug: bool = False):
        self.debug = debug
        self.pdf_parser = PDFParser(debug=debug)
        self.docx_parser = DOCXParser(debug=debug)

    def parse_file(self, file_path: str, filename: str) -> ParseResult:
        """
        Parse a resume file (PDF or DOCX).
        
        Args:
            file_path: Path to the file
            filename: Original filename (used for extension detection)
            
        Returns:
            ParseResult with status, parsed content, or error
        """
        ext = Path(filename).suffix.lower()
        
        logger.info("PARSER START file=%s ext=%s", filename, ext)
        
        if ext == ".pdf":
            result = self.pdf_parser.parse(file_path)
        elif ext in (".docx", ".doc"):
            result = self.docx_parser.parse(file_path)
        else:
            return ParseResult(
                status="failed",
                error=f"Unsupported file type: {ext}",
            )

        # Validate if parsing succeeded
        if result.status == "completed" and result.parsed:
            # Sanitize
            sanitized = sanitize_parsed_resume(result.parsed)
            result.parsed = sanitized
            
            # Validate
            validation = validate_parsed_resume(sanitized)
            
            if not validation.is_valid:
                logger.warning("Validation failed: %s", validation.errors)
                result.parsed.parse_notes.extend(
                    [f"VALIDATION ERROR: {e}" for e in validation.errors]
                )
                # Don't fail parsing, but note the issues
            
            if validation.warnings:
                result.parsed.parse_notes.extend(
                    [f"VALIDATION WARNING: {w}" for w in validation.warnings]
                )

        # Add parser identification
        if result.parsed:
            result.parsed.parse_notes.insert(0, f"Parsed by: {self.__class__.__name__}")
            if self.debug:
                result.parsed.parse_notes.append("Debug mode enabled")

        logger.info("PARSER COMPLETE status=%s", result.status)
        return result

    def parse_to_resume_content(self, file_path: str, filename: str) -> ResumeContent:
        """
        Parse file and return ResumeContent (existing schema).
        
        This is the main integration point for the existing system.
        """
        result = self.parse_file(file_path, filename)
        
        if result.status == "failed" or not result.parsed:
            # Return empty ResumeContent with error in meta
            from app.models.resume import ResumeMeta, ResumeProfile
            return ResumeContent(
                profile=ResumeProfile(),
                meta=ResumeMeta(
                    completeness=0.0,
                    setup_completed=False,
                    setup_step=0,
                ),
            )
        
        return parsed_resume_to_resume_content(result.parsed)

    async def parse_file_async(self, file_path: str, filename: str) -> ParseResult:
        """Async wrapper for parse_file."""
        # For now, just call sync version
        # Could be extended to run in thread pool for CPU-intensive parsing
        return self.parse_file(file_path, filename)


# Backward compatibility function
def parse_resume_file(file_path: str, filename: str, debug: bool = False) -> ParseResult:
    """Standalone function for backward compatibility."""
    parser = ResumeParser(debug=debug)
    return parser.parse_file(file_path, filename)