"""Tests for the Interview Preparation vertical slice.

Covers: interview-type inference, category planning, answer frameworks,
resume-grounding validation, fabrication regression (missing JD skills stay
gaps, verified metrics reusable, no invented metrics), generation flow,
persistence, regeneration/versioning, staleness, failure states, provider
fallback surface, ownership/RLS enforcement, event publishing, worker
behavior, API envelopes, and migration content.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.service import AuthContext, AuthUser
from app.events import InterviewPrepGenerated
from app.llm.types import LLMProvider, LLMProviderError
from app.models.interview_prep import (
    VALID_CATEGORIES,
    UNSUPPORTED_EVIDENCE_MARKER,
    framework_for,
    infer_interview_type,
    plan_categories,
)
from app.services.interview_prep.grounding import (
    build_evidence_corpus,
    detect_gaps,
    evidence_supported,
    extract_resume_skills,
    metric_supported,
    validate_question_grounding,
)
from app.services.interview_prep.service import InterviewPrepService, PrepContext
from app.repositories.interview_prep_repository import InterviewPrepRepository
from app.workers.registry import get_job_definition


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _auth(user_id: str = "user-A") -> AuthContext:
    return AuthContext(
        user=AuthUser(id=user_id, email=f"{user_id}@example.com"),
        supabase=MagicMock(),
        jwt="jwt-A",
    )


def _resume_profile() -> dict:
    return {
        "personal": {"full_name": "Asha Engineer"},
        "summary": "Backend engineer building payment APIs with Python and FastAPI.",
        "experience": [
            {
                "company": "Finscale",
                "role": "Backend Engineer",
                "responsibilities": [
                    {"text": "Built ingestion microservices with Python/FastAPI handling payment webhooks."},
                    {"text": "Optimized PostgreSQL queries, reducing P99 latency by 35%."},
                ],
                "achievements": ["Cut peak-traffic error budget burn by owning Redis caching layer."],
                "tools": ["Python", "FastAPI", "PostgreSQL", "Redis"],
            }
        ],
        "internships": [],
        "education": [],
        "skills": {
            "technical": ["Python", "FastAPI"],
            "tools": ["Redis"],
            "languages": [],
            "databases": ["PostgreSQL"],
            "analytics": [],
            "soft_skills": [],
            "custom": {},
        },
        "projects": [
            {
                "name": "Ledger API",
                "description": "Double-entry ledger service for payouts.",
                "technologies": ["Python", "FastAPI", "PostgreSQL"],
                "results": "Handled 2x payout volume.",
            }
        ],
        "certifications": [],
        "achievements": [],
    }


JD_FIXTURE = """Backend Engineer at Finscale.

