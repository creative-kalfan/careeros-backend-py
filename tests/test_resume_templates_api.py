"""Tests for resume template API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.resume_template_repository import ResumeTemplateRepository


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def base_template_row() -> dict:
    return {
        "id": "template-uuid-123",
        "slug": "faangpath-simple",
        "name": "FAANGPath Simple",
        "description": "A clean ATS-friendly template.",
        "source_repository": "FAANGPath/FAANGPath-Simple",
        "source_url": "https://github.com/FAANGPath/FAANGPath-Simple",
        "author": "FAANGPath",
        "license": "MIT",
        "license_url": "https://opensource.org/licenses/MIT",
        "attribution_required": False,
        "modification_allowed": True,
        "redistribution_allowed": True,
        "layout_type": "single-column",
        "column_count": 1,
        "page_preference": "one-page",
        "ats_characteristics": {
            "single_column": True,
            "tables": False,
            "icons": False,
            "graphics": False,
        },
        "target_roles": ["Software Engineer", "Data Engineer"],
        "target_industries": ["Technology"],
        "target_experience_levels": ["entry", "mid", "senior"],
        "evidence_type": "community",
        "evidence_description": "Popular open-source template.",
        "preview_url": "/templates/faangpath-simple/preview.png",
        "template_path": "templates/faangpath-simple",
        "status": "active",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }


def test_list_templates_returns_active_templates(
    client: TestClient, base_template_row: dict
) -> None:
    with patch.object(ResumeTemplateRepository, "list_templates", return_value=[base_template_row]):
        response = client.get("/api/templates")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["data"]["templates"]) == 1
    assert data["data"]["templates"][0]["slug"] == "faangpath-simple"
    assert data["data"]["templates"][0]["name"] == "FAANGPath Simple"


def test_get_template_by_id(
    client: TestClient, base_template_row: dict
) -> None:
    with patch.object(ResumeTemplateRepository, "get_template_by_id", return_value=base_template_row):
        response = client.get("/api/templates/template-uuid-123")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["slug"] == "faangpath-simple"


def test_get_template_by_slug(
    client: TestClient, base_template_row: dict
) -> None:
    with patch.object(ResumeTemplateRepository, "get_template_by_id", return_value=None):
        with patch.object(ResumeTemplateRepository, "get_template_by_slug", return_value=base_template_row):
            response = client.get("/api/templates/faangpath-simple")
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["slug"] == "faangpath-simple"


def test_get_template_not_found(client: TestClient) -> None:
    with patch.object(ResumeTemplateRepository, "get_template_by_id", return_value=None):
        with patch.object(ResumeTemplateRepository, "get_template_by_slug", return_value=None):
            response = client.get("/api/templates/nonexistent")
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Template not found"


def test_list_templates_empty(client: TestClient) -> None:
    with patch.object(ResumeTemplateRepository, "list_templates", return_value=[]):
        response = client.get("/api/templates")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["data"]["templates"]) == 0
    assert data["data"]["total"] == 0


def test_template_metadata_fields(
    client: TestClient, base_template_row: dict
) -> None:
    with patch.object(ResumeTemplateRepository, "list_templates", return_value=[base_template_row]):
        response = client.get("/api/templates")
    assert response.status_code == 200
    tmpl = response.json()["data"]["templates"][0]
    assert tmpl["sourceUrl"] == "https://github.com/FAANGPath/FAANGPath-Simple"
    assert tmpl["license"] == "MIT"
    assert tmpl["licenseUrl"] == "https://opensource.org/licenses/MIT"
    assert tmpl["attributionRequired"] is False
    assert tmpl["layoutType"] == "single-column"
    assert tmpl["columnCount"] == 1
    assert tmpl["pagePreference"] == "one-page"
    assert tmpl["status"] == "active"
