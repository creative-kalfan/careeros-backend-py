"""Core data models for the resume parser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


@dataclass
class DocumentSpan:
    """A single text span with position and style information."""

    text: str
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    font_size: float
    bold: bool
    italic: bool = False
    font_name: str = ""
    color: int = 0
    flags: int = 0
    origin: Optional[list[float]] = None


@dataclass
class DocumentLine:
    """A line of text composed of spans."""

    spans: list[DocumentSpan]
    page: int
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def font_size(self) -> float:
        if not self.spans:
            return 0.0
        return max(s.font_size for s in self.spans)

    @property
    def bold(self) -> bool:
        return any(s.bold for s in self.spans)


@dataclass
class DocumentBlock:
    """A block of text (paragraph) composed of lines."""

    lines: list[DocumentLine]
    page: int
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


@dataclass
class ParsedContact:
    """Extracted contact information."""

    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    website: Optional[str] = None


@dataclass
class ParsedExperience:
    """A single work experience entry."""

    title: str = ""
    company: str = ""
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    bullets: list[str] = field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


@dataclass
class ParsedEducation:
    """A single education entry."""

    degree: str = ""
    institution: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    gpa: Optional[str] = None
    confidence: Literal["high", "medium", "low"] = "medium"


@dataclass
class ParsedProject:
    """A single project entry."""

    name: str = ""
    description: str = ""
    bullets: list[str] = field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


@dataclass
class ParsedResume:
    """Complete parsed resume output - common schema for PDF and DOCX."""

    contact: ParsedContact = field(default_factory=ParsedContact)
    summary: Optional[str] = None
    experience: list[ParsedExperience] = field(default_factory=list)
    education: list[ParsedEducation] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    projects: list[ParsedProject] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    parse_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contact": {
                "name": self.contact.name,
                "email": self.contact.email,
                "phone": self.contact.phone,
                "location": self.contact.location,
                "linkedin": self.contact.linkedin,
                "github": self.contact.github,
                "website": self.contact.website,
            },
            "summary": self.summary,
            "experience": [
                {
                    "title": e.title,
                    "company": e.company,
                    "location": e.location,
                    "start_date": e.start_date,
                    "end_date": e.end_date,
                    "bullets": e.bullets,
                    "confidence": e.confidence,
                }
                for e in self.experience
            ],
            "education": [
                {
                    "degree": e.degree,
                    "institution": e.institution,
                    "start_date": e.start_date,
                    "end_date": e.end_date,
                    "gpa": e.gpa,
                    "confidence": e.confidence,
                }
                for e in self.education
            ],
            "skills": self.skills,
            "projects": [
                {
                    "name": p.name,
                    "description": p.description,
                    "bullets": p.bullets,
                    "confidence": p.confidence,
                }
                for p in self.projects
            ],
            "certifications": self.certifications,
            "achievements": self.achievements,
            "languages": self.languages,
            "links": self.links,
            "parse_notes": self.parse_notes,
        }


@dataclass
class ParseResult:
    """Result of parsing a resume file."""

    status: Literal["completed", "failed"]
    parsed: Optional[ParsedResume] = None
    error: Optional[str] = None
    raw_text: str = ""
    debug_info: Optional[dict[str, Any]] = None
    geometry: Optional[dict[str, Any]] = None