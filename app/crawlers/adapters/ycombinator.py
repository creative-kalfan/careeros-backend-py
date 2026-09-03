"""Y Combinator Jobs adapter.

Fetches public job postings from YC's Work at a Startup board at
``https://www.ycombinator.com/jobs`` and normalizes them into
:CrawledJob`` objects that feed into the existing ingestion pipeline.

Note: This scraper reads the public HTML page. If YC changes their page
structure, the parser may need updating. No login or API key is required.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import httpx
from parsel import Selector

from app.crawlers.models import CrawledJob


YC_JOBS_URL = "https://www.ycombinator.com/jobs"


# Deterministic ID hashing: FNV-1a 32-bit hash (stable across processes).
# Used so that YC job identity is consistent across crawls and workers.
def _fnv1a_32(value: str) -> str:
    """Return a deterministic 32-bit FNV-1a hash hex string."""
    h = 0x811c9dc5
    for ch in value:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
        h %= 2**32
    return format(h, "08x")


def _extract_text(selector: Selector, *xpaths: str) -> str:
    """Extract the first non-empty text from given XPath expressions."""
    for xpath in xpaths:
        text = selector.xpath(xpath).get()
        if text and text.strip():
            return text.strip()
    return ""


def _extract_attr(selector: Selector, *xpaths: str) -> Optional[str]:
    """Extract the first non-empty attribute value from given XPath expressions."""
    for xpath in xpaths:
        val = selector.xpath(xpath).get()
        if val and val.strip():
            return val.strip()
    return None


def _normalize_location(raw: Optional[str]) -> Optional[str]:
    """Lightly normalize a location string; return None when empty."""
    if not raw:
        return None
    text = raw.strip()
    return text if text else None


def _extract_skills(text: str) -> list[str]:
    """Very light skill tokenisation for YC jobs (best-effort only)."""
    if not text:
        return []
    lowered = text.lower()
    common = {
        "python", "javascript", "typescript", "react", "next.js", "node",
        "java", "go", "ruby", "rust", "php", "sql", "postgres", "postgresql",
        "aws", "docker", "kubernetes", "graphql", "rest", "api", "tensorflow",
        "pytorch", "machine learning", "data science", "data analysis",
        "figma", "ui", "ux", "product", "project management",
    }
    found = [s for s in common if s in lowered]
    # Preserve order of appearance in the original text (deduped)
    seen: set[str] = set()
    ordered: list[str] = []
    for token in re.findall(r"[a-zA-Z+#]+", text):
        t = token.lower()
        if t in common and t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered


def _deterministic_external_id(apply_url: Optional[str], title: str, company: str) -> str:
    """Create a stable external job ID from available YC fields.

    Falls back to a hash of title+company when apply_url is unavailable.
    """
    if apply_url:
        return _fnv1a_32(apply_url)
    return _fnv1a_32(title + company)


class YCAdapter:
    """Fetch and normalize jobs from Y Combinator's public jobs page."""

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self._client = client

    async def __aenter__(self) -> "YCAdapter":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=10.0),
            )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def discover_jobs(self) -> list[CrawledJob]:
        """Scrape YC jobs page and return a list of normalised CrawledJob objects."""
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=10.0),
        )
        owned = self._client is None
        try:
            response = await client.get(YC_JOBS_URL)
            if response.status_code != 200:
                return []
            selector = Selector(text=response.text)

            jobs: list[CrawledJob] = []

            # 1. Primary: Extract from company job links (/companies/<slug>/jobs/<slug>)
            job_links = selector.xpath("//a[contains(@href, '/companies/') and contains(@href, '/jobs/')]")
            seen_urls: set[str] = set()

            for a in job_links[:50]:
                try:
                    href = a.xpath("@href").get()
                    if not href or href in seen_urls:
                        continue
                    seen_urls.add(href)

                    title = "".join(a.xpath(".//text()").getall()).strip()
                    if not title:
                        continue

                    apply_url = href if href.startswith("http") else f"https://www.ycombinator.com{href}"

                    company = ""
                    parts = href.strip("/").split("/")
                    if len(parts) >= 2 and parts[0] == "companies":
                        company_slug = parts[1]
                        company_links = selector.xpath(
                            f"//a[contains(@href, '/companies/{company_slug}') and not(contains(@href, '/jobs/'))]"
                        )
                        if company_links:
                            company_raw = "".join(company_links[0].xpath(".//text()").getall()).strip()
                            company = company_raw.split("(")[0].strip() if company_raw else company_slug.replace("-", " ").title()
                        if not company:
                            company = company_slug.replace("-", " ").title()

                    if not company:
                        company = "Y Combinator startup"

                    parent = a.xpath("ancestor::li | ancestor::div[contains(@class, 'flex') or contains(@class, 'block')][2]")
                    full_context = " ".join(t.strip() for t in parent.xpath(".//text()").getall() if t.strip()) if parent else title

                    employment_type = None
                    for et in ("Full-time", "Part-time", "Contract", "Internship"):
                        if et.lower() in full_context.lower():
                            employment_type = et
                            break

                    location = None
                    if "remote" in full_context.lower():
                        location = "Remote"

                    skills = _extract_skills(title + " " + full_context)
                    external_job_id = _deterministic_external_id(apply_url, title, company)

                    crawled = CrawledJob(
                        title=title,
                        company=company,
                        description=full_context or title,
                        location=location,
                        employment_type=employment_type,
                        apply_url=apply_url,
                        skills=skills,
                        external_job_id=external_job_id,
                        source_platform="ycombinator",
                        raw={"source": "ycombinator", "title": title, "company": company, "apply_url": apply_url},
                    )
                    jobs.append(crawled)
                except Exception:
                    continue

            # 2. Fallback: Card-based extraction if link extraction yielded nothing
            if not jobs:
                for job_sel in selector.xpath(
                    "//div[contains(@class, 'css-1')] | //article"
                )[:50]:
                    try:
                        title = _extract_text(
                            job_sel,
                            ".//h3//text()",
                            ".//h4//text()",
                            ".//a//h3//text()",
                            ".//a//h4//text()",
                        )
                        if not title:
                            continue

                        company = _extract_text(
                            job_sel,
                            ".//div[contains(@class, 'css-')]//text()",
                            ".//a//div//text()",
                        ) or "Y Combinator startup"

                        location = _extract_text(
                            job_sel,
                            ".//span[contains(@class, 'css-')]//text()",
                            ".//div//text()[contains(., 'Remote') or contains(., 'Location')]",
                        ) or None
                        location = _normalize_location(location)

                        apply_url = _extract_attr(
                            job_sel,
                            ".//a[@target='_blank']/@href",
                            ".//a[contains(@class, 'css-')]/@href",
                        )
                        if apply_url and not apply_url.startswith("http"):
                            apply_url = "https://www.ycombinator.com" + apply_url

                        employment_type = _extract_text(
                            job_sel,
                            ".//div[contains(., 'Full-time') or contains(., 'Part-time') or "
                            "contains(., 'Contract') or contains(., 'Internship')]//text()",
                        ) or None

                        description = title + " " + _extract_text(job_sel, ".//p//text()") or ""
                        skills = _extract_skills(title + " " + description)
                        external_job_id = _deterministic_external_id(apply_url, title, company)

                        crawled = CrawledJob(
                            title=title,
                            company=company,
                            description=description,
                            location=location,
                            employment_type=employment_type,
                            apply_url=apply_url,
                            skills=skills,
                            external_job_id=external_job_id,
                            source_platform="ycombinator",
                            raw={"source": "ycombinator", "title": title, "company": company},
                        )
                        jobs.append(crawled)
                    except Exception:
                        continue

            return jobs
        except Exception as e:
            print(f"Error in YCAdapter.discover_jobs: {e}")
            return []
        finally:
            if owned and self._client is not None:
                await self._client.aclose()


async def ingest_yc_jobs() -> dict[str, int]:
    """Convenience wrapper kept for the ARQ worker's existing import.

    Delegates entirely to ``JobIngestionService.ingest_ycombinator_jobs()``
    so there is exactly ONE canonical ingestion path for all sources:

        YC adapter
        → JobService.normalize_and_classify()
        → JobRepository.upsert_jobs()
        → stale deactivation (worker)
        → JobIngested event (worker)
    """
    from app.services.jobs.job_ingestion_service import JobIngestionService

    return await JobIngestionService().ingest_ycombinator_jobs()