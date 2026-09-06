"""Bridge for calling async LLM coroutines from synchronous service code.

Several domain services (whole-resume tailoring, ATS semantic reasoning) are
synchronous but are invoked from ``async`` FastAPI route handlers, i.e. inside
a running event loop. Calling ``asyncio.run()`` there raises ``RuntimeError:
asyncio.run() cannot be called from a running event loop``, which callers
swallowed into a "deterministic fallback" — silently disabling every LLM call
made through the API (the model was never consulted; cross-domain tailoring
degenerated to zero-lift reordering).

This helper detects a running loop and offloads the coroutine to a dedicated
worker thread with its own loop instead, bounded by ``asyncio.wait_for`` so a
hung provider can never stall the request (or the event loop) indefinitely.
LLM failures still propagate to the caller, which keeps its existing
deterministic-fallback behavior.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def run_coro_sync(coro: Coroutine[None, None, T], timeout_seconds: float) -> T:
    """Run *coro* to completion from synchronous code.

    Works both outside an event loop (plain ``asyncio.run``) and inside one
    (offloaded to a single-use worker thread). The coroutine is wrapped in
    ``asyncio.wait_for`` so it is cancelled promptly at *timeout_seconds*;
    the outer ``future.result`` uses a small grace period for thread teardown.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    async def _bounded() -> T:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)

    pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="llm-bridge"
    )
    try:
        future = pool.submit(lambda: asyncio.run(_bounded()))
        try:
            return future.result(timeout=timeout_seconds + 5.0)
        except (concurrent.futures.TimeoutError, TimeoutError, asyncio.TimeoutError) as exc:
            # Typed error so existing ``except LLMProviderError`` handlers
            # degrade gracefully (deterministic fallback / "temporarily
            # unavailable") instead of surfacing a bare 500.
            from app.config import get_settings
            from app.llm.types import LLMProvider, LLMTimeoutError

            try:
                default_provider = LLMProvider(get_settings().llm_default_provider)
            except Exception:
                default_provider = LLMProvider.GROQ
            logger.warning(
                "LLM bridge exceeded %.1fs budget; falling back", timeout_seconds
            )
            raise LLMTimeoutError(
                f"LLM call timed out after {timeout_seconds}s",
                default_provider,
            ) from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
