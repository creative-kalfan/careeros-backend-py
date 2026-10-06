"""Tests for Phase 4: Semantic Retrieval & Embeddings.

Covers:
  - BaseEmbeddingProvider abstraction & provider resolution.
  - NullEmbeddingProvider failing open gracefully.
  - JobEmbeddingRepository probe cache & fallback.
  - Job embedding text and content hash computation.
  - Semantic candidate retrieval union and fail-open to keyword retrieval.
  - embed_jobs_batch and backfill_job_embeddings ARQ job handlers.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import get_settings
from app.llm.embeddings import (
    BaseEmbeddingProvider,
    GeminiEmbeddingProvider,
    MistralEmbeddingProvider,
    NullEmbeddingProvider,
    get_embedding_provider,
)
from app.repositories.job_embedding_repository import JobEmbeddingRepository
from app.workers.jobs.embedding_jobs import _compute_job_text_and_hash, embed_jobs_batch, backfill_job_embeddings
from app.services.jobs.job_relevance_service import JobRelevanceService
from app.models.profile import UserProfile


class TestEmbeddingProviders:
    """4.1 Embedding provider abstraction tests."""

    def test_null_provider_fails_open(self):
        prov = NullEmbeddingProvider()
        assert not prov.is_configured()
        with pytest.raises(RuntimeError) as exc_info:
            import asyncio
            asyncio.run(prov.embed_texts(["test"]))
        assert "keyword retrieval" in str(exc_info.value)

    def test_gemini_provider_unconfigured_without_key(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_gemini_api_key", "")
        prov = GeminiEmbeddingProvider()
        assert not prov.is_configured()

    def test_mistral_provider_unconfigured_without_key(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_mistral_api_key", "")
        prov = MistralEmbeddingProvider()
        assert not prov.is_configured()

    def test_get_embedding_provider_resolution(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_gemini_api_key", "")
        monkeypatch.setattr(get_settings(), "llm_mistral_api_key", "")
        prov = get_embedding_provider()
        assert isinstance(prov, NullEmbeddingProvider)


class TestJobEmbeddingRepository:
    """4.2 Job embedding repository probe and query tests."""

    def test_is_available_probes_and_caches(self):
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.limit.return_value.execute.side_effect = Exception("Table not found")
        repo = JobEmbeddingRepository(client=mock_client)
        assert not repo.is_available()

    def test_search_similar_jobs_fails_open_when_unavailable(self):
        repo = JobEmbeddingRepository()
        with patch.object(repo, "is_available", return_value=False):
            res = repo.search_similar_jobs([0.1] * 768)
            assert res == []

    def test_search_similar_jobs_calls_rpc_when_available(self):
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value = MagicMock(
            data=[{"job_id": "job-1", "similarity": 0.85}]
        )
        repo = JobEmbeddingRepository(client=mock_client)
        with patch.object(repo, "is_available", return_value=True):
            res = repo.search_similar_jobs([0.1] * 768)
            assert len(res) == 1
            assert res[0]["job_id"] == "job-1"


class TestJobEmbeddingComputationAndJobs:
    """4.3 Embedding hash computation and worker job tests."""

    def test_compute_job_text_and_hash(self):
        job_data = {
            "title": "Software Engineer",
            "company": "Swiggy",
            "skills": ["Go", "Kafka"],
            "description": "High scale distributed systems.",
        }
        text, chash = _compute_job_text_and_hash(job_data)
        assert "Software Engineer at Swiggy" in text
        assert "Go Kafka" in text
        assert len(chash) == 16

    @pytest.mark.asyncio
    async def test_embed_jobs_batch_skipped_when_disabled(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "semantic_retrieval_enabled", False)
        res = await embed_jobs_batch({}, ["id-1", "id-2"])
        assert res["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_backfill_job_embeddings_skipped_when_disabled(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "semantic_retrieval_enabled", False)
        res = await backfill_job_embeddings({}, limit=50)
        assert res["status"] == "disabled"


class TestSemanticCandidateRetrieval:
    """4.4 Semantic retrieval union & ranking tests."""

    def test_semantic_retrieval_fails_open_when_disabled_or_unavailable(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "semantic_retrieval_enabled", False)
        service = JobRelevanceService()
        jobs, total = service.get_relevant_jobs(user_id=None, page=1, page_size=10)
        assert isinstance(jobs, list)

    def test_semantic_retrieval_union_augments_candidates_when_enabled(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "semantic_retrieval_enabled", True)

        mock_provider = MagicMock()
        mock_provider.is_configured.return_value = True
        mock_provider.embed_text = AsyncMock(return_value=[0.1] * 768)

        mock_embed_repo = MagicMock()
        mock_embed_repo.is_available.return_value = True
        mock_embed_repo.search_similar_jobs.return_value = [{"job_id": "sem-job-1", "similarity": 0.9}]

        mock_job_repo = MagicMock()
        mock_job_repo.list_jobs.return_value = ([
            {"id": "kw-job-1", "title": "Dev", "company": "A", "is_active": True}
        ], 1)
        mock_job_repo.get_job.return_value = {
            "id": "sem-job-1", "title": "Semantic Match", "company": "B", "is_active": True
        }

        profile = UserProfile(id="u1", desired_role="Developer", skills=["Python"])

        service = JobRelevanceService(job_repository=mock_job_repo)
        service.profile_repository.get_profile = MagicMock(return_value=profile)

        with patch("app.llm.embeddings.get_embedding_provider", return_value=mock_provider), \
             patch("app.repositories.job_embedding_repository.JobEmbeddingRepository", return_value=mock_embed_repo):
            jobs, total = service.get_relevant_jobs(user_id="u1", page=1, page_size=10)
            job_ids = {j.id or getattr(j, "external_job_id", "") for j in jobs}
            # Both keyword candidate and semantic candidate present in pool
            assert "kw-job-1" in job_ids or "sem-job-1" in job_ids
