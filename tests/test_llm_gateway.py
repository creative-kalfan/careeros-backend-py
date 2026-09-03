"""Tests for the LLM Gateway foundation."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import get_settings
from app.llm.providers.base import BaseLLMProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.groq import GroqProvider
from app.llm.providers.mistral import MistralProvider
from app.llm.providers.openrouter import OpenRouterProvider
from app.llm.router import ProviderRouter
from app.llm.types import (
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMProvider,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMTask,
    LLMTimeoutError,
    LLMUsage,
)
from app.llm.gateway import LLMGateway


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_groq_response(content: str = "test") -> dict:
    return {
        "id": "chatcmpl-123",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _make_gemini_response(content: str = "test") -> dict:
    return {
        "id": "gemini-123",
        "candidates": [{"content": {"parts": [{"text": content}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
    }


def _make_mistral_response(content: str = "test") -> dict:
    return {
        "id": "mistral-123",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _make_openrouter_response(content: str = "test") -> dict:
    return {
        "id": "or-123",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _mock_httpx_response(status_code: int = 200, json_data: dict | None = None):
    class MockResponse:
        def __init__(self, status_code, json_data):
            self.status_code = status_code
            self._json_data = json_data
            self.text = json.dumps(json_data or {})
            self.headers = {}

        def json(self):
            return self._json_data

    return MockResponse(status_code, json_data)


class MockAsyncClient:
    def __init__(self, mock_post_func):
        self._post = mock_post_func

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def post(self, *args, **kwargs):
        return await self._post(*args, **kwargs)


def _clear_settings_cache():
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Provider interface tests
# ---------------------------------------------------------------------------


class TestBaseProvider:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            BaseLLMProvider()  # type: ignore[abstract]


class TestGroqProvider:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _clear_settings_cache()
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        yield
        _clear_settings_cache()

    @pytest.fixture
    def provider(self):
        from app.llm.providers.groq import GroqProvider

        return GroqProvider()

    def test_is_configured(self, provider):
        assert provider.is_configured() is True

    @pytest.mark.asyncio
    async def test_generate_success(self, provider, monkeypatch):
        _clear_settings_cache()
        monkeypatch.setenv("GROQ_API_KEY", "test-key")

        mock_response = _make_groq_response("Hello from Groq")

        async def mock_post(*args, **kwargs):
            return _mock_httpx_response(200, mock_response)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient(mock_post))

        request = LLMRequest(
            task=LLMTask.RESUME_SECTION_SUGGESTION, prompt="Say hello", provider=LLMProvider.GROQ
        )
        result = await provider.generate(request)
        assert result.content == "Hello from Groq"
        assert result.provider == LLMProvider.GROQ
        assert result.usage is not None
        assert result.usage.input_tokens == 10

    @pytest.mark.asyncio
    async def test_generate_auth_error(self, provider, monkeypatch):
        async def mock_post(*args, **kwargs):
            return _mock_httpx_response(401)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient(mock_post))

        request = LLMRequest(
            task=LLMTask.RESUME_SECTION_SUGGESTION, prompt="test", provider=LLMProvider.GROQ
        )
        with pytest.raises(LLMAuthenticationError):
            await provider.generate(request)

    @pytest.mark.asyncio
    async def test_generate_rate_limit(self, provider, monkeypatch):
        async def mock_post(*args, **kwargs):
            return _mock_httpx_response(429)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient(mock_post))

        request = LLMRequest(
            task=LLMTask.RESUME_SECTION_SUGGESTION, prompt="test", provider=LLMProvider.GROQ
        )
        with pytest.raises(LLMRateLimitError):
            await provider.generate(request)

    @pytest.mark.asyncio
    async def test_generate_quota_exhausted(self, provider, monkeypatch):
        async def mock_post(*args, **kwargs):
            return _mock_httpx_response(402)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient(mock_post))

        request = LLMRequest(
            task=LLMTask.RESUME_SECTION_SUGGESTION, prompt="test", provider=LLMProvider.GROQ
        )
        with pytest.raises(LLMQuotaExhaustedError):
            await provider.generate(request)

    @pytest.mark.asyncio
    async def test_generate_timeout(self, provider, monkeypatch):
        async def mock_post(*args, **kwargs):
            raise httpx.TimeoutException("timeout")

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient(mock_post))

        request = LLMRequest(
            task=LLMTask.RESUME_SECTION_SUGGESTION, prompt="test", provider=LLMProvider.GROQ
        )
        with pytest.raises(LLMTimeoutError):
            await provider.generate(request)


class TestGeminiProvider:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _clear_settings_cache()
        monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "test-key")
        yield
        _clear_settings_cache()

    @pytest.fixture
    def provider(self):
        from app.llm.providers.gemini import GeminiProvider

        return GeminiProvider()

    def test_is_configured(self, provider):
        assert provider.is_configured() is True

    @pytest.mark.asyncio
    async def test_generate_success(self, provider, monkeypatch):
        mock_response = _make_gemini_response("Hello from Gemini")

        async def mock_post(*args, **kwargs):
            return _mock_httpx_response(200, mock_response)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient(mock_post))

        request = LLMRequest(
            task=LLMTask.RESUME_SECTION_SUGGESTION,
            prompt="Say hello",
            provider=LLMProvider.GOOGLE_GEMINI,
        )
        result = await provider.generate(request)
        assert result.content == "Hello from Gemini"
        assert result.provider == LLMProvider.GOOGLE_GEMINI


class TestMistralProvider:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _clear_settings_cache()
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        yield
        _clear_settings_cache()

    @pytest.fixture
    def provider(self):
        from app.llm.providers.mistral import MistralProvider

        return MistralProvider()

    def test_is_configured(self, provider):
        assert provider.is_configured() is True

    @pytest.mark.asyncio
    async def test_generate_success(self, provider, monkeypatch):
        mock_response = _make_mistral_response("Hello from Mistral")

        async def mock_post(*args, **kwargs):
            return _mock_httpx_response(200, mock_response)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient(mock_post))

        request = LLMRequest(
            task=LLMTask.RESUME_SECTION_SUGGESTION,
            prompt="Say hello",
            provider=LLMProvider.MISTRAL,
        )
        result = await provider.generate(request)
        assert result.content == "Hello from Mistral"
        assert result.provider == LLMProvider.MISTRAL


class TestOpenRouterProvider:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _clear_settings_cache()
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        yield
        _clear_settings_cache()

    @pytest.fixture
    def provider(self):
        from app.llm.providers.openrouter import OpenRouterProvider

        return OpenRouterProvider()

    def test_is_configured(self, provider):
        assert provider.is_configured() is True

    @pytest.mark.asyncio
    async def test_generate_success(self, provider, monkeypatch):
        mock_response = _make_openrouter_response("Hello from OpenRouter")

        async def mock_post(*args, **kwargs):
            return _mock_httpx_response(200, mock_response)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: MockAsyncClient(mock_post))

        request = LLMRequest(
            task=LLMTask.RESUME_SECTION_SUGGESTION,
            prompt="Say hello",
            provider=LLMProvider.OPENROUTER,
        )
        result = await provider.generate(request)
        assert result.content == "Hello from OpenRouter"
        assert result.provider == LLMProvider.OPENROUTER


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestProviderRouter:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _clear_settings_cache()
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "groq")
        yield
        _clear_settings_cache()

    @pytest.fixture
    def router(self):
        from app.llm.router import ProviderRouter

        return ProviderRouter()

    def test_default_provider(self, router):
        assert router.default_provider == LLMProvider.GROQ

    def test_get_provider(self, router):
        provider = router.get_provider(LLMProvider.GROQ)
        assert provider.provider == LLMProvider.GROQ

    def test_get_provider_unconfigured_raises(self, monkeypatch):
        monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "test-anon-key")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
        monkeypatch.delenv("GROQ_API_KEY", raising=False)

        # Settings reads .env via pydantic-settings' env_file, which may
        # contain a real GROQ_API_KEY. Build a Settings instance that
        # ignores the file so the "unconfigured provider" premise holds.
        import app.config as config_module
        import app.llm.providers.groq as groq_module
        import app.llm.router as router_module

        def _settings_no_env_file():
            return config_module.Settings(_env_file=None)

        monkeypatch.setattr(router_module, "get_settings", _settings_no_env_file)
        monkeypatch.setattr(groq_module, "get_settings", _settings_no_env_file)

        from app.llm.router import ProviderRouter

        router = ProviderRouter()
        with pytest.raises(LLMProviderError):
            router.get_provider(LLMProvider.GROQ)


# ---------------------------------------------------------------------------
# Gateway tests
# ---------------------------------------------------------------------------


class TestLLMGateway:
    @pytest.mark.asyncio
    async def test_generate_success(self, monkeypatch):
        _clear_settings_cache()
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "groq")

        async def mock_generate(self, request):
            return LLMResponse(
                provider=LLMProvider.GROQ,
                model="llama-3.3-70b-versatile",
                content="Test response",
                usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            )

        monkeypatch.setattr(GroqProvider, "generate", mock_generate)

        gateway = LLMGateway()
        request = LLMRequest(task=LLMTask.RESUME_SECTION_SUGGESTION, prompt="Say hello")
        result = await gateway.generate(request)
        assert result.content == "Test response"
        assert result.provider == LLMProvider.GROQ

    @pytest.mark.asyncio
    async def test_generate_empty_prompt_raises(self, monkeypatch):
        _clear_settings_cache()
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "groq")
        gateway = LLMGateway()
        request = LLMRequest(task=LLMTask.RESUME_SECTION_SUGGESTION, prompt="   ")
        with pytest.raises(LLMProviderError):
            await gateway.generate(request)


# ---------------------------------------------------------------------------
# OptimizationService LLM integration tests
# ---------------------------------------------------------------------------


class TestOptimizationServiceLLM:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _clear_settings_cache()
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "groq")
        yield
        _clear_settings_cache()

    def test_generate_skills_optimization_llm_success(self, monkeypatch):
        from app.models.resume import ResumeContent, ResumeProfile, SkillCategory
        from app.services.optimization.optimization_service import OptimizationService

        profile = ResumeProfile(
            personal={"full_name": "Test User", "email": "test@example.com"},
            summary="Experienced professional.",
            skills=SkillCategory(technical=["Python", "SQL"], tools=["Power BI"]),
            experience=[],
            education=[],
        )
        resume_content = ResumeContent(profile=profile)

        service = OptimizationService()

        async def mock_generate(self, request):
            return LLMResponse(
                provider=LLMProvider.GROQ,
                model="llama-3.3-70b-versatile",
                content=json.dumps({
                    "section": "skills",
                    "operation": "replace",
                    "original_content": "Python, SQL, Power BI",
                    "suggested_content": "Python, SQL, Power BI, Snowflake, Tableau",
                    "rationale": "Added Snowflake and Tableau as they are relevant to the target Data Analyst role.",
                    "confidence": 0.85,
                }),
                usage=LLMUsage(input_tokens=50, output_tokens=30, total_tokens=80),
            )

        monkeypatch.setattr(GroqProvider, "generate", mock_generate)

        result = service.generate_skills_optimization_llm(
            resume_content=resume_content,
            job_description="Looking for a Data Analyst with Python, SQL, Snowflake, Tableau experience.",
            job_title="Data Analyst",
        )

        assert result.success is True
        assert len(result.suggestions) == 1
        suggestion = result.suggestions[0]
        assert suggestion["type"] == "skills_alignment_llm"
        assert suggestion["section"] == "skills"
        assert suggestion["operation"] == "replace"
        assert "Snowflake" in suggestion["suggestedText"]
        assert suggestion["confidence"] == 0.85

    def test_generate_skills_optimization_llm_malformed_response(self, monkeypatch):
        from app.models.resume import ResumeContent, ResumeProfile, SkillCategory
        from app.services.optimization.optimization_service import OptimizationService

        profile = ResumeProfile(
            personal={"full_name": "Test User", "email": "test@example.com"},
            summary="Experienced professional.",
            skills=SkillCategory(technical=["Python", "SQL"]),
            experience=[],
            education=[],
        )
        resume_content = ResumeContent(profile=profile)

        service = OptimizationService()

        async def mock_generate(self, request):
            return LLMResponse(
                provider=LLMProvider.GROQ,
                model="llama-3.3-70b-versatile",
                content="This is not valid JSON",
                usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            )

        monkeypatch.setattr(GroqProvider, "generate", mock_generate)

        result = service.generate_skills_optimization_llm(
            resume_content=resume_content,
            job_description="Looking for a Data Analyst.",
            job_title="Data Analyst",
        )

        assert result.success is False
        assert "invalid response" in result.message.lower() or "failed" in result.message.lower()
        assert len(result.evidence_issues) > 0

    def test_generate_skills_optimization_llm_provider_failure(self, monkeypatch):
        from app.models.resume import ResumeContent, ResumeProfile, SkillCategory
        from app.services.optimization.optimization_service import OptimizationService

        profile = ResumeProfile(
            personal={"full_name": "Test User", "email": "test@example.com"},
            summary="Experienced professional.",
            skills=SkillCategory(technical=["Python", "SQL"]),
            experience=[],
            education=[],
        )
        resume_content = ResumeContent(profile=profile)

        service = OptimizationService()

        async def mock_generate(self, request):
            raise LLMRateLimitError("Rate limit exceeded", LLMProvider.GROQ)

        monkeypatch.setattr(GroqProvider, "generate", mock_generate)

        result = service.generate_skills_optimization_llm(
            resume_content=resume_content,
            job_description="Looking for a Data Analyst.",
            job_title="Data Analyst",
        )

        assert result.success is False
        assert "unavailable" in result.message.lower() or "try again" in result.message.lower()
        assert len(result.evidence_issues) > 0
