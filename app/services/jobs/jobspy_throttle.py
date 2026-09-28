"""JobSpy provider-aware throttling: delays, circuit breaking, result caching.

Rate limiting is the load-bearing safety property of the JobSpy expansion:
the Firecrawl 429 problem must not be replaced by a JobSpy 429 problem.
All state here is process-local (same scope as the Firecrawl circuit
breaker in ``app.crawlers.generic_fallback`` — one ARQ worker process is
the only scope that needs it). ``monotonic`` / ``sleep`` are injectable so
tests control time deterministically.

Policy:

- Bounded concurrency is enforced by the caller via ``asyncio.Semaphore``
  (``JOBSPY_MAX_CONCURRENT``); this module enforces per-provider minimum
  delays between searches.
- LinkedIn is scheduled conservatively (longer delay) because it is more
  rate-limit sensitive; Indeed carries the broad recurring load.
- 429s are never retried aggressively: a rate-limit record applies
  exponential backoff to that provider and the current search is dropped
  (recorded, not raised). Other providers continue unaffected.
- A provider that fails repeatedly (``JOBSPY_CIRCUIT_THRESHOLD``
  consecutive failures) opens its circuit for
  ``JOBSPY_PROVIDER_COOLDOWN_SECONDS``; probes resume automatically after
  the cooldown.
- Identical query/location/provider/freshness combinations are skipped
  inside ``JOBSPY_SEARCH_CACHE_TTL_HOURS`` (freshness-aware skipping).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def is_rate_limit_error(exc: BaseException) -> bool:
    """True when an exception looks like a provider 429 / rate limit."""
    haystack = f"{exc.__class__.__name__} {exc}".lower()
    return (
        "429" in haystack
        or "rate limit" in haystack
        or "ratelimit" in haystack
        or "too many requests" in haystack
        or "http 406" in haystack  # Naukri bot-gate behaves like a throttle
    )


@dataclass
class ProviderOutcomeRecord:
    """Per-search provider outcome (no credentials, ever)."""

    provider: str
    query_family: str
    location: str
    requested: int
    discovered: int = 0
    valid: int = 0
    elapsed_ms: int = 0
    outcome: str = "success"
    rate_limited: bool = False


class ProviderThrottle:
    """Enforces a minimum delay between consecutive searches per provider."""

    def __init__(
        self,
        default_delay_seconds: float = 5.0,
        per_provider_delay_seconds: Optional[dict[str, float]] = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.default_delay = max(0.0, float(default_delay_seconds or 0.0))
        self.per_provider = {
            str(k).lower(): max(0.0, float(v))
            for k, v in (per_provider_delay_seconds or {}).items()
        }
        self._monotonic = monotonic
        self._sleep = sleep
        self._last_run: dict[str, float] = {}

    def delay_for(self, provider: str) -> float:
        """Configured minimum delay for a provider (seconds)."""
        return self.per_provider.get(str(provider or "").lower(), self.default_delay)

    async def wait(self, provider: str) -> float:
        """Sleep until the provider's minimum delay has elapsed.

        Returns the seconds actually waited (0 when no wait was needed).
        """
        key = str(provider or "").lower()
        delay = self.delay_for(key)
        last = self._last_run.get(key)
        now = self._monotonic()
        remaining = delay - (now - last) if last is not None else 0.0
        waited = 0.0
        if remaining > 0:
            await self._sleep(remaining)
            waited = remaining
        return waited

    def record(self, provider: str) -> None:
        """Stamp a search attempt for a provider (call after each attempt)."""
        self._last_run[str(provider or "").lower()] = self._monotonic()


class JobSpyCircuitBreaker:
    """Per-provider circuit breaker with exponential backoff for 429s."""

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 600.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = max(1, int(failure_threshold or 1))
        self.cooldown_seconds = max(1.0, float(cooldown_seconds or 1.0))
        self._monotonic = monotonic
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def should_skip(self, provider: str) -> bool:
        """True while the provider's circuit is open (log circuit_open=true)."""
        return self._monotonic() < self._open_until.get(str(provider or "").lower(), 0.0)

    @property
    def open_providers(self) -> list[str]:
        """Providers currently under an open circuit (for logging/tests)."""
        now = self._monotonic()
        return [p for p, until in self._open_until.items() if now < until]

    def record_success(self, provider: str) -> None:
        """Close the circuit and reset the failure count."""
        key = str(provider or "").lower()
        self._failures[key] = 0
        self._open_until.pop(key, None)

    def record_failure(self, provider: str) -> None:
        """Record a transient failure; open the circuit at the threshold."""
        key = str(provider or "").lower()
        failures = self._failures.get(key, 0) + 1
        self._failures[key] = failures
        if failures >= self.threshold:
            self._open_until[key] = self._monotonic() + self.cooldown_seconds
            logger.warning(
                "jobspy circuit_open=true provider=%s failures=%d cooldown_s=%.0f",
                key, failures, self.cooldown_seconds,
            )

    def record_rate_limited(self, provider: str) -> None:
        """Record a 429: exponential backoff, never an aggressive retry.

        Backoff doubles per consecutive rate-limit (capped at 3 doublings);
        the circuit opens at the same failure threshold as transient errors.
        """
        key = str(provider or "").lower()
        failures = self._failures.get(key, 0) + 1
        self._failures[key] = failures
        doublings = min(max(failures - 1, 0), 3)
        backoff = self.cooldown_seconds * (2**doublings)
        self._open_until[key] = max(
            self._open_until.get(key, 0.0), self._monotonic() + backoff
        )
        logger.warning(
            "jobspy rate_limited=true provider=%s failures=%d backoff_s=%.0f",
            key, failures, backoff,
        )

    def failure_count(self, provider: str) -> int:
        """Consecutive failure count for a provider (for tests/metrics)."""
        return self._failures.get(str(provider or "").lower(), 0)


