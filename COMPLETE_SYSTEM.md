# CareerOS — Complete System Map & Reality Audit
**Authoritative Reference & Personal System Map**
**Date:** 2026-09-10
**Status:** Canonical copy lives in `careeros-backend-py` (this file). A stale
reference copy remains at the legacy wrapper root (`resume-pilot/COMPLETE_SYSTEM.md`,
dated 2026-09-03); the wrapper repository is not used for documentation commits
(see §12). This file is the version-controlled home of the system documentation.

This document is the single source of truth for the entire CareerOS codebase. It reflects the **actual current working tree, file inventory, API contracts, database schemas, background workers, and Git commits** as of today.

---

## 1. Canonical Repositories & Git Metadata

### 1.1 Canonical Backend: `careeros-backend-py`
- **Local Path:** `C:\Users\pathan Kalfan\resume-pilot\careeros-backend-py`
- **Git Remote:** `https://github.com/creative-kalfan/careeros-backend-py.git`
- **Branch:** `main`
- **Current HEAD:** `a8595338d4b1ca2436c4685d040b5d87bdb6d76b`
- **Commit Message:** `feat(ingestion): upgrade India-first multi-source job pipeline`
- **Preceding Base Release:** `980772448d9f8eba5c972f167b826949500b0e41`
- **Technology:** Python 3.11.9, FastAPI 0.115.6, Uvicorn 0.34.0, Pydantic v2 (2.10.4), Supabase Python client 2.11.0, PyMuPDF 1.25.3, python-docx 1.1.2, ARQ 0.26.1, Redis 5.3.1, APScheduler 3.11.3, PyJWT[crypto] 2.13.0, Sentry SDK 2.19.2, python-jobspy 1.1.82 (worker dependency for Naukri/LinkedIn discovery; deferred import keeps startup safe when absent).
- **Rule:** Exact repository name is `careeros-backend-py`. Never create `backend-v2`, `careos-backend-py`, or duplicate folders.

### 1.2 Canonical Frontend: `careeros-frontend` (also referenced as `careos-frontend`)
- **Local Path:** `C:\Users\pathan Kalfan\resume-pilot\careeros-frontend`
- **Git Remote:** `https://github.com/creative-kalfan/careeros-frontend` (remote project name in GitHub org: `careos-frontend`)
- **Branch:** `main`
- **Current HEAD:** `64cd6e6c4e348973f1003cb0354dc999c6b66af1`
- **Commit Message:** `feat(frontend): integrate resume studio, ats intelligence, job intelligence, and optimizations`
- **Preceding Base Release:** `f89c90b25c9420224c89dbecb091c6706b1564c9`
- **Technology:** React 19.2.0, Vite 8.0.16 + Nitro 3.0.260603-beta (TanStack Start 1.168.26 + Router 1.170.16 + Query 5.101.1), TypeScript 5.8.3, Tailwind CSS 4.2.1, Radix UI primitives, Framer Motion 13.1.1, Three.js 0.185.1, PDF.js 4.10.38, Lucide React 0.575, `@sentry/react` 10.70.0.
- **Dev Port:** `http://localhost:8080` (strictly pinned to port 8080 to match backend CORS policy).

### 1.3 Legacy / Non-Canonical Directories (DO NOT MODIFY)
- **Parent Wrapper:** `C:\Users\pathan Kalfan\resume-pilot` — Legacy monorepo wrapper (`https://github.com/creative-kalfan/career-os.git`, commit `5bc354a`). Contains root `package.json` (root Sentry artifact), `docker-compose.infrastructure.yml`, and documentation. Not the application repository.
- **Legacy Backend:** `C:\Users\pathan Kalfan\resume-pilot\careeros-backend` — Working tree contains only `INVESTIGATION_NOTES.md`. Git history tracks the obsolete Next.js/TypeScript backend. Not runnable; never use as reference.

---

## 2. What CareerOS Is & User Capabilities

### 2.1 What CareerOS Is
CareerOS is an AI-powered Career Operating System designed to replace disconnected job search tools (resume builders, ATS scanners, job boards, spreadsheets) with a single, truthful, unified pipeline.
- It connects **candidate evidence** directly to **job requirements**.
- It enforces **provenance tracking** for every resume bullet and crawled job posting.
- It provides **explainable ATS scoring** and **version-safe resume optimization** without allowing AI hallucination.

### 2.2 What Users Can Currently Do
1. **Authentication & Profile Setup:**
   - Sign up / log in with email and password via Supabase Auth (ES256 asymmetric JWT).
   - Complete multi-step onboarding wizard storing experience, education, preferred roles, and preferred companies.
   - Profile automatically provisions an authenticated RLS-secured profile record.
2. **Resume Upload & Parsing:**
   - Upload PDF or DOCX resumes directly from the browser to private Supabase Storage (`resumes/{user_id}/{uuid}.ext`).
   - Run deterministic PyMuPDF / python-docx parsing producing a structured `ResumeProfile`.
   - Calculate resume completeness score (0–100%) weighted across 7 sections.
3. **Resume Studio & Version Management:**
   - View resumes in an interactive Studio (`/resumes/$id`): Left pane displays AI intelligence and suggestions; Right pane displays the actual resume truth via `PreviewPane` or `PdfCanvasPreview` (rendering exact original PDF bytes via PDF.js).
   - Create derived versions tied to specific jobs (`target_job_title`, `target_company`, `job_description`).
   - Promote any version to `master` (enforced by DB-level partial unique index).
   - Apply atomic profile operations (`replace`, `insert`, `delete` on sections and individual bullet items).
   - Export any resume version to PDF or DOCX via backend binary streaming (`requestBlob`).
4. **ATS Intelligence Diagnostics:**
   - Analyze a resume against any target job description (`POST /api/ats/analyze`).
   - Receive 5 deterministic sub-scores (keyword match, skills match, experience relevance, qualification match, format/structure) plus an overall score.
   - Inspect requirement coverage breakdowns: matched concepts, partial matches, missing requirements, and exact resume evidence locations.
   - Review optional LLM semantic reconciliation upgrades (0.70 threshold) and overrides (0.85 threshold) with strict hallucination guards.
5. **Resume Optimization & Improvement Proposals:**
   - Generate AI suggestions for skills, summary, and experience bullet points targeted to a job description.
   - Review proposed changes with visual diffs and provenance tags (`gap_fill`, `experience_grounded`).
   - Accept or reject proposals individually or in bulk. Accepted proposals are atomically written into a new derived version, preserving the master resume.
6. **Job Search & Ingestion:**
   - Search public crawled jobs filtered by title, role category, location, remote/work-mode, and skills.
   - View personalized job search results scored via an 8-factor matching algorithm (20% role, 20% skill, 15% resume text, 10% experience, 15% location, 10% salary, 5% company preference, 5% freshness) with India-first domestic ranking.
   - Save/bookmark jobs and trigger asynchronous deep job intelligence extraction.
   - Click verified external application links (`apply_url`) with transparent source attribution.
7. **Recommendations & In-App Notifications:**
   - View curated job recommendations feed (`/recommendations`) generated from candidate profile and active resume.
   - Dismiss or save recommendations (dismissed jobs are permanently excluded from future recommendations).
   - Receive in-app notifications when new high-match jobs are recommended. Manage alert preferences per category.
8. **Mission Control Applications Kanban:**
   - Track active job applications on a visual Kanban board (`/applications`) across stages: `applied`, `assessment`, `interview`, `offer`, `rejected`.
   - View conversion metrics (interview rate, offer rate, active applications count).

---

## 3. High-Level System Architecture & Data Flow

```
[Candidate / Browser]
       │
       ├── 1. Direct Upload PDF/DOCX (Storage RLS) ──────────────────────────┐
       │                                                                      ▼
       ├── 2. Auth: Email/Password (ES256 Bearer JWT) ──► [Supabase Auth] ──► [Supabase Storage]
       │                                                       │              (Bucket: resumes/private)
       ├── 3. API Requests (Bearer JWT)                        │
       ▼                                                       ▼
[Frontend: Vite 8 + TanStack Start :8080] ────────► [Backend: FastAPI :8000]
 (React 19, TanStack Query, Tailwind 4)              (ES256 JWKS Verify -> RLS Client)
                                                               │
                     ┌─────────────────────────────────────────┼────────────────────────────────────────┐
                     ▼                                         ▼                                        ▼
             [Domain Services]                         [In-Process EventBus]                    [Background ARQ Workers]
      (ATS, Ingestion, Resume Parser,             (Typed events: JobIngested,              (Redis-backed async execution)
       Optimization, Recs, Personalization)       RecommendationGenerated)                 (Crawl, Parse, Intelligence)
                     │                                         │                                        │
                     ▼                                         ▼                                        ▼
             [Repositories (PostgREST)]               [Notification Subscriber]                [External Integrations]
                     │                                         │                        - Company ATS (Ashby/Greenhouse/Lever)
                     ▼                                         ▼                        - Job Boards (Adzuna / Y Combinator)
         [Supabase PostgreSQL 15+] <───────────────────────────┘                        - Firecrawl Tech Startups
         (21 Tables, 15 Migrations, RLS)                                                - LLM Providers (Groq/Gemini/Mistral)
```

---

## 4. Responsibility Boundaries

### 4.1 Frontend Owns (`careeros-frontend`)
- UI rendering, client-side routing, optimistic caching (TanStack Query, 5-minute stale time).
- Direct-to-storage resume file uploads (bypassing FastAPI memory).
- Supabase session management, token refresh interceptor, route authorization guards.
- Resume Studio two-pane layout: displaying AI proposals on the left, rendering original PDF bytes (`PdfCanvasPreview`) or styled HTML (`PreviewPane`) on the right.
- Visual diff rendering for optimization proposals and interactive Kanban application board.
- Pinned local execution on port `8080`.

### 4.2 Backend Owns (`careeros-backend-py`)
- Request authentication via ES256 JWKS verification using `PyJWT[crypto]`.
- Enforcing PostgreSQL RLS by instantiating caller-scoped Supabase clients.
- Deterministic resume parsing (PyMuPDF / python-docx) and bullet canonicalization (FNV-1a IDs).
- Deterministic 5-subscore ATS analysis against a 50+ concept domain lexicon.
- Orchestrating LLM Gateway calls for semantic reconciliation and section optimizations.
- Scheduled and on-demand job ingestion, crawler dispatching, normalization, deduplication, and stale deactivation.
- 8-factor personalized job matching and recommendation ranking.
- Dispatching async background tasks to Redis/ARQ.

### 4.3 Database Owns (Supabase PostgreSQL 15+)
- Tables, constraints, and relationships across 21 core tables.
- Row Level Security (RLS) policies guaranteeing strict multi-tenant isolation across all user data.
- Database-level deduplication: partial unique index `uq_jobs_source_platform_external_job_id` on jobs.
- Single master version guarantee: partial unique index `uq_master_per_resume` on `resume_versions`.
- Automated timestamp management (`updated_at` triggers) and new user profile provisioning (`handle_new_user` trigger).
- Supabase Storage bucket security (`resumes` bucket private with path-based owner RLS).

