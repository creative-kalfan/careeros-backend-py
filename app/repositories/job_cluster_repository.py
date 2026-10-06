"""Repository for duplicate job clusters and cluster members."""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import uuid4

from app.db.supabase import get_service_client

logger = logging.getLogger(__name__)

_PROBE_CACHE_CLUSTERS: dict[str, bool] = {}


class JobClusterRepository:
    """Data-access for job_clusters and job_cluster_members."""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = get_service_client()
        return self._client

    @classmethod
    def _probe_key(cls, client: Any) -> str:
        url = getattr(client, "supabase_url", None) or getattr(client, "_url", None)
        return str(url) if url else "default"

    def is_available(self) -> bool:
        """Check if job_clusters table exists."""
        client = self._get_client()
        key = self._probe_key(client)
        cached = _PROBE_CACHE_CLUSTERS.get(key)
        if cached is None:
            try:
                client.table("job_clusters").select("id").limit(1).execute()
                cached = True
            except Exception:
                cached = False
            _PROBE_CACHE_CLUSTERS[key] = cached
        return cached

    def add_to_cluster(
        self,
        cluster_key: str,
        job_id: str,
        reason: str,
        confidence: float = 1.0,
        preferred_job_id: Optional[str] = None,
    ) -> Optional[str]:
        """Add job_id to cluster identified by cluster_key (creates cluster if not exists)."""
        if not self.is_available():
            return None

        client = self._get_client()
        try:
            # 1. Upsert cluster
            cluster_res = client.table("job_clusters").select("id, preferred_job_id").eq("cluster_key", cluster_key).execute()
            cluster_id = None
            if cluster_res.data:
                cluster_id = cluster_res.data[0]["id"]
                if preferred_job_id:
                    client.table("job_clusters").update({"preferred_job_id": preferred_job_id}).eq("id", cluster_id).execute()
            else:
                cluster_id = str(uuid4())
                client.table("job_clusters").insert({
                    "id": cluster_id,
                    "cluster_key": cluster_key,
                    "preferred_job_id": preferred_job_id or job_id,
                    "member_count": 1,
                }).execute()

            # 2. Insert member
            client.table("job_cluster_members").upsert({
                "cluster_id": cluster_id,
                "job_id": job_id,
                "reason": reason,
                "confidence": confidence,
            }, on_conflict="cluster_id, job_id").execute()

            return cluster_id
        except Exception as exc:
            logger.warning("Failed to add job to cluster (non-blocking): %s", exc)
            return None

    def get_cluster_for_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """Fetch cluster details and other members for a job."""
        if not self.is_available():
            return None

        client = self._get_client()
        try:
            member_res = client.table("job_cluster_members").select("cluster_id").eq("job_id", job_id).execute()
            if not member_res.data:
                return None
            cluster_id = member_res.data[0]["cluster_id"]

            cluster_res = client.table("job_clusters").select("*").eq("id", cluster_id).execute()
            all_members_res = (
                client.table("job_cluster_members")
                .select("job_id, reason, confidence, jobs:job_id(title, company, source_platform, url, source_tier)")
                .eq("cluster_id", cluster_id)
                .execute()
            )

            cluster_data = cluster_res.data[0] if cluster_res.data else {}
            cluster_data["members"] = all_members_res.data or []
            return cluster_data
        except Exception as exc:
            logger.warning("Failed to get cluster for job: %s", exc)
            return None