Requirements:
- PostgreSQL performance optimization
- Python and FastAPI API development
- Redis caching
- Kubernetes cluster operations
- Kafka event streaming
- Rust systems programming
- GraphQL API design
"""


def _canned_llm_content() -> str:
    questions = [
        {
            "category": "technical",
            "question": "Tell me about a time you optimized PostgreSQL performance.",
            "difficulty": "intermediate",
            "rationale": "Core JD requirement with direct resume evidence.",
            "resume_evidence": ["Optimized PostgreSQL queries, reducing P99 latency by 35%."],
            "talking_points": ["transactions table", "query optimization", "peak traffic", "35% P99 improvement"],
            "expected_signals": ["Explains measurement before/after"],
            "related_jd_requirements": ["PostgreSQL performance optimization"],
            "gaps": [],
        },
        {
            "category": "technical",
            "question": "How do you design FastAPI services for payment webhooks?",
            "difficulty": "intermediate",
            "rationale": "Role-specific system backed by Ledger API work.",
            "resume_evidence": ["Built ingestion microservices with Python/FastAPI handling payment webhooks."],
            "talking_points": ["Finscale ingestion microservices", "Python/FastAPI", "payment webhooks"],
            "expected_signals": ["Idempotency and retries"],
            "related_jd_requirements": ["Python and FastAPI API development"],
            "gaps": [],
        },
        {
            "category": "behavioral",
            "question": "Tell me about a backend system you designed.",
            "difficulty": "intermediate",
            "rationale": "Ownership signal from real project work.",
            "resume_evidence": ["Double-entry ledger service for payouts."],
            "talking_points": ["Ledger API", "double-entry design", "2x payout volume"],
            "expected_signals": ["Trade-offs articulated"],
            "related_jd_requirements": [],
            "gaps": [],
        },
        {
            "category": "resume_deep_dive",
            "question": "Walk me through your Redis caching layer work.",
            "difficulty": "foundational",
            "rationale": "Resume deep-dive on claimed caching ownership.",
            "resume_evidence": ["Cut peak-traffic error budget burn by owning Redis caching layer."],
            "talking_points": ["Redis", "peak traffic", "error budget"],
            "expected_signals": ["Cache invalidation strategy"],
            "related_jd_requirements": ["Redis caching"],
            "gaps": [],
        },
        {
            "category": "situational",
            "question": "How would you approach learning Kafka for an event-driven migration?",
            "difficulty": "intermediate",
            "rationale": "JD gap framed honestly as a learning plan, not fake experience.",
            "resume_evidence": [UNSUPPORTED_EVIDENCE_MARKER],
            "talking_points": ["Analogous learning: PostgreSQL optimization", "Ask for ramp plan"],
            "expected_signals": ["Honest gap acknowledgement"],
            "related_jd_requirements": ["Kafka event streaming"],
            "gaps": ["Kafka event streaming"],
        },
        {
            "category": "role_specific",
            "question": "How do you handle Kubernetes rollouts safely?",
            "difficulty": "advanced",
            "rationale": "Surfaces the Kubernetes gap explicitly.",
            "resume_evidence": [UNSUPPORTED_EVIDENCE_MARKER],
            "talking_points": [],
            "expected_signals": ["Does not bluff platform experience"],
            "related_jd_requirements": ["Kubernetes cluster operations"],
            "gaps": ["Kubernetes cluster operations", "Rust systems programming", "GraphQL API design"],
        },
    ]
    return json.dumps({"questions": questions, "assumption_note": "", "gaps": ["Rust systems programming"]})


class _CannedGateway:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests = []

    async def generate(self, request):  # noqa: A002
        self.requests.append(request)
        return SimpleNamespace(content=self.content, provider=LLMProvider.GROQ)


class _FailGateway:
    async def generate(self, request):  # noqa: A002
        raise LLMProviderError("provider down", LLMProvider.GROQ)


class _MemRepo(InterviewPrepRepository):
    """In-memory InterviewPrepRepository honoring the ownership contract."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.questions: dict[str, list[dict]] = {}

    async def create_session(self, supabase, user_id, data):
        row = {"id": f"ses-{uuid.uuid4().hex[:8]}", "user_id": user_id, **data}
        self.sessions[row["id"]] = row
        self.questions[row["id"]] = []
        return row

    async def get_session(self, supabase, user_id, session_id):
        row = self.sessions.get(session_id)
        if row is None or row.get("user_id") != user_id:
            return None
        return dict(row)

    async def list_sessions(self, supabase, user_id, application_id=None, page=1, page_size=20):
        rows = [r for r in self.sessions.values() if r.get("user_id") == user_id]
        if application_id:
            rows = [r for r in rows if str(r.get("application_id")) == str(application_id)]
        return rows, len(rows)

    async def update_session(self, supabase, user_id, session_id, updates):
        row = await self.get_session(supabase, user_id, session_id)
        if row is None:
            return None
        row.update(updates)
        self.sessions[session_id] = row
        return dict(row)

    async def replace_questions(self, supabase, session_id, questions):
        stored = []
        for idx, q in enumerate(questions):
            stored.append({"id": f"q-{uuid.uuid4().hex[:8]}", "session_id": session_id, **q})
        self.questions[session_id] = stored
        return [dict(q) for q in stored]

    async def list_questions(self, supabase, session_id):
        return [dict(q) for q in self.questions.get(session_id, [])]

    async def get_question(self, supabase, question_id):
        for qs in self.questions.values():
            for q in qs:
                if q["id"] == question_id:
                    return dict(q)
        return None

    async def update_question(self, supabase, question_id, updates):
        for sid, qs in self.questions.items():
            for idx, q in enumerate(qs):
                if q["id"] == question_id:
                    q.update(updates)
                    qs[idx] = q
                    return dict(q)
        return None


