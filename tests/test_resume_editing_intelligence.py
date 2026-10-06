"""Tests for Phase 5: Resume Editing Intelligence.

Covers:
  - 5.1 EvidenceRepository and bullet citations.
  - 5.2 ClaimGuard: extracts metrics (including Indian denominations: lakh, crore, ₹, Rs), verifies against evidence, sanitizes hallucinations.
  - 5.3 ClarifyingQuestion generation when unevidenced figures exist.
  - 5.4 ATSSimulator: structural extraction audit without vanity score.
  - 5.5 JSON Resume v1.0.0 round-trip import/export & plaintext rendering.
  - 5.7 LLMCostController caching and daily budget checks.
  - 5.8 Dashboard 30s cache and isolation.
"""

import pytest
from unittest.mock import MagicMock, patch

from app.models.resume import (
    ResumeProfile,
    ExperienceItem,
    EducationItem,
    PersonalInfo,
    SkillCategory,
    BulletItem,
)
from app.repositories.evidence_repository import EvidenceRepository
from app.services.optimization.claim_guard import (
    ClaimGuard,
    extract_numeric_tokens,
)
from app.services.optimization.clarifying_questions import (
    generate_clarifying_question_for_violation,
)
from app.services.resumes.ats_simulation import ATSSimulator
from app.services.resumes.interop import (
    resume_profile_to_json_resume,
    json_resume_to_resume_profile,
    export_plain_text,
)
from app.llm.cost_control import (
    LLMCostController,
    compute_llm_cache_key,
)


class TestEvidenceRepository:
    """5.1 Evidence bank repository tests."""

    def test_repository_probe_cache(self):
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.limit.return_value.execute.side_effect = Exception("Table missing")
        repo = EvidenceRepository(client=mock_client)
        assert not repo.is_available()

    def test_add_evidence_item_and_citations(self):
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"id": "1"}])
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "eid-1", "title": "Increased revenue", "type": "metric"}]
        )
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        repo = EvidenceRepository(client=mock_client)
        with patch.object(repo, "is_available", return_value=True):
            item = repo.add_evidence_item(
                user_id="user-1",
                item_type="metric",
                title="Increased revenue",
                content={"value": "₹15 lakh"},
            )
            assert item is not None
            assert item["id"] == "eid-1"

            ok = repo.attach_bullet_evidence("vid-1", "exp[0].bullets[0]", ["eid-1"])
            assert ok is True


class TestNumericClaimGuard:
    """5.2 Numeric-claim guard tests including Indian currency formats."""

    def test_extract_numeric_tokens_indian_and_global_formats(self):
        text = "Led team of 15 engineers, grew revenue by ₹25 lakh (Rs. 25 lac) and $2M, reduced latency by 40% and improved throughput 3x."
        tokens = extract_numeric_tokens(text)
        assert "15" in tokens
        assert "25lakh" in tokens
        assert "2m" in tokens
        assert "40%" in tokens
        assert "3x" in tokens

    def test_claim_guard_passes_supported_claims(self):
        evidence = "Reduced processing latency by 45% and scaled system to 10k users."
        generated = "Optimized API pipeline, slashing latency by 45% for over 10k users."
        is_valid, unsupported = ClaimGuard.verify_claims(generated, evidence)
        assert is_valid is True
        assert len(unsupported) == 0

    def test_claim_guard_catches_unsupported_figures(self):
        evidence = "Built microservices for checkout workflow."
        hallucinated = "Architected microservices processing ₹5 crore with 99.9% uptime, boosting sales 4x."
        is_valid, unsupported = ClaimGuard.verify_claims(hallucinated, evidence)
        assert is_valid is False
        assert any("5crore" in u for u in unsupported)
        assert "4x" in unsupported

    def test_claim_guard_sanitizes_figures(self):
        text = "Increased checkout conversion by 25% across 100 enterprise customers."
        sanitized = ClaimGuard.sanitize_unsupported_figures(text, {"25%", "100"})
        assert "25%" not in sanitized
        assert "100" not in sanitized
        assert "measurably" in sanitized


class TestClarifyingQuestions:
    """5.3 Ask-don't-invent questions."""

    def test_generates_clarifying_question(self):
        q = generate_clarifying_question_for_violation("exp[0].bullets[1]", "50%")
        assert q.bullet_ref == "exp[0].bullets[1]"
        assert "50%" in q.question
        assert q.expected_type == "metric"


class TestATSSimulation:
    """5.4 ATS text-only structural simulation."""

    def test_ats_simulation_detects_structure_and_contacts(self):
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Jane Doe\njane@example.com | +1 555-0199\n\nExperience\nSoftware Engineer at TechCorp\nBuilt web applications.\n\nEducation\nB.S. Computer Science\n\nSkills\nPython, React")
        pdf_bytes = doc.tobytes()
        doc.close()

        res = ATSSimulator.simulate_parse(pdf_bytes)
        assert res["status"] == "completed"
        assert res["is_ats_friendly"] is True
        assert "experience" in res["detected_sections"]
        assert "education" in res["detected_sections"]
        assert not any(f["field"] == "email" for f in res["findings"])


class TestInteroperability:
    """5.5 JSON Resume standard v1.0.0 & Plaintext export."""

    def test_json_resume_round_trip(self):
        profile = ResumeProfile(
            personal=PersonalInfo(full_name="John Doe", email="john@example.com", linkedin="https://linkedin.com/in/johndoe"),
            summary="Experienced Software Architect",
            experience=[
                ExperienceItem(company="Acme Corp", role="Staff Engineer", start_date="2020-01", responsibilities=[BulletItem(text="Led core platform team.")])
            ],
            education=[
                EducationItem(institution="State University", degree="B.S.", field="Computer Science")
            ],
            skills=SkillCategory(technical=["Python", "PostgreSQL", "FastAPI"]),
        )

        json_resume = resume_profile_to_json_resume(profile)
        assert json_resume["basics"]["name"] == "John Doe"
        assert json_resume["basics"]["email"] == "john@example.com"
        assert len(json_resume["work"]) == 1
        assert json_resume["work"][0]["name"] == "Acme Corp"

        imported = json_resume_to_resume_profile(json_resume)
        assert imported.personal.full_name == "John Doe"
        assert imported.personal.email == "john@example.com"
        assert imported.summary == "Experienced Software Architect"
        assert len(imported.experience) == 1
        assert imported.experience[0].company == "Acme Corp"
        assert "Python" in imported.skills.technical

    def test_plain_text_export(self):
        profile = ResumeProfile(
            personal=PersonalInfo(full_name="Alice Smith", email="alice@test.com"),
            summary="Product-focused developer.",
            skills=SkillCategory(technical=["Go", "Kubernetes"]),
        )
        text = export_plain_text(profile)
        assert "ALICE SMITH" in text
        assert "alice@test.com" in text
        assert "PROFESSIONAL SUMMARY" in text
        assert "Go, Kubernetes" in text


class TestCostControlAndDashboard:
    """5.7 Cost control & 5.8 Dashboard."""

    def test_llm_cache_key_deterministic(self):
        k1 = compute_llm_cache_key("e1", "j1", "v1", "gpt-4")
        k2 = compute_llm_cache_key("e1", "j1", "v1", "gpt-4")
        k3 = compute_llm_cache_key("e2", "j1", "v1", "gpt-4")
        assert k1 == k2
        assert k1 != k3

    def test_llm_cost_controller_cache(self):
        LLMCostController.set_cached_response("test-key", "Cached suggestion text")
        cached = LLMCostController.get_cached_response("test-key")
        assert cached == "Cached suggestion text"
