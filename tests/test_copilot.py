"""Tests for the AI Copilot backend engine (POST /api/copilot/chat).

All LLM calls are mocked — no provider credentials or network access needed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.service import AuthContext, AuthUser
from app.dependencies import get_current_user
from app.llm.types import LLMProvider, LLMProviderError, LLMResponse, LLMTask, LLMUsage
from app.main import app
from app.models.copilot import CopilotContext, CopilotMessage
from app.services.copilot.prompts import (
    SYSTEM_INSTRUCTION,
    build_copilot_prompt,
    format_history,
    suggest_actions,
    summarize_profile,
    summarize_resume_profile,
)
from app.services.copilot.service import CopilotService


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _ctx(user_id: str = "user-A", jwt: str = "jwt-A") -> AuthContext:
    return AuthContext(
        user=AuthUser(id=user_id, email=f"{user_id}@example.com"),
        supabase=MagicMock(),
        jwt=jwt,
    )


def _llm_response(content: str = "Tighten your top bullet around the metric you already have.") -> LLMResponse:
    return LLMResponse(
        provider=LLMProvider.GROQ,
        model="test-model",
        content=content,
        usage=LLMUsage(input_tokens=120, output_tokens=40, total_tokens=160),
        request_id="req-1",
        latency_ms=12.0,
        finish_reason="stop",
    )


def _service_with_gateway(generate_return=None, generate_side_effect=None) -> tuple[CopilotService, MagicMock]:
    gateway = MagicMock()
    if generate_side_effect is not None:
        gateway.generate = AsyncMock(side_effect=generate_side_effect)
    else:
        gateway.generate = AsyncMock(return_value=generate_return or _llm_response())
    service = CopilotService(gateway_factory=lambda: gateway)
    return service, gateway


def _resume_row() -> dict:
    return {
        "id": "resume-1",
        "user_id": "user-A",
        "content": {
            "profile": {
                "personal": {"full_name": "Asha Engineer"},
                "summary": "Backend engineer building payment APIs with Python and FastAPI.",
                "skills": {"technical": ["Python", "FastAPI"], "tools": ["Redis"]},
                "experience": [
                    {
                        "company": "Finscale",
                        "role": "Backend Engineer",
                        "responsibilities": [{"text": "Built ingestion microservices with Python/FastAPI."}],
                        "achievements": ["Cut P99 latency by 35%."],
                    }
                ],
                "projects": [],
                "education": [],
            }
        },
    }


@pytest.fixture
def authed_client():
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: _ctx()
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _patch_no_profile():
    return patch.object(
        CopilotService, "_get_profile_summary", new=AsyncMock(return_value="")
    )


# ---------------------------------------------------------------------------
# Prompt unit tests
# ---------------------------------------------------------------------------


class TestCopilotPrompts:
    def test_system_instruction_is_ats_focused_and_anti_hallucination(self):
        text = SYSTEM_INSTRUCTION.lower()
        assert "never invent" in text
        assert "ats" in text
        assert "concise" in text or "tactical" in text

    def test_summarize_resume_profile_is_bounded_and_grounded(self):
        profile = _resume_row()["content"]["profile"]
        summary = summarize_resume_profile(profile)
        assert "Finscale" in summary
        assert "Python" in summary
        assert len(summary) <= 2600

    def test_summarize_profile_handles_none(self):
        assert summarize_profile(None) == ""

    def test_format_history_keeps_newest_within_budget(self):
        messages = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"message-{i} " + ("x" * 50)}
            for i in range(40)
        ]
        history = format_history(messages)
        assert "message-39" in history
        assert len(history) <= 6100

    def test_build_prompt_includes_context_blocks(self):
        prompt = build_copilot_prompt(
            history="user: hello",
            profile_block="Target role: Backend Engineer",
            resume_block="Summary: Python engineer",
            current_page="/resumes",
            job_title="Backend Engineer",
            selected_text="Built APIs",
        )
        assert "Target role: Backend Engineer" in prompt
        assert "RESUME EVIDENCE" in prompt
        assert "SELECTED TEXT" in prompt
        assert "user: hello" in prompt

    def test_suggest_actions_resume_page(self):
        actions = suggest_actions(current_page="/resumes/123", last_user_text="help")
        assert len(actions) == 3
        assert any("ATS" in a for a in actions)

    def test_suggest_actions_jobs_page_with_role(self):
        actions = suggest_actions(
            current_page="/jobs", job_title="Backend Engineer", last_user_text="find roles"
        )
        assert any("ailor" in a for a in actions)

    def test_suggest_actions_default(self):
        actions = suggest_actions(last_user_text="hello")
        assert len(actions) == 3


# ---------------------------------------------------------------------------
# Service unit tests (mocked gateway)
# ---------------------------------------------------------------------------


class TestCopilotService:
    @pytest.mark.asyncio
    async def test_chat_success_returns_message_and_chips(self):
        service, gateway = _service_with_gateway()
        with _patch_no_profile():
            data = await service.chat(
                _ctx(),
                [CopilotMessage(role="user", content="How do I improve my summary?")],
                CopilotContext(current_page="/resumes"),
            )
        assert "Tighten" in data.message
        assert len(data.suggested_actions) == 3
        assert data.provider == "groq"
        assert data.usage is not None
        assert data.usage.total_tokens == 160
        # Gateway went through the copilot task with the coach persona.
        request = gateway.generate.await_args.args[0]
        assert request.task == LLMTask.COPILOT_CHAT
        assert "NEVER invent" in (request.system_instruction or "")
        assert "How do I improve my summary?" in request.prompt

    @pytest.mark.asyncio
    async def test_chat_injects_resume_evidence(self):
        service, gateway = _service_with_gateway()
        with (
            _patch_no_profile(),
            patch.object(
                CopilotService, "_get_resume_profile", return_value=_resume_row()["content"]["profile"]
            ) as mock_resume,
        ):
            data = await service.chat(
                _ctx(),
                [CopilotMessage(role="user", content="Tailor this for fintech")],
                CopilotContext(current_page="/resumes", resume_id="resume-1"),
            )
        mock_resume.assert_called_once()
        prompt = gateway.generate.await_args.args[0].prompt
        assert "Finscale" in prompt
        assert any("ATS" in a for a in data.suggested_actions)

    @pytest.mark.asyncio
    async def test_chat_no_user_message_rejected(self):
        service, _ = _service_with_gateway()
        with _patch_no_profile():
            with pytest.raises(HTTPException) as exc_info:
                await service.chat(
                    _ctx(), [CopilotMessage(role="assistant", content="Hi there")], None
                )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_chat_resume_not_found_maps_to_404(self):
        service, _ = _service_with_gateway()
        with (
            _patch_no_profile(),
            patch.object(
                CopilotService,
                "_get_resume_profile",
                side_effect=HTTPException(status_code=404, detail="Resume not found"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await service.chat(
                    _ctx(),
                    [CopilotMessage(role="user", content="hi")],
                    CopilotContext(resume_id="missing"),
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_chat_llm_failure_maps_to_503(self):
        service, _ = _service_with_gateway(
            generate_side_effect=LLMProviderError("down", LLMProvider.GROQ)
        )
        with _patch_no_profile():
            with pytest.raises(HTTPException) as exc_info:
                await service.chat(
                    _ctx(), [CopilotMessage(role="user", content="hello")], None
                )
        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["code"] == "LLM_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_chat_timeout_maps_to_503(self):
        async def _hang(_request):
            await asyncio.sleep(60)
            return _llm_response()

        service = CopilotService(gateway_factory=lambda: SimpleNamespace(generate=_hang))
        with (
            _patch_no_profile(),
            patch("app.services.copilot.service.COPILOT_GATEWAY_TIMEOUT_SECONDS", 0.01),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await service.chat(
                    _ctx(), [CopilotMessage(role="user", content="hello")], None
                )
        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["code"] == "LLM_TIMEOUT"

    @pytest.mark.asyncio
    async def test_chat_empty_llm_content_maps_to_502(self):
        service, _ = _service_with_gateway(generate_return=_llm_response(content="   "))
        with _patch_no_profile():
            with pytest.raises(HTTPException) as exc_info:
                await service.chat(
                    _ctx(), [CopilotMessage(role="user", content="hello")], None
                )
        assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# Route tests (mocked gateway + repos)
# ---------------------------------------------------------------------------


class TestCopilotRoute:
    def test_unauthenticated_rejected(self):
        client = TestClient(app)
        resp = client.post(
            "/api/copilot/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
        assert resp.status_code == 401

    def test_empty_messages_rejected_with_422(self, authed_client):
        resp = authed_client.post("/api/copilot/chat", json={"messages": []})
        assert resp.status_code == 422

    def test_chat_success_envelope(self, authed_client):
        with (
            _patch_no_profile(),
            patch(
                "app.services.copilot.service.CopilotService._get_gateway"
            ) as mock_factory,
        ):
            gateway = MagicMock()
            gateway.generate = AsyncMock(return_value=_llm_response())
            mock_factory.return_value = gateway
            resp = authed_client.post(
                "/api/copilot/chat",
                json={
                    "messages": [{"role": "user", "content": "Help me improve my resume"}],
                    "context": {"current_page": "/resumes", "job_title": "Backend Engineer"},
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert "Tighten" in data["message"]
        assert isinstance(data["suggested_actions"], list)
        assert len(data["suggested_actions"]) == 3
        assert data["usage"]["total_tokens"] == 160
        assert data["provider"] == "groq"

    def test_chat_with_resume_context(self, authed_client):
        with (
            _patch_no_profile(),
            patch(
                "app.services.copilot.service.CopilotService._get_gateway"
            ) as mock_factory,
            patch("app.repositories.resume_repository.ResumeRepository.get_resume") as mock_get,
        ):
            gateway = MagicMock()
            gateway.generate = AsyncMock(return_value=_llm_response())
            mock_factory.return_value = gateway
            mock_get.return_value = _resume_row()
            resp = authed_client.post(
                "/api/copilot/chat",
                json={
                    "messages": [{"role": "user", "content": "Tailor this section"}],
                    "context": {"current_page": "/resumes", "resume_id": "resume-1"},
                },
            )
        assert resp.status_code == 200, resp.text
        prompt = gateway.generate.await_args.args[0].prompt
        assert "Finscale" in prompt
        assert any("ATS" in a for a in resp.json()["data"]["suggested_actions"])

    def test_chat_unknown_resume_returns_404(self, authed_client):
        with (
            _patch_no_profile(),
            patch("app.repositories.resume_repository.ResumeRepository.get_resume") as mock_get,
        ):
            mock_get.return_value = None
            resp = authed_client.post(
                "/api/copilot/chat",
                json={
                    "messages": [{"role": "user", "content": "hello"}],
                    "context": {"resume_id": "other-users-resume"},
                },
            )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RESUME_NOT_FOUND"

    def test_chat_llm_unavailable_returns_503_envelope(self, authed_client):
        with (
            _patch_no_profile(),
            patch(
                "app.services.copilot.service.CopilotService._get_gateway"
            ) as mock_factory,
        ):
            gateway = MagicMock()
            gateway.generate = AsyncMock(
                side_effect=LLMProviderError("down", LLMProvider.GROQ)
            )
            mock_factory.return_value = gateway
            resp = authed_client.post(
                "/api/copilot/chat",
                json={"messages": [{"role": "user", "content": "hello"}]},
            )
        assert resp.status_code == 503
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "LLM_UNAVAILABLE"
        assert isinstance(body["error"]["message"], str)
