"""Prompt construction for interview preparation generation.

Context minimization: only the target role/company, interview type, relevant
JD excerpt, selected resume evidence, and application context are sent. The
full resume profile is never dumped blindly — evidence is pre-selected by
``select_relevant_evidence``.
"""

from __future__ import annotations

from typing import Any

from app.models.interview_prep import CATEGORY_LABELS, plan_categories

MAX_JD_CHARS = 3000
MAX_EVIDENCE_CHARS = 3500

SYSTEM_INSTRUCTION = """You are a precise interview-preparation coach inside CareerOS.
Generate role-specific interview questions grounded ONLY in the provided candidate evidence and job description.

HARD RULES — never violate these:
1. NEVER invent employers, projects, technologies, metrics, responsibilities, certifications, education, achievements, customers, revenue figures, performance percentages, or years of experience.
2. Every resume_evidence string must be traceable to the CANDIDATE EVIDENCE section. If no evidence supports a question angle, put exactly "Not supported by current resume evidence." as the evidence and list the angle under gaps.
3. NEVER claim the candidate has experience with a JD requirement that does not appear in the candidate evidence. Name such requirements under gaps instead.
4. Do NOT output massive essay answers. Provide concise talking_points (short phrases anchored in real evidence) and let the answer_framework structure the candidate's own answer.
5. Return ONLY a single JSON object with fields: questions (array of {category, question, difficulty, rationale, resume_evidence, talking_points, expected_signals, related_jd_requirements, gaps}), assumption_note (string), gaps (array of strings).
6. Categories must be exactly: behavioral, technical, role_specific, resume_deep_dive, situational, company_context. Difficulty must be foundational, intermediate, or advanced.
7. Prefer 5-10 high-quality, non-duplicative questions with a clear reason to exist. Avoid superficial keyword variations."""


def truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…[truncated]"


def select_relevant_evidence(profile: dict[str, Any], jd_text: str, limit: int = MAX_EVIDENCE_CHARS) -> str:
    """Select resume evidence relevant to the JD instead of dumping everything.

    Scores each evidence chunk by token overlap with the JD and keeps the
    highest-signal chunks within the character budget. Falls back to summary
    + skills + most recent experience when the JD is empty.
    """
    from app.services.interview_prep.grounding import normalize
    import re

    chunks: list[str] = []
    if profile.get("summary"):
        chunks.append(f"Summary: {profile['summary']}")
    skills = profile.get("skills") or {}
    skill_bits: list[str] = []
    for key in ("technical", "tools", "languages", "databases", "analytics", "soft_skills"):
        skill_bits.extend(skills.get(key) or [])
    if skill_bits:
        chunks.append("Skills: " + ", ".join(skill_bits[:40]))
    for exp in list(profile.get("experience") or [])[:4]:
        if not isinstance(exp, dict):
            continue
        header = " / ".join(x for x in (exp.get("role"), exp.get("company")) if x)
        bullets: list[str] = []
        for b in (exp.get("responsibilities") or [])[:6]:
            bullets.append(b.get("text") if isinstance(b, dict) else str(b))
        bullets.extend((exp.get("achievements") or [])[:4])
        if exp.get("metrics"):
            bullets.append(str(exp["metrics"]))
        if header or bullets:
            chunks.append(f"{header}: " + " | ".join(b for b in bullets if b)[:600])
    for proj in list(profile.get("projects") or [])[:4]:
        if not isinstance(proj, dict):
            continue
        techs = ", ".join(proj.get("technologies") or [])
        body = " — ".join(x for x in (proj.get("description"), proj.get("results"), proj.get("metrics")) if x)
        chunks.append(f"Project {proj.get('name') or ''} [{techs}]: {body}"[:600])
    for cert in list(profile.get("certifications") or [])[:6]:
        name = cert.get("name") if isinstance(cert, dict) else str(cert)
        if name:
            chunks.append(f"Certification: {name}")
    for edu in list(profile.get("education") or [])[:3]:
        if isinstance(edu, dict):
            chunks.append(
                "Education: " + " ".join(
                    str(x) for x in (edu.get("degree"), edu.get("field"), edu.get("institution")) if x
                )
            )

    jd_tokens = set(re.findall(r"[a-z0-9+#.]+", normalize(jd_text or "")))

    def _score(chunk: str) -> int:
        tokens = set(re.findall(r"[a-z0-9+#.]+", normalize(chunk)))
        overlap = len(tokens & jd_tokens)
        # Always keep skills/summary even with no JD overlap.
        if chunk.startswith(("Skills:", "Summary:")):
            overlap += 3
        return overlap

    ranked = sorted(chunks, key=_score, reverse=True)
    selected: list[str] = []
    used = 0
    for chunk in ranked:
        if used + len(chunk) > limit and selected:
            break
        selected.append(chunk)
        used += len(chunk) + 1
    return "\n".join(selected)


def build_prep_prompt(
    *,
    job_title: str,
    company_name: str,
    interview_type: str,
    interview_name: str | None,
    assumed_type: bool,
    job_description: str,
    evidence: str,
    jd_requirements: list[str],
    categories: list[str],
    scheduled_at: str | None = None,
) -> str:
    """Build the minimized generation prompt."""
    category_hint = ", ".join(f"{c} ({CATEGORY_LABELS.get(c, c)})" for c in categories)
    lines = [
        f"Target role: {job_title or 'Not specified'}",
        f"Company: {company_name or 'Not specified'}",
        f"Interview round: {interview_name or 'General'} (normalized type: {interview_type})",
    ]
    if assumed_type:
        lines.append(
            "NOTE: the interview type could not be determined from the round name, "
            "so generate a balanced set and state that assumption in assumption_note."
        )
    if scheduled_at:
        lines.append(f"Scheduled at: {scheduled_at}")
    lines.append(f"Requested question categories in order: {category_hint}")
    if jd_requirements:
        lines.append("Key JD requirements:\n- " + "\n- ".join(jd_requirements[:12]))
    lines.append("JOB DESCRIPTION (excerpt):\n" + truncate(job_description or "Not provided.", MAX_JD_CHARS))
    lines.append("CANDIDATE EVIDENCE (use only this — do not invent beyond it):\n" + (evidence or "No resume evidence available."))
    lines.append(
        f"Generate exactly {len(categories)} questions following the requested category order. "
        "Each question needs: question, difficulty, rationale (why this matters for THIS candidate), "
        "resume_evidence (traceable strings or the unsupported marker), talking_points (concise, evidence-anchored), "
        "expected_signals (what a strong answer demonstrates), related_jd_requirements (JD substrings or []), "
        "gaps (unsupported angles)."
    )
    return "\n\n".join(lines)


def response_schema() -> dict[str, Any]:
    """JSON-schema hint passed to providers that support constrained output."""
    return {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "question": {"type": "string"},
                        "difficulty": {"type": "string"},
                        "rationale": {"type": "string"},
                        "resume_evidence": {"type": "array", "items": {"type": "string"}},
                        "talking_points": {"type": "array", "items": {"type": "string"}},
                        "expected_signals": {"type": "array", "items": {"type": "string"}},
                        "related_jd_requirements": {"type": "array", "items": {"type": "string"}},
                        "gaps": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["category", "question"],
                },
            },
            "assumption_note": {"type": "string"},
            "gaps": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["questions"],
    }
