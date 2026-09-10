"""Job service: normalization and classification of crawled jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from app.crawlers.models import CrawledJob
from app.crawlers.source_quality import canonicalize_url
from app.models.job import NormalizedJob
from app.parsing.role_classifier import classify

# Deterministic India location aliases: provider spelling -> canonical label.
# Only these exact case-insensitive matches are rewritten; international and
# unknown locations pass through untouched. Original provider text is always
# preserved in CrawledJob.raw / NormalizedJob.raw for audit.
INDIA_LOCATION_ALIASES = {
    "bangalore": "Bengaluru, India",
    "bengaluru": "Bengaluru, India",
    "bombay": "Mumbai, India",
    "mumbai": "Mumbai, India",
    "madras": "Chennai, India",
    "chennai": "Chennai, India",
    "gurgaon": "Gurugram, India",
    "gurugram": "Gurugram, India",
    "delhi": "Delhi NCR, India",
    "new delhi": "Delhi NCR, India",
    "noida": "Noida, India",
    "hyderabad": "Hyderabad, India",
    "pune": "Pune, India",
    "kolkata": "Kolkata, India",
    "calcutta": "Kolkata, India",
    "ahmedabad": "Ahmedabad, India",
    "kochi": "Kochi, India",
    "cochin": "Kochi, India",
    "jaipur": "Jaipur, India",
    "chandigarh": "Chandigarh, India",
}

_VALID = "VALID"
_VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
_INVALID = "INVALID"
_STALE = "STALE"


def normalize_india_location(location: Optional[str]) -> Optional[str]:
    """Rewrite known Indian city aliases to canonical labels, else passthrough."""
    if not location or not isinstance(location, str):
        return location
    key = location.strip().lower().rstrip(",.")
    if key in INDIA_LOCATION_ALIASES:
        return INDIA_LOCATION_ALIASES[key]
    # "City, State"-style values: rewrite a known leading alias only.
    head = key.split(",")[0].strip()
    if head in INDIA_LOCATION_ALIASES:
        return INDIA_LOCATION_ALIASES[head]
    return location


def validate_job(job: NormalizedJob) -> tuple[str, list[str]]:
    """Classify a normalized job: VALID | VALID_WITH_WARNINGS | INVALID | STALE.

    Conservative: optional-field gaps warn, they never invalidate. Only a
    missing title, an unusable URL scheme, or error-page content invalidates.
    """
    reasons: list[str] = []
    if not (job.title or "").strip():
        return _INVALID, ["missing title"]
    url = job.apply_url or job.url or job.canonical_url
    if url:
        try:
            scheme = (urlparse(url).scheme or "").lower()
        except Exception:
            scheme = ""
        if scheme not in ("http", "https"):
            return _INVALID, ["unusable apply URL"]
    text = f"{job.title} {job.description or ''}".lower()
    if ("404" in text and "not found" in text) or "error loading job" in text:
        return _INVALID, ["error-page content"]
    if job.posted_date or job.posted_at:
        try:
            raw = job.posted_date or job.posted_at
            posted = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - posted).total_seconds() / 86400
            if age > 90:
                return _STALE, [f"posted {int(age)}d ago"]
        except Exception:
            reasons.append("unparseable posted date")
    if not (job.company or "").strip():
        reasons.append("missing company")
    if not (job.location or "").strip():
        reasons.append("missing location")
    if not (job.description or "").strip():
        reasons.append("missing description")
    if not (job.source_platform or "").strip():
        reasons.append("unknown source")
    if reasons:
        return _VALID_WITH_WARNINGS, reasons
    return _VALID, []


def needs_enrichment(job: NormalizedJob) -> bool:
    """True when a job is usable but too thin to rank well (Firecrawl trigger).

    Selective gate: only jobs WITH an apply_url and thin content qualify, so
    Firecrawl is event/need-driven, never a blanket crawl.
    """
    if not job.apply_url and not job.url:
        return False
    desc = (job.description or "").strip()
    if len(desc) < 200:
        return True
    if not job.skills and not job.requirements:
        return True
    return False


def merge_enrichment(base: NormalizedJob, enriched: NormalizedJob) -> NormalizedJob:
    """Fill gaps from enrichment without overwriting trusted structured data.

    Only None/empty base fields take the enriched value. High-confidence
    structured fields (title, company, apply_url, salary, posted dates) are
    never overwritten by scraped data.
    """
    protected = {"title", "company", "apply_url", "url", "salary", "salary_min",
                 "salary_max", "salary_currency", "posted_date", "posted_at",
                 "external_job_id", "source_platform"}
    data = base.model_dump()
    extra = enriched.model_dump()
    for key, value in extra.items():
        if key in protected or key == "raw":
            continue
        current = data.get(key)
        if (current is None or current == "" or current == []) and value not in (None, "", []):
            data[key] = value
    return NormalizedJob(**data)


class JobService:
    """Normalizes and classifies crawled jobs into the CareerOS model."""

    def normalize_job(self, crawled: CrawledJob) -> NormalizedJob:
        """Convert a crawled job into the normalized CareerOS model."""
        canonical = canonicalize_url(crawled.apply_url) or None
        return NormalizedJob(
            external_job_id=crawled.external_job_id,
            source_platform=crawled.source_platform,
            title=crawled.title,
            company=crawled.company,
            description=crawled.description,
            location=normalize_india_location(crawled.location),
            canonical_url=canonical,
            remote=crawled.remote,
            workplace_type=crawled.workplace_type,
            employment_type=crawled.employment_type,
            salary=crawled.salary,
            salary_currency=crawled.salary_currency,
            salary_min=crawled.salary_min,
            salary_max=crawled.salary_max,
            apply_url=crawled.apply_url,
            posted_date=crawled.posted_date,
            expires_date=crawled.expires_date,
            experience_level=crawled.experience_level,
            skills=crawled.skills,
            requirements=crawled.requirements,
            responsibilities=crawled.responsibilities,
            raw=crawled.raw,
        )

    def classify_job(self, job: NormalizedJob) -> NormalizedJob:
        """Classify a normalized job into a role category."""
        category = classify(job.title)
        job.role_category = category
        return job

    def normalize_and_classify(self, crawled: CrawledJob) -> NormalizedJob:
        """Normalize and classify a crawled job in one step."""
        normalized = self.normalize_job(crawled)
        return self.classify_job(normalized)