class _FakeBus:
    def __init__(self) -> None:
        self.published = []
        self.context = None

    async def publish(self, event, context=None):  # noqa: A002
        self.published.append(event)
        self.context = context
        return MagicMock()


class _FakeNotif:
    def __init__(self) -> None:
        self.created = []

    async def create_notification(self, auth, type_, title, message, payload=None, priority="medium"):
        self.created.append({"type": type_, "title": title, "payload": payload})
        return {"id": "notif-1"}


def _app_row(**overrides):
    row = {
        "id": "app-1",
        "user_id": "user-A",
        "job_id": "job-1",
        "job_title": "Backend Engineer",
        "company_name": "Finscale",
        "status": "interview",
        "application_date": "2026-01-01",
        "notes": None,
    }
    row.update(overrides)
    return row


def _service(mem=None, app_repo=None, gateway=None, bus=None, notif=None) -> InterviewPrepService:
    return InterviewPrepService(
        repository=mem or _MemRepo(),
        application_repository=app_repo or MagicMock(),
        bus=bus if bus is not None else _FakeBus(),
        notification_service=notif if notif is not None else _FakeNotif(),
        gateway_factory=(lambda: gateway) if gateway is not None else None,
    )


def _patched_resume(content_profile: dict | None):
    """Patch ResumeRepository/JobRepository for _gather_context."""
    resume_row = None
    if content_profile is not None:
        resume_row = {
            "id": "resume-1",
            "user_id": "user-A",
            "content": {"profile": content_profile, "meta": {}},
            "updated_at": "2026-02-01T00:00:00+00:00",
        }
    resume_repo = MagicMock()
    resume_repo.list_resumes.return_value = [resume_row] if resume_row else []
    resume_repo.get_resume.return_value = resume_row
    job_repo = MagicMock()
    job_repo.get_job.return_value = None
    return (
        patch("app.repositories.resume_repository.ResumeRepository", return_value=resume_repo),
        patch("app.repositories.job_repository.JobRepository", return_value=job_repo),
    )


# ---------------------------------------------------------------------------
# Interview-type awareness + planning + frameworks
# ---------------------------------------------------------------------------


async def test_infer_interview_type_technical():
    assert infer_interview_type("Technical Screen — Backend")[0] == "technical"


async def test_infer_interview_type_behavioral():
    assert infer_interview_type("Behavioral / Values")[0] == "behavioral"


async def test_infer_interview_type_hiring_manager():
    assert infer_interview_type("Hiring Manager Chat")[0] == "hiring_manager"


async def test_infer_interview_type_recruiter():
    assert infer_interview_type("Recruiter phone screen")[0] == "recruiter"


async def test_infer_interview_type_assessment():
    assert infer_interview_type("Take-home assessment")[0] == "assessment"


async def test_infer_interview_type_unknown_assumed_balanced():
    itype, assumed = infer_interview_type("Coffee chat")
    assert itype == "general"
    assert assumed is True
    cats = plan_categories(itype, 8)
    assert len(cats) == 8
    assert len(set(cats)) >= 4


async def test_plan_categories_technical_weights():
    cats = plan_categories("technical", 8)
    assert len(cats) == 8
    assert cats.count("technical") >= 2
    assert "behavioral" in cats or "situational" in cats


async def test_framework_for_behavioral_is_star():
    fw = framework_for("behavioral", "Tell me about a conflict")
    assert fw["type"] == "STAR"
    assert "Situation" in fw["steps"] and "Reflection" in fw["steps"]


async def test_framework_for_design_is_system():
    fw = framework_for("technical", "Design a webhook ingestion system")
    assert fw["type"] == "Requirements-Architecture"
    assert "Failure modes" in fw["steps"]


