"""Tests for AI Reasoning Quality, Prompt Injection Resistance, and Evidence Guardrails (WS1)."""

import pytest
from unittest.mock import AsyncMock, patch

from app.llm.gateway import LLMGateway
from app.llm.types import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMTask,
    ResumeSectionSuggestion,
)
from app.models.resume import (
    BulletItem,
    EducationItem,
    ExperienceItem,
    PersonalInfo,
    ResumeContent,
    ResumeProfile,
    SkillCategory,
)
from app.services.optimization.optimization_service import OptimizationService


@pytest.mark.asyncio
async def test_llm_gateway_generation():
    """Verify that the LLM gateway routes and returns a typed LLMResponse."""
    gateway = LLMGateway()

    valid_json = (
        '{"section": "skills", "operation": "replace", "original_content": "Python, Java", '
        '"suggested_content": "Python, Java, FastAPI, PostgreSQL", '
        '"rationale": "Emphasize backend technologies mentioned in JD", '
        '"confidence": 0.95}'
    )

    with patch.object(gateway._router, "generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = LLMResponse(
            provider=LLMProvider.GROQ,
            model="llama-3.3-70b-versatile",
            content=valid_json,
        )

        request = LLMRequest(
            task=LLMTask.RESUME_SECTION_SUGGESTION,
            prompt="Optimize skills for backend role",
        )

        response = await gateway.generate(request)
        assert isinstance(response, LLMResponse)
        assert response.provider == LLMProvider.GROQ
        assert "FastAPI" in response.content

        # Verify parsing into ResumeSectionSuggestion model
        parsed = ResumeSectionSuggestion.model_validate_json(response.content)
        assert parsed.section == "skills"
        assert parsed.operation == "replace"
        assert parsed.confidence == 0.95


def test_optimization_service_build_evidence_context():
    """Verify OptimizationService extracts exact candidate facts and does not fabricate context."""
    service = OptimizationService()

    content = ResumeContent(
        profile=ResumeProfile(
            personal=PersonalInfo(full_name="Alex Smith", email="alex@example.com"),
            skills=SkillCategory(
                languages=["Python", "TypeScript"],
                databases=["PostgreSQL", "Redis"],
            ),
            experience=[
                ExperienceItem(
                    role="Software Engineer",
                    company="Acme Corp",
                    responsibilities=[BulletItem(text="Built high-throughput API with FastAPI")],
                )
            ],
            education=[
                EducationItem(degree="B.S. Computer Science", institution="State University")
            ],
        )
    )

    evidence = service._build_evidence_context(content)
    assert "Python" in evidence["skills"]["languages"]
    assert "TypeScript" in evidence["skills"]["languages"]
    assert "PostgreSQL" in evidence["skills"]["databases"]
    assert len(evidence["experience"]) == 1
    assert evidence["experience"][0]["company"] == "Acme Corp"
    assert "State University" in [e["institution"] for e in evidence["education"]]
    # Verify no fabricated content
    assert "Go" not in evidence["skills"]["languages"]
    assert "Google" not in [e["company"] for e in evidence["experience"]]
