"""Resume parsing service - integrates new layout-aware parser with existing interface."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.models.resume import ResumeContent

from .resume_parser import ResumeParser, parse_resume_file
from .resume_parser.models import ParseResult as NewParseResult

logger = logging.getLogger(__name__)


def is_file_too_large(file_data: bytes, max_bytes: int | None = None) -> bool:
    """Return True if the resume blob exceeds the configured upload limit.

    Used to reject oversized uploads *before* expensive text extraction and
    parsing. The limit is environment-driven via ``MAX_RESUME_UPLOAD_BYTES``
    (see ``app.config.Settings.max_resume_upload_bytes``).
    """
    from app.config import get_settings

    limit = max_bytes if max_bytes is not None else get_settings().max_resume_upload_bytes
    return len(file_data) > limit


@dataclass
class ParseResult:
    """Parse result compatible with existing interface."""
    status: str
    content: dict[str, Any]
    extracted: dict[str, int]
    error: Optional[str] = None
    geometry: Optional[dict[str, Any]] = None


class ResumeParsingService:
    """Resume parsing service using the new layout-aware parser."""

    def __init__(self, debug: bool = False) -> None:
        self.parser = ResumeParser(debug=debug)

    async def parse_file(self, file_path: str, filename: str) -> ParseResult:
        """Extract text from a file and parse into structured resume data."""
        ext = Path(filename).suffix.lower()
        logger.info("PARSER EXTRACT START file_path=%s extension=%s", file_path, ext)
        
        # Use new parser
        result: NewParseResult = await self.parser.parse_file_async(file_path, filename)
        
        if result.status == "failed":
            logger.info("PARSER EXTRACT RESULT status=failed error=%s", result.error)
            return ParseResult(
                status="failed",
                content={},
                extracted={},
                error=result.error or "Parsing failed",
            )

        # Convert to ResumeContent (existing schema)
        from .resume_parser.adapters import parsed_resume_to_resume_content

        resume_content = (
            parsed_resume_to_resume_content(result.parsed)
            if result.parsed
            else self.parser.parse_to_resume_content(file_path, filename)
        )
        
        # Count extracted items
        extracted = self._count_extracted(resume_content)
        
        logger.info("PARSER PARSE COMPLETE status=completed extracted=%s", extracted)
        
        return ParseResult(
            status="completed",
            content=resume_content.to_dict(),
            extracted=extracted,
            geometry=result.geometry,
        )

    def _count_extracted(self, content: ResumeContent) -> dict[str, int]:
        """Count extracted items for response."""
        profile = content.profile
        return {
            "skills_count": sum(
                len(v) for v in profile.skills.model_dump().values() if isinstance(v, list)
            ),
            "experience_count": len(profile.experience),
            "projects_count": len(profile.projects),
            "education_count": len(profile.education),
            "certifications_count": len(profile.certifications),
            "internships_count": len(profile.internships),
            "achievements_count": len(profile.achievements),
            "languages_count": len(profile.languages),
        }


# Backward compatibility - keep the old class name working
__all__ = ["ResumeParsingService", "ParseResult"]