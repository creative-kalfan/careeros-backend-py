"""Job service: normalization and classification of crawled jobs."""

from __future__ import annotations

from typing import Optional

from app.crawlers.models import CrawledJob
from app.models.job import NormalizedJob
from app.parsing.role_classifier import classify


class JobService:
    """Normalizes and classifies crawled jobs into the CareerOS model."""

    def normalize_job(self, crawled: CrawledJob) -> NormalizedJob:
        """Convert a crawled job into the normalized CareerOS model."""
        return NormalizedJob(
            external_job_id=crawled.external_job_id,
            source_platform=crawled.source_platform,
            title=crawled.title,
            company=crawled.company,
            description=crawled.description,
            location=crawled.location,
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