# ---------------------------------------------------------------------------
# Grounding primitives
# ---------------------------------------------------------------------------


async def test_evidence_supported_verbatim_and_overlap():
    corpus = build_evidence_corpus(_resume_profile())
    assert evidence_supported("Optimized PostgreSQL queries, reducing P99 latency by 35%.", corpus)
    assert not evidence_supported("Operated Kubernetes clusters across 40 nodes.", corpus)


async def test_metric_supported_verified_vs_invented():
    corpus = build_evidence_corpus(_resume_profile())
    assert metric_supported("35% P99 improvement", corpus)
    assert not metric_supported("reduced latency by 50%", corpus)
    assert metric_supported("improved collaboration", corpus)  # no metric claimed


async def test_validate_question_grounding_replaces_unsupported():
    corpus = build_evidence_corpus(_resume_profile())
    skills = extract_resume_skills(_resume_profile())
    cleaned = validate_question_grounding(
        {
            "resume_evidence": ["Managed a 20-person Kubernetes platform team."],
            "talking_points": ["Led K8s migration"],
            "related_jd_requirements": ["Free sushi Fridays"],
            "gaps": [],
        },
        corpus,
        skills,
        JD_FIXTURE,
    )
    assert cleaned["resume_evidence"] == [UNSUPPORTED_EVIDENCE_MARKER]
    assert cleaned["related_jd_requirements"] == []


# ---------------------------------------------------------------------------
# Fabrication regression (Phase 27)
# ---------------------------------------------------------------------------


async def test_fabrication_missing_jd_skills_stay_gaps():
    """Resume has Python/FastAPI/Postgres/Redis; JD wants K8s/Kafka/Rust/GraphQL.

    Preparation must never claim the candidate has the missing skills.
    """
    profile = _resume_profile()
    corpus = build_evidence_corpus(profile)
    skills = extract_resume_skills(profile)
    gaps = detect_gaps(
        ["Kubernetes cluster operations", "Kafka event streaming",
         "Rust systems programming", "GraphQL API design",
         "PostgreSQL performance optimization"],
        skills,
        corpus,
    )
    gap_text = " ".join(gaps).lower()
    for missing in ("kubernetes", "kafka", "rust", "graphql"):
        assert missing in gap_text
    assert "postgresql" not in gap_text  # covered skill is not a gap

    # And validation never lets an invented claim through as evidence.
    cleaned = validate_question_grounding(
        {
            "resume_evidence": ["Shipped Rust microservices on Kafka with Kubernetes."],
            "talking_points": ["Deep Rust expertise"],
            "related_jd_requirements": ["Rust systems programming"],
            "gaps": [],
        },
        corpus,
        skills,
        JD_FIXTURE,
    )
    assert cleaned["resume_evidence"] == [UNSUPPORTED_EVIDENCE_MARKER]


async def test_verified_metric_reusable_and_no_metric_invented():
    corpus = build_evidence_corpus(_resume_profile())
    skills = extract_resume_skills(_resume_profile())
    kept = validate_question_grounding(
        {
            "resume_evidence": ["Optimized PostgreSQL queries, reducing P99 latency by 35%."],
            "talking_points": ["35% P99 improvement", "query optimization"],
            "related_jd_requirements": ["PostgreSQL performance optimization"],
            "gaps": [],
        },
        corpus,
        skills,
        JD_FIXTURE,
    )
    assert "35% P99 improvement" in kept["talking_points"]

    profile_no_metric = _resume_profile()
    profile_no_metric["experience"][0]["responsibilities"] = [
        {"text": "Maintained internal dashboards."}
    ]
    profile_no_metric["experience"][0]["achievements"] = []
    bare_corpus = build_evidence_corpus(profile_no_metric)
    assert not metric_supported("cut costs by 40%", bare_corpus)


# ---------------------------------------------------------------------------
# Generation flow
# ---------------------------------------------------------------------------


