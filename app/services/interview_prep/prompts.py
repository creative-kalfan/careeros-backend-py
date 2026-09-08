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


# ---------------------------------------------------------------------------
# Practice drills (role-specific simulation without an application)
# ---------------------------------------------------------------------------

DRILL_SYSTEM_INSTRUCTION = """You are a precise interview-preparation coach inside CareerOS.
Generate role-specific practice drills grounded ONLY in the provided candidate evidence and job description.

HARD RULES — never violate these:
1. NEVER invent employers, projects, technologies, metrics, responsibilities, certifications, education, achievements, or years of experience.
2. Every resume_evidence string must be traceable to the CANDIDATE EVIDENCE section. If no evidence supports a drill angle, put exactly "Not supported by current resume evidence." as the evidence and list the angle under gaps.
3. NEVER claim the candidate has experience with a JD requirement that does not appear in the candidate evidence. Name such requirements under gaps instead.
4. Cover all three drill buckets: technical_screen (core architecture/concepts), behavioral_star (challenges, leadership, conflicts — STAR-structured), live_scenario (timed scenario / what-would-you-do drill).
5. Return ONLY a single JSON object with fields: questions (array of {drill_type, category, question, difficulty, rationale, resume_evidence, talking_points, expected_signals, related_jd_requirements, gaps}), assumption_note (string), gaps (array of strings).
6. drill_type must be exactly: technical_screen, behavioral_star, or live_scenario. Category must be one of: behavioral, technical, role_specific, resume_deep_dive, situational, company_context. Difficulty must be foundational, intermediate, or advanced."""

MAX_DRILL_JD_CHARS = 2500


def build_drill_prompt(
    *,
    target_role: str,
    seniority: str,
    job_description: str,
    evidence: str,
    jd_requirements: list[str],
    count: int,
) -> str:
    """Build the minimized drill-generation prompt (no application context)."""
    lines = [
        f"Target role: {target_role or 'Not specified'}",
        f"Seniority: {seniority or 'mid'}",
        f"Generate exactly {count} practice drills: at least one technical_screen, "
        "at least one behavioral_star, and at least one live_scenario drill.",
        "Behavioral drills must be answerable with the STAR method "
        "(Situation, Task, Action, Result) and include STAR-ready talking points. "
        "Live-scenario drills must pose a realistic on-the-job situation for the role.",
    ]
    if jd_requirements:
        lines.append("Key JD requirements:\n- " + "\n- ".join(jd_requirements[:10]))
    lines.append(
        "JOB DESCRIPTION (excerpt):\n"
        + truncate(job_description or "Not provided.", MAX_DRILL_JD_CHARS)
    )
    lines.append(
        "CANDIDATE EVIDENCE (use only this — do not invent beyond it):\n"
        + (evidence or "No resume evidence available.")
    )
    return "\n\n".join(lines)


def drill_response_schema() -> dict[str, Any]:
    """JSON-schema hint for drill generation."""
    return {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "drill_type": {"type": "string"},
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
                    "required": ["drill_type", "category", "question"],
                },
            },
            "assumption_note": {"type": "string"},
            "gaps": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["questions"],
    }


# ---------------------------------------------------------------------------
# STAR response critique (qualitative coaching, never a hiring score)
# ---------------------------------------------------------------------------

CRITIQUE_SYSTEM_INSTRUCTION = """You are a strict but supportive STAR interview coach inside CareerOS.
Critique ONE candidate practice response against the STAR method (Situation, Task, Action, Result).

HARD RULES — never violate these:
1. Judge ONLY the response text provided. NEVER invent candidate experience beyond it.
2. NEVER output numeric scores, percentages, readiness ratings, or hiring decisions. Coverage must be exactly present, partial, or missing per dimension.
3. Each dimension needs: coverage, feedback (what the response does), suggestion (one concrete next sentence or edit), evidence_quote (a short verbatim substring of the response, or empty string when missing).
4. strengths lists what is concretely working (2-4 items). improvements lists the highest-leverage fixes (2-4 items, STAR-ordered).
5. honest_note states plainly what is still unproven when evidence is thin — never bluff for the candidate.
6. Return ONLY a single JSON object with fields: dimensions (array of {dimension, coverage, feedback, suggestion, evidence_quote}), strengths (array), improvements (array), honest_note (string)."""

MAX_CRITIQUE_RESPONSE_CHARS = 4000


def build_critique_prompt(
    *,
    question: str,
    category: str,
    response_text: str,
    target_role: str | None = None,
    job_description: str = "",
) -> str:
    """Build the minimized critique prompt (response + question only)."""
    lines = [
        f"Interview question ({category or 'behavioral'}): {question}",
        f"Target role: {target_role or 'Not specified'}",
        "CANDIDATE RESPONSE (judge only this):\n" + truncate(response_text or "", MAX_CRITIQUE_RESPONSE_CHARS),
    ]
    if (job_description or "").strip():
        lines.append(
            "JOB CONTEXT (excerpt, for relevance only):\n"
            + truncate(job_description, MAX_DRILL_JD_CHARS)
        )
    lines.append(
        "Critique the response dimension by dimension (Situation, Task, Action, Result). "
        "Quote short verbatim evidence for each dimension you mark present or partial; "
        "leave evidence_quote empty when missing."
    )
    return "\n\n".join(lines)


def critique_response_schema() -> dict[str, Any]:
    """JSON-schema hint for STAR critique output."""
    return {
        "type": "object",
        "properties": {
            "dimensions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "dimension": {"type": "string"},
                        "coverage": {"type": "string"},
                        "feedback": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "evidence_quote": {"type": "string"},
                    },
                    "required": ["dimension", "coverage"],
                },
            },
            "strengths": {"type": "array", "items": {"type": "string"}},
            "improvements": {"type": "array", "items": {"type": "string"}},
            "honest_note": {"type": "string"},
        },
        "required": ["dimensions"],
    }