### 4.4 Background Workers Own (ARQ + Redis)
- `crawl_company_job`: Crawls designated job sources, enforces concurrency locks (`crawl_lock:{source}:{slug}` TTL 300s), normalizes jobs, upserts into DB, deactivates stale postings, and records crawl run history.
- `parse_resume_job`: Asynchronously downloads resume bytes from Storage, enforces 10MB guard, parses content, and updates database records.
- `analyze_job_intelligence`: Asynchronously performs deep deterministic feature extraction on newly ingested jobs.
- `careeros_worker_health`: Periodic worker liveness ping.
- APScheduler: Cron scheduler running inside FastAPI lifespan triggering periodic crawl jobs every 24 hours per provider.

### 4.5 External Services
- **Supabase Auth:** User identity, token generation, JWKS endpoint.
- **Supabase Storage:** Private binary object storage for resumes.
- **LLM Providers (Groq, Gemini, Mistral, OpenRouter):** Sliced context reasoning (backend API keys only; no BYOK).
- **Job Sources:**
  - ATS APIs: Ashby (`api.ashbyhq.com`), Greenhouse (`boards-api.greenhouse.io`), Lever (`api.lever.co`), SmartRecruiters (`api.smartrecruiters.com`).
  - Web Crawling: Firecrawl (curated startups: PostHog, Linear, Razorpay, PhonePe, CRED, Zerodha), Y Combinator Work at a Startup.
  - Job Aggregators: Adzuna India (`/v1/api/jobs/in/search/{page}`, 39-query India rotation incl. measured-incremental city queries, ~6 calls/crawl/day) + JobSpy (`app/crawlers/adapters/jobspy.py`, Naukri/LinkedIn coverage, optional `python-jobspy` dep, graceful empty when uninstalled).
  - JSearch: EVALUATED and deliberately NOT integrated (Adzuna + JobSpy + ATS cover India AI/ML/SAP ABAP; extra cost/rate limits + duplicate volume outweigh incremental coverage; slot reserved behind the aggregator abstraction).
- **Sentry:** Error tracking and performance monitoring in both backend and frontend.

---

## 5. Complete File Structure Inventory

### 5.1 Project Layout (ASCII Map)
```
resume-pilot/ (Parent Wrapper)
├── COMPLETE_SYSTEM.md (This authoritative document)
├── docker-compose.infrastructure.yml (Redis container definition)
├── package.json (Root Sentry dependency artifact)
│
├── careeros-backend-py/ (Canonical Backend — FastAPI)
│   ├── Dockerfile
│   ├── requirements.txt (PyJWT[crypto]==2.13.0, python-jobspy==1.1.82)
│   ├── pytest.ini
│   ├── .env.example
│   ├── app/
│   │   ├── main.py (FastAPI app factory, CORS middleware, lifespan)
│   │   ├── config.py (Pydantic Settings, env variables)
│   │   ├── dependencies.py (FastAPI DI: get_current_user, get_current_admin)
│   │   ├── api/routes/ (14 route modules: jobs, resumes, versions, ats, optimization, improvement, recommendations, notifications, profile, applications, export, templates, dev, notification_preferences)
│   │   ├── auth/ (jwt_verify.py, service.py, router.py)
│   │   ├── crawlers/ (base.py, crawl_registry.py, source_quality.py, firecrawl_client.py, adapters/ incl. jobspy.py, aggregators/)
│   │   ├── db/ (supabase.py: service client and RLS client initializers)
│   │   ├── events/ (bus.py, domain_event.py, registry.py, runtime.py, subscribers/notification_subscriber.py)
│   │   ├── llm/ (gateway.py, router.py, types.py, providers/gemini.py, groq.py, mistral.py, openrouter.py)
│   │   ├── models/ (resume.py, job.py, profile.py, ats.py, optimization.py, improvement.py, job_intelligence.py, resume_template.py)
│   │   ├── repositories/ (job, resume, profile, ats, optimization, notification, recommendation, proposal_decision, job_intelligence, resume_template)
│   │   ├── schemas/ (common.py, resume.py, job.py, ats.py, optimization.py, improvement.py, profile.py, resume_template.py)
│   │   ├── services/ (ats/, jobs/ incl. validation + India normalization + enrichment guards in job_service.py, optimization/, improvement/, notifications/, recommendations/, resume_parser/, export_service.py, resume_parsing.py)
│   │   └── workers/ (settings.py, dispatcher.py, registry.py, jobs/crawl_jobs.py, resume_jobs.py, job_intelligence_job.py)
│   ├── sql/migrations/ (15 migration files: 000-002, 006-017 + README.md)
│   └── tests/ (55 test files + __init__.py covering all subsystems, incl. test_job_ingestion_2o.py)
│
└── careeros-frontend/ (Canonical Frontend — Vite 8 + TanStack + React 19)
    ├── Dockerfile
    ├── package.json (React 19, Vite 8, TanStack Router/Query/Start, Tailwind 4)
    ├── vite.config.ts (Strict port 8080)
    ├── playwright.config.ts
    ├── src/
    │   ├── start.ts (Sentry initialization)
    │   ├── routeTree.gen.ts (TanStack Router generated route definitions)
    │   ├── routes/ (27 route modules: index, auth, onboarding, resumes, ats, jobs, applications, recommendations, notifications, profile, settings, admin, sentry-test)
    │   ├── api/ (17 typed clients: applications, ats, auth, client, config, copilot, dashboard, improvement, index, job-intelligence, jobs, notifications, optimization, recommendations, resume, templates, versions)
    │   ├── hooks/api/ (16 TanStack Query hooks: useApplications, useATS, useDashboardData, useImprovement, useJobIntelligence, useJobs, useMatchJobs, useNotifications, useOptimization, useRecommendations, useResumes, useSavedJobs, useSaveJob, useSearchJobs, useTemplates, useVersions)
    │   ├── components/
    │   │   ├── app/ (sidebar, topbar, account-menu, command-palette)
    │   │   ├── resume/ (left-pane, preview-pane, ats-analysis-dialog, ats-evidence-list, pdf-canvas-preview, version-manager, templates/)
    │   │   ├── jobs/ (job-list, job-details, ai-insights, primary-filters-bar, job-resume-dialog)
    │   │   ├── landing/ (CinematicSceneController, CareerSignalCanvas, scenes/)
    │   │   ├── ats/ (center-pane, left-pane, right-pane, score-ring)
    │   │   ├── dashboard/ (career-3d-topology, widgets)
    │   │   ├── copilot/ (chat-bubble, copilot-panel)
    │   │   └── shared/ (error-state, empty-state, skeletons)
    │   ├── lib/ (19 utilities: ats-evidence-view, evidence-location, motion, proposal-review-helpers, provenance-labels, resume, sentry, supabase)
    │   ├── lib/__tests__/ (8 Vitest test suites)
    │   ├── types/ (10 type files)
    │   └── utils/ (request.ts, api-error.ts)
    └── tests/e2e/ (16 Playwright specs + auth.setup.ts)
```

### 5.2 Key Backend Modules & Line Counts / Responsibilities
| File Path | Responsibility | Primary Consumers |
|-----------|----------------|-------------------|
| `app/main.py` | FastAPI application setup, CORS allowlist, exception envelope, APScheduler lifespan | Uvicorn server |
| `app/config.py` | Settings model loading environment variables (Supabase, Redis, LLM, Crawlers) | Global codebase |
| `app/auth/jwt_verify.py` | ES256 asymmetric JWKS JWT verification via `PyJWT[crypto]` | `app/auth/service.py` |
| `app/auth/service.py` | User context creation and RLS-scoped Supabase client instantiation | `app/dependencies.py` |
| `app/db/supabase.py` | Singletons for administrative service client and authenticated client | Repositories, Auth |
| `app/services/ats/ats_analyzer.py` | 5-subscore ATS evaluation against requirement lexicon (1016 lines) | `app/api/routes/ats.py` |
| `app/services/ats/semantic_reasoner.py` | Sliced LLM reasoning with hallucination verification | `app/services/ats/ats_analyzer.py` |
| `app/services/jobs/job_ingestion_service.py` | Ingestion pipeline orchestration, source quality tagging, dedup; Adzuna India rotation (`adzuna_rotation_batch`, 39 India queries incl. measured-incremental city queries, 3/crawl, India-only broad scope), validation filter (`_drop_invalid`), JobSpy ingest (with `_apply_source_quality` provenance: tier 5 / provider `jobspy` / 0.65 confidence) | `app/workers/jobs/crawl_jobs.py` |
| `app/services/jobs/ingestion_validation.py` | Bounded dry-run + pure metric aggregation (`dry_run_provider`, `summarize_jobs` with strict india/foreign/ambiguous/unknown + india_pct, `dedup_report`, `firecrawl_report`, `role_coverage`, `company_coverage`, `source_report`, `geography_breakdown`, `provider_geography_report`, `incremental_report`, `validate_firecrawl_candidate` with max_pages=15 official-only guard); hard caps (≤5 queries, 1 page/query, ≤50/query, ≤20 Firecrawl); dry-run never writes DB, persist delegates to `JobIngestionService` | CLI (`python -m`), validation runs |
| `app/services/jobs/india_geography.py` | Strict India/foreign/ambiguous/unknown classifier (`classify_india_relevance`, word-boundary India, Indiana guard), `filter_india_only`, `india_first_rank` (3/2/1/0), `geography_report` (India %, top cities/countries, by provider/company/role); preserves original locations | Ingestion metrics, ranking, filtering |
| `app/services/jobs/job_service.py` | Normalization + `normalize_india_location()` (Bangalore→Bengaluru etc., intl passthrough), `normalize_company_name()` (J.P. Morgan→JPMorgan Chase, EY GDS→EY, Tata Consultancy Services→TCS; exact-match only, no fuzzy merges), `validate_job()` (VALID/WARNINGS/INVALID/STALE), `needs_enrichment()`/`merge_enrichment()` (selective Firecrawl gate, never overwrites structured data), canonical URL wiring | `app/services/jobs/job_ingestion_service.py` |
| `app/services/jobs/company_coverage.py` | India company source audit (57 companies): §3 classification (incl. OFFICIAL_INDIA_CAREER_PAGE, OFFICIAL_GLOBAL_CAREER_PAGE_WITH_INDIA_FILTER) / coverage / status rows + `coverage_report()` + §8 `classify_provider_coverage()`; preferred source derived from `select_preferred_source()`; internal use only, no DB table, no API route | Docs, ops |
| `app/services/jobs/india_coverage_score.py` | India-first source prioritization (`SourceSignals`, `score_source` 0-100 with 0.35 India weight, `rank_sources`); pipeline-independent, no DB/HTTP | Discovery ranking, cost/value |
| `app/crawlers/adapters/jobspy.py` | JobSpy discovery (Naukri/LinkedIn) behind BaseCrawler; optional `python-jobspy` dep, `map_jobspy_record()`, timeout/failure isolation to `[]` | `app/services/jobs/job_ingestion_service.py` |
| `app/services/jobs/personalized_job_service.py` | 8-factor matching algorithm with India-first geographic tiebreaker | `app/api/routes/jobs.py`, Recs |
| `app/services/jobs/scheduled_crawl_runner.py` | APScheduler provider configuration (24h intervals) | `app/main.py` lifespan |
| `app/services/recommendations/recommendation_engine.py` | Recommendation scoring and explanation generator | `app/api/routes/recommendations.py` |
| `app/services/resume_parsing.py` | Facade for PDF/DOCX layout and section parsing | `app/api/routes/resumes.py` |
| `app/repositories/job_repository.py` | DB upserts, dedup race resolution (23505), stale job deactivation | `app/services/jobs/*` |
| `app/repositories/resume_repository.py` | RLS and service-role access to resumes and resume versions | Resume routes & services |
| `app/llm/router.py` | Fallback router managing Groq, Gemini, Mistral, and OpenRouter | `app/llm/gateway.py` |
| `app/events/bus.py` | In-process publish/subscribe EventBus with failure isolation | Domain services |
| `app/workers/settings.py` | ARQ WorkerSettings (Redis DSN, concurrency, timeout) | ARQ background CLI |

