"""Intelligent skill grouping, requirement classification, and relationship modeling.

Domain-agnostic technology ecosystem taxonomy and layered relationship reasoning for
CareerOS tailoring. Separates three distinct decisions (product spec Section 9):
1. Internal reasoning: Can these requirements be reasonably connected?
2. Resume display: Should this specific skill actually appear on the resume?
3. Candidate questioning: Does the candidate need to be asked?

Architecture:
- Layer A: Known high-confidence explicit ecosystems (Python, JS/TS, Java, C#, SQL, Office, Soft skills, Cloud/DevOps).
- Layer B: Generic technology relationship inference that reasons over unseen ecosystems
  (R, Go, Rust, Ruby, PHP, Kotlin, Scala, Dart, C++, Elixir, Swift, dbt, Docker, Kubernetes, etc.)
  using reusable relationship principles (language-to-framework, ORM, build/package manager, data/viz library,
  cloud/container tooling, naming patterns) rather than an endless static dictionary.
- Relationship levels: DIRECT, STRONG_ECOSYSTEM, COMMONLY_ASSOCIATED, RELATED, SPECIALIZATION, INDEPENDENT, UNKNOWN.
- Conservative thresholds: Unrelated technologies (Python+Java, React+Python, AWS+Python) are never grouped.
- Truthfulness & friction controls:
  - Soft / behavioral skills are demonstrated through experience, NEVER questioned.
  - General office / productivity tools are handled as a family, never probed individually.
  - Strong ecosystem relationships with supporting context are resolved via truthful reconstruction.
  - Unsupported specializations (e.g. TensorFlow, DBA, VBA) are NEVER automatically claimed or inferred.
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

    DIRECT = "direct"                          # Exact or near-exact match
    STRONG_ECOSYSTEM = "strong_ecosystem"      # Core libraries / standard utilities
    COMMONLY_ASSOCIATED = "commonly_associated"  # Frequently co-occurring tooling
    RELATED = "related"                        # Plausible contextual connection
    SPECIALIZATION = "specialization"          # Advanced specialization (never auto-infer)
    INDEPENDENT = "independent"                # Distinct, unrelated technology
    UNKNOWN = "unknown"                        # Unclassified / insufficient signal
    WEAK = "weak"                              # Distant connection (backward compatibility)


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
# Layer A: Known High-Confidence Explicit Taxonomy
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
            "data processing", "data analysis", "customer data",
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
        specializations=set(),
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


def _matches_phrase(needle: str, haystack: str) -> bool:
    """Safe token-boundary phrase matching even for c#, c++, .net, r."""
    pattern = rf"(?<![a-zA-Z0-9]){re.escape(needle.lower())}(?![a-zA-Z0-9])"
    return bool(re.search(pattern, haystack.lower()))


# ---------------------------------------------------------------------------
# Layer B: Generic Technology Relationship Inference
# ---------------------------------------------------------------------------

@dataclass
class GenericEcosystemSpec:
    """Specification of a technology ecosystem based on reusable principles."""

    id: str
    root: str
    aliases: Set[str] = field(default_factory=set)
    category: RequirementCategory = RequirementCategory.PROGRAMMING_LANGUAGE
    core_libraries: Set[str] = field(default_factory=set)        # frameworks, core packages
    associated_tooling: Set[str] = field(default_factory=set)    # ORMs, build tools, runtimes
    specializations: Set[str] = field(default_factory=set)       # advanced compiler/kernel/internals
    evidence_cues: Set[str] = field(default_factory=set)
    naming_patterns: List[str] = field(default_factory=list)     # compound naming hints

    def all_root_names(self) -> Set[str]:
        return {self.root} | self.aliases

    def all_members(self) -> Set[str]:
        return self.all_root_names() | self.core_libraries | self.associated_tooling | self.specializations


