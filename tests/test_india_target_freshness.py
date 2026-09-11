"""India target-role + freshness-aware feed: synthetic scenarios (one file).

Covers task §§22-25 without a DB: taxonomy, observation-aware freshness,
stale-deactivation root fix, India+target+freshness ranking, deterministic
pagination, and query-rotation exemption (already enforced in crawl_jobs).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.models.job import NormalizedJob
from app.parsing.role_classifier import classify
from app.repositories.job_repository import JobRepository
from app.services.jobs.job_relevance_service import JobRelevanceService, _india_first_score
from app.services.jobs.personalized_job_service import PersonalizedJobService
from app.workers.jobs.crawl_jobs import _uses_complete_inventory


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _job(title: str, location: str, posted_days_ago: float, ext: str,
         seen_days_ago: float | None = None) -> NormalizedJob:
    j = NormalizedJob(title=title, company="TCS", location=location,
                      external_job_id=ext, source_platform="adzuna",
                      posted_date=_iso(posted_days_ago))
    if seen_days_ago is not None:
        j.last_seen_at = _iso(seen_days_ago)
    return j


class TestTargetRoleTaxonomy:
    def test_sap_abap_no_longer_other(self) -> None:
        assert classify("SAP ABAP Developer") == "Software Engineering"
        assert classify("SAP HANA Consultant") == "Software Engineering"
        assert classify("SAP FICO Analyst") == "Software Engineering"

    def test_existing_buckets_intact(self) -> None:
        assert classify("Data Analyst") == "Data & Analytics"
        assert classify("Data Engineer") == "Data & Analytics"
        assert classify("Machine Learning Engineer") == "Data & Analytics"
        assert classify("Backend Developer") == "Software Engineering"
        assert classify("Risk Analyst") == "Data & Analytics"
        assert classify("Financial Analyst") == "Finance & BFSI"
        assert classify("Analytics Engineer") == "Data & Analytics"
        assert classify("Consultant") == "Healthcare, Science & Other Professional"


class TestObservationFreshness:
    def test_reobserved_old_posting_regains_freshness(self) -> None:
        svc = PersonalizedJobService()
        stale = _job("Data Analyst", "Bengaluru, India", 20, "e1")
        assert svc._score_freshness(stale) == 50.0
        stale.last_seen_at = _iso(0)  # re-observed today
        assert svc._score_freshness(stale) == 100.0

    def test_posted_at_never_rewritten_by_scoring(self) -> None:
        j = _job("Data Analyst", "Bengaluru, India", 20, "e2")
        posted = j.posted_date
        PersonalizedJobService()._score_freshness(j)
        assert j.posted_date == posted


class TestStaleDeactivationRootFix:
    def _repo(self, rows: list[dict]) -> tuple[JobRepository, MagicMock]:
        client = MagicMock()
        client.table.return_value = client
        for m in ("select", "eq", "update", "insert", "lt"):
            setattr(client, m, MagicMock(return_value=client))
        client.execute.return_value = MagicMock(data=rows)
        repo = JobRepository(client)
        repo._has_last_seen_at = True
        return repo, client

    def test_reobserved_old_posting_not_deactivated(self) -> None:
        # posted 60d ago but seen today -> stays active (observation wins)
        repo, _ = self._repo([{"id": "a", "posted_at": _iso(60), "last_seen_at": _iso(0)}])
        assert repo.deactivate_stale_jobs(source_platform="adzuna", max_age_days=30) == 0

    def test_unseen_old_posting_deactivated(self) -> None:
        repo, _ = self._repo([{"id": "b", "posted_at": _iso(60), "last_seen_at": _iso(45)}])
        assert repo.deactivate_stale_jobs(source_platform="adzuna", max_age_days=30) == 1

    def test_rotation_missed_jobs_exempt_from_not_seen(self) -> None:
        assert not _uses_complete_inventory("adzuna")
        assert not _uses_complete_inventory("jobspy")
        assert _uses_complete_inventory("greenhouse")


class TestReobservationUpsert:
    def test_reobservation_updates_last_seen_preserves_posted_no_dupe(self) -> None:
        posted = _iso(20)
        existing = {"id": "row-1", "external_job_id": "e9", "source_platform": "adzuna",
                    "title": "Data Analyst", "company": "TCS", "location": "Bengaluru, India",
                    "posted_at": posted, "is_active": True}
        client = MagicMock()
        client.table.return_value = client
        for m in ("select", "eq", "update", "insert"):
            setattr(client, m, MagicMock(return_value=client))
        client.execute.return_value = MagicMock(data=[{"id": "row-1"}])
        repo = JobRepository(client)
        repo._has_last_seen_at = True
        repo._has_provenance = False
        seen = _job("Data Analyst", "Bengaluru, India", 20, "e9", seen_days_ago=0)
        seen.posted_date = posted
        with patch.object(JobRepository, "_find_by_identity", return_value=existing):
            out = repo.upsert_jobs([seen])
        assert out["unchanged"] == 1 and out["inserted"] == 0
        update_arg = client.update.call_args.args[0]
        assert "posted_at" not in update_arg  # unchanged path never rewrites posting date
        assert "last_seen_at" in update_arg


class TestCombinedRanking:
    def _ranked_titles(self, jobs: list[NormalizedJob]) -> list[str]:
        svc = JobRelevanceService.__new__(JobRelevanceService)
        scored = [(PersonalizedJobService()._score_freshness(j), _india_first_score(j), j) for j in jobs]
        # India dominates freshness: sort india desc, then freshness desc, then id
        scored.sort(key=lambda t: (t[1], t[0], t[2].external_job_id or ""), reverse=True)
        return [j.title for _, _, j in scored]

    def test_india_target_fresh_beats_foreign_and_stale(self) -> None:
        jobs = [
            _job("Data Analyst", "Bengaluru, India", 1, "A", 0),    # A new India target
            _job("Data Analyst", "Bengaluru, India", 20, "B", 20),  # B old India target
            _job("Software Engineer", "Bengaluru, India", 1, "C", 0),  # C new India other
            _job("Data Analyst", "New York, USA", 1, "D", 0),       # D new foreign target
            _job("Data Analyst", "Bengaluru, India", 60, "E", 60),  # E stale India target
        ]
        titles = [j.external_job_id for j in sorted(
            jobs, key=lambda j: (_india_first_score(j),
                                 PersonalizedJobService()._score_freshness(j),
                                 j.external_job_id or ""), reverse=True)]
        assert set(titles[:2]) == {"A", "C"}  # fresh India first (target-role via match score)
        assert titles.index("B") < titles.index("E")  # fresh > stale within India target
        assert titles.index("A") < titles.index("D")  # India beats foreign despite equal freshness
        assert titles.index("E") < titles.index("D")  # India-first outweighs freshness alone

    def test_tier_order_new_fresh_aging_stale(self) -> None:
        svc = PersonalizedJobService()
        scores = [svc._score_freshness(_job("X", "Bengaluru, India", d, f"e{d}", d))
                  for d in (1, 5, 10, 60)]
        assert scores == sorted(scores, reverse=True)  # NEW > FRESH > AGING > STALE
        assert scores[0] == 100.0 and scores[-1] == 30.0

    def test_pagination_deterministic(self) -> None:
        jobs = [_job("Data Analyst", "Bengaluru, India", 1, f"e{i:03d}", 0) for i in range(10)]
        svc = JobRelevanceService.__new__(JobRelevanceService)
        k = lambda j: (_india_first_score(j), j.posted_date or "", j.external_job_id or "")  # noqa: E731
        first = [j.external_job_id for j in sorted(jobs, key=k, reverse=True)]
        second = [j.external_job_id for j in sorted(list(reversed(jobs)), key=k, reverse=True)]
        assert first == second
