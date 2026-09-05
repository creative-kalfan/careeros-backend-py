"""Ground non-numeric tailored claims in the candidate's source resume."""

from __future__ import annotations

import re
from typing import Any

from app.models.resume import ResumeProfile


_WORD_RE = re.compile(r"[a-z][a-z0-9+#.-]*", re.IGNORECASE)
_KNOWN_TERMS = {
    "aws", "azure", "gcp", "kubernetes", "docker", "terraform", "ansible",
    "python", "java", "javascript", "typescript", "react", "fastapi", "django",
    "postgresql", "mysql", "mongodb", "redis", "kafka", "graphql", "spark",
    "tableau", "powerbi", "salesforce", "sap", "linux", "git", "jira",
}
_ALIASES = {"k8s": "kubernetes", "postgres": "postgresql", "js": "javascript", "ts": "typescript"}
_SCOPE_PATTERNS = ("led a team", "managed a team", "managed team", "cross-functional team", "global team")


def _tokens(text: str) -> set[str]:
    return {_ALIASES.get(token.casefold(), token.casefold()) for token in _WORD_RE.findall(text or "")}


def _profile_text(profile: ResumeProfile) -> str:
    """Serialize candidate facts only; job description is deliberately excluded."""
    parts: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(profile.model_dump())
    return " ".join(parts)


class SemanticFabricationGuard:
    """Flags new skills, title terms, and scope claims before persistence."""

    @classmethod
    def audit_tailored_profile(
        cls, source_profile: ResumeProfile, tailored_profile_dict: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        source_text = _profile_text(source_profile)
        source_tokens = _tokens(source_text)
        issues: list[str] = []

        def flag(phrase: str, location: str) -> None:
            message = f"Ungrounded claim in {location}: {phrase}"
            if message not in issues:
                issues.append(message)

        skills = tailored_profile_dict.get("skills") or {}
        if isinstance(skills, dict):
            for category, values in skills.items():
                if not isinstance(values, list):
                    continue
                for value in values:
                    phrase = str(value).strip()
                    phrase_tokens = _tokens(phrase)
                    if phrase_tokens and not phrase_tokens.issubset(source_tokens):
                        flag(phrase, f"skills.{category}")

        for index, exp in enumerate(tailored_profile_dict.get("experience") or []):
            if not isinstance(exp, dict):
                continue
            role = str(exp.get("role") or "").strip()
            role_tokens = _tokens(role)
            if role_tokens and not role_tokens.issubset(source_tokens):
                flag(role, f"experience[{index}].role")
            for bullet_index, bullet in enumerate(exp.get("responsibilities") or []):
                text = bullet.get("text", "") if isinstance(bullet, dict) else str(bullet)
                cls._audit_text(text, source_text, source_tokens, f"experience[{index}].bullet[{bullet_index}]", flag)

        summary = tailored_profile_dict.get("summary")
        if isinstance(summary, str):
            cls._audit_text(summary, source_text, source_tokens, "summary", flag)
        return dict(tailored_profile_dict), issues

    @staticmethod
    def _audit_text(text: str, source_text: str, source_tokens: set[str], location: str, flag) -> None:
        lowered = text.casefold()
        for term in _KNOWN_TERMS.intersection(_tokens(text)):
            if term not in source_tokens:
                flag(term, location)
        for phrase in _SCOPE_PATTERNS:
            if phrase in lowered and phrase not in source_text.casefold():
                flag(phrase, location)


semantic_guard = SemanticFabricationGuard()
