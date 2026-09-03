"""Google Gemini LLM provider implementation."""

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


class GeminiProvider(BaseLLMProvider):
    provider = LLMProvider.GOOGLE_GEMINI
    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.llm_gemini_api_key
        self._default_model = settings.llm_gemini_model

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._default_model
        url = f"{self._BASE_URL}/models/{model}:generateContent?key={self._api_key}"

        contents: list[dict[str, Any]] = []
        if request.system_instruction:
            contents.append({"role": "user", "parts": [{"text": request.system_instruction}]})
        contents.append({"role": "user", "parts": [{"text": request.prompt}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
        }

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException:
            raise LLMTimeoutError("Gemini request timed out", self.provider)
        except httpx.HTTPError as exc:
            raise LLMProviderUnavailableError(
                f"Gemini network error: {exc}", self.provider
            ) from exc

        latency_ms = (time.perf_counter() - start) * 1000.0

        if response.status_code == 400:
            raise LLMInvalidRequestError("Invalid Gemini request", self.provider, response.text)
        if response.status_code == 401:
            raise LLMAuthenticationError("Invalid Gemini API key", self.provider)
        if response.status_code == 403:
            raise LLMAuthenticationError("Gemini permission denied", self.provider)
        if response.status_code == 404:
            raise LLMInvalidRequestError(f"Gemini model not found: {model}", self.provider)
        if response.status_code == 429:
            raise LLMRateLimitError("Gemini rate limit exceeded", self.provider)
        if response.status_code == 503:
            raise LLMQuotaExhaustedError("Gemini quota exhausted", self.provider)
        if response.status_code >= 500:
            raise LLMProviderUnavailableError("Gemini service error", self.provider)

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMProviderError("Invalid Gemini response", self.provider) from exc

        try:
            candidates = data.get("candidates", [])
            content = candidates[0]["content"]["parts"][0]["text"]
            finish_reason = candidates[0].get("finishReason")
            usage_meta = data.get("usageMetadata", {})
            usage = LLMUsage(
                input_tokens=usage_meta.get("promptTokenCount"),
                output_tokens=usage_meta.get("candidatesTokenCount"),
                total_tokens=usage_meta.get("totalTokenCount"),
                raw=usage_meta,
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("Malformed Gemini response", self.provider) from exc

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
