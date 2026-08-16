"""Base class for ATS adapters.

Mirrors ``BaseCrawler.ts``'s shared interface. Every adapter implements
``discover_jobs()`` the same way: given a company slug, returns a list of
normalized :class:`CrawledJob`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.crawlers.models import CrawledJob


class BaseCrawler(ABC):
    """Abstract base for ATS adapters."""

    @abstractmethod
    async def discover_jobs(self) -> list[CrawledJob]:
        """Fetch and normalize job postings for this ATS."""
        raise NotImplementedError