# Extensible standard registry of generic ecosystems (R, Go, Rust, Ruby, PHP, Kotlin, Scala, Dart, etc.)
_GENERIC_ECOSYSTEMS: List[GenericEcosystemSpec] = [
    # R ecosystem: data science, statistical computing
    GenericEcosystemSpec(
        id="r",
        root="r",
        aliases={"r-lang", "r programming", "r-project"},
        core_libraries={"tidyverse", "dplyr", "ggplot2", "shiny", "rmarkdown", "data.table"},
        associated_tooling={"roxygen2", "tidyr", "purrr", "stringr", "lubridate", "devtools", "bioconductor"},
        specializations={"bioconductor administration"},
        evidence_cues={"statistics", "data analysis", "statistical", "modeling", "visualization", "biostatistics"},
    ),
    # Go ecosystem: microservices, concurrency, systems
    GenericEcosystemSpec(
        id="go",
        root="go",
        aliases={"golang"},
        core_libraries={"gin", "gorm", "goroutine", "goroutines", "echo", "chi", "fiber"},
        associated_tooling={"viper", "cobra", "zap", "protobuf", "grpc", "mux"},
        specializations={"go runtime internals", "go compiler"},
        evidence_cues={"backend", "concurrency", "microservices", "high performance", "systems", "api"},
    ),
    # Rust ecosystem: systems, async runtimes, safety
    GenericEcosystemSpec(
        id="rust",
        root="rust",
        aliases={"rustlang"},
        core_libraries={"tokio", "actix", "actix-web", "axum", "cargo", "serde"},
        associated_tooling={"diesel", "sqlx", "reqwest", "tonic", "tracing", "rayon"},
        specializations={"unsafe rust", "embedded rust", "rust compiler"},
        evidence_cues={"systems", "concurrency", "performance", "async", "backend"},
    ),
    # Ruby ecosystem: web MVC, automation
    GenericEcosystemSpec(
        id="ruby",
        root="ruby",
        aliases=set(),
        core_libraries={"rails", "ruby on rails", "gem", "gems", "bundler", "rspec"},
        associated_tooling={"sidekiq", "activerecord", "sinatra", "capybara", "puma"},
        specializations={"mruby"},
        evidence_cues={"web", "backend", "mvc", "api", "full stack"},
    ),
    # PHP ecosystem: modern web frameworks
    GenericEcosystemSpec(
        id="php",
        root="php",
        aliases={"php8", "php7"},
        core_libraries={"laravel", "composer", "symfony"},
        associated_tooling={"doctrine", "phpunit", "eloquent", "wordpress", "drupal"},
        specializations={"php c-extensions"},
        evidence_cues={"web", "backend", "mvc", "cms", "api"},
    ),
    # Kotlin ecosystem: Android & modern backend
    GenericEcosystemSpec(
        id="kotlin",
        root="kotlin",
        aliases=set(),
        core_libraries={"ktor", "coroutines", "kotlin coroutines", "jetpack compose"},
        associated_tooling={"spring", "spring boot", "android", "gradle"},
        specializations={"kotlin native compiler"},
        evidence_cues={"android", "mobile", "backend", "jvm", "api"},
    ),
    # Scala ecosystem: distributed data processing
    GenericEcosystemSpec(
        id="scala",
        root="scala",
        aliases=set(),
        core_libraries={"spark", "apache spark", "sbt"},
        associated_tooling={"akka", "cats", "zio", "play", "play framework", "kafka"},
        specializations={"scala compiler plugin"},
        evidence_cues={"data engineering", "distributed", "big data", "functional programming"},
    ),
    # C++ ecosystem: systems, graphics, cross-platform
    GenericEcosystemSpec(
        id="cpp",
        root="c++",
        aliases={"cpp"},
        core_libraries={"qt", "stl", "cmake"},
        associated_tooling={"boost", "opencv", "opengl", "clang", "gcc"},
        specializations={"cuda", "kernel development"},
        evidence_cues={"systems", "performance", "desktop", "graphics", "embedded"},
    ),
    # Dart ecosystem: cross-platform mobile UI
    GenericEcosystemSpec(
        id="dart",
        root="dart",
        aliases=set(),
        core_libraries={"flutter", "pub"},
        associated_tooling={"bloc", "provider", "riverpod", "dart frog"},
        specializations={"flutter engine internals"},
        evidence_cues={"mobile", "ios", "android", "cross-platform", "app", "frontend"},
    ),
    # Elixir ecosystem: concurrent, fault-tolerant web
    GenericEcosystemSpec(
        id="elixir",
        root="elixir",
        aliases=set(),
        core_libraries={"phoenix", "phoenix framework", "mix", "ecto"},
        associated_tooling={"otp", "erlang", "liveview"},
        specializations={"erlang vm internals"},
        evidence_cues={"concurrency", "fault tolerant", "distributed", "web", "realtime"},
    ),
    # Swift ecosystem: Apple platforms
    GenericEcosystemSpec(
        id="swift",
        root="swift",
        aliases=set(),
        core_libraries={"swiftui", "uikit", "xcode"},
        associated_tooling={"combine", "cocoapods", "spm", "core data"},
        specializations={"swift compiler"},
        evidence_cues={"ios", "macos", "apple", "mobile", "app"},
    ),
    # Infrastructure & Data Tooling Ecosystems
    GenericEcosystemSpec(
        id="terraform",
        root="terraform",
        aliases=set(),
        category=RequirementCategory.CLOUD_DEVOPS,
        core_libraries={"hcl", "terraform providers", "aws provider", "azure provider", "gcp provider"},
        associated_tooling={"terragrunt", "terraform cloud"},
        specializations={"custom terraform provider development"},
        evidence_cues={"iac", "infrastructure as code", "cloud", "provisioning"},
    ),
    GenericEcosystemSpec(
        id="docker",
        root="docker",
        aliases=set(),
        category=RequirementCategory.CLOUD_DEVOPS,
        core_libraries={"docker compose", "docker-compose", "dockerfile", "containerization"},
        associated_tooling={"containerd", "docker swarm"},
        specializations={"container runtime internals"},
        evidence_cues={"containers", "devops", "deployment", "microservices"},
    ),
    GenericEcosystemSpec(
        id="kubernetes",
        root="kubernetes",
        aliases={"k8s"},
        category=RequirementCategory.CLOUD_DEVOPS,
        core_libraries={"helm", "kubectl", "kustomize", "k8s manifests"},
        associated_tooling={"ingress", "argocd", "flux"},
        specializations={"kubernetes operator development"},
        evidence_cues={"cluster", "orchestration", "devops", "deployment"},
    ),
    GenericEcosystemSpec(
        id="spark",
        root="spark",
        aliases={"apache spark"},
        category=RequirementCategory.DATABASE,
        core_libraries={"pyspark", "spark sql", "spark dataframe"},
        associated_tooling={"databricks", "hadoop", "delta lake"},
        specializations={"spark internals tuning"},
        evidence_cues={"big data", "etl", "data engineering", "pipeline"},
    ),
    GenericEcosystemSpec(
        id="dbt",
        root="dbt",
        aliases=set(),
        category=RequirementCategory.DATABASE,
        core_libraries={"dbt core", "dbt cloud", "data transformations"},
        associated_tooling={"snowflake", "bigquery", "redshift", "sql", "databricks"},
        specializations={"custom dbt adapter development"},
        evidence_cues={"data warehouse", "analytics engineering", "sql", "modeling"},
    ),
]


