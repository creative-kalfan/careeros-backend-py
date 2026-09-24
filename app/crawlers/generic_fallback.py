"""Generic career-page fallback routing + Firecrawl circuit breaker.

Routing policy (direct ATS adapters always win — this module only handles
the generic career-page case):

    generic career page → Crawl4AI → (on failure) Firecrawl → graceful failure

Firecrawl 429s previously produced a retry storm (attempt 1..4 per call,
repeated every crawl). The process-local circuit breaker below stops that:
a 429 opens the circuit, Firecrawl is skipped during cooldown, then a
single probe decides whether to close it. No Redis state — one worker
process is the only scope that needs it.

``monotonic`` is injectable so tests control time deterministically.
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Callable, Optional

from app.crawlers.models import CrawledJob

logger = logging.getLogger(__name__)


class ProviderOutcome(str, Enum):
    SUCCESS = "success"
    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    CONFIG = "config"
    PERMANENT = "permanent"


def classify_firecrawl_error(exc: BaseException) -> ProviderOutcome:
    """Map a Firecrawl failure to a provider outcome (no retries here)."""
    from app.crawlers.firecrawl_client import (
        FirecrawlAuthError,
        FirecrawlConfigurationError,
        FirecrawlRateLimitError,
    )

    if isinstance(exc, FirecrawlRateLimitError):
        return ProviderOutcome.RATE_LIMITED
    if "429" in exc.__class__.__name__ or "429" in str(exc):
        return ProviderOutcome.RATE_LIMITED
    if isinstance(exc, (FirecrawlConfigurationError, FirecrawlAuthError)):
        return ProviderOutcome.CONFIG
    return ProviderOutcome.TRANSIENT


def classify_crawl4ai_error(exc: BaseException) -> ProviderOutcome:
    """Map a Crawl4AI failure to a provider outcome."""
    from app.crawlers.adapters.crawl4ai import Crawl4AIConfigurationError

    if isinstance(exc, Crawl4AIConfigurationError):
        return ProviderOutcome.CONFIG
    return ProviderOutcome.TRANSIENT


class FirecrawlCircuitBreaker:
    """Process-local cooldown breaker for Firecrawl 429s.

    Closed (normal) → ``should_skip()`` False. A rate-limit record opens
    it until ``cooldown_until``; after that one probe is allowed through.
    Probe success closes it, another 429 extends the cooldown.
    """

    def __init__(
        self,
        cooldown_seconds: float = 300.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cooldown_seconds = float(cooldown_seconds)
        self._monotonic = monotonic
        self.cooldown_until: float = 0.0

    @property
    def is_open(self) -> bool:
        return self._monotonic() < self.cooldown_until

    def should_skip(self) -> bool:
        return self.is_open

    def record_success(self) -> None:
        self.cooldown_until = 0.0

    def record_rate_limited(self) -> None:
        now = self._monotonic()
        self.cooldown_until = max(self.cooldown_until, now) + self.cooldown_seconds
        logger.warning(
            "crawler provider=firecrawl state=rate_limited cooldown_until=%.1f cooldown_s=%.0f",
            self.cooldown_until, self.cooldown_seconds,
        )


# Process-wide singleton; resettable in tests via ``reset_firecrawl_breaker``.
_breaker: Optional[FirecrawlCircuitBreaker] = None


def get_firecrawl_breaker() -> FirecrawlCircuitBreaker:
    global _breaker
    if _breaker is None:
        from app.config import get_settings

        _breaker = FirecrawlCircuitBreaker(
            cooldown_seconds=float(get_settings().firecrawl_circuit_cooldown_seconds)
        )
    return _breaker


def reset_firecrawl_breaker(
    cooldown_seconds: float = 300.0,
    monotonic: Callable[[], float] = time.monotonic,
) -> FirecrawlCircuitBreaker:
    global _breaker
    _breaker = FirecrawlCircuitBreaker(cooldown_seconds, monotonic)
    return _breaker


async def crawl_generic_career_page(
    careers_url: str,
    company: Optional[str] = None,
    company_website: Optional[str] = None,
) -> tuple[list[CrawledJob], dict[str, Any]]:
    """Crawl one generic career page: Crawl4AI first, Firecrawl as fallback.

    Returns ``(jobs, meta)`` where meta carries provider, fallback, counts,
    and durations for structured logging. Never raises for provider
    failures — an empty job list plus meta describes the failure.
    """
    from app.config import get_settings

    settings = get_settings()
    start = time.monotonic()
    meta: dict[str, Any] = {
        "provider": None, "fallback": None, "jobs": 0,
        "crawl4ai_outcome": None, "firecrawl_outcome": None,
        "firecrawl_skipped_by_circuit": False,
    }

    if settings.crawl4ai_enabled:
        from app.crawlers.adapters.crawl4ai import Crawl4AIAdapter

        try:
            jobs = await Crawl4AIAdapter(
                careers_url, company=company, company_website=company_website
            ).discover_jobs()
            meta.update(provider="crawl4ai", crawl4ai_outcome="success", jobs=len(jobs))
            logger.info(
                "crawler provider=crawl4ai url=%s success=true jobs=%d duration_ms=%d",
                careers_url, len(jobs), int((time.monotonic() - start) * 1000),
            )
            return jobs, meta
        except Exception as exc:
            outcome = classify_crawl4ai_error(exc)
            meta["crawl4ai_outcome"] = outcome.value
            logger.warning(
                "crawler provider=crawl4ai url=%s success=false error=%s outcome=%s",
                careers_url, exc.__class__.__name__, outcome.value,
            )
            if outcome == ProviderOutcome.CONFIG:
                logger.warning(
                    "crawler fallback from=crawl4ai to=firecrawl url=%s reason=config-disabled",
                    careers_url,
                )
            else:
                logger.warning(
                    "crawler fallback from=crawl4ai to=firecrawl url=%s reason=%s",
                    careers_url, exc.__class__.__name__,
                )
    else:
        meta["crawl4ai_outcome"] = "disabled"

    breaker = get_firecrawl_breaker()
    if breaker.should_skip():
        meta["firecrawl_skipped_by_circuit"] = True
        logger.warning(
            "crawler provider=firecrawl url=%s skipped=true reason=circuit-open cooldown_until=%.1f",
            careers_url, breaker.cooldown_until,
        )
        return [], meta

    from app.crawlers.adapters.firecrawl import FirecrawlAdapter

    try:
        jobs = await FirecrawlAdapter(
            careers_url, company=company, company_website=company_website
        ).discover_jobs()
        breaker.record_success()
        meta.update(provider="firecrawl", fallback="crawl4ai",
                    firecrawl_outcome="success", jobs=len(jobs))
        logger.info(
            "crawler provider=firecrawl url=%s success=true jobs=%d duration_ms=%d fallback_from=crawl4ai",
            careers_url, len(jobs), int((time.monotonic() - start) * 1000),
        )
        return jobs, meta
    except Exception as exc:
        outcome = classify_firecrawl_error(exc)
        meta["firecrawl_outcome"] = outcome.value
        if outcome == ProviderOutcome.RATE_LIMITED:
            breaker.record_rate_limited()
        logger.warning(
            "crawler provider=firecrawl url=%s success=false error=%s outcome=%s",
            careers_url, exc.__class__.__name__, outcome.value,
        )
        return [], meta
