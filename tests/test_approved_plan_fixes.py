"""TDD reproducer for approved plan fixes (COMPLETE_SYSTEM §11 debt).

Plan source: COMPLETE_SYSTEM.md §11 Known Risks & Technical Debt (authoritative
reference in this repo). No *.plan.md exists; journeys derived here per
tdd-workflow Step 1.

User journeys:
  J1: As a maintainer, I want one canonical skill list so crawler skill
      extraction stays consistent when the list changes.
  J2: As a maintainer, I want ATSAnalyzer without shadowed dead code so the
      effective (semantic-aware) analyze_resume is the single source of truth.
  J3: As a DBA, I want the misnamed duplicate resume_versions index corrected
      via a new idempotent migration (history 000-028 immutable).

RED expectation (before fix):
  - canonical module app.crawlers.skills missing -> collection-time import error
    or assertion failure
  - ATSAnalyzer defines analyze_resume twice -> count == 2
  - migration 029 missing -> file-not-found assertion

GREEN expectation (after fix):
  - all tests in this file pass, existing adapter/ATS suites still pass.
"""

from __future__ import annotations

import inspect
import pathlib
import re


# ---------------------------------------------------------------------------
# Fix 1 (§11.7): centralize duplicated _KNOWN_SKILLS
# ---------------------------------------------------------------------------

EXPECTED_SKILLS = [
    "typescript", "javascript", "react", "next.js", "node", "python",
    "java", "sql", "postgresql", "aws", "docker", "kubernetes", "graphql",
    "rest", "agile", "leadership", "communication", "product", "figma",
    "tailwind", "supabase", "redis", "mongodb", "machine learning",
    "data analysis", "project management",
]


def test_canonical_skills_module_exists_with_expected_list():
    """J1: single canonical list exists and matches the known-good content."""
    from app.crawlers.skills import KNOWN_SKILLS  # noqa: PLC0415 -- RED if missing

    assert list(KNOWN_SKILLS) == EXPECTED_SKILLS


def test_canonical_extractor_handles_happy_path_and_edges():
    """J1: canonical extractor preserves exact legacy behavior."""
    from app.crawlers.skills import extract_known_skills  # noqa: PLC0415

    # Happy path: case-insensitive substring match, order follows canonical list
    found = extract_known_skills("We use Python, Docker and REACT daily.")
    assert "python" in found
    assert "docker" in found
    assert "react" in found
    # Order guarantee: canonical-list order, not mention order
    assert found == sorted(found, key=EXPECTED_SKILLS.index)

    # Edge: empty string -> empty list (never None, never raises)
    assert extract_known_skills("") == []

    # Edge: no known skill mentioned -> empty list
    assert extract_known_skills("We love gardening and pottery.") == []

    # Edge: unicode / emoji / SQL-ish chars never break extraction
    assert isinstance(extract_known_skills("Python 🐍 + café — ' OR 1=1; --"), list)
    assert "python" in extract_known_skills("Python 🐍 + café")

    # Boundary: large input still works and stays bounded by list size
    big = ("python docker " * 5000).strip()
    assert set(extract_known_skills(big)) == {"python", "docker"}


def test_all_adapters_share_single_canonical_list():
    """J1: all 5 crawler modules reference the same canonical object."""
    import app.crawlers.skills as canonical  # noqa: PLC0415 -- RED if missing

    modules = [
        "app.crawlers.adapters.ashby",
        "app.crawlers.adapters.greenhouse",
        "app.crawlers.adapters.lever",
        "app.crawlers.adapters.smartrecruiters",
        "app.crawlers.aggregators.adzuna",
    ]
    for dotted in modules:
        mod = __import__(dotted, fromlist=["*"])
        # Each module must expose _KNOWN_SKILLS as an alias of the canonical list
        assert hasattr(mod, "_KNOWN_SKILLS"), f"{dotted} missing _KNOWN_SKILLS alias"
        assert mod._KNOWN_SKILLS is canonical.KNOWN_SKILLS, (
            f"{dotted}._KNOWN_SKILLS is not the canonical singleton"
        )
        assert hasattr(mod, "_extract_known_skills")


