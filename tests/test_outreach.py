import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_user
from app.auth.service import AuthContext, AuthUser

client = TestClient(app)


def test_generate_outreach_endpoint():
    fake_user = AuthUser(
        id="user-456",
        email="candidate@example.com",
        role="user",
    )
    fake_supabase = MagicMock()
    fake_auth = AuthContext(
        user=fake_user,
        supabase=fake_supabase,
        jwt="test-jwt",
    )

    app.dependency_overrides[get_current_user] = lambda: fake_auth

    fake_resume = {
        "id": "res-123",
        "user_id": "user-456",
        "content": {
            "profile": {
                "personal": {"fullName": "Alex Developer"},
                "skills": {
                    "technical": ["Python", "FastAPI", "Redis", "PostgreSQL", "Docker"]
                },
                "experience": [
                    {
                        "role": "Backend Engineer",
                        "company": "Startup X",
                        "bullets": ["Scaled FastAPI microservices to handle 10k RPS."]
                    }
                ]
            }
        }
    }

    fake_job = {
        "id": "job-789",
        "title": "Staff Backend Engineer",
        "company": "Swiggy",
        "description": "Looking for high-scale Python, FastAPI, and Redis experts.",
        "skills": ["Python", "FastAPI", "Redis"],
    }

    try:
        with patch("app.repositories.resume_repository.ResumeRepository.get_resume", return_value=fake_resume), \
             patch("app.repositories.job_repository.JobRepository.get_job", return_value=fake_job), \
             patch("app.llm.gateway.LLMGateway.generate", new_callable=AsyncMock) as mock_llm_gen:

            mock_response = MagicMock()
            mock_response.content = (
                "Hi Swiggy team, I saw you're expanding your Staff Backend team and wanted to connect.\n"
                "At Startup X, I scaled FastAPI microservices with Redis to 10k RPS, exactly matching your backend stack.\n"
                "Would you be open to a 10-minute chat this week to explore how I could contribute to your infrastructure?"
            )
            mock_llm_gen.return_value = mock_response

            payload = {
                "resume_id": "res-123",
                "job_id": "job-789",
            }
            res = client.post("/api/outreach/generate", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            msg = data["data"]["message"]
            lines = [l for l in msg.strip().splitlines() if l.strip()]
            assert len(lines) == 3
            assert "Swiggy" in lines[0]
            assert "FastAPI" in lines[1]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
