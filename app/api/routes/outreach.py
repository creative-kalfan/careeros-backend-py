"""Outreach API routes.

Provides endpoints for generating personalized, high-conversion cold emails
and referral messages connecting candidate resume experience with job requirements.
"""

from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.repositories.job_repository import JobRepository
from app.repositories.resume_repository import ResumeRepository
from app.schemas.common import SuccessResponse
from app.llm import get_llm_gateway
from app.llm.types import LLMProvider, LLMRequest, LLMTask

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/outreach", tags=["outreach"])


class OutreachGenerateRequest(BaseModel):
    resume_id: str = Field(description="ID of candidate's resume")
    job_id: str = Field(description="ID of target job")


class OutreachGenerateResponse(BaseModel):
    message: str = Field(description="Generated 3-line personalized outreach email or message")


@router.post("/generate", response_model=SuccessResponse[OutreachGenerateResponse])
async def generate_outreach(
    body: OutreachGenerateRequest,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[OutreachGenerateResponse]:
    """Generate a concise, 3-line cold email/referral pitch based on Resume and Job tech stack intersection."""
    # 1. Fetch Resume
    resume_repo = ResumeRepository(auth.supabase)
    resume = resume_repo.get_resume(auth.user.id, body.resume_id)
    if not resume:
        # Fallback query if resume is stored globally
        resume = resume_repo.get_by_id(body.resume_id)
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found",
        )

    # 2. Fetch Job
    job = JobRepository().get_job(body.job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    job_title = job.get("title") or "Software Engineer"
    company = job.get("company") or "the team"
    job_desc = job.get("description") or ""
    job_skills = job.get("skills") or []
    if isinstance(job_skills, list):
        job_skills_str = ", ".join(job_skills)
    else:
        job_skills_str = str(job_skills)

    # 3. Extract candidate background highlights
    content = resume.get("content") or {}
    profile = content.get("profile") or {}
    personal = profile.get("personal") or {}
    candidate_name = personal.get("fullName") or personal.get("name") or "Candidate"
    skills_obj = profile.get("skills") or {}
    experiences = profile.get("experience") or []

    candidate_skills = []
    if isinstance(skills_obj, dict):
        for k in ("technical", "tools", "languages", "databases", "analytics"):
            val = skills_obj.get(k)
            if isinstance(val, list):
                candidate_skills.extend(val)
    elif isinstance(skills_obj, list):
        candidate_skills.extend(skills_obj)

    exp_summary = []
    if isinstance(experiences, list):
        for exp in experiences[:2]:
            role = exp.get("role") or exp.get("title") or ""
            comp = exp.get("company") or ""
            bullets = exp.get("bullets") or []
            bullet_str = bullets[0] if bullets else ""
            if role or comp:
                exp_summary.append(f"{role} at {comp}: {bullet_str}")

    candidate_background = (
        f"Name: {candidate_name}\n"
        f"Skills: {', '.join(candidate_skills[:15])}\n"
        f"Recent Experience: {'; '.join(exp_summary)}"
    )

    # 4. Construct strict 3-line prompt for Groq LLM
    prompt = (
        f"You are an elite Tech Career Coach & Referral Strategist.\n"
        f"Draft a concise, high-conversion cold outreach message (email/LinkedIn) from the candidate to a hiring manager or engineer at {company} for the role of '{job_title}'.\n\n"
        f"Candidate Profile:\n{candidate_background}\n\n"
        f"Target Job Requirements & Tech Stack:\nTitle: {job_title}\nCompany: {company}\nRequired Skills: {job_skills_str}\nDescription excerpt: {job_desc[:500]}\n\n"
        f"STRICT RULES:\n"
        f"1. Exactly 3 lines total. No more, no less.\n"
        f"2. You MUST highlight the EXACT intersection between the job's tech stack and the candidate's technical achievements/skills.\n"
        f"3. Line 1: Clear, personalized hook acknowledging the company's work and candidate's matching specialization.\n"
        f"4. Line 2: Concrete technical proof point proving hands-on proficiency in the shared tech stack.\n"
        f"5. Line 3: Direct, low-friction call to action asking for a quick 10-minute chat or referral.\n"
        f"6. Output ONLY the 3 lines of message text. No subject line, no greetings like 'Dear Sir', no placeholders like [Your Name] if known (use '{candidate_name}'), no extra commentary."
    )

    llm = get_llm_gateway()
    try:
        response = await llm.generate(
            LLMRequest(
                task=LLMTask.RESUME_SECTION_SUGGESTION,
                prompt=prompt,
                system_instruction="You write strictly 3-line cold emails highlighting tech intersections. Return plain text only.",
                provider=LLMProvider.GROQ,
                temperature=0.3,
            )
        )
        message_text = response.content.strip()
    except Exception as exc:
        logger.exception("Failed to generate cold outreach email via Groq: %s", exc)
        # Fallback deterministic 3-line message
        shared_skills = candidate_skills[0] if candidate_skills else "Python & distributed systems"
        message_text = (
            f"Hi team, I noticed {company} is expanding its {job_title} team and wanted to reach out regarding your tech stack.\n"
            f"My background in {shared_skills} directly aligns with what you're building, having delivered high-throughput production systems.\n"
            f"Would you be open to a brief 10-minute chat this week to discuss how I can contribute to {company}?"
        )

    return SuccessResponse(data=OutreachGenerateResponse(message=message_text))
