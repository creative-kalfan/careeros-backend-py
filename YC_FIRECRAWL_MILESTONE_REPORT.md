# CareerOS Backend Milestone - YC Job Ingestion + Firecrawl Official Career-Page Ingestion

## A. Existing backend architecture discovered
- FastAPI + Uvicorn backend under `careeros-backend-py/app`.
- Canonical job pipeline: adapters -> `JobService.normalize_and_classify()` -> `JobRepository.upsert_jobs()` (Supabase, service role) -> workers (`crawl_company_job`, ARQ) -> stale deactivation -> `JobIngested` event via the in-process Event Bus.
- Dedup identity is `(source_platform, external_job_id)` backed by a DB partial unique index (migration 013).
- Existing ATS adapters under `app/crawlers/adapters/` (Ashby, Greenhouse, Lever, SmartRecruiters) and aggregators under `app/crawlers/aggregators/` (Adzuna). Base crawler in `app/crawlers/base.py`.
- Ranking lives in `PersonalizedJobService.calculate_match_score` (8-factor) consumed by `JobRelevanceService` and the `RecommendationEngine`.

## B. Existing adapters reusable for YC
- YC is a discovery layer. Each posting apply URL carries `external_job_id` + `source_platform` and flows through the canonical pipeline.
- ATS/company URLs via YC are classified by `source_quality.classify_source` and reuse existing provenance (no duplicate scraping).
- `app/crawlers/adapters/ycombinator.py` reuses `CrawledJob` + `JobIngestionService.ingest_ycombinator_jobs()`.

## C. YC ingestion implementation
- `YCAdapter` fetches the public Work at a Startup board, normalizes company/title/location/employment_type/description/skills, and builds a deterministic FNV-1a `external_job_id` (never `python hash()`).
- Missing fields stay None; nothing fabricated.
- `JobIngestionService.ingest_ycombinator_jobs()` applies source quality and persists via the canonical repo.

## D. Firecrawl implementation
- `app/crawlers/firecrawl_client.py` - typed async HTTP client.
- `app/crawlers/adapters/firecrawl.py` - `FirecrawlAdapter` (map -> scrape -> parse -> provenance).
- `app/crawlers/source_quality.py` - canonical source tiers + official-domain verification.
- `app/services/jobs/source_priority.py` - bounded source-quality ranking bonus.
- `app/services/jobs/job_ingestion_service.py::ingest_firecrawl_jobs()` - canonical integration.
## E. Firecrawl API integration details
- Endpoints: `/map`, `/scrape`, `/crawl` (bounded polling).
- Auth via `Authorization: Bearer <key>` (backend-only).
- Exponential backoff with jitter on 429/5xx/network errors; typed errors (FirecrawlConfigurationError, FirecrawlAuthError, FirecrawlRateLimitError, FirecrawlServerError, FirecrawlJobTimeout).
- Per-page failure isolation: one bad page never kills the crawl.
- Defaults: timeout 30s, max_retries 3, max_pages_per_crawl 15.

## F. Environment variables added
`.env.example` (both backend and root):
- FIRECRAWL_API_KEY (empty = disabled; invoking without it fails clearly)
- FIRECRAWL_API_URL, FIRECRAWL_TIMEOUT_SECONDS, FIRECRAWL_MAX_RETRIES, FIRECRAWL_MAX_PAGES_PER_CRAWL
- JOB_STALE_AFTER_DAYS

## G. Database migrations
`sql/migrations/016_job_source_provenance.sql`.

## H. Tables/columns changed
`public.jobs` gains: source_tier, source_provider, canonical_url, source_verified, source_confidence, company_website, careers_url, logo_url, first_seen_at, last_crawled_at, source_history. Reuses last_seen_at/url/source_platform/is_active. Indexes on (source_tier, is_active) and (source_verified, is_active).

## I. Canonical ingestion flow
DISCOVER -> EXTRACT -> VALIDATE -> NORMALIZE -> COMPANY RESOLUTION -> SOURCE VERIFICATION -> DEDUPLICATE -> SOURCE QUALITY ASSIGNMENT -> PERSIST -> INDEX -> MATCH -> RANK -> RECOMMEND via JobIngestionService/JobRepository.

