"""Intelligent skill grouping, requirement classification, and relationship modeling.

Domain-agnostic technology ecosystem taxonomy and relationship reasoning for
CareerOS tailoring. Separates three distinct decisions (product spec Section 9):
1. Internal reasoning: Can these requirements be reasonably connected?
2. Resume display: Should this specific skill actually appear on the resume?
3. Candidate questioning: Does the candidate need to be asked?

Enforces truthfulness and friction controls:
- Soft / behavioral skills are demonstrated through experience, NEVER questioned.
- General office / productivity tools are handled as a family, never probed individually.
- Strong ecosystem relationships with supporting context are resolved via truthful
  reconstruction instead of interrogating the candidate.
- Unsupported specializations (e.g. Python -> TensorFlow, SQL -> DBA, JS -> React/Angular/Vue)
  are NEVER automatically claimed or inferred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Collection, Dict, List, Optional, Sequence, Set, Tuple

from app.services.optimization.evidence_model import CandidateEvidence, EvidenceIndex
from app.services.optimization.jd_requirements import normalize_key


class RequirementCategory(str, Enum):
    """Semantic category of a job requirement."""

    SOFT_SKILL = "soft_skill"
    PRODUCTIVITY_OFFICE = "productivity_office"
    PROGRAMMING_LANGUAGE = "programming_language"
    ECOSYSTEM_CORE = "ecosystem_core"
    ECOSYSTEM_ASSOCIATED = "ecosystem_associated"
    DATABASE = "database"
    CLOUD_DEVOPS = "cloud_devops"
    SPECIALIZED_TECH = "specialized_tech"
    GENERAL_TECH = "general_tech"
    DOMAIN_ROLE = "domain_role"
    LOGISTICS = "logistics"
    OTHER = "other"


class RelationshipStrength(str, Enum):
    """Strength of connection between candidate knowledge and a requirement."""

    STRONG_ECOSYSTEM = "strong_ecosystem"      # Core libraries / standard utilities
    COMMONLY_ASSOCIATED = "commonly_associated"  # Frequently co-occurring tooling
    WEAK = "weak"                              # Distant / indirect connection
    SPECIALIZATION = "specialization"          # Advanced specialization (never auto-infer)
    INDEPENDENT = "independent"                # Distinct, unrelated technology


@dataclass
class SkillFamily:
    """A generic, multi-technology ecosystem or competency family."""

    id: str
    name: str
    category: RequirementCategory
    root_languages: Set[str] = field(default_factory=set)
    core_members: Set[str] = field(default_factory=set)
    associated_members: Set[str] = field(default_factory=set)
    specializations: Set[str] = field(default_factory=set)
    evidence_cues: Set[str] = field(default_factory=set)

    def all_members(self) -> Set[str]:
        return self.root_languages | self.core_members | self.associated_members | self.specializations


# ---------------------------------------------------------------------------
# Domain-independent Ecosystem & Competency Taxonomy
# Multi-ecosystem: Python, JavaScript/TypeScript, Java, C#/.NET, SQL,
# Office/Productivity, Soft/Behavioral, Cloud/DevOps, Mobile, etc.
# ---------------------------------------------------------------------------

_TAXONOMY: List[SkillFamily] = [
    # 1. Python Ecosystem
    SkillFamily(
        id="python",
        name="Python Ecosystem",
        category=RequirementCategory.PROGRAMMING_LANGUAGE,
        root_languages={"python", "python3", "py"},
        core_members={
            "pandas", "numpy", "matplotlib", "seaborn", "jupyter", "jupyter notebook",
            "pytest", "pip", "virtualenv", "ipython", "poetry",
        },
        associated_members={
            "scikit-learn", "sklearn", "scipy", "statsmodels", "requests",
            "beautifulsoup", "flask", "fastapi", "django", "sqlalchemy",
            "celery", "pydantic", "alembic",
        },
        specializations={
            "tensorflow", "pytorch", "keras", "pyspark", "huggingface", "llm",
            "nlp", "computer vision", "deep learning", "langchain", "ray",
        },
        evidence_cues={
            "churn", "analytics", "dataset", "dataframe", "pipeline", "etl",
            "data processing", "script", "automation", "backend", "api",
            "data analysis", "customer data", "model",
        },
    ),
    # 2. JavaScript / TypeScript Ecosystem
    SkillFamily(
        id="javascript",
        name="JavaScript / TypeScript Ecosystem",
        category=RequirementCategory.PROGRAMMING_LANGUAGE,
        root_languages={"javascript", "typescript", "js", "ts", "ecmascript"},
        core_members={
            "node.js", "nodejs", "node", "npm", "es6", "express", "jest",
            "yarn", "pnpm", "vitest",
        },
        associated_members={
            "react", "next.js", "nextjs", "vue", "vuejs", "angular",
            "tailwind", "redux", "vite", "webpack", "html", "css",
            "rest apis", "rest api", "full stack",
        },
        specializations={
            "react native", "electron", "web3", "three.js", "angular universal",
            "wasm", "webassembly", "solidity",
        },
        evidence_cues={
            "frontend", "ui", "web", "app", "component", "interface",
            "browser", "client-side", "responsive", "spa", "dashboard",
        },
    ),
    # 3. Java Ecosystem
    SkillFamily(
        id="java",
        name="Java Ecosystem",
        category=RequirementCategory.PROGRAMMING_LANGUAGE,
        root_languages={"java", "jvm"},
        core_members={
            "spring", "spring boot", "hibernate", "jpa", "maven", "gradle",
            "junit", "jdb",
        },
        associated_members={
            "microservices", "kafka", "rest api", "rest apis", "jdbc",
            "tomcat", "spring cloud", "servlets",
        },
        specializations={
            "android", "hadoop", "spark", "websphere", "weblogic",
            "spring security", "reactive java",
        },
        evidence_cues={
            "backend", "enterprise", "service", "api", "oop", "server",
            "high-throughput", "distributed",
        },
    ),
    # 4. C# / .NET Ecosystem
    SkillFamily(
        id="csharp",
        name="C# / .NET Ecosystem",
        category=RequirementCategory.PROGRAMMING_LANGUAGE,
        root_languages={"c#", "csharp", "dotnet", ".net"},
        core_members={
            ".net core", "asp.net", "asp.net core", "entity framework",
            "linq", "nuget", "visual studio",
        },
        associated_members={
            "sql server", "ms sql", "web api", "azure", "rest",
            "wpf", "wcf", "xunit",
        },
        specializations={
            "blazor", "xamarin", "unity", "maui", "game development",
        },
        evidence_cues={
            "windows", "backend", "services", "enterprise", "api",
            "desktop", "c# development",
        },
    ),
    # 5. SQL / Relational Databases
    SkillFamily(
        id="sql",
        name="Relational Databases & SQL",
        category=RequirementCategory.DATABASE,
        root_languages={"sql", "relational databases", "rdbms"},
        core_members={
            "database querying", "queries", "joins", "stored procedures",
            "schema design", "indexes", "views",
        },
        associated_members={
            "postgresql", "postgres", "mysql", "sql server", "sqlite",
            "oracle", "database design", "crud",
        },
        specializations={
            "database administration", "dba", "postgresql administration",
            "query tuning", "performance tuning", "sharding", "replication",
            "clustering", "high availability",
        },
        evidence_cues={
            "extract", "reporting", "tables", "schema", "dataset", "analytics",
            "warehouse", "crud", "query", "queries", "data extraction",
        },
    ),
    # 6. General Productivity & Office Skills
    SkillFamily(
        id="productivity_office",
        name="Office & Productivity Tools",
        category=RequirementCategory.PRODUCTIVITY_OFFICE,
        root_languages={"microsoft office", "ms office", "office 365", "google workspace"},
        core_members={
            "excel", "word", "powerpoint", "outlook", "google docs",
            "google sheets", "google slides", "spreadsheets",
            "presentation tools", "documentation tools",
        },
        associated_members={
            "confluence", "notion", "sharepoint", "trello", "asana",
            "jira", "slack", "teams", "reporting tools",
        },
        specializations={
            "vba", "macros", "advanced excel modeling", "visual basic",
            "macro development",
        },
        evidence_cues={
            "reporting", "documentation", "spreadsheets", "presentations",
            "operational tracking", "data analysis", "tracker", "trackers",
            "client follow-ups", "reconciliation", "monthly report",
            "invoicing", "minutes", "status updates",
        },
    ),
    # 7. Soft & Behavioral Skills
    SkillFamily(
        id="soft_skills",
        name="Soft & Behavioral Competencies",
        category=RequirementCategory.SOFT_SKILL,
        root_languages={"soft skills", "interpersonal skills", "behavioral"},
        core_members={
            "communication", "teamwork", "collaboration", "leadership",
            "problem solving", "adaptability", "time management",
            "attention to detail", "stakeholder management", "interpersonal",
            "critical thinking", "organization", "conflict resolution",
            "client relations", "coordination", "cross-functional",
            "prioritization", "ownership", "bias for action", "work ethic",
            "active listening",
        },
        associated_members={
            "presentation skills", "mentoring", "facilitation",
            "negotiation", "relationship building", "empathy",
        },
        specializations=set(),  # soft skills have no unsupported tech specialization
        evidence_cues={
            "coordinated", "led", "collaborated", "communicated", "presented",
            "resolved", "managed", "organized", "supported", "tracked",
            "liaised", "facilitated", "worked with", "cross-functional",
            "stakeholders", "team", "partners", "clients",
        },
    ),
    # 8. Cloud & DevOps
    SkillFamily(
        id="cloud_devops",
        name="Cloud, Containers & DevOps",
        category=RequirementCategory.CLOUD_DEVOPS,
        root_languages={"devops", "cloud", "infrastructure"},
        core_members={
            "git", "version control", "github", "gitlab", "linux", "bash",
            "rest apis", "http", "docker", "containers",
        },
        associated_members={
            "kubernetes", "k8s", "ci/cd", "aws", "azure", "gcp",
            "terraform", "helm", "ansible", "nginx",
        },
        specializations={
            "site reliability engineering", "sre", "platform engineering",
            "istio", "devsecops", "service mesh", "chaos engineering",
        },
        evidence_cues={
            "deploy", "build", "pipeline", "infra", "server", "cloud",
            "production", "containerized", "releases",
        },
    ),
]

_SOFT_SKILL_TERMS = frozenset(
    term
    for fam in _TAXONOMY
    if fam.category == RequirementCategory.SOFT_SKILL
    for term in fam.all_members()
)

_OFFICE_TERMS = frozenset(
    term
    for fam in _TAXONOMY
    if fam.category == RequirementCategory.PRODUCTIVITY_OFFICE
    for term in fam.all_members()
)


# ---------------------------------------------------------------------------
# Requirement Classifier
# ---------------------------------------------------------------------------

def _matches_phrase(needle: str, haystack: str) -> bool:
    """Safe token-boundary phrase matching even for c#, c++, .net."""
    pattern = rf"(?<![a-zA-Z0-9]){re.escape(needle.lower())}(?![a-zA-Z0-9])"
    return bool(re.search(pattern, haystack.lower()))