# ---------------------------------------------------------------------------
# Provider Architecture: Layer A (Known) + Layer B (Generic Pattern)
# ---------------------------------------------------------------------------

class RelationshipProvider:
    """Abstract interface for relationship evaluation providers."""

    def evaluate(
        self, candidate_skills: Collection[str], target_req: str
    ) -> Optional[Tuple[RelationshipStrength, Optional[str], Optional[SkillFamily]]]:
        raise NotImplementedError

    def get_relationship_strength(
        self, skill_a: str, skill_b: str
    ) -> Optional[RelationshipStrength]:
        raise NotImplementedError

    def find_family_for_skill(self, skill: str) -> Optional[SkillFamily]:
        return None


class KnownRelationshipProvider(RelationshipProvider):
    """Layer A: High-confidence explicit relationship evaluation."""

    def __init__(self, families: Optional[Sequence[SkillFamily]] = None):
        self.families: List[SkillFamily] = list(families or _TAXONOMY)
        self._by_id: Dict[str, SkillFamily] = {f.id: f for f in self.families}

    def find_family_for_skill(self, skill: str) -> Optional[SkillFamily]:
        s = skill.lower().strip()
        for fam in self.families:
            if s in fam.all_members() or any(
                _matches_phrase(m, s) for m in fam.all_members()
            ):
                return fam
        return None

    def evaluate(
        self, candidate_skills: Collection[str], target_req: str
    ) -> Optional[Tuple[RelationshipStrength, Optional[str], Optional[SkillFamily]]]:
        target = target_req.lower().strip()
        fam = self.find_family_for_skill(target)
        if not fam:
            return None

        cand_set = {s.lower().strip() for s in candidate_skills}

        has_root = any(
            any(r == c or _matches_phrase(r, c) for r in fam.root_languages)
            for c in cand_set
        )
        has_core = any(
            any(m == c or _matches_phrase(m, c) for m in fam.core_members)
            for c in cand_set
        )

        # 1. Specialization guard: applies only if candidate has roots/cores in this family
        is_spec = target in fam.specializations or any(
            _matches_phrase(s, target) for s in fam.specializations
        )
        if is_spec and (has_root or has_core):
            has_direct_spec = any(
                target == c or _matches_phrase(target, c) for c in cand_set
            )
            if not has_direct_spec:
                return RelationshipStrength.SPECIALIZATION, None, fam

        # 2. Strong ecosystem
        is_core = target in fam.core_members or any(
            _matches_phrase(c, target) for c in fam.core_members
        )
        is_root_target = target in fam.root_languages or any(
            _matches_phrase(r, target) for r in fam.root_languages
        )
        if has_root and (is_core or is_root_target):
            matching_root = next(
                (
                    c for c in candidate_skills
                    if any(r == c.lower().strip() or _matches_phrase(r, c) for r in fam.root_languages)
                ),
                fam.name,
            )
            return RelationshipStrength.STRONG_ECOSYSTEM, matching_root, fam

        # 3. Commonly associated
        is_assoc = target in fam.associated_members or any(
            _matches_phrase(a, target) for a in fam.associated_members
        )
        if (has_root or has_core) and is_assoc:
            return RelationshipStrength.COMMONLY_ASSOCIATED, fam.name, fam

        if has_root or has_core:
            return RelationshipStrength.WEAK, fam.name, fam

        return RelationshipStrength.INDEPENDENT, None, None

    def get_relationship_strength(
        self, skill_a: str, skill_b: str
    ) -> Optional[RelationshipStrength]:
        res = self.evaluate([skill_a], skill_b)
        if res is not None:
            return res[0]
        # Check reverse
        res_rev = self.evaluate([skill_b], skill_a)
        if res_rev is not None:
            return res_rev[0]
        return None


