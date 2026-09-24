"""Shared deterministic parsing for generic company career pages.

Extracted from :mod:`app.crawlers.adapters.firecrawl` so the Crawl4AI
adapter reuses the exact same heuristics instead of duplicating them.
No LLM, no network — pure HTML → :class:`CrawledJob` parsing.

The ``retrieval`` / ``source_platform`` labels are parameters because the
retrieval mechanism (crawl4ai vs firecrawl) and the source family are
different concepts; tiers are still decided by
:mod:`app.crawlers.source_quality` from the URL domain.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from parsel import Selector

from app.crawlers.models import CrawledJob
from app.crawlers.source_quality import (
    detect_ats_provider,
    is_aggregator_url,
    is_official_career_url,
    stable_hash,
)

logger = logging.getLogger(__name__)

# Path patterns that look like individual job postings.
_JOB_PATH_PATTERN = re.compile(
    r"/(?:job|jobs|career|careers|opening|position|requisition|role|vacancy)"
    r"|-[0-9]{4,}$|/\d{4,}(?:/|$)",
    re.IGNORECASE,
)

# Path patterns we never crawl (blogs, marketing, docs...).
_EXCLUDED_PATH_PATTERN = re.compile(
    r"/(?:blog|press|news|docs?|help|pricing|about|contact|legal|privacy|terms)"
    r"|\.pdf$|\.png$|\.jpg$|\.svg$|\.css$|\.js$",
    re.IGNORECASE,
)

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"

_POSTED_PATTERN = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTHS})[a-z]*\s+(\d{{4}})\b"
    rf"|({_MONTHS})[a-z]*\s+(\d{{1,2}}),?\s+(\d{{4}})",
    re.IGNORECASE,
)


def _looks_like_job_url(url: str) -> bool:
    """Heuristic filter for candidate job-detail URLs."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    path = parsed.path or "/"
    if _EXCLUDED_PATH_PATTERN.search(path):
        return False
    return bool(_JOB_PATH_PATTERN.search(path))


def _extract_posted_date(text: str) -> Optional[str]:
    """Best-effort ISO date extraction ('12 Mar 2024' / 'Mar 12, 2024').

    Returns None when no reliable date is present — never fabricated.
    """
    if not text:
        return None
    match = _POSTED_PATTERN.search(text[:4000])
    if not match:
        return None
    month_map = {m: i + 1 for i, m in enumerate(_MONTHS.split("|"))}
    groups = match.groups()
    try:
        if groups[0]:  # 12 Mar 2024
            day, mon, year = int(groups[0]), month_map[groups[1].lower()[:3]], int(groups[2])
        else:  # Mar 12, 2024
            mon, day, year = month_map[groups[3].lower()[:3]], int(groups[4]), int(groups[5])
        return datetime(year, mon, day, tzinfo=timezone.utc).isoformat()
    except (KeyError, ValueError):
        return None


def _company_identity_from_html(html: str, page_url: str) -> dict[str, Any]:
    """Extract company identity/logo metadata from a career page.

    Priority: official logo (og:image on the official domain) → favicon.
    No logos are generated; only real assets found on the page are reported.
    """
    identity: dict[str, Any] = {}
    if not html:
        return identity
    sel = Selector(text=html)
    site_name = sel.xpath("//meta[@property='og:site-name']/@content").get()
    if site_name and site_name.strip():
        identity["company_name"] = site_name.strip()
    og_image = sel.xpath("//meta[@property='og:image']/@content").get()
    if og_image and og_image.strip():
        identity["logo_url"] = urljoin(page_url, og_image.strip())
    favicon = sel.xpath(
        "//link[@rel='icon' or @rel='shortcut icon' or @rel='apple-touch-icon']/@href"
    ).get()
    if favicon and favicon.strip():
        identity["favicon_url"] = urljoin(page_url, favicon.strip())
    return identity


def parse_career_job_page(
    url: str,
    html: str,
    *,
    company: Optional[str] = None,
    careers_url: Optional[str] = None,
    company_website: Optional[str] = None,
    retrieval: str = "firecrawl",
    source_platform: str = "firecrawl",
) -> Optional[CrawledJob]:
    """Parse one job page into a CrawledJob (None when not a job page)."""
    if not html:
        return None
    sel = Selector(text=html)
    title = None
    for xpath in ("//h1//text()", "//h2//text()", "//title//text()"):
        for value in sel.xpath(xpath).getall():
            value = (value or "").strip()
            if len(value) >= 3:
                title = value
                break
        if title:
            break
    if not title:
        return None

    location = None
    for token in sel.xpath(
        "//div[contains(., 'Location')]//text() | //span[contains(@class,'location')]//text()"
    ).getall():
        token = (token or "").strip()
        if not token or len(token) > 80:
            continue
        if token.lower().startswith("location"):
            remainder = token.split(":", 1)[-1].strip()
            if remainder:
                location = remainder
                break
            continue  # bare 'Location' label
        if "Location" not in token:
            location = token
            break

    description = " ".join(
        t.strip() for t in sel.xpath("//p//text()").getall() if t and t.strip()
    )[:6000] or title

    employment_type = None
    for label in ("Full-time", "Part-time", "Contract", "Internship", "Temporary"):
        if label.lower() in (title + " " + description).lower():
            employment_type = label
            break

    remote = "remote" in (title + " " + (location or "")).lower() or None
    posted_date = _extract_posted_date(description)

    from app.services.jobs.mass_hiring_detector import detect_mass_hiring

    mass_info = detect_mass_hiring(
        title=title,
        description=description,
        url=url,
        location=location or "",
    )

    raw: dict[str, Any] = {
        "retrieval": retrieval,
        "careers_url": careers_url,
        "company_website": company_website,
        "canonical_url": url,
        "discovered_url": url,
        "source_domain": urlparse(url).hostname,
        "official_candidate": is_official_career_url(url, company, careers_url),
        "ats_provider": detect_ats_provider(url),
        "aggregator": is_aggregator_url(url),
        "first_discovered_at": datetime.now(timezone.utc).isoformat(),
        "mass_hiring": mass_info.get("confidence"),
        "mass_hiring_status": mass_info.get("status"),
        "mass_hiring_details": mass_info,
    }

    return CrawledJob(
        title=title,
        company=company or "",
        description=description,
        location=location,
        employment_type=employment_type,
        remote=remote,
        posted_date=posted_date,
        apply_url=url,
        skills=[],
        external_job_id=stable_hash(url),
        source_platform=source_platform,
        raw=raw,
    )