def classify_requirement_type(
    statement: str, base_category: str = ""
) -> Tuple[RequirementCategory, str]:
    """Classify requirement statement into high-level category and canonical concept."""
    low = (statement or "").lower().strip()

    # 1. Specializations check (e.g. TensorFlow, VBA, DBA, Blazor)
    for fam in _TAXONOMY:
        for s in fam.specializations:
            if _matches_phrase(s, low):
                return RequirementCategory.SPECIALIZED_TECH, fam.name

    # 2. Soft / behavioral check
    for term in _SOFT_SKILL_TERMS:
        if _matches_phrase(term, low):
            return RequirementCategory.SOFT_SKILL, "Soft Competency"

    # 3. General productivity / office check
    for term in _OFFICE_TERMS:
        if _matches_phrase(term, low):
            return RequirementCategory.PRODUCTIVITY_OFFICE, "Office & Productivity"

    # 4. Programming language / ecosystem check
    for fam in _TAXONOMY:
        if fam.category in (RequirementCategory.SOFT_SKILL, RequirementCategory.PRODUCTIVITY_OFFICE):
            continue
        # Root language check
        for r in fam.root_languages:
            if _matches_phrase(r, low):
                if fam.category == RequirementCategory.DATABASE:
                    return RequirementCategory.DATABASE, fam.name
                return RequirementCategory.PROGRAMMING_LANGUAGE, fam.name
        # Core ecosystem check
        for c in fam.core_members:
            if _matches_phrase(c, low):
                return RequirementCategory.ECOSYSTEM_CORE, fam.name
        # Associated member check
        for a in fam.associated_members:
            if _matches_phrase(a, low):
                return RequirementCategory.ECOSYSTEM_ASSOCIATED, fam.name

    # 5. Logistics (location, work auth)
    if base_category in ("location", "work_authorization"):
        return RequirementCategory.LOGISTICS, base_category

    # 6. Default fallback based on existing category
    if base_category in ("technical_skill", "tool"):
        return RequirementCategory.GENERAL_TECH, "Technical Skill"
    return RequirementCategory.DOMAIN_ROLE, "Domain Requirement"


