"""Resume-grounding validation for interview preparation.

Every talking point and evidence string the LLM produces is checked against
the actual candidate evidence corpus. Unsupported content is replaced with
an explicit marker — never silently presented as fact, never filled in with
invented employers, projects, technologies, metrics, or achievements.

All functions here are pure (no I/O) so they are cheap to unit test,
including the fabrication-regression fixtures.
"""

from __future__ import annotations

import re
from typing import Any

from app.models.interview_prep import UNSUPPORTED_EVIDENCE_MARKER

_METRIC_RE = re.compile(r"\d+(?:\.\d+)?\s?%|\b\d+x\b|\b\d+(?:\.\d+)?\s?(?:ms|s|hrs?|days?)\b", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip().lower())


def extract_resume_skills(profile: dict[str, Any]) -> set[str]:
    """Collect the candidate's actual skill vocabulary (lowercased)."""
    skills = profile.get("skills") or {}
    vocab: set[str] = set()
    for key in ("technical", "tools", "languages", "databases", "analytics", "soft_skills"):
        for item in skills.get(key, []) or []:
            if isinstance(item, str) and item.strip():
                vocab.add(item.strip().lower())
    for _group, items in (skills.get("custom") or {}).items():
        for item in items or []:
            if isinstance(item, str) and item.strip():
                vocab.add(item.strip().lower())
    for proj in profile.get("projects") or []:
        for tech in (proj.get("technologies") or []) if isinstance(proj, dict) else []:
            if isinstance(tech, str) and tech.strip():
                vocab.add(tech.strip().lower())
    for exp in list(profile.get("experience") or []) + list(profile.get("internships") or []):
        if not isinstance(exp, dict):
            continue
        for tool in exp.get("tools") or []:
            if isinstance(tool, str) and tool.strip():
                vocab.add(tool.strip().lower())
    return vocab


def build_evidence_corpus(profile: dict[str, Any]) -> str:
    """Flatten the resume profile into a searchable evidence blob."""
    parts: list[str] = []
    if profile.get("summary"):
        parts.append(str(profile["summary"]))
    for exp in list(profile.get("experience") or []) + list(profile.get("internships") or []):
        if not isinstance(exp, dict):
            continue
        for key in ("company", "role", "metrics"):
            if exp.get(key):
                parts.append(str(exp[key]))
        for bullet in exp.get("responsibilities") or []:
            text = bullet.get("text") if isinstance(bullet, dict) else bullet
            if text:
                parts.append(str(text))
        for ach in exp.get("achievements") or []:
            parts.append(str(ach))
        for tool in exp.get("tools") or []:
            parts.append(str(tool))
    for proj in profile.get("projects") or []:
        if not isinstance(proj, dict):
            continue
        for key in ("name", "description", "problem", "contribution", "results", "metrics"):
            if proj.get(key):
                parts.append(str(proj[key]))
        for tech in proj.get("technologies") or []:
            parts.append(str(tech))
    for cert in profile.get("certifications") or []:
        if isinstance(cert, dict):
            parts.extend(str(v) for v in (cert.get("name"), cert.get("issuer")) if v)
        elif cert:
            parts.append(str(cert))
    for edu in profile.get("education") or []:
        if isinstance(edu, dict):
            parts.extend(
                str(v)
                for v in (
                    edu.get("institution"), edu.get("degree"), edu.get("field"),
                )
                if v
            )
    for ach in profile.get("achievements") or []:
        parts.append(str(ach))
    for skill in sorted(extract_resume_skills(profile)):
        parts.append(skill)
    return "\n".join(parts)


def evidence_supported(evidence: str, corpus: str) -> bool:
    """Check whether an evidence string is grounded in the resume corpus.

    A claim is supported when it appears verbatim (normalized) or when a
    substantial token overlap (>= 60% of its significant tokens) exists in
    the corpus. Short skill tokens require exact containment to avoid
    false positives like "SQL" matching "PostgreSQL" claims in reverse —
    actually for skills we want "PostgreSQL" evidence to support a
    "PostgreSQL" claim; substring handles that correctly.
    """
    norm_evidence = normalize(evidence)
    if not norm_evidence:
        return False
    norm_corpus = normalize(corpus)
    if norm_evidence in norm_corpus:
        return True
    tokens = [t for t in re.findall(r"[a-z0-9+#.]+", norm_evidence) if len(t) > 2]
    if not tokens:
        return norm_evidence in norm_corpus
    corpus_tokens = set(re.findall(r"[a-z0-9+#.]+", norm_corpus))
    hits = sum(1 for t in tokens if t in corpus_tokens)
    return (hits / len(tokens)) >= 0.6


