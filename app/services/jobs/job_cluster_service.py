"""Service for deterministic clustering of duplicate job postings without merging."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Optional

from app.models.job import NormalizedJob
from app.repositories.job_cluster_repository import JobClusterRepository

logger = logging.getLogger(__name__)


def compute_deterministic_cluster_keys(job: NormalizedJob | dict[str, Any]) -> list[tuple[str, str]]:
    """Compute cluster keys and reasons for a job.
    
    Deterministic cluster keys:
      1. (canonical_url) -> identical canonical URL.
      2. (normalized_company + normalized_title + normalized_location + description_hash) -> content match.
    """
    keys: list[tuple[str, str]] = []

    # Helper getters
    def _get(field: str) -> str:
        if isinstance(job, dict):
            return str(job.get(field) or "").strip()
        return str(getattr(job, field, None) or "").strip()

    canonical_url = _get("canonical_url") or _get("url")
    if canonical_url and len(canonical_url) > 10:
        url_hash = hashlib.sha256(canonical_url.lower().encode()).hexdigest()[:24]
        keys.append((f"url:{url_hash}", "identical_canonical_url"))

    company = re.sub(r"[^a-z0-9]", "", _get("company").lower())
    title = re.sub(r"[^a-z0-9]", "", _get("title").lower())
    location = re.sub(r"[^a-z0-9]", "", _get("location").lower())
    desc = _get("description")
    
    if company and title and desc:
        desc_hash = hashlib.sha256(desc.strip().encode()).hexdigest()[:16]
        content_key = f"content:{company}:{title}:{location}:{desc_hash}"
        keys.append((content_key, "identical_identity_and_content_hash"))

    return keys


class JobClusterService:
    """Clustering service for finding duplicate postings across platforms."""

    def __init__(self, repository: Optional[JobClusterRepository] = None) -> None:
        self.repo = repository or JobClusterRepository()

    def cluster_job(self, job_id: str, job: NormalizedJob | dict[str, Any]) -> Optional[str]:
        """Index a job into its duplicate cluster(s) deterministically."""
        keys = compute_deterministic_cluster_keys(job)
        last_cluster_id = None
        for key, reason in keys:
            cluster_id = self.repo.add_to_cluster(
                cluster_key=key,
                job_id=job_id,
                reason=reason,
                confidence=1.0,
            )
            if cluster_id:
                last_cluster_id = cluster_id
        return last_cluster_id

    def decorate_job_with_cluster_metadata(self, job_dict: dict[str, Any]) -> dict[str, Any]:
        """Enrich a job API representation with also_listed_on and preferred_apply_url."""
        job_id = job_dict.get("id")
        if not job_id:
            return job_dict

        cluster = self.repo.get_cluster_for_job(job_id)
        if not cluster:
            job_dict["also_listed_on"] = []
            job_dict["preferred_apply_url"] = job_dict.get("url")
            return job_dict

        members = cluster.get("members", [])
        also_listed = []
        preferred_url = job_dict.get("url")
        best_tier = job_dict.get("source_tier") or 5

        for m in members:
            m_job = m.get("jobs") or {}
            m_id = m.get("job_id")
            if m_id != job_id and m_job:
                platform = m_job.get("source_platform") or "unknown"
                also_listed.append({
                    "job_id": m_id,
                    "platform": platform,
                    "url": m_job.get("url"),
                })
            
            # Prefer ATS-direct (tier 1 or 2) over aggregator/best-effort (tier 4 or 5)
            tier = m_job.get("source_tier") or 5
            if tier < best_tier and m_job.get("url"):
                best_tier = tier
                preferred_url = m_job.get("url")

        job_dict["also_listed_on"] = also_listed
        job_dict["preferred_apply_url"] = preferred_url
        return job_dict