class SearchCache:
    """Freshness-aware skip log for identical searches.

    Keyed on (site, query, location, hours_old); entries live for the
    configured TTL so the same combination is never re-requested inside
    the freshness window.
    """

    def __init__(
        self,
        ttl_seconds: float = 24 * 3600,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = max(1.0, float(ttl_seconds or 1.0))
        self._monotonic = monotonic
        self._stamps: dict[str, float] = {}

    @staticmethod
    def key(site: str, query: str, location: str, hours_old: Optional[int]) -> str:
        """Deterministic cache key (lowercased, whitespace-collapsed)."""
        def _norm(value: Any) -> str:
            return " ".join(str(value or "").strip().lower().split())
        return f"{_norm(site)}|{_norm(query)}|{_norm(location)}|{hours_old!s}"

    def is_fresh(self, key: str) -> bool:
        """True when the key was searched inside the TTL window."""
        stamped = self._stamps.get(key)
        if stamped is None:
            return False
        if self._monotonic() - stamped >= self.ttl_seconds:
            self._stamps.pop(key, None)
            return False
        return True

    def mark(self, key: str) -> None:
        """Record a successful search for the key."""
        self._stamps[key] = self._monotonic()

    def __len__(self) -> int:
        return len(self._stamps)


# ---------------------------------------------------------------------------
# Process-local singletons (one ARQ worker scope, mirroring the Firecrawl
# breaker). Injectable overrides keep orchestration independently testable.
# ---------------------------------------------------------------------------

_throttle: Optional[ProviderThrottle] = None
_breaker: Optional[JobSpyCircuitBreaker] = None
_cache: Optional[SearchCache] = None


def get_jobspy_throttle() -> ProviderThrottle:
    """Process-local throttle built from settings (lazy singleton)."""
    global _throttle
    if _throttle is None:
        from app.config import get_settings

        settings = get_settings()
        _throttle = ProviderThrottle(
            default_delay_seconds=float(
                getattr(settings, "jobspy_per_provider_delay_seconds", 5.0)
            ),
            per_provider_delay_seconds={
                "linkedin": float(
                    getattr(settings, "jobspy_linkedin_delay_seconds", 15.0)
                )
            },
        )
    return _throttle


def get_jobspy_breaker() -> JobSpyCircuitBreaker:
    """Process-local circuit breaker built from settings (lazy singleton)."""
    global _breaker
    if _breaker is None:
        from app.config import get_settings

        settings = get_settings()
        _breaker = JobSpyCircuitBreaker(
            failure_threshold=int(getattr(settings, "jobspy_circuit_threshold", 3)),
            cooldown_seconds=float(
                getattr(settings, "jobspy_provider_cooldown_seconds", 600.0)
            ),
        )
    return _breaker


def get_jobspy_cache() -> SearchCache:
    """Process-local search cache built from settings (lazy singleton)."""
    global _cache
    if _cache is None:
        from app.config import get_settings

        settings = get_settings()
        _cache = SearchCache(
            ttl_seconds=float(
                getattr(settings, "jobspy_search_cache_ttl_hours", 24.0)
            )
            * 3600.0,
        )
    return _cache


def reset_jobspy_throttle_state() -> None:
    """Drop process-local throttle/breaker/cache singletons (tests only)."""
    global _throttle, _breaker, _cache
    _throttle = None
    _breaker = None
    _cache = None
