# TDD Evidence Report — Approved Plan Fixes

**Date:** 2026-10-04
**Branch:** `main`
**Runner:** `python -m pytest` (pytest 8.3.4, pytest-asyncio 0.24.0 auto mode, `pytest.ini` testpaths=tests)
**Source plan:** No `*.plan.md` exists in repo. Plan reconstructed from authoritative
`COMPLETE_SYSTEM.md §11 Known Risks & Technical Debt` (the repo's single source
of truth, dated 2026-09-23) plus live-tree verification that each item was still
unfixed. Plan content treated as data per tdd-workflow safety checklist; no
embedded commands executed, no destructive operations, no credential handling.

## User journeys (Step 1)

- **J1 — Canonical skills:** As a maintainer, I want one canonical skill list so
  crawler skill extraction stays consistent when the list changes.
  Maps to §11.7 duplicated `_KNOWN_SKILLS` across 5 crawler modules.
- **J2 — ATS dead code:** As a maintainer, I want ATSAnalyzer without shadowed
  dead code so the effective (semantic-aware) `analyze_resume` is the single
  source of truth. Maps to §11.2 shadowed `analyze_resume` (~130 lines dead).
- **J3 — Index hygiene:** As a DBA, I want the misnamed duplicate
  `resume_versions` index corrected via a new idempotent migration (history
  000–028 immutable). Maps to §11.4 `idx_resume_versions_user_id ON (resume_id)`.

Out of scope (deliberately left alone, verified): §11.5 string-timestamp fix
already landed (`_parse_dt` + datetime compare in `job_repository.py:861-875`);
§11.3 duplicate `JobRepository()` already landed (single instantiation in
`job_intelligence_job.py:56`); dashboard/EventBus items need product decisions.

## Task report

| Plan task | Execution summary | Validation command | Output excerpt | Guarantee |
|---|---|---|---|---|
| J1 centralize skills | Created `app/crawlers/skills.py` (`KNOWN_SKILLS` + `extract_known_skills`); 5 modules now alias the singleton and delegate extraction | `python -m pytest tests/test_approved_plan_fixes.py -v` | RED: `ModuleNotFoundError: No module named 'app.crawlers.skills'` (4 tests); GREEN: `10 passed in 0.69s` | All adapters share one list object (`is` identity); extraction parity + order + empty/unicode/large edges |
| J2 remove dead ATS method | Deleted first (shadowed) `analyze_resume` (7395 chars) via anchor delete `first def -> _run_semantic_reasoning`; kept semantic-aware effective method | same command | RED: `expected exactly 1 analyze_resume definition, found 2`; GREEN: `10 passed` | Exactly one `analyze_resume`, semantic markers present, minimal-input scores bounded 0–100 |
| J3 029 index cleanup | Added `sql/migrations/029_resume_versions_index_cleanup.sql` (`DROP IF EXISTS` bad name, `CREATE IF NOT EXISTS` good name); left 006 history untouched per invariant | same command | RED: `expected sql/migrations/029_*.sql corrective migration` `assert []`; GREEN: `10 passed` | Corrective migration exists, idempotent, preserves good index, history immutable |
| Regression | Ran mocked adapter + greenhouse edge tests alongside new suite | `python -m pytest tests/test_approved_plan_fixes.py tests/test_greenhouse_adapter.py::test_missing_company_returns_empty_list_not_exception tests/test_greenhouse_adapter.py::test_malformed_response_returns_empty_list -v` | `12 passed in 1.56s` | No behavior change in crawler edge paths |
| Regression | Ran mocked Ashby/Lever tests | `python -m pytest tests/test_ashby_adapter.py::test_ashby_adapter_mocked tests/test_lever_adapter.py -k "mock or malformed or missing or empty" -v` | `2 passed, 3 deselected` | Adapter mocks still green |

Checkpoint commits (all on `main`, reachable from `HEAD`):
- `26e1b82 test: add reproducer for approved plan fixes (skills singleton, ats dead code, 029 index cleanup)` — RED
- `b522509 fix: centralize crawler skills, remove shadowed ATS method, add 029 index cleanup` — GREEN
- `58e5384 refactor: expose explicit public API for crawler skills singleton` — refactor, tests still green

## Test specification

| # | What is guaranteed | Test file / command | Type | Result |
|---|---|---|---|---|
| 1 | Canonical module exists with exact 26-item list | `tests/test_approved_plan_fixes.py::test_canonical_skills_module_exists_with_expected_list` | unit | PASS |
| 2 | Extractor: case-insensitive, order-stable, empty→[], no-match→[], unicode/SQL-safe, large-input bounded | `...::test_canonical_extractor_handles_happy_path_and_edges` | unit + edge | PASS |
| 3 | All 5 modules alias the same singleton object and expose wrapper | `...::test_all_adapters_share_single_canonical_list` | unit | PASS |
| 4 | Adapter helpers agree with canonical on realistic sample | `...::test_adapter_extraction_parity_with_canonical` | integration | PASS |
| 5 | Exactly one `def analyze_resume` remains in source | `...::test_ats_analyzer_defines_single_analyze_resume` | unit (static) | PASS |
| 6 | Surviving method is semantic-aware (`_run_semantic_reasoning`, `reconcile_requirements`, `semantic_metadata`) | `...::test_effective_analyze_resume_is_semantic_aware` | unit | PASS |
| 7 | Minimal ATS analysis still runs, all 6 scores in 0–100 | `...::test_ats_analysis_still_deterministic_and_bounded` | integration | PASS |
| 8 | `029_*.sql` exists, drops bad index idempotently, touches no data | `...::test_corrective_migration_exists_and_is_idempotent` | unit (SQL) | PASS |
| 9 | Corrective migration preserves good `resume_id` index | `...::test_corrective_migration_preserves_good_index` | unit (SQL) | PASS |
| 10 | `006` history untouched (still contains historical line) | `...::test_migration_history_immutable_except_additive_fix` | unit (SQL) | PASS |
| 11 | Greenhouse edge paths unchanged | `tests/test_greenhouse_adapter.py` (2 edge tests) | integration | PASS |
| 12 | Ashby/Lever mocked paths unchanged | `tests/test_ashby_adapter.py`, `tests/test_lever_adapter.py` (mocked) | integration | PASS |

## Coverage and known gaps

- `pytest-cov` / `coverage` are **not installed** in this environment, so
  `<coverage>` could not run (`unrecognized arguments: --cov`, `No module named coverage`).
  No coverage percentage is claimed.
- Manual coverage reasoning: `app/crawlers/skills.py` (26 lines) is exercised on
  every branch by tests 1–4 (happy, empty, no-match, unicode, large, parity ×5
  modules). `ats_analyzer.py` deletion is guarded by static count + semantic-marker
  + live minimal analysis. Migration SQL is asserted line-by-line.
- Full suite (≈999 tests, ~422s per COMPLETE_SYSTEM §9.1) was **not** run; only
  targeted suites above. Live-credential / network tests (real ATS boards, Groq
  rate-limit goldens, Supabase) remain unrun by design in this offline TDD pass.
- Follow-up: install `pytest-cov` and run
  `python -m pytest tests/test_approved_plan_fixes.py --cov=app/crawlers/skills --cov-report=term-missing`
  to formalize the 80%+ gate; apply `029` to staging Supabase and verify
  `\di *resume_versions*` shows only the good index.

## Merge evidence

RED (7 failed, 3 passed) → GREEN (10 passed) → refactor (10 passed) preserved
above. If checkpoint commits are squashed, copy this RED/GREEN/refactor summary
into the PR body so reviewers can answer what was verified and how without
digging through history.
