"""Resume data models for the CareerOS Resume Module (Step 1)."""

from __future__ import annotations

import uuid
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator


def _gen_id() -> str:
    return uuid.uuid4().hex[:12]


class PersonalInfo(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    headline: Optional[str] = None
    website: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None


class BulletItem(BaseModel):
    """A single bullet point with a stable ID for item-level addressing."""

    id: str = Field(default_factory=_gen_id)
    text: str = ""


class ExperienceItem(BaseModel):
    id: str = Field(default_factory=_gen_id)
    company: Optional[str] = None
    role: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    current: bool = False
    employment_type: Optional[str] = None
    responsibilities: list[BulletItem] = []
    achievements: list[str] = []
    tools: list[str] = []
    metrics: Optional[str] = None

    @field_validator("responsibilities", mode="before")
    @classmethod
    def _coerce_responsibilities(cls, v: Any) -> list[BulletItem]:
        """Accept legacy list[str] and convert each string to BulletItem.
        Also deduplicates IDs: if two bullets share an ID, the second gets a new one."""
        if not isinstance(v, list):
            return v
        result: list[BulletItem] = []
        seen_ids: set[str] = set()
        for item in v:
            if isinstance(item, str):
                b = BulletItem(text=item)
            elif isinstance(item, dict):
                b = BulletItem(**item)
            elif isinstance(item, BulletItem):
                b = item
            else:
                continue
            # Deduplicate: if ID already seen, regenerate
            if b.id in seen_ids:
                b = BulletItem(text=b.text)
            seen_ids.add(b.id)
            result.append(b)
        return result

    def get_responsibility_texts(self) -> list[str]:
        """Return responsibility bullet text as plain strings (for boundaries)."""
        return [b.text for b in self.responsibilities]

    def get_all_bullet_texts(self) -> list[str]:
        """Return all bullet text as plain strings (responsibilities + achievements)."""
        return self.get_responsibility_texts() + self.achievements


class EducationItem(BaseModel):
    id: str = Field(default_factory=_gen_id)
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    gpa: Optional[str] = None
    coursework: list[str] = []
    achievements: list[str] = []


class SkillCategory(BaseModel):
    technical: list[str] = []
    tools: list[str] = []
    languages: list[str] = []
    databases: list[str] = []
    analytics: list[str] = []
    soft_skills: list[str] = []
    custom: dict[str, list[str]] = {}

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SkillCategory:
        if not data:
            return cls()
        try:
            return cls.model_validate(data)
        except Exception:
            return cls()


class ProjectItem(BaseModel):
    id: str = Field(default_factory=_gen_id)
    name: Optional[str] = None
    description: Optional[str] = None
    problem: Optional[str] = None
    contribution: Optional[str] = None
    technologies: list[str] = []
    methodology: Optional[str] = None
    results: Optional[str] = None
    metrics: Optional[str] = None
    url: Optional[str] = None


class CertificationItem(BaseModel):
    id: str = Field(default_factory=_gen_id)
    name: Optional[str] = None
    issuer: Optional[str] = None
    date: Optional[str] = None
    credential_url: Optional[str] = None


class LeadershipItem(BaseModel):
    id: str = Field(default_factory=_gen_id)
    organization: Optional[str] = None
    role: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None


class LanguageItem(BaseModel):
    id: str = Field(default_factory=_gen_id)
    language: Optional[str] = None
    proficiency: Optional[str] = None


class LinkItem(BaseModel):
    id: str = Field(default_factory=_gen_id)
    label: Optional[str] = None
    url: Optional[str] = None


class AdditionalItem(BaseModel):
    id: str = Field(default_factory=_gen_id)
    title: Optional[str] = None
    description: Optional[str] = None


class ResumeProfile(BaseModel):
    """Structured resume / candidate profile data."""

    personal: PersonalInfo = Field(default_factory=PersonalInfo)
    target_role: Optional[str] = None
    summary: Optional[str] = None
    experience: list[ExperienceItem] = []
    internships: list[ExperienceItem] = []
    education: list[EducationItem] = []
    skills: SkillCategory = Field(default_factory=SkillCategory)
    projects: list[ProjectItem] = []
    certifications: list[CertificationItem] = []
    achievements: list[str] = []
    leadership: list[LeadershipItem] = []
    languages: list[LanguageItem] = []
    links: list[LinkItem] = []
    additional: list[AdditionalItem] = []

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ResumeProfile:
        if not data:
            return cls()
        try:
            return cls.model_validate(data)
        except Exception:
            return cls()


class ResumeMeta(BaseModel):
    is_fresher: Optional[bool] = None
    experience_level: Optional[str] = None
    completeness: float = 0.0
    setup_completed: bool = False
    setup_step: int = 0


class ResumeContent(BaseModel):
    """Full resume payload stored in JSONB."""

    profile: ResumeProfile = Field(default_factory=ResumeProfile)
    meta: ResumeMeta = Field(default_factory=ResumeMeta)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ResumeContent:
        if not data:
            return cls()
        try:
            return cls.model_validate(data)
        except Exception:
            return cls()

    @staticmethod
    def _has_legacy_bullets(raw_data: dict[str, Any]) -> bool:
        """Check if raw content dict has legacy list[str] responsibilities."""
        if not raw_data:
            return False
        profile = raw_data.get("profile", {})
        for exp_list_key in ("experience", "internships"):
            for exp in profile.get(exp_list_key, []):
                resp = exp.get("responsibilities", [])
                if resp and isinstance(resp[0], str):
                    return True
        return False

    def canonicalize(self) -> bool:
        """Generate missing IDs and deduplicate. Returns True if any change was made."""
        changed = False
        for exp_list in (self.profile.experience, self.profile.internships):
            for exp in exp_list:
                # Deduplicate bullet IDs within this experience item
                seen_ids: dict[str, int] = {}
                deduped: list[BulletItem] = []
                for b in exp.responsibilities:
                    if b.id in seen_ids:
                        # Regenerate only the conflicting ID
                        b = BulletItem(text=b.text)
                        changed = True
                    seen_ids[b.id] = seen_ids.get(b.id, 0) + 1
                    deduped.append(b)
                if len(deduped) != len(exp.responsibilities):
                    exp.responsibilities = deduped
                    changed = True
        return changed


class ResumeVersion(BaseModel):
    """Job-specific resume version derived from a master resume."""

    id: str
    resume_id: str
    version_name: str = "Untitled Version"
    source: str = "manual"
    content: dict[str, Any] = Field(default_factory=dict)
    target_job_title: str | None = None
    target_company: str | None = None
    target_job_id: str | None = None
    target_job_url: str | None = None
    job_description: str | None = None
    template: str = "minimal"
    status: str = "active"
    is_master: bool = False
    parent_version_id: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    last_ats_score: float | None = None
    last_analyzed_at: str | None = None
    sections_config: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
