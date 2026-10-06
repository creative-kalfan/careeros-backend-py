"""Background ARQ worker jobs for batch embedding generation and backfill."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.config import get_settings
from app.db.supabase import get_service_client
from app.llm.embeddings import get_embedding_provider
from app.repositories.job_embedding_repository import JobEmbeddingRepository
from app.workers.registry import register_job

logger = logging.getLogger(__name__)


def _compute_job_text_and_hash(job_row: dict[str, Any]) -> tuple[str, str]:
    """Build embedding input text and content hash for a job."""
    title = str(job_row.get("title") or "").strip()
    company = str(job_row.get("company") or "").strip()
    skills = " ".join(job_row.get("skills") or [])
    desc = str(job_row.get("description") or "").strip()[:1000]

    text = f"{title} at {company}. Skills: {skills}. Overview: {desc}".strip()
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return text, content_hash


@register_job(
    "embed_jobs_batch",
    timeout=120,
    max_tries=2,
    retry=True,
    description="Embed a batch of active jobs into pgvector job_embeddings.",
)
async def embed_jobs_batch(ctx: dict[str, Any], job_ids: list[str]) -> dict[str, Any]:
    """Embed a list of jobs by primary key in a single batch."""
    settings = get_settings()
    if not settings.semantic_retrieval_enabled:
        return {"status": "skipped", "reason": "semantic_retrieval_disabled"}

    provider = get_embedding_provider()
    repo = JobEmbeddingRepository()
    if not provider.is_configured() or not repo.is_available():
        return {"status": "skipped", "reason": "provider_or_repo_unavailable"}

    client = get_service_client()
    res = client.table("jobs").select("id, title, company, skills, description, is_active").in_("id", job_ids[:settings.embed_batch_size]).execute()
    jobs = getattr(res, "data", None) or []
    if not jobs:
        return {"embedded": 0, "status": "no_jobs"}

    # Filter out already-embedded identical hashes
    existing = repo.get_existing_hashes([j["id"] for j in jobs], settings.embedding_model)
    to_embed: list[tuple[dict[str, Any], str, str]] = []

    for j in jobs:
        if not j.get("is_active"):
            continue
        text, chash = _compute_job_text_and_hash(j)
        if existing.get(j["id"]) == chash:
            continue  # Already up to date
        to_embed.append((j, text, chash))

    if not to_embed:
        return {"embedded": 0, "status": "all_up_to_date"}

    texts = [t[1] for t in to_embed]
    embeddings = await provider.embed_texts(texts)

    saved_count = 0
    for (job_dict, _, chash), vec in zip(to_embed, embeddings):
        if vec:
            ok = repo.save_embedding(
                job_id=job_dict["id"],
                model=settings.embedding_model,
                dims=len(vec),
                content_hash=chash,
                embedding=vec,
            )
            if ok:
                saved_count += 1

    return {"embedded": saved_count, "status": "success"}


@register_job(
    "backfill_job_embeddings",
    timeout=300,
    max_tries=1,
    retry=False,
    description="Find active unembedded jobs within max age and enqueue embed batches.",
)
async def backfill_job_embeddings(ctx: dict[str, Any], limit: int = 200) -> dict[str, Any]:
    """Backfill missing embeddings for active jobs."""
    settings = get_settings()
    if not settings.semantic_retrieval_enabled:
        return {"enqueued": 0, "status": "disabled"}

    client = get_service_client()
    repo = JobEmbeddingRepository()
    if not repo.is_available():
        return {"enqueued": 0, "status": "repo_unavailable"}

    # Fetch active jobs within EMBED_MAX_AGE_DAYS
    res = (
        client.table("jobs")
        .select("id")
        .eq("is_active", True)
        .order("created_at", desc=True)
        .limit(min(limit, settings.embed_max_rows_cap))
        .execute()
    )
    rows = getattr(res, "data", None) or []
    if not rows:
        return {"enqueued": 0, "status": "no_jobs"}

    all_ids = [r["id"] for r in rows if "id" in r]
    existing = repo.get_existing_hashes(all_ids, settings.embedding_model)
    unembedded_ids = [jid for jid in all_ids if jid not in existing]

    if not unembedded_ids:
        return {"enqueued": 0, "status": "all_embedded"}

    from app.workers.dispatcher import enqueue
    batch_size = settings.embed_batch_size
    enqueued = 0
    for i in range(0, len(unembedded_ids), batch_size):
        chunk = unembedded_ids[i : i + batch_size]
        await enqueue("embed_jobs_batch", chunk)
        enqueued += len(chunk)

    return {"enqueued": enqueued, "status": "success"}