async def test_generate_persists_session_questions_event_and_notification():
    mem = _MemRepo()
    bus, notif = _FakeBus(), _FakeNotif()
    app_repo = MagicMock()
    app_repo.get_application = AsyncMock(return_value=_app_row())
    app_repo.get_child = AsyncMock(return_value={
        "id": "int-1", "application_id": "app-1", "name": "Technical Screen",
        "scheduled_at": "2026-03-01T10:00:00Z", "status": "scheduled",
    })
    svc = _service(mem, app_repo, _CannedGateway(_canned_llm_content()), bus, notif)
    p1, p2 = _patched_resume(_resume_profile())
    with p1, p2:
        result = await svc.generate(_auth(), "app-1", interview_id="int-1")

    assert result["status"] == "ready"
    assert result["application_id"] == "app-1"
    assert result["interview_type"] == "technical"
    assert len(result["questions"]) == 6
    assert {q["category"] for q in result["questions"]} >= {"technical", "behavioral", "situational"}
    assert all(q.get("answer_framework", {}).get("steps") for q in result["questions"])
    assert all((q.get("rationale") or "").strip() for q in result["questions"])
    # Event + notification reuse
    assert len(bus.published) == 1
    event = bus.published[0]
    assert isinstance(event, InterviewPrepGenerated)
    assert event.session_id == result["id"]
    assert event.question_count == 6
    assert bus.context is not None
    assert notif.created and notif.created[0]["type"] == "interview_prep_ready"
    # Source metadata tracked for staleness/versioning
    assert result["source_fingerprint"]
    assert result["version"] == 1
    assert result["source_metadata"]["job_title"] == "Backend Engineer"


async def test_generate_uses_correct_application_context():
    """Two applications for one user: prep must use the requested one."""
    mem = _MemRepo()
    app_repo = MagicMock()

    async def _get_app(supabase, user_id, app_id):
        if app_id == "app-behavioral":
            return _app_row(id="app-behavioral", job_title="Engineering Manager", company_name="Globex")
        return _app_row(id="app-1", job_title="Backend Engineer", company_name="Finscale")

    async def _get_child(supabase, app_id, table, child_id):
        if app_id == "app-behavioral":
            return {"id": "int-9", "application_id": app_id, "name": "Behavioral / Values", "status": "scheduled"}
        return {"id": "int-1", "application_id": app_id, "name": "Technical Screen", "status": "scheduled"}

    app_repo.get_application = AsyncMock(side_effect=_get_app)
    app_repo.get_child = AsyncMock(side_effect=_get_child)
    svc = _service(mem, app_repo, _CannedGateway(_canned_llm_content()))
    p1, p2 = _patched_resume(_resume_profile())
    with p1, p2:
        result = await svc.generate(_auth(), "app-behavioral", interview_id="int-9")

    assert result["application_id"] == "app-behavioral"
    assert result["interview_type"] == "behavioral"
    assert result["source_metadata"]["company_name"] == "Globex"


async def test_generation_quality_jd_evidence_no_duplicates():
    mem = _MemRepo()
    app_repo = MagicMock()
    app_repo.get_application = AsyncMock(return_value=_app_row())
    app_repo.get_child = AsyncMock(return_value={"id": "int-1", "name": "Technical Screen", "status": "scheduled"})
    svc = _service(mem, app_repo, _CannedGateway(_canned_llm_content()))
    p1, p2 = _patched_resume(_resume_profile())
    with p1, p2:
        result = await svc.generate(_auth(), "app-1", interview_id="int-1")

    questions = result["questions"]
    assert 5 <= len(questions) <= 10
    texts = [q["question"].strip().lower() for q in questions]
    assert len(set(texts)) == len(texts)  # no duplicates
    assert all(q["category"] in VALID_CATEGORIES for q in questions)
    jd_norm = JD_FIXTURE.lower()
    for q in questions:
        for req in q.get("related_jd_requirements") or []:
            assert req.lower() in jd_norm  # JD mapping is real
        assert q["talking_points"] or q["gaps"]  # useful: points or honest gaps
    joined = " ".join(
        t for q in questions for t in (q.get("talking_points") or [])
    ).lower()
    for missing in ("kubernetes", "kafka", "rust", "graphql"):
        assert missing not in joined  # never presented as candidate experience


