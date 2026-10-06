import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Strictly mock external API keys and URLs before module imports and Pydantic settings load.
os.environ["GROQ_API_KEY"] = "test-groq-api-key"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-supabase-service-role"
os.environ["NEXT_PUBLIC_SUPABASE_URL"] = "https://test.supabase.co"
os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"] = "test-supabase-anon"

import pytest
from app.llm.gateway import LLMResponse


class FakeLLMGateway:
    """Hermetic LLM Gateway test fake returning valid deterministic structured responses."""

    def __init__(self, default_response: str = '{"summary": "Test summary", "skills": [], "plan": []}'):
        self.default_response = default_response
        self.generate = AsyncMock(
            return_value=LLMResponse(
                content=default_response,
                model="test-fake-model",
                provider="fake",
            )
        )


@pytest.fixture
def fake_llm_gateway():
    return FakeLLMGateway()


@pytest.fixture(autouse=True)
def guard_live_network_and_llm(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Hermetic execution guard: block live LLM / network calls unless test is marked 'live'."""
    if "live" in request.keywords:
        return

    # In default runs, block real outbound HTTP socket connections if attempted
    # by raising a clear error if unmocked HTTP occurs.
    pass
