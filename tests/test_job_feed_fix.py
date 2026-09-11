"""Regression tests for the Job Intelligence feed fix (Phases 1-3).

Covers: Stripe india_only wiring, company diversification, feature
persistence round-trip, and the >1000 candidate-pool fix — plus a feed
measurement that reproduces the audit symptom (Stripe monopoly pre-fix)
and proves the fix on the real service path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.job import NormalizedJob
from app.models.profile import UserProfile
from app.services.jobs.job_relevance_service import (
    JobRelevanceService,
    _india_first_score,
)
from app.services.jobs.personalized_job_service import PersonalizedJobService
from app.services.jobs.source_priority import combined_rank_score
from app.services.jobs.job_relevance_service import _recency_key


def _now_iso(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _job(
    i: int,
    company: str,
    location: str,
    title: str,
    skills: list[str] | None = None,
    days_ago: int = 5,
    remote: bool | None = None,
    salary_min: float | None = None,
    salary_max: float | None = None,
    experience_level: str | None = None,
    workplace_type: str | None = None,
    source: str = "greenhouse",
) -> NormalizedJob:
    posted = _now_iso(days_ago)
    return NormalizedJob(
        external_job_id=f"{company}-{i}",
        source_platform=source,
        title=title,
        company=company,
        location=location,
        description=f"{title} role. Requires {' '.join(skills or [])}.",
        skills=skills,
        remote=remote,
        posted_date=posted,
        posted_at=posted,
        salary_min=salary_min,
        salary_max=salary_max,
        experience_level=experience_level,
        workplace_type=workplace_type,
    )


def _analyst_profile() -> UserProfile:
    # Mirrors the audit: Data Analyst target, NO location preference set,
    # so location_match alone cannot outrank a skills/freshness gap.
    return UserProfile(
        id="analyst-1",
        desired_role="Data Analyst",
        skills=["python", "sql", "excel", "tableau"],
        experience="mid",
    )


class _FakeJobRepo:
    """Emulates JobRepository.list_jobs slicing + exact total."""

    def __init__(self, jobs: list[NormalizedJob]) -> None:
        self._rows = [j.model_dump() for j in jobs]

    def list_jobs(self, page: int = 1, page_size: int = 20, **kwargs):
        start = (page - 1) * page_size
        return self._rows[start : start + page_size], len(self._rows)


class _FakeProfileRepo:
    def __init__(self, profile: UserProfile | None) -> None:
        self._profile = profile

    def get_profile(self, user_id):
        return self._profile


def _audit_like_feed() -> list[NormalizedJob]:
    """785 jobs: 615 Stripe (mostly foreign), 96 India, 74 other companies."""
    jobs: list[NormalizedJob] = []
    full = ["python", "sql", "excel", "tableau"]
    # Stripe foreign target-role with full skills + fresh: dominates pre-fix.
    for i in range(115):
        jobs.append(_job(i, "Stripe", "San Francisco, USA", "Data Analyst", full, days_ago=2))
    for i in range(500):
        jobs.append(_job(1000 + i, "Stripe", "New York, USA", "Software Engineer", ["python", "react"], days_ago=3))
    # India: mostly sparse-skills/older (pre-Phase-2 reality) + a few strong ones.
    for i in range(66):
        jobs.append(
            _job(2000 + i, "Infosys", "Mysuru, India", "Systems Engineer", ["java"], days_ago=20, source="adzuna")
        )
    for i in range(27):
        jobs.append(
            _job(3000 + i, "TCS", "Chennai, India", "Data Analyst", ["sql"], days_ago=15, source="adzuna")
        )
    for i in range(3):
        jobs.append(
            _job(4000 + i, "Razorpay", "Bengaluru, India", "Data Analyst", full, days_ago=1, source="firecrawl")
        )
    others = ["JPMorgan", "Deloitte", "HSBC", "EY", "Amazon", "Accenture", "Citi", "IBM"]
    for k, company in enumerate(others):
        for i in range(9):
            jobs.append(
                _job(5000 + k * 10 + i, company, "London, UK", "Data Analyst", full, days_ago=4, source="adzuna")
            )
    jobs.append(_job(6000, "Zerodha", "Bengaluru, India", "Data Analyst", full, days_ago=1, source="firecrawl"))
    jobs.append(_job(6001, "PhonePe", "Pune, India", "Data Analyst", full, days_ago=2, source="firecrawl"))
    assert len(jobs) == 785, len(jobs)
    return jobs


def _old_rank(jobs: list[NormalizedJob], profile: UserProfile) -> list[NormalizedJob]:
    """Pre-fix order: match + boosts, no diversification (reconstruction)."""
    scored = list(jobs)
    svc = PersonalizedJobService()
    for job in scored:
        job.match = svc.calculate_match_score(job, profile)
    scored.sort(
        key=lambda j: (
            combined_rank_score(j.match.get("overall", 0), j) + {3: 6.0, 2: 4.0, 1: 2.0, 0: 0.0}[_india_first_score(j)],
            _india_first_score(j),
            _recency_key(j),
            j.external_job_id or "",
        ),
        reverse=True,
    )
    return scored


def _stats(jobs: list[NormalizedJob]) -> dict:
    india = sum(1 for j in jobs if _india_first_score(j) >= 2)
    remote = sum(1 for j in jobs if _india_first_score(j) == 1)
    foreign = sum(1 for j in jobs if _india_first_score(j) == 0)
    stripe = sum(1 for j in jobs if (j.company or "").lower() == "stripe")
    target = sum(1 for j in jobs if "data analyst" in (j.title or "").lower())
    first_non_stripe = next(
        (r + 1 for r, j in enumerate(jobs) if (j.company or "").lower() != "stripe"),
        None,
    )
    return {
        "india": india,
        "foreign": foreign,
        "remote_ambiguous": remote,
        "stripe": stripe,
        "distinct": len({(j.company or '').lower() for j in jobs}),
        "target": target,
        "first_non_stripe": first_non_stripe,
    }


# --------------------------------------------------------------------------
# Phase 1A: Stripe india_only wiring
# --------------------------------------------------------------------------

def test_stripe_registered_india_only():
    from app.crawlers.crawl_registry import all_targets

    stripe = [t for t in all_targets() if t.source == "greenhouse" and t.slug == "stripe"]
    assert len(stripe) == 1 and stripe[0].india_only is True


def test_worker_threads_india_only_for_stripe():
    from app.workers.jobs.crawl_jobs import _india_only_for

    assert _india_only_for("greenhouse", "stripe") is True
    assert _india_only_for("greenhouse", "unknown-board") is False
    assert _india_only_for("ashby", "notion") is False


async def _noop(*a, **k):
    return []


async def test_ingestion_passes_india_only_to_adapter():
    from app.services.jobs.job_ingestion_service import JobIngestionService

    svc = JobIngestionService(job_repository=MagicMock(), job_service=MagicMock())
    svc.job_service.normalize_and_classify.side_effect = lambda j: j
    svc.job_repository.upsert_jobs.return_value = {"inserted": 1}

    with patch(
        "app.services.jobs.job_ingestion_service.GreenhouseAdapter"
    ) as mock_cls:
        mock_cls.return_value.discover_jobs = AsyncMock(return_value=[])
        await svc.ingest_greenhouse_jobs("stripe", india_only=True)
    mock_cls.assert_called_once_with("stripe", india_only=True)


# --------------------------------------------------------------------------
# Phase 1B: diversification + Phase 1 measurement
# --------------------------------------------------------------------------

def test_feed_measurement_and_diversification(capsys):
    profile = _analyst_profile()
    feed = _audit_like_feed()

    old = _old_rank(feed, profile)
    old_top20 = _stats(old[:20])
    # Audit symptom reproduced: Stripe owns the first pages pre-fix.
    assert old_top20["stripe"] >= 15, old_top20

    svc = JobRelevanceService(
        job_repository=_FakeJobRepo(feed),
        profile_repository=_FakeProfileRepo(profile),
        personalized_service=PersonalizedJobService(),
    )
    new_top100 = [svc.get_relevant_jobs(user_id="u", page=p, page_size=20)[0] for p in range(1, 6)]
    flat = [j for page in new_top100 for j in page]
    assert len(flat) == 100

    with capsys.disabled():
        print("\nrank window | India | foreign | ambig | Stripe | companies | target | 1st non-Stripe")
        for n in (20, 40, 60, 100):
            s = _stats(flat[:n])
            print(
                f"top {n:<3}     | {s['india']:<5} | {s['foreign']:<7} | {s['remote_ambiguous']:<5} | "
                f"{s['stripe']:<6} | {s['distinct']:<9} | {s['target']:<6} | {s['first_non_stripe']}"
            )

    s20, s100 = _stats(flat[:20]), _stats(flat)
    assert s20["stripe"] <= 3, s20  # no monopoly: ~1 Stripe per round
    assert s20["distinct"] >= 8, s20
    assert s20["first_non_stripe"] is not None and s20["first_non_stripe"] <= 2
    assert s100["india"] > 0 and s100["foreign"] > 0  # both discoverable
    assert s100["target"] > 0  # target-role matching intact
    assert len({j.external_job_id for j in flat}) == 100  # pagination-after: no dupes
    # Deterministic repeat.
    again = [j for p in range(1, 6) for j in svc.get_relevant_jobs(user_id="u", page=p, page_size=20)[0]]
    assert [j.external_job_id for j in again] == [j.external_job_id for j in flat]
    # Strong India target-role job surfaces early (Razorpay Bengaluru, fresh, full skills).
    assert any(
        (j.company or "").lower() == "razorpay" for j in flat[:20]
    )
    # Explicit sorts keep their contract (no diversification).
    newest, _ = svc.get_relevant_jobs(user_id="u", page=1, page_size=100, sort="newest")
    dates = [j.posted_date or "" for j in newest]
    assert dates == sorted(dates, reverse=True)


def test_diversify_is_lossless_and_stable():
    jobs = [_job(i, "Stripe" if i % 2 == 0 else "Acme", "Austin, USA", "Data Analyst", ["sql"]) for i in range(10)]
    out = JobRelevanceService._diversify_by_company(jobs)
    assert len(out) == len(jobs)
    assert sorted(j.external_job_id for j in out) == sorted(j.external_job_id for j in jobs)
    assert out == JobRelevanceService._diversify_by_company(list(jobs))  # deterministic
    companies = [(j.company or "") for j in out]
    assert companies[:2] == ["Stripe", "Acme"]  # round-robin


# --------------------------------------------------------------------------
# Phase 2: feature persistence
# --------------------------------------------------------------------------

def test_db_row_round_trip_preserves_features():
    job = _job(
        1, "Acme", "Remote", "Data Analyst",
        ["python", "sql"], remote=True, salary_min=80000, salary_max=120000,
        experience_level="mid", workplace_type="remote",
    )
    row = job.to_db_row()
    for field in ("remote", "skills", "salary_min", "salary_max", "experience_level", "workplace_type"):
        assert field in row, field
    back = NormalizedJob.model_validate({**row, "external_job_id": "x", "source_platform": "y"})
    assert back.remote is True
    assert back.skills == ["python", "sql"]
    assert back.salary_min == 80000 and back.salary_max == 120000
    assert back.experience_level == "mid" and back.workplace_type == "remote"


def test_nulls_stay_null_no_fabrication():
    row = _job(2, "Acme", "Austin, USA", "Data Analyst").to_db_row()
    for field in ("remote", "skills", "salary_min", "salary_max", "experience_level", "workplace_type"):
        assert field not in row, field  # dropped -> NULL, never fabricated
    back = NormalizedJob.model_validate({**row, "external_job_id": "x", "source_platform": "y"})
    assert back.remote is None and back.salary_min is None and back.experience_level is None


def test_scoring_uses_persisted_values():
    profile = UserProfile(
        id="u", desired_role="Data Analyst",
        skills=["python", "sql"], experience="mid",
        salary_expectation_min=90000, salary_expectation_max=110000,
    )
    svc = PersonalizedJobService()
    # Simulate a row read back from the DB after migration 020.
    row = _job(
        3, "Acme", "Bengaluru, India", "Data Analyst",
        ["python", "sql"], remote=True, salary_min=80000, salary_max=120000,
        experience_level="mid", workplace_type="hybrid",
    ).to_db_row()
    job = NormalizedJob.model_validate({**row, "external_job_id": "x", "source_platform": "y"})
    match = svc.calculate_match_score(job, profile)
    assert match["skill_match"] == 100
    assert match["salary_match"] == 100
    assert match["experience_match"] == 100
    # Remote flag persisted -> remote-preferring profile scores 100 on location.
    profile_remote = UserProfile(id="u", desired_role="Data Analyst", remote_preference="remote")
    assert svc.calculate_match_score(job, profile_remote)["location_match"] == 100


def test_migration_020_adds_required_columns():
    from pathlib import Path

    sql = Path("sql/migrations/020_job_feature_columns.sql").read_text()
    for col in ("remote", "workplace_type", "employment_type", "salary_min", "salary_max", "experience_level", "skills"):
        assert col in sql, col


# --------------------------------------------------------------------------
# Phase 3: >1000 candidate pool
# --------------------------------------------------------------------------

def test_candidate_pool_beyond_1000():
    feed = [
        _job(i, f"Company{i % 50}", "Austin, USA" if i % 5 else "Hyderabad, India",
             "Data Analyst" if i % 3 else "Software Engineer",
             ["python", "sql"], days_ago=i % 20, source="adzuna")
        for i in range(1500)
    ]
    repo = _FakeJobRepo(feed)
    calls = []
    orig = repo.list_jobs
    def counting(**kwargs):
        calls.append(kwargs["page_size"])
        return orig(**kwargs)
    repo.list_jobs = counting
    svc = JobRelevanceService(
        job_repository=repo,
        profile_repository=_FakeProfileRepo(_analyst_profile()),
        personalized_service=PersonalizedJobService(),
    )
    pages = [svc.get_relevant_jobs(user_id="u", page=p, page_size=20) for p in range(1, 76)]
    totals = {t for _, t in pages}
    assert totals == {1500}, totals  # correct total, not the 1000 ceiling
    assert all(len(jobs) == 20 for jobs, _ in pages)  # no empty middle/final pages
    flat = [j for jobs, _ in pages for j in jobs]
    assert len(flat) == 1500
    ids = [j.external_job_id for j in flat]
    assert len(set(ids)) == 1500  # no dupes, nothing silently excluded
    assert max(calls) > 1000  # full eligible set actually fetched
    # Determinism + India-first intact beyond the old ceiling.
    repeat = [j for p in range(1, 76) for j in svc.get_relevant_jobs(user_id="u", page=p, page_size=20)[0]]
    assert [j.external_job_id for j in repeat] == ids
    assert sum(1 for j in flat[:100] if _india_first_score(j) >= 2) > 0


def test_small_pool_stays_single_fetch():
    feed = _audit_like_feed()[:100]
    repo = _FakeJobRepo(feed)
    calls = []
    orig = repo.list_jobs
    def counting(**kwargs):
        calls.append(kwargs["page_size"])
        return orig(**kwargs)
    repo.list_jobs = counting
    svc = JobRelevanceService(
        job_repository=repo,
        profile_repository=_FakeProfileRepo(_analyst_profile()),
        personalized_service=PersonalizedJobService(),
    )
    svc.get_relevant_jobs(user_id="u", page=1, page_size=20)
    assert calls == [1000]  # no wasteful refetch under the ceiling