# ---------------------------------------------------------------------------
# Failure states (Phase 13): truthful, no fake questions
# ---------------------------------------------------------------------------


async def test_llm_failure_marks_failed_without_fake_questions():
    mem = _MemRepo()
    bus = _FakeBus()
    app_repo = MagicMock()
    app_repo.get_application = AsyncMock(return_value=_app_row())
    svc = _service(mem, app_repo, _FailGateway(), bus)
    p1, p2 = _patched_resume(_resume_profile())
    with p1, p2:
        result = await svc.generate(_auth(), "app-1")

    assert result["status"] == "failed"
    assert result["error"]
    assert result["questions"] == []
    assert bus.published == []  # no success event on failure


async def test_malformed_llm_response_marks_failed():
    mem = _MemRepo()
    app_repo = MagicMock()
    app_repo.get_application = AsyncMock(return_value=_app_row())
    svc = _service(mem, app_repo, _CannedGateway("not json at all {{{"))
    p1, p2 = _patched_resume(_resume_profile())
    with p1, p2:
        result = await svc.generate(_auth(), "app-1")
    assert result["status"] == "failed"
    assert result["questions"] == []


# ---------------------------------------------------------------------------
# Ownership / RLS (Phase 15)
# ---------------------------------------------------------------------------


async def test_generate_rejects_other_users_application():
    app_repo = MagicMock()
    app_repo.get_application = AsyncMock(return_value=None)  # not owned
    svc = _service(_MemRepo(), app_repo, _CannedGateway(_canned_llm_content()))
    with pytest.raises(HTTPException) as exc:
        await svc.generate(_auth("user-A"), "app-other")
    assert exc.value.status_code == 404


async def test_session_and_question_cross_user_isolation():
    mem = _MemRepo()
    app_repo = MagicMock()
    app_repo.get_application = AsyncMock(return_value=_app_row())
    app_repo.get_child = AsyncMock(return_value={"id": "int-1", "name": "Technical Screen", "status": "scheduled"})
    svc = _service(mem, app_repo, _CannedGateway(_canned_llm_content()))
    p1, p2 = _patched_resume(_resume_profile())
    with p1, p2:
        owned = await svc.generate(_auth("user-A"), "app-1", interview_id="int-1")

    # User B cannot read the session…
    with pytest.raises(HTTPException) as exc:
        await svc.get_session(_auth("user-B"), owned["id"])
    assert exc.value.status_code == 404
    # …nor flip its question state (404, not 403, to avoid existence leaks).
    qid = owned["questions"][0]["id"]
    with pytest.raises(HTTPException) as exc2:
        await svc.update_question(_auth("user-B"), qid, {"is_prepared": True})
    assert exc2.value.status_code == 404


# ---------------------------------------------------------------------------
# Regeneration / versioning / staleness (Phase 17)
# ---------------------------------------------------------------------------


async def test_regenerate_bumps_version_and_refreshes_content():
    mem = _MemRepo()
    app_repo = MagicMock()
    app_repo.get_application = AsyncMock(return_value=_app_row())
    app_repo.get_child = AsyncMock(return_value={"id": "int-1", "name": "Technical Screen", "status": "scheduled"})
    gateway = _CannedGateway(_canned_llm_content())
    svc = _service(mem, app_repo, gateway)
    p1, p2 = _patched_resume(_resume_profile())
    with p1, p2:
        first = await svc.generate(_auth(), "app-1", interview_id="int-1")
        second = await svc.regenerate(_auth(), first["id"])

    assert second["id"] == first["id"]  # same session, fresh state
    assert second["version"] == 2
    assert second["status"] == "ready"
    assert len(gateway.requests) == 2  # actually called generation again