class GenericPatternRelationshipProvider(RelationshipProvider):
    """Layer B: Generic technology relationship inference for unseen/extensible ecosystems.

    Reasons about ecosystems without requiring every technology to be statically pre-registered.
    Supports dynamic registration and pattern matching:
    - Language -> Framework / Library (e.g. Go -> Gin, Rust -> Tokio, Dart -> Flutter)
    - Language -> ORM (e.g. Go -> GORM, Rust -> Diesel, Ruby -> ActiveRecord)
    - Language -> Package Manager / Build (e.g. Rust -> Cargo, Elixir -> Mix, Dart -> Pub)
    - Tool -> Suffix / Compound (e.g. Docker -> Docker Compose, Spark -> PySpark)
    """

    def __init__(self, specs: Optional[Sequence[GenericEcosystemSpec]] = None):
        self.specs: List[GenericEcosystemSpec] = list(specs or _GENERIC_ECOSYSTEMS)

    def register_ecosystem(self, spec: GenericEcosystemSpec) -> None:
        """Dynamically extend the relationship engine with a new ecosystem at runtime."""
        self.specs = [s for s in self.specs if s.id != spec.id] + [spec]

    def _find_spec_for_skill(self, skill: str) -> Optional[GenericEcosystemSpec]:
        s = skill.lower().strip()
        for spec in self.specs:
            if s in spec.all_members() or any(
                _matches_phrase(m, s) for m in spec.all_members()
            ):
                return spec
        # Generic prefix / suffix reasoning:
        # e.g., "docker-compose" or "docker compose" -> docker
        if "docker" in s and ("compose" in s or "swarm" in s):
            return next((sp for sp in self.specs if sp.id == "docker"), None)
        if s.startswith("py") and len(s) > 3:
            # e.g. pyspark, pytest
            return next((sp for sp in self.specs if sp.id == "spark"), None)
        return None

    def find_family_for_skill(self, skill: str) -> Optional[SkillFamily]:
        spec = self._find_spec_for_skill(skill)
        if not spec:
            return None
        return SkillFamily(
            id=spec.id,
            name=f"{spec.root.title()} Ecosystem",
            category=spec.category,
            root_languages=spec.all_root_names(),
            core_members=spec.core_libraries,
            associated_members=spec.associated_tooling,
            specializations=spec.specializations,
            evidence_cues=spec.evidence_cues,
        )

    def evaluate(
        self, candidate_skills: Collection[str], target_req: str
    ) -> Optional[Tuple[RelationshipStrength, Optional[str], Optional[SkillFamily]]]:
        target = target_req.lower().strip()
        spec = self._find_spec_for_skill(target)
        if not spec:
            return None

        fam = self.find_family_for_skill(target)
        cand_set = {s.lower().strip() for s in candidate_skills}

        has_root = any(
            any(r == c or _matches_phrase(r, c) for r in spec.all_root_names())
            for c in cand_set
        )
        has_core = any(
            any(m == c or _matches_phrase(m, c) for m in spec.core_libraries)
            for c in cand_set
        )

        # 1. Specialization check: applies only if candidate has roots/cores in this family
        if (target in spec.specializations or any(_matches_phrase(s, target) for s in spec.specializations)) and (has_root or has_core):
            has_direct_spec = any(target == c or _matches_phrase(target, c) for c in cand_set)
            if not has_direct_spec:
                return RelationshipStrength.SPECIALIZATION, None, fam

        # 2. Strong ecosystem check (core library / tool belonging to verified root)
        is_core = target in spec.core_libraries or any(_matches_phrase(c, target) for c in spec.core_libraries)
        is_root_target = target in spec.all_root_names() or any(_matches_phrase(r, target) for r in spec.all_root_names())

        if has_root and (is_core or is_root_target):
            matching_root = next(
                (c for c in candidate_skills if any(r == c.lower().strip() or _matches_phrase(r, c) for r in spec.all_root_names())),
                spec.root.title(),
            )
            return RelationshipStrength.STRONG_ECOSYSTEM, matching_root, fam

        # 3. Commonly associated check (ORM, runtime, adjacent tool)
        is_assoc = target in spec.associated_tooling or any(_matches_phrase(a, target) for a in spec.associated_tooling)
        if (has_root or has_core) and is_assoc:
            return RelationshipStrength.COMMONLY_ASSOCIATED, spec.root.title(), fam

        if has_root or has_core:
            return RelationshipStrength.RELATED, spec.root.title(), fam

        return RelationshipStrength.INDEPENDENT, None, None

    def get_relationship_strength(
        self, skill_a: str, skill_b: str
    ) -> Optional[RelationshipStrength]:
        res = self.evaluate([skill_a], skill_b)
        if res is not None:
            return res[0]
        res_rev = self.evaluate([skill_b], skill_a)
        if res_rev is not None:
            return res_rev[0]
        return None