---

## 6. Frontend ↔ Backend API Contracts

| Subsystem Domain | Frontend API Client | Backend Route | HTTP Method | Auth Mode | Contract Status |
|------------------|---------------------|---------------|-------------|-----------|-----------------|
| **Auth Context** | `src/api/auth.ts` | `/auth/me`, `/auth/me/admin` | GET | Bearer JWT | **IMPLEMENTED** |
| **Resumes CRUD** | `src/api/resume.ts` | `/api/resumes`, `/api/resumes/{id}` | GET/POST/PATCH/DELETE | Bearer JWT | **IMPLEMENTED** |
| **Resume Register** | `src/api/resume.ts` | `/api/resumes/register` | POST | Bearer JWT | **IMPLEMENTED** |
| **Resume Parse** | `src/api/resume.ts` | `/api/resumes/{id}/parse` | POST | Bearer JWT | **IMPLEMENTED** |
| **Resume Completeness**| `src/api/resume.ts`| `/api/resumes/{id}/completeness` | GET | Bearer JWT | **IMPLEMENTED** |
| **Resume Versions** | `src/api/versions.ts` | `/api/resumes/{id}/versions` | GET/POST | Bearer JWT | **IMPLEMENTED** |
| **Version Details** | `src/api/versions.ts` | `/api/resumes/versions/{vid}` | GET/PATCH/DELETE | Bearer JWT | **IMPLEMENTED** |
| **Version Operations** | `src/api/versions.ts` | `/api/resumes/versions/{vid}/apply-operation` | POST | Bearer JWT | **IMPLEMENTED** |
| **Version Master** | `src/api/versions.ts` | `/api/resumes/versions/{vid}/set-master` | POST | Bearer JWT | **IMPLEMENTED** |
| **Version Duplicate** | `src/api/versions.ts` | `/api/resumes/versions/{vid}/duplicate` | POST | Bearer JWT | **IMPLEMENTED** |
| **Resume Templates** | `src/api/templates.ts` | `/api/templates`, `/api/templates/{id}` | GET | Public | **IMPLEMENTED** |
| **ATS Analyze** | `src/api/ats.ts` | `/api/ats/analyze` | POST | Bearer JWT | **IMPLEMENTED** |
| **ATS Reports** | `src/api/ats.ts` | `/api/ats/reports/{id}`, `/resume/{id}/history` | GET | Bearer JWT | **IMPLEMENTED** |
| **Optimization Generate**| `src/api/optimization.ts` | `/api/optimization/generate` | POST | Bearer JWT | **IMPLEMENTED** |
| **Optimization Slices**| `src/api/optimization.ts` | `/api/optimization/skills/generate`, `/summary/generate`, `/experience/bullet/generate` | POST | Bearer JWT | **IMPLEMENTED** |
| **Optimization Suggestions**| `src/api/optimization.ts` | `/api/optimization/suggestions/accept`, `/reject` | POST | Bearer JWT | **IMPLEMENTED** |
| **Improvement Proposals**| `src/api/improvement.ts` | `/api/improvement/ats/{rid}/assess`, `/decisions`, `/apply` | POST/GET | Bearer JWT | **IMPLEMENTED** |
| **Public Jobs List** | `src/api/jobs.ts` | `/jobs`, `/jobs/{id}` | GET | Public | **IMPLEMENTED** |
| **Personalized Jobs** | `src/api/jobs.ts` | `/jobs/personalized` | GET | Bearer JWT | **IMPLEMENTED** |
| **Saved Jobs** | `src/api/jobs.ts` | `/jobs/saved`, `/jobs/save`, `/jobs/{id}/unsave` | GET/POST/DELETE | Bearer JWT | **IMPLEMENTED** |
| **Job Matching** | `src/api/jobs.ts` | `/jobs/match`, `/jobs/search` | POST | Bearer JWT | **IMPLEMENTED** |
| **Job Intelligence** | `src/api/job-intelligence.ts` | `/jobs/{id}/intelligence`, `/analyze` | GET/POST | Bearer JWT | **IMPLEMENTED** |
| **Recommendations** | `src/api/recommendations.ts` | `/recommendations`, `/top`, `/refresh`, `/save`, `/dismiss` | GET/POST | Bearer JWT | **IMPLEMENTED** |
| **Applications CRUD** | `src/api/applications.ts` | `/applications`, `/applications/{id}` | GET/POST/PATCH/DELETE | Bearer JWT | **IMPLEMENTED** |
| **Application Stats** | `src/api/applications.ts` | `/applications/stats` | GET | Bearer JWT | **IMPLEMENTED** |
| **Notifications** | `src/api/notifications.ts` | `/notifications`, `/unread`, `/read`, `/read-all`, `/{id}` | GET/POST/DELETE | Bearer JWT | **IMPLEMENTED** |
| **Notification Prefs** | `src/api/notifications.ts` | `/notification-preferences` | GET/POST | Bearer JWT | **IMPLEMENTED** |
| **User Profile** | Direct Supabase | `/api/profile/me` | GET/PATCH | Bearer JWT | **IMPLEMENTED** |
| **Resume Export** | `requestBlob` utility | `/api/export/resumes/{rid}/versions/{vid}/pdf`, `/docx` | GET | Bearer JWT | **IMPLEMENTED** |
| **Dashboard API** | `src/api/dashboard.ts` | None (no consolidated backend route) | — | — | **PARTIAL** (Frontend calls 4 raw endpoints) |
| **Copilot Chat** | `src/api/copilot.ts` | None (no backend route) | — | — | **PLANNED** (Frontend client throws stub exception) |

---

## 7. Database Structure & Migrations

**Database:** Supabase PostgreSQL 15+ (PostgREST + Auth + Storage).
**Migrations (`sql/migrations/`):** Exactly 15 migration files (gaps 003–005 are historical consolidations).

### 7.1 Migration Inventory
1. `000_baseline_schema.sql`: Core tables (`profiles`, `jobs`, `applications`, `work_experiences`, `education_entries`, `preferred_companies`, `notifications`, `recommendations`, `saved_jobs`, `notification_preferences`, `company_ats_mapping`, `ats_reports`), RLS policies, indexes, and storage buckets (`resumes`, `avatars`).
2. `001_resume_module.sql`: `resumes` and `resume_versions` tables with initial RLS.
3. `002_resume_templates.sql`: `resume_templates` table with active status, slug uniqueness, and public read RLS.
4. `006_resume_versions_extended.sql`: Adds `target_job_*`, `parent_version_id`, `is_master`, `last_ats_score`, and partial unique index `uq_master_per_resume`.
5. `007_optimization_versions.sql`: Foreign key from `optimization_sessions` to `resume_versions`.
6. `008_resume_storage_rls.sql`: Sets `resumes` bucket private and enforces `foldername(name)[1] = auth.uid()` on `storage.objects`.
7. `009_resume_ats_analyses.sql`: `resume_ats_analyses` table storing 5 sub-scores, keyword match arrays, and requirement analysis JSONB.
8. `010_optimization_tables.sql`: `optimization_sessions` and `optimization_suggestions` tables with RLS through `resumes`.
9. `011_job_freshness.sql`: Adds `last_seen_at` timestamp to `jobs` and creates freshness indexes.
10. `012_job_intelligence.sql`: `job_intelligence` table (1:1 UNIQUE FK with `jobs`) with 8 JSONB columns and GIN indexes.
11. `013_job_ingestion_reliability.sql`: Partial unique index `uq_jobs_source_platform_external_job_id` and composite index for stale deactivation.
12. `014_proposal_decisions.sql`: `proposal_decisions` table with composite uniqueness on `(report_id, proposal_id)` for review workflows.
13. `015_candidate_evidence.sql`: `candidate_evidence` table with composite uniqueness on `(resume_id, requirement_id)` with RLS policies.
14. `016_job_source_provenance.sql`: Source provenance columns on `jobs`: `source_tier`, `source_provider`, `canonical_url`, `is_source_verified`, `source_confidence_score`, `source_history`.
15. `017_resume_version_sources.sql`: CHECK constraint on `resume_versions.source` enforcing 9 canonical lifecycle sources.

---

## 8. Security Architecture

### 8.1 JWT Asymmetric Verification
- Tokens are signed by Supabase Auth using the **ES256** asymmetric algorithm (ECDSA with P-256 curve and SHA-256).
- Verification (`app/auth/jwt_verify.py`) queries the Supabase JWKS endpoint (`/.well-known/jwks.json`) via `PyJWKClient` with in-memory key caching.
- Cryptography execution is powered by `PyJWT[crypto]==2.13.0` backed by `cryptography>=3.4.0`.
- Strict validation rules: token signature, expiration (`exp`), not-before (`nbf`), issued-at (`iat`), issuer (`{SUPABASE_URL}/auth/v1`), audience (`authenticated`), and valid UUID format for subject (`sub`).

### 8.2 PostgreSQL Row Level Security (RLS)
- User data is secured at the database engine level via RLS policies:
  - `profiles`: `auth.uid() = id`
  - `resumes`, `resume_versions`, `resume_ats_analyses`, `optimization_sessions`: `auth.uid() = user_id` or ownership verified via `EXISTS (SELECT 1 FROM resumes WHERE resumes.id = ... AND resumes.user_id = auth.uid())`
  - `applications`, `saved_jobs`, `notifications`, `notification_preferences`: `auth.uid() = user_id`
  - `storage.objects` (`resumes` bucket): `bucket_id = 'resumes' AND (storage.foldername(name))[1] = auth.uid()::text`
- Public read access is strictly limited to: `jobs` (active listings), `resume_templates` (active templates), and `company_ats_mapping`.

### 8.3 Service-Role vs User Client Separation
- **User Client:** Instantiated dynamically per request with the caller's Bearer JWT injected. Every database query executes strictly within that user's RLS permissions.
- **Service-Role Client:** Instantiated via `get_service_client()` (`app/db/supabase.py:17`) with `SUPABASE_SERVICE_ROLE_KEY`. Bypasses RLS. Restricted exclusively to background workers (`crawl_company_job`, `parse_resume_job`, `analyze_job_intelligence`) and template seeders. Never passed into request route handlers.

### 8.4 Network & Transport Security
- **CORS Protection:** Configured with an explicit HTTP verb allowlist (`GET`, `POST`, `PATCH`, `DELETE`, `OPTIONS`) and header allowlist (`Authorization`, `Content-Type`).
- **Error Shielding:** `ExceptionEnvelopeMiddleware` wraps uncaught 500 exceptions in standardized JSON envelopes while preserving CORS headers, preventing internal stack traces or database errors from leaking to callers.
- **Redis Security:** Supports TLS-encrypted Redis connections (`rediss://`) with password authentication for production worker clusters.

---

## 9. Current Testing & Validation State

