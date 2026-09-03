"""LLM Gateway — provider-agnostic structured LLM access for CareerOS."""

from .gateway import LLMGateway, get_llm_gateway
from .router import ProviderRouter, get_provider_router
from .types import (
    LLMProvider,
    LLMTask,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    LLMProviderError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMQuotaExhaustedError,
    LLMProviderUnavailableError,
    LLMTimeoutError,
    LLMInvalidRequestError,
    StructuredSuggestion,
    ResumeSectionSuggestion,
)

__all__ = [
    "LLMGateway",
    "get_llm_gateway",
    "ProviderRouter",
    "get_provider_router",
    "LLMProvider",
    "LLMTask",
    "LLMRequest",
    "LLMResponse",
    "LLMUsage",
    "LLMProviderError",
    "LLMAuthenticationError",
    "LLMRateLimitError",
    "LLMQuotaExhaustedError",
    "LLMProviderUnavailableError",
    "LLMTimeoutError",
    "LLMInvalidRequestError",
    "StructuredSuggestion",
    "ResumeSectionSuggestion",
]