# ---------------------------------------------------------------------------
# Requirement Classifier
# ---------------------------------------------------------------------------

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
    for spec in _GENERIC_ECOSYSTEMS:
        for s in spec.specializations:
            if _matches_phrase(s, low):
                return RequirementCategory.SPECIALIZED_TECH, f"{spec.root.title()} Specialization"

    # 2. Soft / behavioral check
    for term in _SOFT_SKILL_TERMS:
        if _matches_phrase(term, low):
            return RequirementCategory.SOFT_SKILL, "Soft Competency"

    # 3. General productivity / office check
    for term in _OFFICE_TERMS:
        if _matches_phrase(term, low):
            return RequirementCategory.PRODUCTIVITY_OFFICE, "Office & Productivity"

    # 4. Programming language / ecosystem check from Layer A (Known)
    for fam in _TAXONOMY:
        if fam.category in (RequirementCategory.SOFT_SKILL, RequirementCategory.PRODUCTIVITY_OFFICE):
            continue
        for r in fam.root_languages:
            if _matches_phrase(r, low):
                if fam.category == RequirementCategory.DATABASE:
                    return RequirementCategory.DATABASE, fam.name
                return RequirementCategory.PROGRAMMING_LANGUAGE, fam.name
        for c in fam.core_members:
            if _matches_phrase(c, low):
                return RequirementCategory.ECOSYSTEM_CORE, fam.name
        for a in fam.associated_members:
            if _matches_phrase(a, low):
                return RequirementCategory.ECOSYSTEM_ASSOCIATED, fam.name

    # 5. Generic pattern check from Layer B
    for spec in _GENERIC_ECOSYSTEMS:
        for r in spec.all_root_names():
            if _matches_phrase(r, low):
                return spec.category, f"{spec.root.title()} Ecosystem"
        for c in spec.core_libraries:
            if _matches_phrase(c, low):
                return RequirementCategory.ECOSYSTEM_CORE, f"{spec.root.title()} Ecosystem"
        for a in spec.associated_tooling:
            if _matches_phrase(a, low):
                return RequirementCategory.ECOSYSTEM_ASSOCIATED, f"{spec.root.title()} Ecosystem"

    # 6. Logistics (location, work auth)
    if base_category in ("location", "work_authorization"):
        return RequirementCategory.LOGISTICS, base_category

    # 7. Default fallback based on existing category
    if base_category in ("technical_skill", "tool"):
        return RequirementCategory.GENERAL_TECH, "Technical Skill"
    return RequirementCategory.DOMAIN_ROLE, "Domain Requirement"


