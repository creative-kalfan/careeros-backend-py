"""Regression tests for POST /api/resumes/{id}/versions/apply-tailoring failures.

Covers the Finance Associate incident class:
- S3: stale/missing parent_version_id must be a structured 404, never a bare 500.
- Parent versions belonging to another resume must be a structured 400.
- SEMANTIC_FABRICATION 422s must carry a string message plus structured details
  (the error envelope requires message: str).
- run_coro_sync must execute coroutines from inside a running event loop
  (asyncio.run() raises RuntimeError there and silently disabled all LLM calls
  made through async route handlers) and enforce its timeout budget.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from app.auth.service import AuthContext, AuthUser
from app.dependencies import get_current_user
from app.llm.sync_bridge import run_coro_sync
from app.llm.types import LLMProviderError
from app.main import app
from app.models.resume import (
    BulletItem,
    ExperienceItem,
    PersonalInfo,
    ResumeContent,
    ResumeProfile,
    SkillCategory,
)
from app.repositories.resume_repository import ResumeRepository
from app.services.resumes.compiler_service import resume_compiler_service


def _sample_content() -> ResumeContent:
    return ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Jane Doe", email="jane@example.com"),
            summary="Senior Software Engineer with 6 years building distributed systems.",
            skills=SkillCategory(technical=["Python", "FastAPI"], tools=["Git"]),
            experience=[
                ExperienceItem(
                    company="Acme Corp",
                    role="Senior Backend Engineer",
                    responsibilities=[BulletItem(text="Built services handling 10k RPS.")],
                    tools=["Python"],
                )
            ],
        )
    )


def _client() -> TestClient:
    user = AuthUser(id="user-123", email="user@example.com")
    auth_ctx = AuthContext(user=user, supabase=MagicMock(), jwt="fake-jwt-token")
    app.dependency_overrides[get_current_user] = lambda: auth_ctx
    return TestClient(app, raise_server_exceptions=False)


def _teardown() -> None:
    app.dependency_overrides.pop(get_current_user, None)


_MOCK_RESUME = {
    "id": "resume-123",
    "user_id": "user-123",
    "title": "Master",
    "content": _sample_content().to_dict(),
}
_MOCK_VER = {
    "id": "ver-new-123",
    "resume_id": "resume-123",
    "version_name": "V",
    "source": "job_specific",
    "content": _sample_content().to_dict(),
    "meta": {},
    "status": "active",
    "is_master": False,
    "created_at": "2026-09-05T10:00:00Z",
    "updated_at": "2026-09-05T10:00:00Z",
}
_MOCK_COMPILE = {
    "storage_path": "u/versions/ver-new-123.pdf",
    "docx_storage_path": "u/versions/ver-new-123.docx",
    "geometry": {"pages": []},
    "strategy": "document_compiler",
}


def _post(client: TestClient, payload: dict, get_version=None):
    with patch.object(ResumeRepository, "get_resume", return_value=_MOCK_RESUME), \
        patch.object(ResumeRepository, "get_version", side_effect=get_version), \
        patch.object(ResumeRepository, "create_version", return_value=dict(_MOCK_VER)), \
        patch.object(ResumeRepository, "update_version", return_value=dict(_MOCK_VER)), \
        patch.object(ResumeRepository, "delete_version", return_value=True), \
        patch.object(resume_compiler_service, "compile_and_persist", return_value=_MOCK_COMPILE):
        return client.post("/api/resumes/resume-123/versions/apply-tailoring", json=payload)


def test_stale_parent_version_returns_structured_404_not_500() -> None:
    client = _client()
    try:
        def _raise(vid: str):
            raise Exception('{"code":"PGRST116","message":"0 rows"}')

        res = _post(
            client,
            {
                "parent_version_id": "00000000-0000-0000-0000-000000000000",
                "tailored_profile": _sample_content().profile.to_dict(),
                "job_description": "Lead Python Developer with FastAPI.",
                "job_title": "Lead Python Developer",
            },
            get_version=_raise,
        )
        assert res.status_code == 404
        body = res.json()
        assert body["success"] is False
        assert body["error"]["code"] == "PARENT_VERSION_NOT_FOUND"
        assert isinstance(body["error"]["message"], str)
        assert "deleted" in body["error"]["message"]
    finally:
        _teardown()


def test_parent_version_from_other_resume_returns_400() -> None:
    client = _client()
    try:
        other = dict(_sample_content().to_dict())
        res = _post(
            client,
            {
                "parent_version_id": "ver-other-resume",
                "tailored_profile": _sample_content().profile.to_dict(),
                "job_description": "Lead Python Developer with FastAPI.",
                "job_title": "Lead Python Developer",
            },
            get_version=lambda vid: {**_MOCK_VER, "id": vid, "resume_id": "resume-OTHER"},
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "VERSION_RESUME_MISMATCH"
    finally:
        _teardown()


def test_semantic_block_returns_string_message_with_details() -> None:
    client = _client()
    try:
        tailored = _sample_content().profile.to_dict()
        tailored["skills"]["technical"] = ["Python", "Financial Modeling"]
        res = _post(
            client,
            {
                "tailored_profile": tailored,
                "job_description": "Finance Associate: reconciliation, financial modeling.",
                "job_title": "Finance Associate",
            },
            get_version=lambda vid: None,
        )
        assert res.status_code == 422
        body = res.json()
        assert body["error"]["code"] == "SEMANTIC_FABRICATION"
        assert isinstance(body["error"]["message"], str)
        assert isinstance(body["error"]["details"], list)
        assert body["error"]["details"]
    finally:
        _teardown()


def test_deterministic_tailor_output_passes_semantic_guard() -> None:
    """The deterministic tailor must not write JD terms the candidate lacks.

    Regression: it injected raw JD requirements (e.g. Kubernetes) into the
    summary, so apply-tailoring's own semantic guard rejected the pipeline's
    own output with SEMANTIC_FABRICATION.
    """
    from app.services.optimization.semantic_guard import semantic_guard
    from app.services.optimization.whole_resume_tailoring_service import (
        whole_resume_tailoring_service,
    )

    result = whole_resume_tailoring_service.tailor_resume(
        resume_content=_sample_content(),
        job_description=(
            "Lead Python Developer. Requirements: FastAPI, PostgreSQL, AWS, "
            "Docker, Kubernetes, microservices, team leadership."
        ),
        job_title="Lead Python Developer",
        company="ScaleTech",
    )
    _, issues = semantic_guard.audit_tailored_profile(
        _sample_content().profile, result.tailored_profile
    )
    assert issues == []


def test_run_coro_sync_inside_running_loop() -> None:
    async def _main() -> str:
        async def _coro() -> str:
            await asyncio.sleep(0)
            return "llm-ok"

        # asyncio.run() would raise RuntimeError here; the bridge must not.
        return run_coro_sync(_coro(), timeout_seconds=5.0)

    assert asyncio.run(_main()) == "llm-ok"


def test_run_coro_sync_timeout_raises_typed_error() -> None:
    async def _main() -> None:
        async def _hang() -> str:
            await asyncio.sleep(30)
            return "never"

        with pytest.raises(LLMProviderError):
            run_coro_sync(_hang(), timeout_seconds=0.2)

    asyncio.run(_main())


def test_run_coro_sync_outside_loop() -> None:
    async def _coro() -> int:
        return 42

    assert run_coro_sync(_coro(), timeout_seconds=5.0) == 42
