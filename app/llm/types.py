"""LLM Gateway types, request/response models, and structured schemas."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class LLMProvider(str, Enum):
    GROQ = "groq"
    GOOGLE_GEMINI = "google_gemini"
    MISTRAL = "mistral"
    OPENROUTER = "openrouter"


class LLMTask(str, Enum):
    RESUME_SECTION_SUGGESTION = "resume_section_suggestion"
    ATS_SEMANTIC_REASONING = "ats_semantic_reasoning"
    RESUME_IMPROVEMENT_ASSESSMENT = "resume_improvement_assessment"
    INTERVIEW_PREP_GENERATION = "interview_prep_generation"
    # Future tasks: resume_summary, cover_letter, etc.


class LLMUsage(BaseModel):
    """Token usage metadata. All fields optional because providers differ."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class LLMRequest(BaseModel):
    """Provider-neutral LLM request."""

    task: LLMTask
    prompt: str
    system_instruction: str | None = None
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 1024
    response_schema: dict[str, Any] | None = None
    provider: LLMProvider | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Provider-neutral LLM response."""

    provider: LLMProvider
    model: str
    content: str
    usage: LLMUsage | None = None
    request_id: str | None = None
    latency_ms: float | None = None
    finish_reason: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ResumeSectionSuggestion(BaseModel):
    """Structured suggestion for a single resume section operation."""

    section: str = Field(description="Resume section: experience, skills, summary, education, projects")
    operation: str = Field(description="Operation: replace, insert, delete")
    original_content: str = Field(description="Original text from the resume")
    suggested_content: str = Field(description="Proposed replacement or new text")
    rationale: str = Field(description="Why this change improves the resume")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")


class StructuredSuggestion(BaseModel):
    """Wrapper for structured LLM output."""

    suggestions: list[ResumeSectionSuggestion] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Provider errors
# ---------------------------------------------------------------------------


class LLMProviderError(Exception):
    """Base LLM provider error."""

    def __init__(self, message: str, provider: LLMProvider, detail: str | None = None):
        self.provider = provider
        self.detail = detail
        super().__init__(message)


class LLMAuthenticationError(LLMProviderError):
    """Invalid API key or credentials."""


class LLMRateLimitError(LLMProviderError):
    """Rate limit exceeded (429)."""


class LLMQuotaExhaustedError(LLMProviderError):
    """Quota or billing limit reached."""


class LLMProviderUnavailableError(LLMProviderError):
    """Provider service is down or unreachable."""


class LLMTimeoutError(LLMProviderError):
    """Request timed out."""


class LLMInvalidRequestError(LLMProviderError):
    """Bad request (400) — prompt too long, invalid params, etc."""
