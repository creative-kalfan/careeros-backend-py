import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_user
from app.auth.service import AuthContext, AuthUser
from app.models.resume_ast import ExperienceNode

client = TestClient(app)


def test_translate_project_endpoint():
    fake_user = AuthUser(
        id="user-123",
        email="dev@example.com",
        role="user",
    )
    fake_supabase = MagicMock()
    fake_query = MagicMock()
    fake_query.select.return_value = fake_query
    fake_query.eq.return_value = fake_query
    fake_query.order.return_value = fake_query
    fake_query.limit.return_value = fake_query
    fake_query.execute.return_value = MagicMock(
        data=[
            {"skill_name": "FastAPI"},
            {"skill_name": "PostgreSQL"},
            {"skill_name": "Docker"},
            {"skill_name": "Redis"},
        ]
    )
    fake_supabase.table.return_value = fake_query

    fake_auth = AuthContext(
        user=fake_user,
        supabase=fake_supabase,
        jwt="bearer-token",
    )

    app.dependency_overrides[get_current_user] = lambda: fake_auth

    mock_llm_response = MagicMock()
    mock_llm_response.content = json.dumps({
        "type": "experience",
        "company": "Personal Project - CareerOS",
        "role": "Senior Backend Engineer",
        "description": "Architected and deployed high-throughput backend services.",
        "start_date": "2024-01",
        "end_date": "Present",
        "bullets": [
            "Engineered distributed web crawlers using FastAPI, Redis, and PostgreSQL handling 50k+ jobs daily.",
            "Containerized backend microservices with Docker, achieving 99.9% uptime and sub-100ms API response latency."
        ]
    })

    try:
        with patch("app.llm.gateway.LLMGateway.generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_llm_response

            payload = {
                "project_details": "I built an open source job scraper and tracker using python, postgresql and docker.",
                "role_title": "Senior Backend Engineer",
            }
            # Test singular /api/resume/translate-project
            resp = client.post("/api/resume/translate-project", json=payload)
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            node = data["data"]
            assert node["type"] == "experience"
            assert node["role"] == "Senior Backend Engineer"
            assert node["company"] == "Personal Project - CareerOS"
            assert len(node["bullets"]) == 2
            assert "FastAPI" in node["bullets"][0]

            # Verify it validates strictly as ExperienceNode
            validated = ExperienceNode.model_validate(node)
            assert validated.role == "Senior Backend Engineer"

            # Also test plural /api/resumes/translate-project
            resp_plural = client.post("/api/resumes/translate-project", json=payload)
            assert resp_plural.status_code == 200
            assert resp_plural.json()["success"] is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)