# ---------------------------------------------------------------------------
# Composite Skill Relationship Engine
# ---------------------------------------------------------------------------

class SkillRelationshipEngine:
    """Evaluates technology ecosystem relationships with confidence.

    Combines Layer A (known high confidence) and Layer B (generic pattern inference).
    Answers: 'How strongly are these two requirements or technologies related?'
    Enforces conservative thresholds to prevent dangerous over-inference.
    """

    def __init__(
        self,
        known_provider: Optional[KnownRelationshipProvider] = None,
        generic_provider: Optional[GenericPatternRelationshipProvider] = None,
    ):
        self.known_provider = known_provider or KnownRelationshipProvider()
        self.generic_provider = generic_provider or GenericPatternRelationshipProvider()
        self.providers: List[RelationshipProvider] = [self.known_provider, self.generic_provider]
        # Keep .families for backward compatibility with existing tests
        self.families: List[SkillFamily] = self.known_provider.families
        self._by_id: Dict[str, SkillFamily] = self.known_provider._by_id

    def register_ecosystem(self, spec: GenericEcosystemSpec) -> None:
        """Add or update an ecosystem specification dynamically."""
        self.generic_provider.register_ecosystem(spec)

    def find_family_for_skill(self, skill: str) -> Optional[SkillFamily]:
        """Find the skill family that claims this skill across all providers."""
        for provider in self.providers:
            fam = provider.find_family_for_skill(skill)
            if fam is not None:
                return fam
        return None

    def evaluate_relationship(
        self, candidate_skills: Collection[str], target_req: str
    ) -> Tuple[RelationshipStrength, Optional[str], Optional[SkillFamily]]:
        """Assess the connection between candidate skills and target requirement.

        Distinguishes:
        1. Strong ecosystem relationship (core member of candidate's verified root language)
        2. Commonly associated technology
        3. Weak / Related relationship
        4. Independent / unsupported specialization (TensorFlow, DBA, VBA, etc.)
        """
        # 1. Evaluate known provider (Layer A)
        res = self.known_provider.evaluate(candidate_skills, target_req)
        if res is not None and res[0] != RelationshipStrength.INDEPENDENT:
            return res

        # 2. Evaluate generic pattern provider (Layer B)
        res_generic = self.generic_provider.evaluate(candidate_skills, target_req)
        if res_generic is not None and res_generic[0] != RelationshipStrength.INDEPENDENT:
            return res_generic

        # If both providers returned INDEPENDENT or None, check if target has a known family
        fam = self.find_family_for_skill(target_req)
        return RelationshipStrength.INDEPENDENT, None, fam

    def get_relationship_strength(self, skill_a: str, skill_b: str) -> RelationshipStrength:
        """Directly determine relationship strength between two technologies."""
        a = (skill_a or "").strip().lower()
        b = (skill_b or "").strip().lower()
        if not a or not b:
            return RelationshipStrength.UNKNOWN
        if a == b:
            return RelationshipStrength.DIRECT

        # Check known provider
        st = self.known_provider.get_relationship_strength(skill_a, skill_b)
        if st is not None and st not in (RelationshipStrength.INDEPENDENT, RelationshipStrength.UNKNOWN):
            return st

        # Check generic pattern provider
        st_gen = self.generic_provider.get_relationship_strength(skill_a, skill_b)
        if st_gen is not None and st_gen not in (RelationshipStrength.INDEPENDENT, RelationshipStrength.UNKNOWN):
            return st_gen

        # Conservative guardrail: distinct root languages are strictly INDEPENDENT
        return RelationshipStrength.INDEPENDENT

    def get_ecosystem_groups_for_candidate(
        self, candidate_skills: Collection[str], target_requirements: Collection[str]
    ) -> Dict[str, List[str]]:
        """Group target requirements by candidate verified root language ecosystems.

        Example:
        Candidate has Python.
        Target requirements: [pandas, numpy, matplotlib, docker, react]
        Returns: {"Python": ["pandas", "numpy", "matplotlib"]}
        """
        groups: Dict[str, List[str]] = {}
        for target in target_requirements:
            strength, root, fam = self.evaluate_relationship(candidate_skills, target)
            if strength in (RelationshipStrength.STRONG_ECOSYSTEM, RelationshipStrength.COMMONLY_ASSOCIATED) and root:
                groups.setdefault(root, []).append(target)
        return {r: items for r, items in groups.items() if len(items) >= 2}

    def can_resolve_from_candidate_context(
        self,
        target_req: str,
        target_category: str,
        evidence_index: EvidenceIndex,
    ) -> Tuple[bool, str]:
        """Ask: 'Can I reasonably handle this requirement using information already provided?'

        If yes, DO NOT ask the candidate.
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
                _matches_phrase(cue, full_text) for cue in fam.evidence_cues
            )
            if has_office_skill or has_evidence_cue:
                return True, "office_family_supported"

        # C. Strong Programming Ecosystem + Context:
        strength, root, fam = self.evaluate_relationship(evidence_index.skill_set, low)
        if strength == RelationshipStrength.STRONG_ECOSYSTEM and fam:
            full_text = evidence_index.full_text_lower
            has_context_cues = any(
                _matches_phrase(cue, full_text) for cue in fam.evidence_cues
            )
            if has_context_cues:
                return True, f"ecosystem_reconstructable_{fam.id}"

        # D. Direct or near-direct hit in full resume text (e.g. mentioned in bullet or coursework)
        if len(low) >= 4 and _matches_phrase(low, evidence_index.full_text_lower):
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
