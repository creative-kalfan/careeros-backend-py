"""Repository for storing and querying job vector embeddings."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.db.supabase import get_service_client

logger = logging.getLogger(__name__)

_PROBE_CACHE_VECTOR: dict[str, bool] = {}


class JobEmbeddingRepository:
    """Data-access for pgvector job embeddings with graceful fallback."""

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
        """Probe if job_embeddings table exists in the database."""
        client = self._get_client()
        key = self._probe_key(client)
        cached = _PROBE_CACHE_VECTOR.get(key)
        if cached is None:
            try:
                client.table("job_embeddings").select("id").limit(1).execute()
                cached = True
            except Exception:
                cached = False
            _PROBE_CACHE_VECTOR[key] = cached
        return cached

    def save_embedding(
        self,
        job_id: str,
        model: str,
        dims: int,
        content_hash: str,
        embedding: list[float],
    ) -> bool:
        """Persist a job embedding vector (idempotent upsert)."""
        if not self.is_available():
            return False

        try:
            payload = {
                "job_id": job_id,
                "model": model,
                "dims": dims,
                "content_hash": content_hash,
                "embedding": embedding,
            }
            self._get_client().table("job_embeddings").upsert(
                payload, on_conflict="job_id,model"
            ).execute()
            return True
        except Exception as exc:
            logger.warning("Failed to save job embedding for %s: %s", job_id, exc)
            return False

    def get_existing_hashes(self, job_ids: list[str], model: str) -> dict[str, str]:
        """Return a mapping of job_id -> content_hash for jobs already embedded with this model."""
        if not self.is_available() or not job_ids:
            return {}

        try:
            res = (
                self._get_client()
                .table("job_embeddings")
                .select("job_id, content_hash")
                .eq("model", model)
                .in_("job_id", job_ids[:100])
                .execute()
            )
            data = getattr(res, "data", None) or []
            return {r["job_id"]: r["content_hash"] for r in data if "job_id" in r and "content_hash" in r}
        except Exception:
            return {}

    def search_similar_jobs(
        self,
        query_embedding: list[float],
        top_k: int = 50,
        min_similarity: float = 0.5,
        newer_than_days: int = 90,
    ) -> list[dict[str, Any]]:
        """Search top-K nearest jobs using pgvector RPC match_job_embeddings."""
        if not self.is_available() or not query_embedding:
            return []

        try:
            client = self._get_client()
            res = client.rpc(
                "match_job_embeddings",
                {
                    "query_embedding": query_embedding,
                    "match_threshold": min_similarity,
                    "match_count": top_k,
                    "filter_active": True,
                    "filter_newer_than_days": newer_than_days,
                },
            ).execute()
            data = getattr(res, "data", None) or []
            return data
        except Exception as exc:
            logger.warning("match_job_embeddings RPC search failed (failing open): %s", exc)
            return []
