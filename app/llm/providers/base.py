"""Base LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.llm.types import LLMProvider, LLMRequest, LLMResponse, LLMProviderError


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    provider: LLMProvider

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a completion for the given request.

        Must not raise provider-specific exceptions — wrap them in
        ``LLMProviderError`` subclasses defined in ``app.llm.types``.
        """
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if the provider has the minimum required config (e.g. API key)."""
        ...