# ---------------------------------------------------------------------------
# Relationship Modeling & Confidence Engine
# ---------------------------------------------------------------------------

class SkillRelationshipEngine:
    """Evaluates technology ecosystem relationships with confidence."""

    def __init__(self, families: Optional[Sequence[SkillFamily]] = None):
        self.families: List[SkillFamily] = list(families or _TAXONOMY)
        self._by_id: Dict[str, SkillFamily] = {f.id: f for f in self.families}

    def find_family_for_skill(self, skill: str) -> Optional[SkillFamily]:
        """Find the skill family that claims this skill."""
        s = skill.lower().strip()
        for fam in self.families:
            if s in fam.all_members() or any(
                re.search(rf"\b{re.escape(m)}\b", s) for m in fam.all_members()
            ):
                return fam
        return None

    def evaluate_relationship(
        self, candidate_skills: Collection[str], target_req: str
    ) -> Tuple[RelationshipStrength, Optional[str], Optional[SkillFamily]]:
        """Assess the connection between candidate skills and target requirement.

        Distinguishes:
        1. Strong ecosystem relationship (core member of candidate's verified root language)
        2. Commonly associated technology
        3. Weak relationship
        4. Independent / unsupported specialization (TensorFlow, DBA, VBA, etc.)
        """
        target = target_req.lower().strip()
        fam = self.find_family_for_skill(target)
        if not fam:
            return RelationshipStrength.INDEPENDENT, None, None

        cand_set = {s.lower().strip() for s in candidate_skills}

        # Check for candidate roots in this family
        has_root = any(
            any(r == c or re.search(rf"\b{re.escape(r)}\b", c) for r in fam.root_languages)
            for c in cand_set
        )
        has_core = any(
            any(m == c or re.search(rf"\b{re.escape(m)}\b", c) for m in fam.core_members)
            for c in cand_set
        )

        # 1. Unsupported specialization guard (Section 10):
        # Even if candidate has Python, target=TensorFlow is a SPECIALIZATION.
        # Even if candidate has SQL, target=PostgreSQL Administration is a SPECIALIZATION.
        # Even if candidate has Office, target=VBA is a SPECIALIZATION.
        # Even if candidate has JavaScript, target=React/Angular/Vue is not automatically claimed.
        is_spec = target in fam.specializations or any(
            re.search(rf"\b{re.escape(s)}\b", target) for s in fam.specializations
        )
        if is_spec:
            # Does candidate have direct evidence for this specialization?
            has_direct_spec = any(
                target == c or re.search(rf"\b{re.escape(target)}\b", c)
                for c in cand_set
            )
            if not has_direct_spec:
                return RelationshipStrength.SPECIALIZATION, None, fam

        # 2. Strong ecosystem relationship
        is_core = target in fam.core_members or any(
            re.search(rf"\b{re.escape(c)}\b", target) for c in fam.core_members
        )
        is_root_target = target in fam.root_languages or any(
            re.search(rf"\b{re.escape(r)}\b", target) for r in fam.root_languages
        )
        if has_root and (is_core or is_root_target):
            # Pick the cleanest root language match
            matching_root = next(
                (
                    c for c in candidate_skills
                    if any(r == c.lower().strip() or re.search(rf"\b{re.escape(r)}\b", c.lower()) for r in fam.root_languages)
                ),
                fam.name,
            )
            return RelationshipStrength.STRONG_ECOSYSTEM, matching_root, fam

        # 3. Commonly associated
        is_assoc = target in fam.associated_members or any(
            re.search(rf"\b{re.escape(a)}\b", target) for a in fam.associated_members
        )
        if (has_root or has_core) and is_assoc:
            return RelationshipStrength.COMMONLY_ASSOCIATED, fam.name, fam

        if has_root or has_core:
            return RelationshipStrength.WEAK, fam.name, fam

        return RelationshipStrength.INDEPENDENT, None, None

    def can_resolve_from_candidate_context(
        self,
        target_req: str,
        target_category: str,
        evidence_index: EvidenceIndex,
    ) -> Tuple[bool, str]:
        """Ask: 'Can I reasonably handle this requirement using information already provided?'

        If yes, DO NOT ask the candidate (Section 4).
        """
        low = target_req.lower().strip()
        req_type, _ = classify_requirement_type(low, target_category)

        # A. Soft / Behavioral: Always demonstrated through experience, NEVER questioned.
        if req_type == RequirementCategory.SOFT_SKILL:
            return True, "soft_skill_demonstrated"

        # B. General Productivity / Office:
        # Handled as a family. If candidate has ANY office evidence (Excel, Word, documentation,
        # reporting, spreadsheets, trackers), it is covered.
        if req_type == RequirementCategory.PRODUCTIVITY_OFFICE:
            fam = self._by_id["productivity_office"]
            full_text = evidence_index.full_text_lower
            has_office_skill = bool(fam.core_members & evidence_index.skill_set) or bool(
                fam.root_languages & evidence_index.skill_set
            )
            has_evidence_cue = any(
                re.search(rf"\b{re.escape(cue)}\b", full_text) for cue in fam.evidence_cues
            )
            if has_office_skill or has_evidence_cue:
                return True, "office_family_supported"

        # C. Strong Programming Ecosystem + Context:
        # e.g. Candidate has Python, and has projects/experience with data/churn/analytics
        # JD asks for Pandas / NumPy / Matplotlib.
        strength, root, fam = self.evaluate_relationship(evidence_index.skill_set, low)
        if strength == RelationshipStrength.STRONG_ECOSYSTEM and fam:
            # Check for supporting evidence cues in candidate projects/experience
            full_text = evidence_index.full_text_lower
            has_context_cues = any(
                re.search(rf"\b{re.escape(cue)}\b", full_text) for cue in fam.evidence_cues
            )
            if has_context_cues:
                return True, f"ecosystem_reconstructable_{fam.id}"

        # D. Direct or near-direct hit in full resume text (e.g. mentioned in bullet or coursework)
        if len(low) >= 4 and re.search(rf"\b{re.escape(low)}\b", evidence_index.full_text_lower):
            return True, "buried_in_resume_text"

        return False, ""

    def should_question_candidate(
        self,
        target_req: str,
        target_category: str,
        evidence_index: EvidenceIndex,
        is_direct_or_claimable: bool,
    ) -> bool:
        """Single decision policy: Does the candidate need to be asked?

        Returns False if the requirement can be legitimately inferred, reconstructed,
        demonstrated via soft skill framing, or is already directly present.
        """
        if is_direct_or_claimable:
            return False

        can_resolve, _ = self.can_resolve_from_candidate_context(
            target_req, target_category, evidence_index
        )
        if can_resolve:
            return False

        # Independent / genuine high-impact technical gaps remain for candidate questioning.
        return True


# Global default engine instance
skill_relationship_engine = SkillRelationshipEngine()
