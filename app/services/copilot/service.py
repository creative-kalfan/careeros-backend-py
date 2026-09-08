"""AI Copilot context engine: assembles grounded prompts, calls the LLM gateway.

Routes stay thin; all business logic (context gathering, prompt assembly,
gateway invocation, timeout/error mapping, follow-up chips) lives here.

Design notes (per AGENTS.md conventions):
- Reuses the shared ``LLMGateway`` / ``ProviderRouter`` fallback engine
  (Groq -> Gemini -> Mistral -> OpenRouter). Never calls providers directly.
- Async service: route handlers ``await`` it directly. Never ``asyncio.run``.
- RLS-scoped reads only: profile via the RLS ``auth.supabase`` client,
  resumes via ``ResumeRepository(jwt=auth.jwt)`` with an explicit ownership
  check (unknown/forbidden id -> 404, never 403, to avoid existence leaks).
- No persistence: chat is stateless. No credentials ever enter the prompt.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from fastapi import HTTPException

from app.llm.types import LLMProviderError, LLMRequest, LLMTask
from app.models.copilot import CopilotChatData, CopilotContext, CopilotMessage, CopilotUsage
from app.services.copilot.prompts import (
    SYSTEM_INSTRUCTION,
    build_copilot_prompt,
    format_history,
    suggest_actions,
    summarize_profile,
    summarize_resume_profile,
)

logger = logging.getLogger(__name__)

# Gateway budget for a single chat turn. Providers enforce their own 60s
# httpx timeout; this tighter bound keeps the ⌘I panel responsive and maps
# hangs to a typed, retryable 503 instead of a stalled request.
COPILOT_GATEWAY_TIMEOUT_SECONDS = 30.0


class CopilotService:
    """Use-case layer for the AI Copilot chat domain."""

    def __init__(self, gateway_factory: Any = None) -> None:
        self.gateway_factory = gateway_factory

    def _get_gateway(self) -> Any:
        if self.gateway_factory is not None:
            return self.gateway_factory()
        from app.llm.gateway import get_llm_gateway

        return get_llm_gateway()

    # -- Context gathering -------------------------------------------------

    async def _get_profile_summary(self, auth: Any) -> str:
        """Best-effort user-profile summary (empty string when unavailable)."""
        try:
            from app.repositories.profile_repository import ProfileRepository

            repo = ProfileRepository(client=auth.supabase)
            profile = await repo.aget_profile(auth.user.id)
        except Exception as exc:  # noqa: BLE001 — profile is optional context
            logger.debug("Copilot profile lookup skipped: %s", exc)
            return ""
        try:
            return summarize_profile(profile)
        except Exception as exc:  # noqa: BLE001 — never break chat on formatting
            logger.debug("Copilot profile summarize skipped: %s", exc)
            return ""

    def _get_resume_profile(self, auth: Any, resume_id: str) -> dict[str, Any]:
        """Return the resume's profile dict or raise 404 (ownership-checked)."""
        from app.repositories.resume_repository import ResumeRepository

        repo = ResumeRepository(jwt=getattr(auth, "jwt", None))
        try:
            row = repo.get_resume(auth.user.id, resume_id)
        except Exception as exc:  # noqa: BLE001 — DB errors degrade to 500 below
            logger.error("Copilot resume lookup failed", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "RESUME_LOOKUP_FAILED",
                    "message": "Could not load resume context. Please try again.",
                },
            ) from exc
        if not row:
            raise HTTPException(
                status_code=404,
                detail={"code": "RESUME_NOT_FOUND", "message": "Resume not found"},
            )
        try:
            from app.models.resume import ResumeContent

            return ResumeContent.from_dict(row.get("content") or {}).profile.model_dump()
        except Exception:  # noqa: BLE001 — malformed content degrades gracefully
            return {}

    # -- Public API --------------------------------------------------------

    async def chat(
        self,
        auth: Any,
        messages: list[CopilotMessage],
        context: Optional[CopilotContext] = None,
    ) -> CopilotChatData:
        """Answer the last user message with resume/profile-grounded context."""
        ctx = context or CopilotContext()
        history_in = [m.model_dump() for m in messages]

        # The answer target is the last user message; without one there is
        # nothing to respond to.
        last_user_text = ""
        for msg in reversed(history_in):
            if msg.get("role") == "user" and str(msg.get("content", "")).strip():
                last_user_text = str(msg["content"]).strip()
                break
        if not last_user_text:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "NO_USER_MESSAGE",
                    "message": "At least one user message is required.",
                },
            )

        profile_block = await self._get_profile_summary(auth)
        resume_block = ""
        if ctx.resume_id:
            resume_block = summarize_resume_profile(
                self._get_resume_profile(auth, ctx.resume_id)
            )

        prompt = build_copilot_prompt(
            history=format_history(history_in),
            profile_block=profile_block,
            resume_block=resume_block,
            current_page=ctx.current_page,
            job_title=ctx.job_title,
            company=ctx.company,
            selected_text=ctx.selected_text,
            job_description=ctx.job_description,
        )

        gateway = self._get_gateway()
        try:
            response = await asyncio.wait_for(
                gateway.generate(
                    LLMRequest(
                        task=LLMTask.COPILOT_CHAT,
                        prompt=prompt,
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.5,
                        max_tokens=1024,
                        metadata={
                            "current_page": ctx.current_page or "",
                            "has_resume": bool(ctx.resume_id),
                        },
                    )
                ),
                timeout=COPILOT_GATEWAY_TIMEOUT_SECONDS,
            )
        except HTTPException:
            raise
        except asyncio.TimeoutError as exc:
            logger.warning("Copilot LLM timed out")
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "LLM_TIMEOUT",
                    "message": "AI assistant timed out. Please try again.",
                },
            ) from exc
        except LLMProviderError as exc:
            logger.warning("Copilot LLM unavailable: %s", exc)
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "LLM_UNAVAILABLE",
                    "message": "AI assistant is temporarily unavailable. Please try again.",
                },
            ) from exc

        message = (response.content or "").strip()
        if not message:
            logger.warning("Copilot LLM returned empty content")
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "LLM_EMPTY_RESPONSE",
                    "message": "AI assistant returned an empty response. Please try again.",
                },
            )

        usage: Optional[CopilotUsage] = None
        if response.usage is not None:
            usage = CopilotUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                total_tokens=response.usage.total_tokens,
            )

        return CopilotChatData(
            message=message,
            suggested_actions=suggest_actions(
                current_page=ctx.current_page,
                resume_id=ctx.resume_id,
                job_title=ctx.job_title,
                last_user_text=last_user_text,
            ),
            provider=response.provider.value
            if getattr(response, "provider", None) is not None
            else None,
            model=getattr(response, "model", None),
            usage=usage,
        )
