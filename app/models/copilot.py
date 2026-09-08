"""AI Copilot domain models.

Request/response contract for ``POST /api/copilot/chat`` — the backend
engine behind the frontend Copilot panel (``⌘I``).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class CopilotMessage(BaseModel):
    """A single chat message in the Copilot conversation."""

    role: Literal["user", "assistant", "system"] = Field(
        description="Message role. Only 'user' messages drive new answers; "
        "prior 'assistant'/'system' entries are history context."
    )
    content: str = Field(
        min_length=1,
        max_length=8000,
        description="Message text (1..8000 chars).",
    )


class CopilotContext(BaseModel):
    """Optional client-supplied context for grounding the assistant."""

    current_page: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Frontend route or area, e.g. '/resumes', '/jobs'.",
    )
    resume_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Active resume id for resume-grounded answers.",
    )
    job_title: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Target role, e.g. 'Backend Engineer'.",
    )
    company: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Target company, when known.",
    )
    selected_text: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="User-selected snippet (resume section, JD excerpt).",
    )
    job_description: Optional[str] = Field(
        default=None,
        max_length=8000,
        description="Target job description excerpt, when available.",
    )


class CopilotChatRequest(BaseModel):
    """Request body for ``POST /api/copilot/chat``."""

    messages: list[CopilotMessage] = Field(
        min_length=1,
        max_length=50,
        description="Conversation history; last 'user' message is answered.",
    )
    context: Optional[CopilotContext] = Field(
        default=None,
        description="Optional grounding context (page, resume, role, snippets).",
    )


class CopilotUsage(BaseModel):
    """Token tracking metadata echoed from the LLM provider."""

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class CopilotChatData(BaseModel):
    """Structured assistant response with context-aware follow-up chips."""

    message: str = Field(description="Assistant response text.")
    suggested_actions: list[str] = Field(
        default_factory=list,
        description="Quick-chip follow-ups, e.g. 'Tailor this section'.",
    )
    provider: Optional[str] = Field(
        default=None, description="LLM provider that served the response."
    )
    model: Optional[str] = Field(
        default=None, description="Model name that served the response."
    )
    usage: Optional[CopilotUsage] = Field(
        default=None, description="Token usage reported by the provider."
    )