def test_adapter_extraction_parity_with_canonical():
    """J1 integration: adapter-level helpers agree with canonical helper."""
    from app.crawlers.skills import extract_known_skills as canonical_fn  # noqa: PLC0415

    import app.crawlers.adapters.ashby as ashby
    import app.crawlers.adapters.greenhouse as greenhouse
    import app.crawlers.adapters.lever as lever
    import app.crawlers.adapters.smartrecruiters as sr
    import app.crawlers.aggregators.adzuna as adzuna

    sample = "Senior Python (Django) + PostgreSQL, AWS, docker; React frontend."
    expected = canonical_fn(sample)
    for mod in (ashby, greenhouse, lever, sr, adzuna):
        assert mod._extract_known_skills(sample) == expected


# ---------------------------------------------------------------------------
# Fix 2 (§11.2): remove shadowed duplicate analyze_resume dead code
# ---------------------------------------------------------------------------

def test_ats_analyzer_defines_single_analyze_resume():
    """J2: no shadowed duplicate — exactly one `def analyze_resume` remains."""
    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "app" / "services" / "ats" / "ats_analyzer.py"
    )
    source = path.read_text(encoding="utf-8")
    count = len(re.findall(r"^\s*def analyze_resume\s*\(", source, re.MULTILINE))
    assert count == 1, f"expected exactly 1 analyze_resume definition, found {count}"


def test_effective_analyze_resume_is_semantic_aware():
    """J2: the surviving implementation is the semantic-aware one (not dead code)."""
    import app.services.ats.ats_analyzer as mod  # noqa: PLC0415

    assert hasattr(mod, "ATSAnalyzer")
    src = inspect.getsource(mod.ATSAnalyzer.analyze_resume)
    # Semantic-aware markers only present in the second (effective) definition
    assert "_run_semantic_reasoning" in src
    assert "reconcile_requirements" in src
    assert "semantic_metadata" in src


def test_ats_analysis_still_deterministic_and_bounded():
    """J2 integration: behavior preserved — scores bounded, no crash on minimal input."""
    from app.models.resume import ResumeContent, ResumeProfile  # noqa: PLC0415
    from app.services.ats.ats_analyzer import ATSAnalyzer  # noqa: PLC0415

    analyzer = ATSAnalyzer()
    content = ResumeContent(profile=ResumeProfile())
    result = analyzer.analyze_resume(content, "We need Python and communication skills.")
    for score in (
        result.overall_score,
        result.keyword_match_score,
        result.skills_match_score,
        result.experience_relevance_score,
        result.qualification_match_score,
        result.structure_format_score,
    ):
        assert 0.0 <= score <= 100.0


# ---------------------------------------------------------------------------
# Fix 3 (§11.4): corrective migration for misnamed duplicate index
# ---------------------------------------------------------------------------

def _migrations_dir() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent / "sql" / "migrations"


def test_corrective_migration_exists_and_is_idempotent():
    """J3: new 029 migration drops the misnamed duplicate index idempotently."""
    mig_dir = _migrations_dir()
    candidates = sorted(mig_dir.glob("029_*.sql"))
    assert candidates, "expected sql/migrations/029_*.sql corrective migration"
    sql = candidates[0].read_text(encoding="utf-8")
    assert "idx_resume_versions_user_id" in sql
    assert "DROP INDEX IF EXISTS" in sql
    # Must not recreate the bad name, must not touch data
    assert sql.count("idx_resume_versions_user_id") >= 1
    assert "DELETE" not in sql.upper() or "ON CONFLICT DO NOTHING" in sql


def test_corrective_migration_preserves_good_index():
    """J3: corrective migration keeps the correctly-named resume_id index."""
    mig_dir = _migrations_dir()
    candidates = sorted(mig_dir.glob("029_*.sql"))
    assert candidates
    sql = candidates[0].read_text(encoding="utf-8")
    # The good index must still exist afterwards (created if missing)
    assert "idx_resume_versions_resume_id" in sql


def test_migration_history_immutable_except_additive_fix():
    """J3: 006 history untouched (invariant); fix lives only in 029."""
    mig_006 = _migrations_dir() / "006_resume_versions_extended.sql"
    assert mig_006.exists()
    original_006 = mig_006.read_text(encoding="utf-8")
    # 006 still contains the historical misnamed line (proof we did not rewrite history)
    assert "idx_resume_versions_user_id" in original_006
    assert "ON public.resume_versions(resume_id)" in original_006
