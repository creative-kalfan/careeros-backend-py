"""LLM Gateway — main entry point for LLM generation."""

from __future__ import annotations

import logging
import time
import uuid

from app.llm.router import ProviderRouter, get_provider_router
from app.llm.types import (
    LLMProviderError,
    LLMRequest,
    LLMResponse,
)

logger = logging.getLogger(__name__)


class LLMGateway:
    """Provider-agnostic gateway for structured LLM generation."""

    def __init__(self, router: ProviderRouter | None = None) -> None:
        self._router = router or get_provider_router()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a response for the given request.

        Returns a provider-neutral ``LLMResponse``.
        """
        if not request.prompt.strip():
            raise LLMProviderError("Prompt must not be empty", request.provider or self._router.default_provider)

        start = time.perf_counter()
        response = await self._router.generate(request)
        response.latency_ms = (time.perf_counter() - start) * 1000.0
        return response


def get_llm_gateway() -> LLMGateway:
    """Return a cached gateway instance."""
    return LLMGateway()
