"""Embedding provider abstraction for semantic retrieval.

Providers supported:
  - GeminiProvider (google-gemini: text-embedding-004)
  - MistralProvider (mistral: mistral-embed)
  - OpenRouterProvider (openrouter embedding endpoints)
  - Stub / Mock provider with clear error when unconfigured.
Fail-open policy: If provider is unconfigured or raises, callers fail open to keyword search.
"""

from __future__ import annotations

import abc
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class BaseEmbeddingProvider(abc.ABC):
    """Abstract base class for vector embedding providers."""

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """Return True if required API credentials exist."""
        pass

    @abc.abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of text strings into vector floats."""
        pass

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string."""
        results = await self.embed_texts([text])
        return results[0] if results else []


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """Google Gemini text-embedding-004 provider."""

    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.llm_gemini_api_key
        self._model = settings.embedding_model or "text-embedding-004"

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.is_configured():
            raise RuntimeError("Gemini embedding provider is not configured (missing GOOGLE_GEMINI_API_KEY)")
        if not texts:
            return []

        url = f"{self._BASE_URL}/models/{self._model}:batchEmbedContents?key={self._api_key}"
        requests = [
            {"model": f"models/{self._model}", "content": {"parts": [{"text": t}]}}
            for t in texts
        ]

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(url, json={"requests": requests})
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini embed API error ({resp.status_code}): {resp.text}")
            data = resp.json()
            embeddings = data.get("embeddings", [])
            return [e.get("values", []) for e in embeddings]


class MistralEmbeddingProvider(BaseEmbeddingProvider):
    """Mistral AI mistral-embed provider."""

    _BASE_URL = "https://api.mistral.ai/v1/embeddings"

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.llm_mistral_api_key
        self._model = settings.embedding_model if "mistral" in settings.embedding_model else "mistral-embed"

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.is_configured():
            raise RuntimeError("Mistral embedding provider is not configured (missing MISTRAL_API_KEY)")
        if not texts:
            return []

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "input": texts,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(self._BASE_URL, json=payload, headers=headers)
            if resp.status_code != 200:
                raise RuntimeError(f"Mistral embed API error ({resp.status_code}): {resp.text}")
            data = resp.json()
            items = data.get("data", [])
            items.sort(key=lambda x: x.get("index", 0))
            return [item.get("embedding", []) for item in items]


class NullEmbeddingProvider(BaseEmbeddingProvider):
    """Fallback stub provider when no supported provider is enabled."""

    def is_configured(self) -> bool:
        return False

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("No embedding provider configured or available. Failing open to keyword retrieval.")


def get_embedding_provider() -> BaseEmbeddingProvider:
    """Resolve embedding provider instance based on settings."""
    settings = get_settings()
    provider_name = (settings.embedding_provider or "").lower()

    if provider_name in ("gemini", "google", "google-gemini"):
        prov = GeminiEmbeddingProvider()
        if prov.is_configured():
            return prov
    elif provider_name == "mistral":
        prov = MistralEmbeddingProvider()
        if prov.is_configured():
            return prov

    # Auto-fallback: check if any configured
    gemini = GeminiEmbeddingProvider()
    if gemini.is_configured():
        return gemini
    mistral = MistralEmbeddingProvider()
    if mistral.is_configured():
        return mistral

    return NullEmbeddingProvider()