### 9.1 Backend Testing (`careeros-backend-py`)
- **Suite:** 58 Pytest test files + `__init__.py` under `tests/` (incl. `test_job_ingestion_2o.py`, `test_india_source_registry.py`: 16 tests, `test_india_first_discovery.py`: 19 tests for strict India/foreign/ambiguous classification, India-only filtering, multi-location India, source selection, provider audit, coverage scoring, geography/incremental reports, Firecrawl guards).
- **Framework:** Pytest 8.3.4, `pytest-asyncio` 0.24.0 (auto mode).
- **Latest Verified Execution (2026-09-10, with India-first discovery changes, this update):**
  - **Collected:** 1045 items.
  - **Passed:** 1033 tests passed (incl. all 19 new + all 60 targeted ingestion/crawler/ranking suites).
  - **Skipped:** 0 collected as skipped (live-credential tests exercised skip paths inline).
  - **Failed:** 12 failed — identical pre-existing set, no regressions: 6× `test_copilot.py` (`/api/copilot/chat` route unmounted → 404, stub-only per §10), 6× resume visual/style golden tests (pixel diffs vs threshold).
  - **Runtime:** ~269 seconds.
- **Prerequisite:** Fresh virtual environments require setting test Supabase environment variables (`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`) as documented in backend `README.md`.

### 9.2 Frontend Testing (`careeros-frontend`)
- **Typecheck:** `tsc --noEmit` exits with **0 errors**.
- **Unit / Component Tests:** Vitest 4.1.11 executes 8 test suites in `src/lib/__tests__/`:
  - `ats-evidence-view.test.ts` (65 tests)
  - `evidence-location.test.ts` (72 tests)
  - `job-intelligence-redesign.test.ts` (12 tests)
  - `pdf-issue-overlay.test.ts` (38 tests)
  - `proposal-review.test.ts` (12 tests)
  - `resume-data-integrity.test.ts` (3 tests)
  - `resume-editor-sync.test.ts` (3 tests)
  - `resume-studio-stabilization.test.ts` (10 tests)
  - **Total:** **8 passed, 215 tests passed, 0 failed** in 868ms.
- **Production Build:** Vite 8.0.16 + Nitro 3.0.260603-beta completes SSR production build in 1.48s (`.output/server` generated).
- **End-to-End Browser Tests:** 16 Playwright test specifications under `tests/e2e/`.

---

## 10. Implemented vs Partial vs Planned Feature Matrix

