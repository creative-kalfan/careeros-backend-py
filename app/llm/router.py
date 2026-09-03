"""LLM provider router — selects and falls back across providers."""

from __future__ import annotations

import logging
import time
import uuid
from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.llm.providers.base import BaseLLMProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.groq import GroqProvider
from app.llm.providers.mistral import MistralProvider
from app.llm.providers.openrouter import OpenRouterProvider
from app.llm.types import (
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMProvider,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMProviderUnavailableError,
    LLMQuotaExhaustedError,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)


class ProviderRouter:
    """Routes LLM requests to configured providers with fallback."""

    _PROVIDER_CLASSES: dict[LLMProvider, type[BaseLLMProvider]] = {
        LLMProvider.GROQ: GroqProvider,
        LLMProvider.GOOGLE_GEMINI: GeminiProvider,
        LLMProvider.MISTRAL: MistralProvider,
        LLMProvider.OPENROUTER: OpenRouterProvider,
    }

    def __init__(self) -> None:
        settings = get_settings()
        self._default_provider = LLMProvider(settings.llm_default_provider)
        self._providers: dict[LLMProvider, BaseLLMProvider] = {
            name: cls() for name, cls in self._PROVIDER_CLASSES.items()
        }

    @property
    def default_provider(self) -> LLMProvider:
        return self._default_provider

    def get_provider(self, provider: LLMProvider | None = None) -> BaseLLMProvider:
        """Return a configured provider instance.

        Raises ``LLMProviderError`` if the requested provider is not configured.
        """
        target = provider or self._default_provider
        instance = self._providers.get(target)
        if instance is None or not instance.is_configured():
            raise LLMProviderError(
                f"Provider {target.value} is not configured", target
            )
        return instance

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a response, trying preferred provider then fallbacks."""
        preferred = request.provider or self._default_provider
        fallback_order = self._build_fallback_order(preferred)

        last_error: LLMProviderError | None = None
        for provider_name in fallback_order:
            instance = self._providers.get(provider_name)
            if instance is None or not instance.is_configured():
                logger.debug("Skipping unconfigured provider %s", provider_name.value)
                continue
            try:
                return await instance.generate(request)
            except LLMAuthenticationError as exc:
                logger.error("LLM auth error for %s: %s", provider_name.value, exc)
                last_error = exc
                continue
            except LLMQuotaExhaustedError as exc:
                logger.warning("LLM quota exhausted for %s: %s", provider_name.value, exc)
                last_error = exc
                continue
            except LLMRateLimitError as exc:
                logger.warning("LLM rate limited for %s: %s", provider_name.value, exc)
                last_error = exc
                continue
            except LLMTimeoutError as exc:
                logger.warning("LLM timeout for %s: %s", provider_name.value, exc)
                last_error = exc
                continue
            except LLMProviderUnavailableError as exc:
                logger.warning("LLM provider unavailable %s: %s", provider_name.value, exc)
                last_error = exc
                continue
            except LLMInvalidRequestError as exc:
                logger.error("LLM invalid request for %s: %s", provider_name.value, exc)
                raise
            except LLMProviderError as exc:
                logger.error("LLM provider error for %s: %s", provider_name.value, exc)
                last_error = exc
                continue

        if last_error:
            raise last_error
        raise LLMProviderError("No LLM providers configured", self._default_provider)

    def _build_fallback_order(self, preferred: LLMProvider) -> list[LLMProvider]:
        """Return provider order: preferred first, then the rest."""
        order = [preferred]
        for name in self._PROVIDER_CLASSES:
            if name != preferred:
                order.append(name)
        return order


@lru_cache
def get_provider_router() -> ProviderRouter:
    """Return a cached ProviderRouter instance."""
    return ProviderRouter()