async def test_staleness_detected_after_jd_change():
    mem = _MemRepo()
    app_repo = MagicMock()
    app = _app_row()
    app_repo.get_application = AsyncMock(return_value=app)
    app_repo.get_child = AsyncMock(return_value={"id": "int-1", "name": "Technical Screen", "status": "scheduled"})
    svc = _service(mem, app_repo, _CannedGateway(_canned_llm_content()))
    p1, p2 = _patched_resume(_resume_profile())
    with p1, p2:
        created = await svc.generate(_auth(), "app-1", interview_id="int-1")
        fresh = await svc.session_with_staleness(_auth(), created["id"])
        assert fresh["is_stale"] is False

    # Simulate the job description changing underneath the session.
    job_repo = MagicMock()
    job_repo.get_job.return_value = {
        "id": "job-1", "title": "Backend Engineer", "company": "Finscale",
        "description": "Completely rewritten JD about embedded C firmware.",
    }
    resume_repo = MagicMock()
    resume_repo.list_resumes.return_value = []
    resume_repo.get_resume.return_value = {
        "id": "resume-1",
        "user_id": "user-A",
        "content": {"profile": _resume_profile(), "meta": {}},
        "updated_at": "2026-02-01T00:00:00+00:00",
    }
    with patch("app.repositories.resume_repository.ResumeRepository", return_value=resume_repo), \
         patch("app.repositories.job_repository.JobRepository", return_value=job_repo):
        stale = await svc.session_with_staleness(_auth(), created["id"])
    assert stale["is_stale"] is True
    assert stale["stale_reason"]


# ---------------------------------------------------------------------------
# Progress (Phase 21): real counts, no fake scores
# ---------------------------------------------------------------------------


async def test_update_question_tracks_real_progress():
    mem = _MemRepo()
    app_repo = MagicMock()
    app_repo.get_application = AsyncMock(return_value=_app_row())
    app_repo.get_child = AsyncMock(return_value={"id": "int-1", "name": "Technical Screen", "status": "scheduled"})
    svc = _service(mem, app_repo, _CannedGateway(_canned_llm_content()))
    p1, p2 = _patched_resume(_resume_profile())
    with p1, p2:
        created = await svc.generate(_auth(), "app-1", interview_id="int-1")
    assert created["remaining"] == 6

    q1, q2 = created["questions"][0]["id"], created["questions"][1]["id"]
    await svc.update_question(_auth(), q1, {"is_prepared": True})
    await svc.update_question(_auth(), q2, {"is_prepared": True, "is_bookmarked": True})
    reloaded = await svc.get_session(_auth(), created["id"])
    assert reloaded["prepared_total"] == 2
    assert reloaded["bookmarked_total"] == 1
    assert reloaded["remaining"] == 4
    assert "readiness" not in json.dumps(reloaded).lower()  # no fake score field


# ---------------------------------------------------------------------------
# Provider fallback surface: typed errors propagate as truthful failure
# ---------------------------------------------------------------------------


async def test_gateway_uses_interview_prep_task_and_schema():
    gateway = _CannedGateway(_canned_llm_content())
    mem = _MemRepo()
    app_repo = MagicMock()
    app_repo.get_application = AsyncMock(return_value=_app_row())
    svc = _service(mem, app_repo, gateway)
    p1, p2 = _patched_resume(_resume_profile())
    with p1, p2:
        await svc.generate(_auth(), "app-1")
    from app.llm.types import LLMTask

    assert gateway.requests and gateway.requests[0].task == LLMTask.INTERVIEW_PREP_GENERATION
    assert gateway.requests[0].response_schema  # structured output requested


# ---------------------------------------------------------------------------
# Worker (Phase 12)
# ---------------------------------------------------------------------------


async def test_worker_job_registered():
    # Other test modules clear the global job registry (autouse fixtures),
    # so re-register defensively: the decorator is idempotent and this also
    # repairs global state for tests running after us.
    import app.workers.jobs.interview_prep_jobs as job_module
    from app.workers.registry import register_job

    register_job(
        "generate_interview_prep_job",
        timeout=300,
        max_tries=2,
        retry=True,
        description="Generate interview preparation questions for a session in the background.",
    )(job_module.generate_interview_prep_job)
    definition = get_job_definition("generate_interview_prep_job")
    assert definition.max_tries == 2