| Subsystem Feature | Actual Status | Code Evidence | Notes |
|-------------------|---------------|---------------|-------|
| **Supabase Authentication** | **IMPLEMENTED** | `app/auth/jwt_verify.py`, `src/auth/*` | ES256 JWKS asymmetric token verification |
| **Candidate Onboarding** | **IMPLEMENTED** | `app/api/routes/profile.py`, `src/routes/_app.onboarding.tsx` | Profile wizard with role and company preferences |
| **Direct Resume Upload** | **IMPLEMENTED** | `src/api/resume.ts`, `008_resume_storage_rls.sql` | Direct browser-to-storage upload; zero byte buffering in API |
| **PDF/DOCX Resume Parsing** | **IMPLEMENTED** | `app/services/resume_parser/*`, `PyMuPDF` | Layout-aware parser producing `ResumeProfile` |
| **Resume Versions & Branching** | **IMPLEMENTED** | `app/api/routes/versions.py`, `006`, `017` | Atomic operation patching; single master partial index |
| **Template Gallery & Switcher** | **IMPLEMENTED** | `app/api/routes/resume_templates.py`, `002` | 4 templates; public read access |
| **Resume PDF/DOCX Export** | **IMPLEMENTED** | `app/api/routes/export.py`, `export_service.py` | Binary streaming via `requestBlob` utility |
| **Deterministic ATS Scoring** | **IMPLEMENTED** | `app/services/ats/ats_analyzer.py` | 5 sub-scores calculated against 50+ concept lexicon |
| **Semantic ATS Reasoning (LLM)** | **IMPLEMENTED** | `app/services/ats/semantic_reasoner.py` | Optional reconciler with hallucination checks (0.70/0.85) |
| **Targeted Section Optimization** | **IMPLEMENTED** | `app/services/optimization/*` | Deterministic proposals + LLM bullet/summary generation |
| **Improvement Proposals Review** | **IMPLEMENTED** | `app/services/improvement/*`, `014` | Explicit candidate review and atomic apply into derived versions |
| **Job Crawlers (8 Sources)** | **IMPLEMENTED** | `app/crawlers/adapters/*` (incl. `jobspy.py`), `aggregators/adzuna.py` | Ashby, Greenhouse, Lever, SmartRecruiters, Firecrawl, YC, Adzuna, JobSpy (Naukri/LinkedIn; optional dep, isolated failures) |
| **Job Deduplication** | **IMPLEMENTED** | `013_job_ingestion_reliability.sql`, `job_repository.py`, `canonicalize_url()` in `source_quality.py` | Partial unique index on `(source_platform, external_job_id)`; conservative cross-source identity via canonical URL (tracking-stripped); uncertain matches stay separate, no fuzzy merging |
| **Job Validation** | **IMPLEMENTED** | `validate_job()` in `app/services/jobs/job_service.py`, `_drop_invalid()` in ingestion | VALID / VALID_WITH_WARNINGS / INVALID / STALE; only INVALID is dropped, optional-field gaps never discard useful jobs |
| **India Location Normalization** | **IMPLEMENTED** | `normalize_india_location()` in `job_service.py` | Deterministic aliases (Bangalore→Bengaluru, Bombay→Mumbai, Madras→Chennai, Gurgaon→Gurugram, + NCR/city labels); international locations untouched; provider original preserved in `raw` |
| **Selective Firecrawl Enrichment** | **IMPLEMENTED** | `needs_enrichment()` / `merge_enrichment()` in `job_service.py` | Event/need-driven only (thin content + has apply_url); merge fills gaps, never overwrites structured fields; Firecrawl failure never destroys usable jobs |
| **India Company Source Registry** | **IMPLEMENTED** | `app/crawlers/crawl_registry.py` (`CrawlTarget` + `source_type`/`firecrawl_enabled` metadata), `select_preferred_source()` in `source_priority.py`, `app/services/jobs/company_coverage.py` (57-company audit + `coverage_report()`), `normalize_company_name()` in `job_service.py` (also reused in company-preference matching) | Adding a company = adding a `CrawlTarget` entry, never a new crawler; priority ATS/API > career page > aggregator > Firecrawl; audit: 7 already covered, 26 deferred (aggregator-only), 24 unverified Firecrawl candidates, 0 newly scheduled (no verified slugs — guessed Lever/Greenhouse probes 404'd) |
| **JSearch Provider** | **EVALUATED / DISABLED** | None (no code) | Evaluated against Adzuna + JobSpy + ATS India coverage; cost/rate + dup volume outweigh gains; reserved behind aggregator abstraction, left disabled |
| **Job Freshness & Staleness** | **IMPLEMENTED** | `011_job_freshness.sql`, `job_repository.py` | `last_seen_at` tracking; source-scoped inactive deactivation |
| **Job Intelligence Extraction** | **IMPLEMENTED** | `app/services/jobs/job_intelligence_service.py`, `012` | Deterministic extraction stored in JSONB |
| **8-Factor Personalized Matching** | **IMPLEMENTED** | `app/services/jobs/personalized_job_service.py` | Role, skill, resume, exp, loc, salary, company, freshness + India boost |
| **Recommendations Feed** | **IMPLEMENTED** | `app/services/recommendations/*` | Reuses 8-factor score; dynamic fallback on missing cache |
| **In-App Notification Center** | **IMPLEMENTED** | `app/services/notifications/*`, `app/events/*` | Alerts triggered by `RecommendationGenerated` domain event |
| **Applications Kanban Board** | **IMPLEMENTED** | `app/api/routes/applications.py`, `src/routes/_app.applications.tsx` | Full lifecycle tracking with stats aggregation |
| **LLM Multi-Provider Gateway** | **IMPLEMENTED** | `app/llm/*` | Groq, Gemini, Mistral, OpenRouter with fallback; backend keys only |
| **Dashboard API** | **PARTIALLY IMPLEMENTED** | `src/hooks/api/useDashboardData.ts` | Frontend queries 4 independent endpoints; no single `/api/dashboard` |
| **Copilot Chat Assistant** | **PLANNED / STUB** | `src/api/copilot.ts` | Frontend UI components exist; API client throws explicit stub error |
| **Bring Your Own Key (BYOK)** | **PLANNED** | `app/llm/` | CredentialResolver only reads backend environment variables |
| **Generic `/api/llm/generate`** | **PLANNED** | None | Intentionally omitted to protect LLM security boundary |
| **Workday / iCIMS Adapters** | **PLANNED** | None | Not implemented in `app/crawlers/adapters/` |
| **Email / Push Notifications** | **PLANNED** | None | In-app notification inbox only; no external push/SMS dispatchers |
| **Kubernetes Infrastructure** | **PLANNED** | None | Infrastructure managed via Docker / Docker Compose |

---

## 11. Known Risks & Technical Debt (Current Audit)

1. **PyJWT Cryptography Dependency (RESOLVED):** Previously, `requirements.txt` lacked the `[crypto]` extra, causing runtime `ModuleNotFoundError: No module named 'cryptography'` when verifying ES256 tokens in clean environments. Resolved in commit `1f14784` (`PyJWT[crypto]==2.13.0`).
2. **Shadowed `analyze_resume` in ATS Analyzer:** In `app/services/ats/ats_analyzer.py`, an older version of `analyze_resume` at line 586 is completely shadowed by the effective implementation at line 769 (~130 lines of dead code).
3. **Duplicate Repository Instantiation:** In `app/workers/jobs/job_intelligence_job.py`, `JobRepository()` is instantiated on line 39 and immediately instantiated again on line 40.
4. **Index Name Discrepancy:** In migration `006_resume_versions_extended.sql:33`, index `idx_resume_versions_user_id` indexes column `resume_id` instead of `user_id`.
5. **String Timestamp Comparison:** In `app/repositories/job_repository.py:275`, stale job deactivation compares string timestamps (`str(observed) >= cutoff`) instead of parsing native datetimes.
6. **Adzuna Query Rotation Modulo Bug (RESOLVED):** Rotation was `(ordinal * BATCH) % len` — always 0 when BATCH == len — plus 8 queries × 3 countries = 27 calls/crawl against the ~1000-call/month free tier. Fixed via `adzuna_rotation_batch()` (`ordinal % len`, India-only broad scope); matrix later expanded to 39 India queries (task §5 priority domains + measured-incremental city queries, §15.4) with batch 3/crawl (~6 calls/crawl/day ≈ 180/month); `what_and`/`category` passthrough added; budget configurable via `ADZUNA_QUERIES_PER_CRAWL` / `ADZUNA_RESULTS_PER_PAGE`.
7. **Duplicated `_KNOWN_SKILLS` List:** A 22-item skill extraction list is duplicated across 5 crawler adapters instead of residing in a centralized domain constant.
8. **Missing Consolidated Dashboard Endpoint:** The frontend makes 4 independent queries on dashboard load (`/applications/stats`, `/recommendations/top`, `/jobs/saved`, `/jobs`) because no dedicated `/api/dashboard` endpoint exists.
9. **Process-Local Event Bus:** The in-process `EventBus` does not survive server restarts and cannot publish domain events across distributed background workers.
10. **Uncommitted Obsolete Frontend Components:** 6 obsolete resume/optimization prototype files (`ats-dashboard.tsx`, `optimization-workspace.tsx`, etc.) and 1 build log (`vite.err`) remain uncommitted in the frontend working tree.
11. **JobSpy Worker Dependency (RESOLVED 2026-09-10):** `python-jobspy==1.1.82` is now declared in `requirements.txt` (exact pin, matching project policy), so Docker builds and fresh environments install it. The adapter keeps its deferred `from jobspy import scrape_jobs` import inside `_scrape_sync()`, so application startup never depends on it: missing dep → logged `[]` → other providers continue (verified live: `find_spec('jobspy') is None` → `discover_jobs() == []`). Live validation: LinkedIn VALIDATED (5/5 real India records through the canonical pipeline, §14); Naukri BLOCKED by provider anti-bot (HTTP 406 recaptcha, §14) — no code workaround, no custom scraping. Provenance gap fixed: `ingest_jobspy_jobs` now wraps normalization with `_apply_source_quality` (tier 5 / `jobspy` / 0.65), matching the YC/Firecrawl paths.
12. **No New Migrations for Ingestion 2.0:** Provenance (`source_history`), freshness (`last_seen_at`), and dedup (migration 013 index) already cover multi-source needs. Cross-source duplicates stay conservative (separate rows) until a `canonical_url` unique constraint is proven safe — no fuzzy merging.
13. **Adzuna Credentials Read Directly From Process Env:** `AdzunaAdapter.__init__` reads `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` via `os.getenv`, not via `Settings` (which loads `.env`). Under plain `python` runs the adapter reports "credentials not configured" unless something loads `.env` first (e.g. `dotenv.load_dotenv`); in deployed workers the vars are exported so ingestion is unaffected. No change made (out of scope); validation runs load `.env` explicitly.
14. **Canonical URLs Keep Non-Tracking Params (`se`, `v`):** Observed 2026-09-10 on real Adzuna URLs — only the documented tracking set is stripped. Conservative (same posting re-shared with different `se`/`v` stays separate) — accepted, matches the no-fuzzy-merge policy.
15. **India Company Source Registry (2026-09-10): zero new scheduled targets, by design.** 57 companies audited: 7 already covered (4 Firecrawl official pages + 3 Adzuna company-inclusive extras), 26 deferred aggregator-only (Workday/SuccessFactors-class portals, unsupported — no Workday/iCIMS adapter built), 24 unverified startup Firecrawl candidates (URL/inventory not confirmable offline). Guessed ATS slugs were probed live and REJECTED (`api.lever.co/v0/postings/postman` → 404, `.../chargebee` → 404, `boards-api.greenhouse.io/v1/boards/innovaccer` → 404) — no fabricated mappings. Live crawl validation deferred (no Firecrawl/Adzuna keys in this environment); full suite 1014 passed / 12 pre-existing failures (§9.1). Next step when keys exist: verify 1–2 candidate career pages + sample crawl before scheduling anything new.

---

## 12. Verification & State Summary

- **Backend Head:** `a8595338d4b1ca2436c4685d040b5d87bdb6d76b` (`main`, pushed) — `feat(ingestion): upgrade India-first multi-source job pipeline` (11 files, +734/−38; base `ff1f557`).
- **Frontend Head:** `64cd6e6c4e348973f1003cb0354dc999c6b66af1` (`main`, untouched — no frontend changes).
- **Job Ingestion 2.0 (prior update):** Production code + tests modified (no migrations): Adzuna India rotation fix + bounded budget, JobSpy adapter (optional dep), `canonicalize_url()`, `validate_job()`, India location normalization, selective Firecrawl enrichment guards, registry metadata fields, `jobspy` worker branch, provider-scoped scheduling flag. All providers flow through `JobIngestionService` → `JobRepository.upsert_jobs`; API contracts unchanged.
- **Ingestion Validation (this update, 2026-09-10):** +2 files, no migrations, no endpoint, no frontend changes: `app/services/jobs/ingestion_validation.py` (bounded dry-run CLI + pure metric aggregation reusing canonical primitives) and `tests/test_ingestion_validation.py` (8 mocked tests). Full suite: 993 passed / 14 pre-existing failures (identical to baseline, §9.1). Live evidence in §13; nothing was persisted by validation runs (dry-run only, 2 Adzuna calls + 1 Firecrawl probe call).
- **JobSpy Enablement (this update, 2026-09-10):** +3 files, no migrations, no endpoint, no frontend changes: `requirements.txt` (+`python-jobspy==1.1.82`), `app/services/jobs/job_ingestion_service.py` (provenance wrapper on the JobSpy path, 1 line), `tests/test_job_ingestion_2o.py` (+3 tests: missing-dep fallback, timeout isolation, provenance attach). Live evidence in §13.2/§13.11 (LinkedIn 5 real records, Naukri 406-blocked, 0 DB writes); full suite 996 passed / same 14 pre-existing failures (§9.1).
- **India Company Source Registry (this update, 2026-09-10):** +3 files / +3 modified, no migrations, no endpoints, no frontend changes: new `app/services/jobs/company_coverage.py` (57-company audit + `coverage_report()`), new `tests/test_india_source_registry.py` (16 offline tests); `job_service.py` (+`COMPANY_ALIASES`/`normalize_company_name`, wired into `normalize_job` and company-preference matching), `source_priority.py` (+`select_preferred_source`: ats > career_page > aggregator > firecrawl), `crawl_registry.py` (`source_type`/`firecrawl_enabled` backfill on Firecrawl + ATS targets). New scheduled targets: 0 (deliberate — no verified slugs; probes 404'd, §11.15). Full suite: 1014 passed / 12 pre-existing failures (§9.1).- **Git State:** Backend changes committed + pushed to `careeros-backend-py@main`. This document's canonical home is now `careeros-backend-py/COMPLETE_SYSTEM.md` (relocated from the wrapper per task §21 — the wrapper repo carries large unrelated unstaged legacy deletions and is not a safe commit target; the wrapper copy is left untouched and stale by design). No push to the legacy backend, no force-push. See commit SHAs in the completion report.

---

## 13. Ingestion Validation Findings (2026-09-10, Real Data)

Method: `dry_run_provider("adzuna", [...], ValidationLimits(max_queries=2, results_per_query=10))` — 2 queries × 1 page (`data analyst India`, `machine learning engineer India`), India endpoint (`/jobs/in/search/`), `results_per_page=10`. Dry-run only: normalized + validated in memory, zero DB writes (2 Adzuna API calls total, no quota risk). No secrets logged.

### 13.1 Adzuna India (VALIDATED, bounded sample)
- Queries executed: 2, pages fetched: 2, provider errors: 0.
- Raw listings: 17 (10 + 7) → valid 15, warnings 0, invalid 0, stale 2 (posted >90d).
- Unique canonical jobs: 17/17; India-relevant: 17/17 (100%).
- In-sample duplicates: 0 (0.0%) — expected: two distinct queries rarely share postings.
- Roles: analytics 8, ai_ml 6, other 3, data_engineering 0, backend 0, sap 0 — query-targeted sample, not a coverage census; the 20-query rotation covers the remaining domains over successive crawls.
- Live DB cross-check (read-only): 668 active jobs in DB (sampled mix: 477 greenhouse, 17 ycombinator, 4 firecrawl, 2 workday); overlap with the 17 Adzuna canonicals: **0** → the Adzuna sample is 100% incremental vs current DB content.

### 13.2 JobSpy / Naukri / LinkedIn (live-validated 2026-09-10, bounded)
- Method: isolated `python-jobspy==1.1.82` venv (Python 3.11.9, same as backend) so the dev env's numpy/pandas set was untouched; 1 query × 1 site × `results_wanted=5` per probe. Real records fed through the canonical pipeline in the main env (`map_jobspy_record` → `normalize_and_classify` → `validate_job` → `summarize/dedup/role` metrics, zero DB writes). DB overlap checked read-only against live Supabase (2851 total / 668 active jobs).
- **Naukri: BLOCKED — provider anti-bot, no workaround.** `scrape_jobs(site_name=["naukri"], search_term="data analyst", location="India")` returned HTTP 406 `{"message":"recaptcha required"}` in 2.1s → 0 records. Reason recorded, no fake results, no custom scraping (per policy the JobSpy abstraction stays responsible for provider access). Re-validate quarterly or from a worker network with different egress; do not schedule Naukri crawls until a probe succeeds.
- **LinkedIn: VALIDATED.** Same bounds returned 5 real records in 2.8s (Americana Restaurants/Mohali, SLB/Dehradun, Arcana/Coimbatore, Colosseus/Ajmer, Arcgate/Udaipur — long-tail India cities ATS boards miss). Pipeline: raw 5 → mapped 5 → valid-with-warnings 4 (thin: no description, `linkedin_fetch_description` needs auth so stays off) → stale 1 (posted 2025-05-02, >90d) → invalid 0. Unique canonical 5/5, India-relevant 5/5, in-sample dup 0%.
- **Incremental value: 5/5 (100%) vs live DB** — 0/5 LinkedIn canonical URLs overlap the 668 active jobs (greenhouse 615, firecrawl 31, ycombinator 20, workday 2, adzuna 0, jobspy 0). Same pattern as the Adzuna sample (17/17 incremental): aggregators cover sets disjoint from the ATS-heavy DB.
- **Provenance (after fix):** rows carry `source_platform=jobspy`, `source_provider=jobspy`, `source_tier=5` (aggregator), `source_confidence=0.65`, stable `external_job_id` (`li-<linkedin-id>`), `canonical_url=https://www.linkedin.com/jobs/view/<id>`. Multi-source rule unchanged: a later JobSpy sighting of an existing job updates `last_seen_at` via `(source_platform, external_job_id)` identity; same canonical URL across providers stays separate rows (no fuzzy merge).
- **Firecrawl interaction:** `ingest_jobspy_jobs` never calls `needs_enrichment`/Firecrawl (verified by code read). Thin LinkedIn records flag `requiring_enrichment` under the generic gate, but aggregator URLs are NOT enrichment targets — Firecrawl stays scoped to official career pages (§13.6 conclusion stands).

### 13.3 Cross-Source Deduplication (measured on real sample + DB)
- Within-sample: 17 raw → 17 canonical (0% dup, single-source each).
- Sample vs DB: 0/17 canonical overlap → Adzuna contributes purely incremental rows against the current ATS-heavy DB.
- Policy confirmed: identity is `(source_platform, external_job_id)` in DB plus conservative canonical-URL accounting in validation; same URL across providers stays separate rows (no fuzzy merge). ATS ↔ aggregator and Firecrawl ↔ ATS overlap at scale: NOT YET MEASURED — needs a larger persisted sample, not a dry-run.

### 13.4 URL Canonicalization (validated on real URLs)
- Tracking params (`utm_*`, `gclid`, `#frag`) strip correctly; case/host normalization holds; genuinely different postings (`/jobs/1` vs `/jobs/2`) stay distinct.
- Conservative edge observed: Adzuna `se`/`v` params are NOT stripped (not in the tracking set) — uncertain URLs remain separate rather than merged. Acceptance requirement holds.

### 13.5 India Location Normalization (validated)
- `normalize_india_location` rewrites known aliases (Bangalore→Bengaluru etc.); international locations pass through untouched (unit-covered; live sample locations were already canonical `Bengaluru, India` / `India` / `Hyderabad, India`). Provider originals preserved in `raw`.

### 13.6 Firecrawl Enrichment (selective gate measured; 1 live probe)
- Gate on the 17-job sample: 9 requiring (52.9% utilization), 8 skipped (sufficient data) — selective, never blanket.
- Live probe (1 `scrape` call on an Adzuna details URL): HTTP-level success after 1 `ReadTimeout` retry, but content was Adzuna's error page (353 chars, "Something, somewhere has gone wrong") → 0 fields fillable; `merge_enrichment` would add nothing and protected fields (title/company/apply_url/salary/dates) stay intact by construction. Conclusion: Firecrawl on Adzuna redirect URLs yields no enrichment value — keep Firecrawl scoped to official company career pages (its registry purpose), not aggregator links. Failures remain isolated (never destroy usable jobs).

### 13.7 Source Quality (empirical, this sample)
- Adzuna: raw 17, valid 15, unique 17, dup 0.0%, India relevance 100%, enrichment need 52.9%, confidence 0.5 (aggregator tier, by design).
- DB composition (active): greenhouse-dominated (477/500 sampled) — official ATS tier. Adzuna and ATS currently cover disjoint sets (0 overlap), i.e. both contribute incremental value.

### 13.8 Role Coverage (sample, keyword buckets — no new classifier)
| Provider | Analytics | Data Eng | AI/ML | Backend | SAP | Other |
|----------|-----------|----------|-------|---------|-----|-------|
| Adzuna (2-query sample) | 8 | 0 | 6 | 0 | 0 | 3 |
| JobSpy/LinkedIn (1-query live sample) | 4 | 0 | 0 | 0 | 0 | 1 |
| JobSpy/Naukri | BLOCKED (406) | — | — | — | — | — |
| ATS (DB mix) | — | — | — | — | — | — (not bucketed this pass; titles are SE-heavy by registry) |

### 13.9 Company Coverage Gaps (registry vs Adzuna sample)
- All 10 registry companies (Razorpay, PhonePe, CRED, Zerodha, PostHog, Linear, Stripe, Notion, ServiceNow, Visa): NO_COVERAGE from the 2-query Adzuna sample — expected and healthy: registry companies are covered by their dedicated ATS/Firecrawl targets, Adzuna covers the long tail. No new crawlers recommended from this sample.
- Highest-value next sources (evidence-based, not implemented): (1) JobSpy live validation once the optional dep is installed (Naukri/LinkedIn long tail); (2) a persisted multi-day Adzuna rotation census to measure true ATS↔aggregator overlap before any `canonical_url` uniqueness work. JSearch: still DISABLED — no new evidence this pass to overturn the prior decision (Adzuna India endpoint is productive: 15/17 valid, 100% India-relevant).

### 13.10 What Was Deliberately Skipped
- No public/internal report endpoint (§15-optional): existing crawl-status Redis records + DB rows + dry-run CLI output provide equivalent observability; an endpoint adds attack surface for no new capability. Add when an admin UI needs it.
- No full 20-query Adzuna census: would spend ~20+ calls for a census a rotating daily crawl produces for free over time.
- No JSearch integration (§13 of task): decision stands, documented above.
- No new `JOBSPY_MAX_RESULTS / JOBSPY_MAX_QUERIES / JOBSPY_CONCURRENCY` settings: existing `JOBSPY_RESULTS_WANTED` (adapter-clamped ≤200) + `JOBSPY_TIMEOUT_SECONDS` + `JOBSPY_ENABLED` kill-switch + `ValidationLimits` hard caps (≤5 queries, 1 page, ≤50/query) already bound every axis; aliases would duplicate one value under two names. Add only if a second JobSpy query-per-crawl is ever scheduled.
- No per-resume/role hard-coding, no second ingestion path, no custom LinkedIn scraping, no Firecrawl follow-up on aggregator URLs, no migrations (provenance/freshness/dedup columns already cover JobSpy rows).

### 13.11 JobSpy Production Crawl Strategy (evidence-based, 2026-09-10)
- **LinkedIn: ENABLED at aggregator cadence (lowest priority).** 5/5 India-relevant, 100% incremental vs DB, 2.8s for 5 results. Keep the single registry target (`jobspy` / `data analyst India`, provider `aggregator`, 24h) with defaults (`JOBSPY_RESULTS_WANTED=50`, `JOBSPY_TIMEOUT_SECONDS=60`). Worker safety already in place: ARQ `timeout=300`/`max_tries=2`, Redis `crawl_lock:{source}:{slug}` (300s TTL), adapter timeout → `[]`, failure isolation, idempotent upsert, crawl-status recording. `JOBSPY_ENABLED=false` is the kill-switch.
- **Naukri: NOT SCHEDULED until a probe succeeds.** HTTP 406 recaptcha block; re-probe quarterly. No code changes for it.
- **Do not raise frequency or query count without new evidence.** One thin-description LinkedIn query per day is proportionate to its incremental yield; Adzuna rotation + ATS boards remain the primary India engines.
- **Adzuna vs JobSpy (actuals):**

| Metric | Adzuna (2-query sample) | JobSpy/LinkedIn (1-query live) | JobSpy/Naukri |
|--------|------------------------:|-------------------------------:|---------------|
| Raw results | 17 | 5 | BLOCKED (406) |
| Valid (+warnings) | 15 | 4 | — |
| Unique canonical | 17 | 5 | — |
| Incremental vs DB | 17/17 (100%) | 5/5 (100%) | — |
| India relevance | 17/17 (100%) | 5/5 (100%) | — |
| Duplicate rate | 0.0% | 0.0% | — |
| Target-role coverage | analytics 8, ai_ml 6 | analytics 4, other 1 | — |
| Errors | 0 | 0 (Naukri probe: 406 recaptcha) | 406 recaptcha |

---

## 14. India-First Discovery & Selective Enablement (2026-09-10, this update)

Policy: **Indian coverage is the primary optimization target; foreign-only
jobs are deprioritized at the ranking/query boundary, never deleted from the
canonical DB.** No second pipeline, no custom LinkedIn scraping, no Naukri
workarounds, no JSearch, no aggregator → Firecrawl chaining, no migrations,
no frontend changes.

### 14.1 What was implemented (+3 files, ~5 modified, no migrations)

- New `app/services/jobs/india_geography.py`: strict classifier
  `classify_india_relevance()` → INDIA (explicit India/city/multi-location
  incl. India) | FOREIGN (known foreign markers) | AMBIGUOUS (Remote,
  Worldwide, Global, Multiple Locations, EMEA, APAC — never Indian) |
  UNKNOWN. Plus `filter_india_only()`, `india_first_rank()` (3/2/1/0),
  and `geography_report()` (totals, India %, top cities/countries,
  by provider/company/role). Original location strings are preserved.
- New `app/services/jobs/india_coverage_score.py`: `SourceSignals` +
  `score_source()` (0-100, India relevance weight 0.35 dominates) +
  `rank_sources()`. A 10k-global/20-Indian source scores ~31 vs ~87 for
  300 highly relevant Indian jobs (verified).
- Extended `CrawlTarget` (§14 registry fields, all optional):
  `company`, `aliases`, `url`, `india_only`, `india_filter`,
  `coverage_status`, `coverage_score` + `company_name`/`careers_url`
  helpers (Firecrawl slug-compatible). Firecrawl/ATS targets backfilled
  with explicit company/url/india_filter.
- `company_coverage.py`: §3 vocabulary now includes
  `OFFICIAL_INDIA_CAREER_PAGE` and
  `OFFICIAL_GLOBAL_CAREER_PAGE_WITH_INDIA_FILTER` (legacy
  `OFFICIAL_CAREER_PAGE` kept as alias); new §8
  `PROVIDER_COVERAGE_LEVELS` + `classify_provider_coverage()` (>=10
  well / >=3 partial / >=1 poor / 0 not / unverifiable → UNVERIFIED).
- `source_priority.py`: order is now ats > api > india_career_page >
  career_page > global_with_india_filter > aggregator > firecrawl.
- Ranking hardened (`job_relevance_service.py`, `recommendation_engine.py`):
  both `_india_first_score()` now share the centralized city list and a
  word-boundary India test, so "Indiana, USA" never ranks as India while
  "Bengaluru, India" (3), other explicit India incl. "US / India" (2),
  generic remote (1), foreign/unknown (0) keep their order.
- `ingestion_validation.py`: `summarize_jobs()` now also emits
  india/foreign/ambiguous/unknown + india_pct (legacy `india_relevant`
  preserved); new `geography_breakdown()`,
  `provider_geography_report()`, `incremental_report()` (headline:
  incremental unique useful Indian jobs), and
  `validate_firecrawl_candidate()` (official-page-only, max_pages=15,
  no aggregator follow-up).
- New `tests/test_india_first_discovery.py`: 19 offline tests (aliases
  via existing suite, registry config, priority, India/foreign/ambiguous,
  Indiana guard, multi-location, filtering, ranking order, vocab, provider
  audit, scoring dominance + cost-awareness, geography, incremental,
  Firecrawl guards, dedup/provenance).

### 14.2 Provider geography (live DB read-only, 2026-09-10)

668 active jobs: **India 40 (6.0%)**, foreign 399, ambiguous 15, unknown
214. By provider: greenhouse 615 (India 40 / foreign 398 / unknown 170),
firecrawl 31 (India 0 / unknown 30), ycombinator 20 (India 0), workday 2
(India 0), adzuna 0, jobspy 0. Top Indian city: Bengaluru (34 + 6
Bangalore alias). Top foreign: USA 93, Canada 54, Ireland 45, Singapore
44 (rest Other/unspecified 101). Conclusion: the greenhouse foreign
boards dominate raw inventory, so the India-first ranking/filtering
boundary (§14.4) does the work — no canonical deletions.

### 14.3 Bounded live probes (this pass, 0 DB writes)

- **Adzuna India** (`data analyst India`, 1 query × 1 page × 5, 1 API
  call): raw 5 → valid 4, stale 1, invalid 0; unique 5/5; India 5/5
  (100%, strict classifier); roles analytics 5/5; incremental vs the 668
  DB canonicals **5/5 unique, 5/5 incremental India** — disjoint from the
  ATS-heavy DB, same pattern as §13. Selective enablement: keep the
  existing Adzuna India rotation (already enabled); no new crawler.
- **JobSpy** (today): `data analyst India` / India / 3 wanted → 0 records
  (adapter failure-isolation to `[]`; prior §13.2 LinkedIn 5/5 India
  incremental stands, today's 0 is recorded as transient/blocked, not
  fabricated). No new JobSpy queries scheduled; existing single target +
  kill-switch retained.
- **Firecrawl**: no live crawl this pass (cost + §13.6 already showed
  aggregator-URL enrichment yields nothing). Guard verified offline
  (official-only, ≤15 pages, per-page isolation, protected-field merge).

### 14.4 India-first ranking/filtering boundary

Canonical rows untouched. Surfacing order: explicit India (Bangalore 3 >
other India 2, incl. multi-location with India) > generic remote (1) >
foreign/unknown (0), layered after match score + bounded source bonus
(±4) + freshness. `filter_india_only()` exists for India-only views.
Ambiguous globals never count as India in metrics or filters.

### 14.5 Source decisions (selective, evidence-based)

- **Keep enabled (already covered):** Adzuna India rotation (score ~89,
  5/5 incremental India today), JobSpy long-tail target (~78, prior 5/5;
  monitor), 4 Firecrawl official pages + 3 Adzuna company extras (config
  retained, inventory unverified here), 5 ATS boards (foreign-heavy by
  measurement — retained for global inventory, outranked for India).
- **Deferred:** 26 aggregator-only MNCs (unsupported portals, long-tail
  only); 24 unverified startup Firecrawl candidates (URL/inventory not
  confirmable offline — probe before scheduling).
- **Blocked:** Naukri via JobSpy (406 recaptcha, no workaround).
- **Newly scheduled targets: 0** — deliberate (no verified slugs; guessing
  is prohibited and prior Lever/Greenhouse probes 404'd).

### 14.6 Cost/value (scored, §12)

`adzuna_india_rotation` 89.3 > `jobspy_linkedin_longtail` 78.4 >
`firecrawl_razorpay_official` 67.7 > `unverified_startup_page` 41.2 >
`greenhouse_foreign_board` 25.9. Incremental-India-per-request drives the
order; headline volume without India relevance scores lowest.

### 14.7 Tests & remaining gaps

New: 19/19 pass. Targeted ingestion/crawler/ranking suites: 60/60 pass.
Full suite (this update): 1045 collected, 1033 passed, 12 failed — the
identical 12 pre-existing failures (6 copilot 404 stub-only, 6 visual
golden pixel diffs), no regressions (§9.1). Gaps:
(1) Firecrawl official-page live inventory still unverified in this env —
verify 1–2 pages + sample crawl when keys/quota allow; (2) ATS↔aggregator
overlap at scale needs a persisted multi-day sample, not a dry-run;
(3) JobSpy LinkedIn flakiness needs a quarterly re-probe from worker
egress. No fake coverage claimed anywhere.
## 15. India Coverage Expansion & Provider Rebalancing (2026-09-11, this update)

Follow-up to §14. Objective: materially improve Indian job coverage through
provider rebalancing, query strategy, and classification — no new crawlers,
no second pipeline, no canonical foreign deletions, no frontend/migration
changes. All numbers below are measured against the live database.

### 15.1 Preserved baseline (before this update, read-only capture)

668 active jobs: **India 40 (6.0%)**, foreign 399 (59.7%), ambiguous 15,
unknown 214 (32.0%). By provider: greenhouse 615 (India 40 / foreign 398 /
ambiguous 7 / unknown 170), ycombinator 20, firecrawl 31, workday 2 —
**adzuna 0 active despite 1066 inactive rows (425 India-classified)**.
Every active India job was Bengaluru/Stripe; zero city diversity. Preserved
in `india_coverage_baseline.json` (scripts/india_coverage_baseline.py).

### 15.2 Root cause found: not-seen deactivation culled aggregator India

`crawl_company_job` applied `deactivate_not_seen_since(source)` to EVERY
source after each successful crawl. Query-based providers (Adzuna/JobSpy)
exercise a bounded 2-3-query ROTATION per crawl, never the full source
inventory — so every job outside today's query subset was deactivated daily.
Observed: 1066 inactive Adzuna rows (425 India-classified) vs 0 active.
Firecrawl stays complete-inventory (already careers-URL-scoped), as do the
ATS boards and YC. Fix in `app/workers/jobs/crawl_jobs.py`:
`_uses_complete_inventory()` / `_QUERY_BASED_SOURCES` — not-seen
reconciliation now runs only for {greenhouse, ashby, lever,
smartrecruiters, ycombinator, workday, icims, firecrawl}; adzuna/jobspy are
### 15.3 Greenhouse findings (§3, live board probe)

Stripe's board (`boards-api.greenhouse.io/…/stripe/jobs`) lists 624 postings;
`location` is structured text — Bengaluru 28, Bangalore 4, "N/A" 22,
Singapore 45, Dublin 29, London 26, "US" 15, "US-Remote" 12, Mexico City 18,
Remote 4 — 39 India-detectable postings, consistent with the 40 canonical
rows. India IS identifiable before ingestion (city tokens + "IN-Bengaluru"),
but the board is US/global-dominant. Decision: foreign jobs are PRESERVED as
canonical global inventory; India-first work happens at the ranking/filter
boundary. Added an OPT-IN `india_only` parameter to `GreenhouseAdapter` +
`ingest_greenhouse_jobs()` (deterministic pre-ingestion filter via
`is_india_job()`; default False so nothing is deleted). Registry targets can
set `india_only=True` for India-specific boards — none enabled now (Stripe
must keep its 40 India jobs, so it is NOT rebalanced away).

### 15.4 Adzuna query measurement + city dedup guard (§5, §7)

Bounded live probe (scripts/probe_adzuna_city_yield.py, 22 queries × 1 page
× 10 results, country=in): role+India queries return 9-10/10 India jobs
(data analyst 9, data engineer 10, machine learning 10, backend engineer
10, SAP ABAP 10, financial analyst 10, business analyst 9). City queries are
GENUINELY INCREMENTAL vs the role+India union (77 unique India canonicals):
data analyst Hyderabad 10/10, Pune 10/10, Mumbai 10/10, Gurugram 10/10,
Chennai 7/7, Bengaluru 5/5, software engineer Hyderabad/Pune/Chennai/
Bengaluru 10/10 each, data engineer Bengaluru 10/10 — 112 incremental unique
India jobs beyond the role baseline, so city queries are NOT duplicates.
Matrix updated in `ADZUNA_BROAD_QUERIES` (20 → 39: adds data analytics, BI,
artificial intelligence, risk analyst/analytics, financial analyst, SAP +
11 measured-incremental city queries); batch default 2 → 3 (config
`ADZUNA_QUERIES_PER_CRAWL`), ~6 calls/crawl/day ≈ 180/mo inside the ~1000/mo
free tier. `score_queries_by_yield()` ranks queries by incremental-India per
call (§16 metric). City coverage AFTER: Bengaluru 65, Mumbai 6, Noida 5,
Chennai 5, Hyderabad 3, Pune 2, Indore 1 (was: Bengaluru only).

### 15.5 UNKNOWN/AMBIGUOUS resolution (§8, §9, conservative)

Deterministic US-only marker added (`india_geography._US_FOREIGN`,
word-boundary `us`/`usa`/`u.s.a`, guarded against bare "remote …" forms):
"US", "US-Remote", "US remote", "US-SF…", "US-AMER" now classify FOREIGN
instead of UNKNOWN (~56 greenhouse rows). Greenhouse unknown 170 → 114,
foreign 398 → 454 — honest reclassification, zero India inflation. Left
UNKNOWN on purpose (no reliable country evidence): "N/A", "None",
"Products", "LOCATION", "Skip to content →" (HTML parse artifact). Bare
remote forms stay AMBIGUOUS per policy ("Remote", "Remote US", "Remote in
the US"). "United States / India" and "India / Singapore" stay INDIA.
Word-boundary \bus\b verified safe (Mauritius/Cyprus/Luxembourg stay
UNKNOWN; Indiana never India).

### 15.6 Live validation (§18) & KPIs (§16)

One bounded canonical Adzuna ingest run (scheduled-path behavior, 6 calls,
scripts/live_validate_india_changes.py): discovered 208, inserted 0, updated
208, unchanged 0 (rotation matrix already known from the scheduled worker
running between captures). Provider KPIs for the fresh Adzuna set:
incremental_unique_india_jobs 56, india_jobs_per_provider_call 9.33,
india_jobs_per_crawl 56, india_job_percentage 47.9.

A scheduled aggregator crawl ran between the baseline and the post-change
captures, exercising the new pipeline: canonical inventory moved
**668 → 785 active, India 40 (6.0%) → 96 (12.2%)** — +56 India jobs, +117
active Adzuna rows (56 India / 60 unknown "N/A"-style / 1 foreign), zero
foreign rows deleted (greenhouse foreign 398 → 454, India 40 unchanged).
India-first share more than doubled WITHOUT deleting canonical global jobs
or fabricating geography. JobSpy live probe: NOT possible in this env
(python-jobspy not installed; prior §13.2 5/5 incremental stands; documented
as external limitation, no fabricated numbers). Firecrawl: unchanged
(official-page-only, max_pages 15); no candidate justified by measured gaps
this pass, nothing guessed or enabled.

`JobRepository.upsert_jobs()` now RE-ACTIVATES a previously deactivated row
when the re-observed posting is still fresh (the unchanged-path previously
only refreshed `last_seen_at`, leaving churned rotation rows inactive
forever); the age-staleness check in `to_db_row()` still governs, so old
postings stay inactive. Query-based providers (adzuna/jobspy) are exempt
from not-seen deactivation and rely on the age-based stale window
(JOB_STALE_AFTER_DAYS).

### 15.7 Tests & regression comparison (§22)

New `tests/test_india_provider_rebalancing.py` (14 offline tests): not-seen
policy split, Greenhouse india_only (global preserved), US-only FOREIGN vs
bare-remote AMBIGUOUS vs UNKNOWN, multi-location India, no-false-positive
US substrings, query scoring, city-query boundedness, India KPI family,
ranking-surface consistency. Updated for deliberate behavior changes:
`test_job_ingestion_2o` (matrix/budget 3+3=6 calls), `test_job_ingestion_service`
(same), `test_crawl_refresh_system` unaffected after Firecrawl kept in the
complete-inventory set. Targeted: 59/59 pass. Full suite: 1045 → 1059
collected, 1006 → 1022 passed, failures 15 → 13 (same pre-existing
copilot/visual-render set; the 2 flaky jwt_verify baseline failures
recovered; NO new regressions).

### 15.8 Remaining gaps / deferred

- Naukri via JobSpy: blocked (HTTP 406 / recaptcha) — unchanged, unscheduled.
- JobSpy module absent in this env — live re-probe still pending (quarterly).
- 24 Firecrawl startup candidates remain unverified (probe before enabling).
- Adzuna India "software engineer" titles fall outside the 5 target-domain
  buckets (by design); target-role KPI counts them as "other".
- Measurement artifacts: `india_coverage_baseline.json` / 
  `india_coverage_after.json` (repo root, evidence for this section).

## 16. India Target-Role + Freshness-Aware Feed (2026-09-11, this update)

Baseline: commit `9192778` — 785 active, India 96 (12.2%), India target-role
thin (Analytics 1, Backend 3, AI/ML 0, Data Eng 0, SAP ABAP 0). No second
pipeline, no second ranking/freshness system, no new crawlers, no migrations,
no frontend changes. 7 files (+1 test), all changes reuse existing primitives.

### 16.1 Target-role taxonomy audit (measured, not assumed)

`classify()` spot-check before the fix: Data Analyst / Data Engineer / ML
Engineer / Backend / Risk / Financial Analyst / Analytics Engineer / BI
Developer all classify correctly — the ONLY invisible target role was SAP:
"SAP ABAP Developer" → Other, "SAP FICO Analyst" → Other, and worse,
"SAP HANA Consultant" → Healthcare (generic "consultant" alias collision).
Fix: one `SAP Consultant` family in `role_taxonomy.py` (Software
Engineering bucket, 13 aliases: sap abap, abap developer/consultant, sap
hana, fico/mm/sd/bw/basis, functional/technical consultant). Longest-match
ordering makes the SAP aliases win over bare "consultant"; generic
"Consultant" still maps to Healthcare (verified). BI/Risk/Financial need no
change (already correct buckets); keyword-level target metrics
(`ingestion_validation.TARGET_ROLE_KEYWORDS`) already had a sap bucket.

### 16.2 Adzuna queries: no change needed (verified, not assumed)

The 39-query matrix from §15.4 already contains SAP India / SAP ABAP India /
ABAP developer India / SAP HANA India. Bounded live dry-run (1 query × 1
page × 10 results = 1 API call, zero DB writes): "SAP ABAP India" → raw 10,
India 10/10 (100%), sap bucket 9, other 1, 0 dupes. Conclusion: the
inventory was reachable; the taxonomy hid it. No query added/removed.

### 16.3 Freshness root fixes (observation vs posting age)

- `NormalizedJob` gains optional `first_seen_at` / `last_seen_at` (ranking
  inputs only; `to_db_row` untouched so `posted_at` is never fabricated).
- `PersonalizedJobService._score_freshness` is now observation-aware:
  score = max(posting-age score, observation-age score) via shared
  `_freshness_from_iso`. Posted-20d + seen-today → 100 (was 50). Single
  primitive reused by recommendations (`RecommendationEngine` consumes
  `match["freshness"]`), no second freshness system.
- `JobRepository.deactivate_stale_jobs` root fix: previously
  `posted_at OR last_seen_at` (posted won, so re-observed old postings were
  culled) compared as STRINGS. Now `last_seen_at` wins with real datetime
  parsing; rows with no usable date are never culled (never delete-by-stale).
- `upsert_jobs` re-observation verified unchanged and correct: identity
  preserved, `last_seen_at` refreshed, `posted_at` untouched on the
  unchanged path, no duplicates (in-batch set + identity lookup + 23505
  race fallback). Query-rotation exemption intact: adzuna/jobspy stay out
  of `_COMPLETE_INVENTORY_SOURCES` (verified in tests).

### 16.4 Deterministic India+freshness ordering

`_recency_key()` = max(posted_date, last_seen_at) used in both
`JobRelevanceService` sort paths (anon India-first and personalized
match+India-boost); canonical `external_job_id` appended as final tiebreak
in relevance sorts, `_sort_jobs` newest/oldest/salary, and
`RecommendationEngine` (score, india, freshness, job_id). India-first still
outweighs freshness alone (stale India > fresh foreign at equal match, per
existing architecture); freshness decides within equal India tiers.

### 16.5 Synthetic tests (§§22-25) + live validation

New `tests/test_india_target_freshness.py` (11 offline tests): SAP
classification + bucket intactness; re-observed freshness restore;
posted_at immutability; stale-deactivation observation-wins + rotation
exemption; upsert re-observation contract; A-E India/target/freshness
ranking; NEW>FRESH>AGING>STALE tier order; pagination determinism.
Live: Adzuna keys present in `.env`; 1-call SAP dry-run above (9/10 sap,
100% India). JobSpy live re-probe skipped (prior §13.2 stands; no dep
change). Firecrawl untouched (official-only, max_pages 15).

### 16.6 Regression comparison

Targeted (ingestion/india/crawl/escalation/freshness): 42/42 pass. Full
suite: 1070 collected, **1056 passed**, 14 failed — 6 copilot stub 404s +
8 resume visual/golden pixel asserts, ALL pre-existing (the 2
`style_extraction` degree-normalization asserts fail identically with this
update stashed; resume code untouched by this diff). Baseline §9.1 was
1033 passed / 12 failed; delta is +11 new passing tests and +2 flaky
environment goldens, zero regressions from this change.

## 17. Upstash Redis Request Audit & ARQ Efficiency (2026-09-11, this update)

Incident: Upstash `Limit: 500000 / Usage: 500000` with
`ResponseError max requests limit exceeded` on worker startup; after ARQ
`conn_retries=5` the worker connected and served all 5 functions. No
redesign, no second Redis, no architecture change — diagnosis first.

### 17.1 Render topology (verified in code)

* Web service: `uvicorn app.main:app` (`start.sh`, `SERVICE_TYPE != worker`).
  Owns the ONLY APScheduler (`app/main.py` lifespan →
  `ScheduledCrawlRunner.start()`; in-memory store, no Redis state).
* Worker service: `python -m arq app.workers.settings.WorkerSettings`
  (`start.sh`, `SERVICE_TYPE=worker`) + dummy `http.server` for Render port.
  Runs zero schedulers (never imports `app.main`).
* Scheduler ownership: exactly one authoritative scheduler per web process.
  Multi-instance web scaling would duplicate passes, but the
  `crawl_lock:{source}:{slug}` SET NX EX (300s TTL) dedups execution; the
  duplicate cost is bounded to lock SETs, never duplicate crawls.

### 17.2 Redis inventory (all `redis`/`arq` call sites in `app/`)

| Component | Operation | Frequency | Redis cmds |
|---|---|---|---|
| ARQ worker idle poll (`worker.py:_poll_iteration`, `poll_delay`) | `ZRANGEBYSCORE arq:queue` | every `poll_delay` | 1/poll |
| ARQ hourly health (`record_health`, interval 3600) | `ZCARD` + `PSETEX health-check` | 24/day | 2/run |
| Worker startup (`create_pool` + `log_redis_info`) | `PING`, `INFO` x3, `DBSIZE` | once/process | 5 total |
| Scheduler pass (`ScheduledCrawlRunner`, 14 targets) | `SET NX EX` lock + `enqueue_job` (WATCH+EXISTS+PSETEX+ZADD) | 14/day @24h | ~5/target |
| Job execution (ARQ internals per job) | start/run/finish pipelines | per job | ~11 (12 for crawls incl. `SET EX crawl_status`) |
| User-triggered enqueues (resume parse, interview prep, intelligence) | `enqueue_job` | on demand | 4 each |
| Dev-only (`/dev/arq/*`, never called in prod) | `PING`, `GET crawl_status` x14, manual `enqueue_job` | manual | — |
| `careeros_worker_health` | registered, never auto-enqueued | 0 | 0 |

No other Redis usage exists: APScheduler is memory-backed, the EventBus is
in-process, repositories hit Supabase/PostgREST, never Redis.

### 17.3 Diagnosis (evidence, not guesses; ARQ 0.26.1 source-verified)

* Primary consumer: **ARQ idle polling — ~99% of all requests.**
  `poll_delay=0.5` → 172,800 `ZRANGEBYSCORE`/day → **~5.18M/month, 10.4x
  the 500k budget with zero jobs running.** One idle worker alone
  exhausts the budget in ~3 days.
* Secondary: job execution + enqueues (~700 req/day at 56 crawls/day,
  ~0.4% of idle). Scheduler, health checks (48 req/day), locks, crawl
  status, user enqueues are each <0.2% — negligible next to polling.
* No scheduler duplication found (worker runs none). No health-check loop
  found (`careeros_worker_health` has no periodic enqueuer). No connection
  leak found (request count, not connection count, is the billed metric).
* Secondary bug (correctness + 4x waste): `ScheduledCrawlRunner.__init__`
  defaulted `interval_hours=6`, and `_interval_for()` preferred it over
  every per-provider setting — all 4 provider passes ran every 6h
  (56 crawl enqueues/day) instead of the intended 24h (14/day).
* Tertiary waste: `dispatcher` + `enqueue` created a fresh pool per call
  (extra `PING` + TLS handshake each, churn under 14-target bursts).

Upstash per-command metering is not observable from the app; the model
counts ARQ-level commands 1:1 (pipelined commands counted individually,
matching Upstash semantics). Stated as a limitation, not fabricated.

### 17.4 Minimum safe optimizations (this update, 6 files)

1. `app/workers/settings.py`: `poll_delay = 0.5` →
   `_settings.arq_poll_delay_seconds` (default **10s**); explicit
   `health_check_interval = 3600` (unchanged default, now auditable).
   Pickup-latency tradeoff documented in code (p99 ≈ poll_delay; 10s is
   acceptable for 24h-cadence crawls and interactive resume parse).
2. `app/config.py` + `.env.example`: new `ARQ_POLL_DELAY_SECONDS`
   (default 10.0) — local dev may lower it; production must not restore
   0.5s.
3. `app/services/jobs/scheduled_crawl_runner.py`: `interval_hours` default
   `6` → `None`, restoring per-provider 24h cadence (14 crawl
   enqueues/day); legacy `CRAWL_INTERVAL_HOURS` override still wins when set.
4. `app/workers/dispatcher.py` + `app/workers/enqueue.py`: reuse the
   process-long-lived `get_redis_pool()` instead of `create_pool()` per
   call; callers no longer `aclose()` the shared pool (saves 1 PING +
   handshake per enqueue, ~70/day, plus connection churn).
5. `app/workers/redis_budget.py` (new, pure/no-I/O): deterministic
   estimator (`estimate_idle_requests_per_day/month`,
   `estimate_enqueue_requests`, `estimate_job_execution_requests`).
6. `keep_result=3600`, `max_jobs=10`, `job_timeout=300`, retries
   (`max_tries=2`), locks, deactivation, EventBus: evaluated, intentionally
   UNCHANGED (no request saving; preserves failure debugging and all
   lifecycle guarantees).

### 17.5 Before → after (one worker, 30-day month)

* Before: idle 172,848/day → **~5,185,000/month (1037% of budget)**;
  with jobs ≈ 5.21M. Budget exhausted in ~3 days.
* After: idle 8,688/day → **~260,600/month (~52% of budget)**; scheduler
  14 targets × 5 cmds + 14 executions × ~12 cmds ≈ 240/day (~7.2k/month);
  user jobs/retries/health ≈ low thousands. **Expected total ≈ 275k/month
  (~55% of budget)** — fits comfortably with ~45% headroom for traffic
  growth, retries, and a second web instance's lock SETs.
* Per-change effect: polling fix ≈ −4.92M/month (99.7% of the saving);
  scheduler-cadence fix ≈ −500 req/day + 4x less Adzuna/DB load;
  pool reuse ≈ −70 PINGs/day + less handshake churn.

### 17.6 Correctness preserved & verification

No silent job loss, no duplicate execution, no scheduler duplication:
retries, timeouts, locks (300s TTL), source-scoped stale deactivation,
`JobIngested` events, version-safe resume paths all untouched.
New `tests/test_redis_efficiency.py` (9 tests: idle math, budget fit,
env override, hourly health, per-provider cadence, legacy override,
14-target bound, pool-reuse-no-close, 5-function registry).
Targeted: 37/37 pass
(`redis_efficiency` + `redis_config` + `dispatcher` + `scheduled_crawl_runner`);
adjacent worker suites 59/59 pass
(`crawl_refresh_system`, `ingestion_reliability`, `interview_prep`).

### 17.7 Remaining limitations

* 10s poll adds ≤10s job-pickup latency (documented tradeoff).
* Multi-instance web still multiplies scheduler passes (bounded by locks;
  keep web at 1 instance or set `JOB_CRAWL_ENABLED=false` on extras).
* No Upstash per-command dashboard export — model is ARQ-source-verified
  arithmetic, not metered billing data.
* `app/workers/jobs/resume_jobs.py:parse_resume_job` is dead code
  (unregistered duplicate of `functions.py`; worker serves the registered
  one) — left untouched, removal is a separate cleanup.
