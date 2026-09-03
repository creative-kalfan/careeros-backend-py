"""Tests for health check endpoints."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check_root():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_check_no_api_prefix():
    """/health is the canonical liveness endpoint. Routers are mounted
    without an /api prefix (see app/main.py), so /api/health is
    intentionally NOT part of the contract (verified against git history).
    """
    assert client.get("/api/health").status_code == 404
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