async def test_worker_rejects_unknown_session():
    from app.workers.jobs.interview_prep_jobs import generate_interview_prep_job

    with patch("app.db.supabase.get_service_client", return_value=MagicMock()), \
         patch.object(InterviewPrepRepository, "get_session", new=AsyncMock(return_value=None)):
        with pytest.raises(ValueError):
            await generate_interview_prep_job({}, "missing", "user-A")


async def test_worker_skips_non_generating_session():
    from app.workers.jobs.interview_prep_jobs import generate_interview_prep_job

    session = {"id": "s-1", "user_id": "user-A", "status": "ready"}
    with patch("app.db.supabase.get_service_client", return_value=MagicMock()), \
         patch.object(InterviewPrepRepository, "get_session", new=AsyncMock(return_value=session)):
        result = await generate_interview_prep_job({}, "s-1", "user-A")
    assert result["skipped"] is True


# ---------------------------------------------------------------------------
# Migration (Phase 14)
# ---------------------------------------------------------------------------


def test_migration_019_defines_tables_and_rls():
    from pathlib import Path

    sql = Path("sql/migrations/019_interview_prep.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS public.interview_prep_sessions" in sql
    assert "CREATE TABLE IF NOT EXISTS public.interview_prep_questions" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "Users manage own interview prep sessions" in sql
    assert "Users manage own interview prep questions" in sql
    assert "ON DELETE CASCADE" in sql


# ---------------------------------------------------------------------------
# API envelopes (Phase 16): thin routes, standard contract
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client():
    from app.main import app
    from app.dependencies import get_current_user

    user = AuthUser(id="user-A", email="user-A@example.com")
    ctx = AuthContext(user=user, supabase=MagicMock(), jwt="jwt-A")
    app.dependency_overrides[get_current_user] = lambda: ctx
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_api_generate_returns_envelope(api_client):
    import app.api.routes.interview_prep as route_module

    fake_session = {"id": "s-1", "status": "ready", "questions": []}
    with patch.object(route_module, "SERVICE") as svc:
        svc.generate = AsyncMock(return_value=fake_session)
        resp = api_client.post(
            "/api/interview-prep/generate",
            json={"application_id": "app-1", "interview_id": "int-1"},
        )
    assert resp.status_code == 201
    assert resp.json()["success"] is True
    assert resp.json()["data"]["id"] == "s-1"


def test_api_generate_requires_application_id(api_client):
    resp = api_client.post("/api/interview-prep/generate", json={"application_id": ""})
    assert resp.status_code == 400


def test_api_session_not_found_envelope(api_client):
    import app.api.routes.interview_prep as route_module

    with patch.object(route_module, "SERVICE") as svc:
        svc.session_with_staleness = AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Preparation session not found")
        )
        resp = api_client.get("/api/interview-prep/sessions/missing")
    assert resp.status_code == 404
    assert resp.json()["success"] is False


def test_api_update_question_envelope(api_client):
    import app.api.routes.interview_prep as route_module

    with patch.object(route_module, "SERVICE") as svc:
        svc.update_question = AsyncMock(return_value={"id": "q-1", "is_prepared": True})
        resp = api_client.patch("/api/interview-prep/questions/q-1", json={"is_prepared": True})
    assert resp.status_code == 200
    assert resp.json()["data"]["is_prepared"] is True


def test_api_regenerate_envelope(api_client):
    import app.api.routes.interview_prep as route_module

    with patch.object(route_module, "SERVICE") as svc:
        svc.regenerate = AsyncMock(return_value={"id": "s-1", "status": "ready", "version": 2})
        resp = api_client.post("/api/interview-prep/sessions/s-1/regenerate")
    assert resp.status_code == 200
    assert resp.json()["data"]["version"] == 2


def test_api_list_by_application_envelope(api_client):
    import app.api.routes.interview_prep as route_module

    with patch.object(route_module, "SERVICE") as svc:
        svc.list_sessions = AsyncMock(return_value={"sessions": [{"id": "s-1"}], "total": 1})
        resp = api_client.get("/api/interview-prep/by-application/app-1")
    assert resp.status_code == 200
    assert resp.json()["data"] == [{"id": "s-1"}]
