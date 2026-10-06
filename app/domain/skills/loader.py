"""Domain-level Skill Ontology loader and boundary-safe matcher.

Provides:
  - Canonical skill definitions, aliases, and categories.
  - Boundary-safe alias matching (avoiding false positives for short tokens like 'R' and 'Go').
  - Single source of truth across crawlers, ATS analyzer, and Job Intelligence.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ONTOLOGY_FILE = Path(__file__).parent / "ontology.json"


@dataclass(frozen=True)
class SkillDefinition:
    canonical: str
    category: str
    aliases: tuple[str, ...]


class SkillOntology:
    """In-memory loaded skill ontology."""

    def __init__(self, version: str, skills: list[SkillDefinition]) -> None:
        self.version = version
        self.skills = skills
        self.canonical_map: dict[str, SkillDefinition] = {s.canonical.lower(): s for s in skills}
        
        # Build alias -> canonical mapping
        self.alias_to_canonical: dict[str, str] = {}
        for s in skills:
            for alias in s.aliases:
                self.alias_to_canonical[alias.lower().strip()] = s.canonical

        # Compile regex patterns for boundary-safe extraction
        # For single-letter or very short ambiguous tokens, require strict word boundaries or explicit phrases
        self._compiled_patterns: list[tuple[re.Pattern, str]] = []
        for s in skills:
            for alias in s.aliases:
                alias_clean = alias.strip().lower()
                # Strict boundary for words with letters/digits
                # If alias contains symbols like c++, c#, .js, escape appropriately
                if alias_clean in ("r", "go"):
                    # Special word-boundary: "R" must not match inside words, or standalone letter in text
                    # e.g. " R " or "R programming"
                    pattern = re.compile(rf"(?<![a-zA-Z0-9_]){re.escape(alias_clean)}(?![a-zA-Z0-9_])", re.IGNORECASE)
                elif "+" in alias_clean or "#" in alias_clean:
                    pattern = re.compile(rf"(?<![a-zA-Z0-9_]){re.escape(alias_clean)}(?![a-zA-Z0-9_])", re.IGNORECASE)
                else:
                    pattern = re.compile(rf"\b{re.escape(alias_clean)}\b", re.IGNORECASE)
                self._compiled_patterns.append((pattern, s.canonical))

    def normalize(self, skill_name: str) -> str:
        """Map raw skill string or alias to canonical form."""
        if not skill_name:
            return ""
        cleaned = skill_name.strip().lower()
        return self.alias_to_canonical.get(cleaned, skill_name.strip())

    def get_category(self, skill_name: str) -> Optional[str]:
        """Get canonical category for a skill name or alias."""
        canonical = self.normalize(skill_name).lower()
        defn = self.canonical_map.get(canonical)
        return defn.category if defn else None

    def extract_skills(self, text: str) -> list[str]:
        """Extract canonical skills from text using boundary-safe matching."""
        if not text:
            return []
        
        matched: set[str] = set()
        for pattern, canonical in self._compiled_patterns:
            if pattern.search(text):
                matched.add(canonical)
                
        # Return in stable canonical order
        return [s.canonical for s in self.skills if s.canonical in matched]


    @property
    def aliases(self) -> dict[str, str]:
        return self.alias_to_canonical


@lru_cache(maxsize=1)
def get_skill_ontology() -> SkillOntology:
    """Load and cache the skill ontology from ontology.json."""
    if not _ONTOLOGY_FILE.exists():
        logger.error("Skill ontology file %s not found", _ONTOLOGY_FILE)
        return SkillOntology(version="0.0.0", skills=[])
        
    try:
        with open(_ONTOLOGY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        version = data.get("version", "1.0.0")
        raw_skills = data.get("skills", [])
        definitions = [
            SkillDefinition(
                canonical=item["canonical"],
                category=item.get("category", "general"),
                aliases=tuple(item.get("aliases", [item["canonical"]])),
            )
            for item in raw_skills
            if "canonical" in item
        ]
        return SkillOntology(version=version, skills=definitions)
    except Exception as exc:
        logger.exception("Failed to load skill ontology: %s", exc)
        return SkillOntology(version="0.0.0", skills=[])


def extract_skills_with_ontology(text: str) -> list[str]:
    """Helper to extract skills from text using canonical ontology."""
    return get_skill_ontology().extract_skills(text)
