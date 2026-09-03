"""Mistral LLM provider implementation."""

from __future__ import annotations

import time
import uuid

import httpx
from app.config import get_settings
from app.llm.providers.base import BaseLLMProvider
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
    LLMTimeoutError,
    LLMUsage,
)


class MistralProvider(BaseLLMProvider):
    provider = LLMProvider.MISTRAL
    _BASE_URL = "https://api.mistral.ai/v1"

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.llm_mistral_api_key
        self._default_model = settings.llm_mistral_model

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._default_model
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": [],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        if request.system_instruction:
            payload["messages"].append({"role": "system", "content": request.system_instruction})
        payload["messages"].append({"role": "user", "content": request.prompt})

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.post(
                    f"{self._BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException:
            raise LLMTimeoutError("Mistral request timed out", self.provider)
        except httpx.HTTPError as exc:
            raise LLMProviderUnavailableError(
                f"Mistral network error: {exc}", self.provider
            ) from exc

        latency_ms = (time.perf_counter() - start) * 1000.0

        if response.status_code == 401:
            raise LLMAuthenticationError("Invalid Mistral API key", self.provider)
        if response.status_code == 429:
            raise LLMRateLimitError("Mistral rate limit exceeded", self.provider)
        if response.status_code == 402:
            raise LLMQuotaExhaustedError("Mistral quota exhausted", self.provider)
        if response.status_code == 400:
            raise LLMInvalidRequestError("Invalid Mistral request", self.provider, response.text)
        if response.status_code == 404:
            raise LLMInvalidRequestError(f"Mistral model not found: {model}", self.provider)
        if response.status_code >= 500:
            raise LLMProviderUnavailableError("Mistral service error", self.provider)

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMProviderError("Invalid Mistral response", self.provider) from exc

        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
            finish_reason = choice.get("finish_reason")
            usage_data = data.get("usage", {})
            usage = LLMUsage(
                input_tokens=usage_data.get("prompt_tokens"),
                output_tokens=usage_data.get("completion_tokens"),
                total_tokens=usage_data.get("total_tokens"),
                raw=usage_data,
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("Malformed Mistral response", self.provider) from exc

        return LLMResponse(
            provider=self.provider,
            model=model,
            content=content,
            usage=usage,
            request_id=data.get("id"),
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            raw=data,
        )