## J. Source verification logic
`source_quality.py` verifies the URL domain (not the retrieval mechanism):
- Own-domain -> tier 1 official_company_career
- Known ATS board (boards.greenhouse.io, jobs.lever.co, jobs.ashbyhq.com, myworkdayjobs.com, icims.com, ...) -> tier 2 official_ats
- YC board -> tier 3
- Other verified -> tier 4
- Aggregator (linkedin.com, indeed.com, glassdoor.com, adzuna., ycombinator.com, ...) -> tier 5
- Firecrawl retrieval alone never implies official.

## K. Deduplication logic
- Existing (source_platform, external_job_id) dedup preserved.
- `_apply_source_escalation` merges provenance and never downgrades.

## L. Secondary -> official source upgrade behavior
`JobRepository._apply_source_escalation`: when a better (lower) tier is discovered, the existing canonical row is updated in place (updated), not duplicated; previous provenance is appended to source_history. Worse/equal sources ignored (no downgrade).

## M. Company/logo handling
`_company_identity_from_html` extracts official logo (og:image) or favicon from the career page; real assets only, never fabricated. Populates company/logo_url/favicon_url into raw, then persisted via logo_url.
## N. Source-priority ranking logic
`source_priority.combined_rank_score = match_overall + source_quality_bonus`, bounded bonuses: official=+4, official_ats=+3, yc=+2, other=0, aggregator=-1. Applied as the primary sort key in JobRelevanceService and RecommendationEngine, so source quality complements (never replaces) candidate relevance.

## O. Freshness/staleness behavior
- Jobs older than STALE_JOB_DAYS (30) are inserted/updated with is_active=False.
- deactivate_stale_jobs(source_platform=...) runs after successful crawls (worker), source-scoped, NO LONGER SEEN -> INACTIVE (never deleted).
- Freshness is a ranking factor (freshness match component) and a tie-break.

## P. Tests added
tests/test_firecrawl_client.py, test_firecrawl_adapter.py, test_source_quality.py, test_source_priority_ranking.py, test_source_escalation.py, test_ycombinator.py. Real-crawl test optional, skips without FIRECRAWL_API_KEY.

## Q. Test/typecheck/lint/build results
- Tests: 535 passed (milestone + existing backend). 5 deselected are pre-existing failures in unrelated untracked WIP features (Job Intelligence API route, LLM gateway provider routing, /api/health prefix) - not part of this milestone.
- Typecheck/lint: mypy/ruff/flake8/black not installed; validated via `python -m compileall app` (exit 0) and explicit module imports (ALL_IMPORTS_OK).
- Build: byte-compile + import validation pass.
- Migration 016 well-formed (BEGIN/COMMIT balanced, last_seen_at reused from migration 011, no duplicate fields).

## R. Real Firecrawl integration result
Skipped - FIRECRAWL_API_KEY not configured, so all Firecrawl behavior covered by mocked tests. No fake success reported.

## S. Exact modified files
- Modified (tracked): .env.example, app/api/routes/jobs.py, app/config.py, app/crawlers/aggregators/adzuna.py, app/models/job.py, app/repositories/job_repository.py, app/services/jobs/job_ingestion_service.py, app/services/jobs/job_relevance_service.py, app/services/jobs/scheduled_crawl_runner.py, app/services/recommendations/recommendation_engine.py, app/workers/jobs/crawl_jobs.py, supportive app/auth/service.py, app/db/supabase.py, app/main.py + tests.
- Added (new): app/crawlers/adapters/firecrawl.py, app/crawlers/adapters/ycombinator.py, app/crawlers/firecrawl_client.py, app/crawlers/source_quality.py, app/services/jobs/source_priority.py, sql/migrations/016_job_source_provenance.sql, new test files.

## T. Explicit confirmation
"Frontend files were not modified."
All changes under careeros-backend-py/. No careeros-frontend/ files created, edited, deleted, or restructured.