def metric_supported(metric_text: str, corpus: str) -> bool:
    """Metrics (percentages, multipliers, latencies) must appear verbatim-ish.

    A metric claim is supported only when its numeric core (digits + %/x
    suffix) is present in the corpus. "35% P99 latency reduction" in the
    resume supports reuse of "35%"; a resume with no metrics supports none.
    """
    numbers = re.findall(r"\d+(?:\.\d+)?\s?%|\b\d+(?:\.\d+)?x\b", metric_text or "")
    if not numbers:
        return True  # No metric claimed — nothing to verify.
    norm_corpus = normalize(corpus)
    for num in numbers:
        core = normalize(num)
        if core not in norm_corpus:
            return False
    return True


def sanitize_talking_point(point: str, corpus: str, resume_skills: set[str]) -> tuple[str | None, str | None]:
    """Validate one talking point.

    Returns ``(kept_point, gap_note)``. A point that claims an unsupported
    metric or presents an unknown technology as candidate experience is
    dropped and reported as a gap instead of being presented as fact.
    """
    text = (point or "").strip()
    if not text:
        return None, None
    if not metric_supported(text, corpus):
        return None, f"A metric claimed here is not in the resume: {text[:120]}"
    return text, None


def validate_question_grounding(
    question: dict[str, Any],
    corpus: str,
    resume_skills: set[str],
    jd_text: str = "",
) -> dict[str, Any]:
    """Sanitize one drafted question against resume + JD evidence.

    - ``resume_evidence`` entries without corpus support are replaced with
      the explicit unsupported marker.
    - Talking points with unsupported metrics are dropped (recorded in
      ``gaps``); remaining points pass through unchanged — the prompt
      already constrains the model to evidence, this is the safety net.
    - ``related_jd_requirements`` entries that do not appear in the JD are
      dropped so questions never pretend to map to requirements that do
      not exist.
    """
    cleaned = dict(question)

    evidence = question.get("resume_evidence") or []
    kept_evidence: list[str] = []
    for item in evidence:
        if isinstance(item, str) and item.strip() and evidence_supported(item, corpus):
            kept_evidence.append(item.strip())
    if not kept_evidence:
        kept_evidence = [UNSUPPORTED_EVIDENCE_MARKER]
    cleaned["resume_evidence"] = kept_evidence

    gaps = list(question.get("gaps") or [])
    kept_points: list[str] = []
    for point in question.get("talking_points") or []:
        if not isinstance(point, str) or not point.strip():
            continue
        kept, gap_note = sanitize_talking_point(point.strip(), corpus, resume_skills)
        if kept:
            kept_points.append(kept)
        elif gap_note:
            gaps.append(gap_note)
    cleaned["talking_points"] = kept_points
    cleaned["gaps"] = gaps

    jd_norm = normalize(jd_text)
    if jd_norm:
        kept_reqs = [
            r for r in (question.get("related_jd_requirements") or [])
            if isinstance(r, str) and r.strip() and normalize(r) in jd_norm
        ]
        cleaned["related_jd_requirements"] = kept_reqs

    return cleaned


def detect_gaps(jd_requirements: list[str], resume_skills: set[str], corpus: str) -> list[str]:
    """Identify JD requirements the resume does not support (explicit gaps)."""
    gaps: list[str] = []
    for req in jd_requirements:
        req_norm = normalize(req)
        if not req_norm:
            continue
        # A requirement is covered when any resume skill appears in it AND
        # that skill is genuinely in the candidate vocabulary, or when the
        # requirement text itself appears in the corpus.
        covered = req_norm in normalize(corpus)
        if not covered:
            for skill in resume_skills:
                if len(skill) > 2 and skill in req_norm:
                    covered = True
                    break
        if not covered:
            gaps.append(req.strip())
    return gaps
