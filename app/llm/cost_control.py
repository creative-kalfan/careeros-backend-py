"""LLM Cost Control: Caching, User daily quotas, and Usage Ledger."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

from app.db.supabase import get_service_client

logger = logging.getLogger(__name__)

# In-memory LRU / TTL cache for LLM responses
_RESPONSE_CACHE: dict[str, tuple[str, float]] = {}


def compute_llm_cache_key(
    evidence_hash: str,
    jd_hash: str,
    prompt_version: str,
    model: str,
) -> str:
    """Generate deterministic cache key for LLM suggestions."""
    raw = f"{evidence_hash}:{jd_hash}:{prompt_version}:{model}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class LLMCostController:
    """Manages LLM usage limits, response caching, and usage tracking."""

    @classmethod
    def get_cached_response(cls, cache_key: str) -> Optional[str]:
        return _RESPONSE_CACHE.get(cache_key, (None, 0))[0]

    @classmethod
    def set_cached_response(cls, cache_key: str, response_text: str) -> None:
        import time
        if len(_RESPONSE_CACHE) > 5000:
            _RESPONSE_CACHE.clear()
        _RESPONSE_CACHE[cache_key] = (response_text, time.time())

    @classmethod
    def check_user_daily_quota(
        cls,
        user_id: str,
        daily_limit_usd: float = 2.0,
    ) -> bool:
        """Check if user has exceeded their daily LLM quota."""
        try:
            client = get_service_client()
            # Simple probe check
            res = (
                client.table("llm_usage")
                .select("cost_estimate_usd")
                .eq("user_id", user_id)
                .gte("created_at", "now() - interval '24 hours'")
                .execute()
            )
            rows = getattr(res, "data", None) or []
            total = sum(float(r.get("cost_estimate_usd") or 0) for r in rows)
            return total < daily_limit_usd
        except Exception:
            return True  # Fail open if table not present

    @classmethod
    def record_usage(
        cls,
        user_id: Optional[str],
        feature: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
    ) -> None:
        """Record usage row in llm_usage table."""
        try:
            client = get_service_client()
            client.table("llm_usage").insert({
                "user_id": user_id,
                "feature": feature,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_estimate_usd": cost_usd,
            }).execute()
        except Exception as exc:
            logger.warning("Failed to record LLM usage ledger (non-blocking): %s", exc)
