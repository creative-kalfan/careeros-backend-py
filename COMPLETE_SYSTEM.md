# CareerOS — Complete System Map & Reality Audit
**Authoritative Reference & Personal System Map**
**Date:** 2026-09-03
**Status:** Local Personal Document (Uncommitted / Reference-Only)

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
- **Technology:** Python 3.11.9, FastAPI 0.115.6, Uvicorn 0.34.0, Pydantic v2 (2.10.4), Supabase Python client 2.11.0, PyMuPDF 1.25.3, python-docx 1.1.2, ARQ 0.26.1, Redis 5.3.1, APScheduler 3.11.3, PyJWT[crypto] 2.13.0, Sentry SDK 2.19.2.
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
  - Job Aggregators: Adzuna India (`/v1/api/jobs/in/search/{page}`, 20-query India rotation, ~5 calls/crawl/day) + JobSpy (`app/crawlers/adapters/jobspy.py`, Naukri/LinkedIn coverage, optional `python-jobspy` dep, graceful empty when uninstalled).
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
│   ├── requirements.txt (PyJWT[crypto]==2.13.0)
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
| `app/services/jobs/job_ingestion_service.py` | Ingestion pipeline orchestration, source quality tagging, dedup; Adzuna India rotation (`adzuna_rotation_batch`, 20 India queries, 2/crawl, India-only broad scope), validation filter (`_drop_invalid`), JobSpy ingest | `app/workers/jobs/crawl_jobs.py` |
| `app/services/jobs/job_service.py` | Normalization + `normalize_india_location()` (Bangalore→Bengaluru etc., intl passthrough), `validate_job()` (VALID/WARNINGS/INVALID/STALE), `needs_enrichment()`/`merge_enrichment()` (selective Firecrawl gate, never overwrites structured data), canonical URL wiring | `app/services/jobs/job_ingestion_service.py` |
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
- **Suite:** 55 Pytest test files + `__init__.py` under `tests/` (incl. `test_job_ingestion_2o.py`: 15 tests for India endpoint, rotation, JobSpy, canonical URL, validation, India normalization, enrichment guard, provenance, registry, workers).
- **Framework:** Pytest 8.3.4, `pytest-asyncio` 0.24.0 (auto mode).
- **Latest Verified Execution (2026-09-10, with Ingestion 2.0 changes):**
  - **Collected:** 999 items.
  - **Passed:** 985 tests passed (incl. all 15 new + all ingestion/crawler/scheduler suites: 58/58 targeted).
  - **Skipped:** 0 collected as skipped (live-credential tests exercised skip paths inline).
  - **Failed:** 14 failed — ALL pre-existing and unrelated to ingestion (verified failing on clean tree via `git stash`): 6× `test_copilot.py` (`/api/copilot/chat` route unmounted → 404, stub-only per §10), 8× resume visual/style golden tests (Groq rate-limit → legacy-parser fallback + pixel diffs 3.9–16.0 vs 2.0 threshold).
  - **Runtime:** ~422 seconds.
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
6. **Adzuna Query Rotation Modulo Bug (RESOLVED):** Rotation was `(ordinal * BATCH) % len` — always 0 when BATCH == len — plus 8 queries × 3 countries = 27 calls/crawl against the ~1000-call/month free tier. Fixed via `adzuna_rotation_batch()` (`ordinal % len`, 20 India queries across analytics/engineering/AI-ML/backend/SAP, 2 per crawl, India-only broad scope → ~5 calls/crawl/day ≈ 150/month); `what_and`/`category` passthrough added; budget configurable via `ADZUNA_QUERIES_PER_CRAWL` / `ADZUNA_RESULTS_PER_PAGE`.
7. **Duplicated `_KNOWN_SKILLS` List:** A 22-item skill extraction list is duplicated across 5 crawler adapters instead of residing in a centralized domain constant.
8. **Missing Consolidated Dashboard Endpoint:** The frontend makes 4 independent queries on dashboard load (`/applications/stats`, `/recommendations/top`, `/jobs/saved`, `/jobs`) because no dedicated `/api/dashboard` endpoint exists.
9. **Process-Local Event Bus:** The in-process `EventBus` does not survive server restarts and cannot publish domain events across distributed background workers.
10. **Uncommitted Obsolete Frontend Components:** 6 obsolete resume/optimization prototype files (`ats-dashboard.tsx`, `optimization-workspace.tsx`, etc.) and 1 build log (`vite.err`) remain uncommitted in the frontend working tree.
11. **JobSpy Optional Dependency:** `python-jobspy` is intentionally NOT in `requirements.txt`. The adapter degrades to an empty (logged) crawl when uninstalled; install it only on workers that run JobSpy discovery. No RLS/schema impact (reuses `JobIngestionService` → `JobRepository.upsert_jobs`).
12. **No New Migrations for Ingestion 2.0:** Provenance (`source_history`), freshness (`last_seen_at`), and dedup (migration 013 index) already cover multi-source needs. Cross-source duplicates stay conservative (separate rows) until a `canonical_url` unique constraint is proven safe — no fuzzy merging.

---

## 12. Verification & State Summary

- **Backend Head:** `a8595338d4b1ca2436c4685d040b5d87bdb6d76b` (`main`, pushed) — `feat(ingestion): upgrade India-first multi-source job pipeline` (11 files, +734/−38; base `ff1f557`).
- **Frontend Head:** `64cd6e6c4e348973f1003cb0354dc999c6b66af1` (`main`, untouched — no frontend changes).
- **Job Ingestion 2.0 (this update):** Production code + tests modified (no migrations): Adzuna India rotation fix + bounded budget, JobSpy adapter (optional dep), `canonicalize_url()`, `validate_job()`, India location normalization, selective Firecrawl enrichment guards, registry metadata fields, `jobspy` worker branch, provider-scoped scheduling flag. All providers flow through `JobIngestionService` → `JobRepository.upsert_jobs`; API contracts unchanged.
- **Git State:** Backend changes committed + pushed to `careeros-backend-py@main`; this document committed to the wrapper repo. See commit SHAs in the completion report.

---

## 13. Job Intelligence Stabilization Pass (2026-09-12)

One continuous end-to-end pass over the existing Job Intelligence surface. No
architecture change, no second pipeline, no crawler/service rewrite.

### Fixes

- **Salary contract (DB → API → UI):** `JobOut` now exposes `salary_min` /
  `salary_max` / `salary_currency` alongside the legacy `salary` string
  (`app/schemas/job.py::from_db_row`). Frontend `adaptJob` prefers the
  numeric fields (migration 020) and falls back to parsing the string; genuinely
  unknown salary still renders "Not disclosed" — never fabricated.
- **Experience filter:** `"Fresher"` now maps to the Entry bucket
  (`job_relevance_service.py::_python_filter`), alongside junior/intern/entry.
  Stored `experience_level` NULLs continue to use the existing
  title/description inference, so crawlers need not populate the column.
- **Remote definition:** unchanged single definition (explicit flag OR location
  text) enforced Python-side; DB pre-filter stays bypassed for remote so
  flag-remote rows with plain city locations are not dropped. Hybrid is display
  only (`toWorkMode`); no Hybrid filter is offered because the backend exposes
  only a boolean remote flag.
- **`pageSize`:** GET routes already accepted `pageSize`/`page_size`;
  `POST /jobs/search` now also accepts snake_case `page_size` and
  `employment_type` in addition to camelCase.
- **`includeAts`:** `GET /jobs/personalized` now accepts both `includeAts`
  (frontend) and `include_ats`; both remain documented no-ops for scoring
  (`ats_score` stays null until ATS-on-jobs is implemented).
- **Dead contract removed:** `roleCategory` and `includeInactive` dropped from
  frontend `JobSearchFilters` — the backend never consumed them and the client
  never sent them. `NormalizedJob.roleCategory` (display) is untouched.
- **Detail/saved shapes:** `getJob` accepts backend `data` directly or wrapped
  as `{ job }`; `getSavedJobs` accepts the backend raw array or legacy
  `{ savedJobs }`. No backend change (other clients unaffected).
- **Bookmarks:** the Jobs page merges `useSavedJobs` ids over the personalized
  feed, so saved state survives pagination, refresh, and navigation, and both
  views agree. Optimistic updates + `["jobs","saved"]` invalidation unchanged;
  no new state architecture, no duplicate storage. (`adaptJob` default
  `bookmarked: false` retained for unmerged contexts.)
- **Truthful AI Insights:** removed fabricated fallbacks (90% experience,
  100% location, 85% salary, "Mid-Level", "Verified"). Missing breakdowns now
  render "Not enough data — run analysis"; seniority shows the real stored
  value or an unavailable note; ATS shows the real score or "Not available".
  Fresh `matchResult` still takes precedence via the existing
  `matchScore ?? overall` + snake/camel readers; the selected-job stale guard
  (`effectiveMatchResult`) is unchanged.
- **Re-analyze:** untouched and verified — real stored profile, canonical DB
  job on `jobId`, canonical `calculate_match_score`, normalized aliases
  (companyName/role/overview/techStack/applyUrl/postedDate), structured errors
  (JOB_REQUIRED/INVALID_RESUME_TEXT/JOB_NOT_FOUND/MATCH_FAILED).

### Left intentionally alone

- `useSearchJobs` / `useJob` / `buildSearchFilters`: unused but functional,
  not user-facing — no broad cleanup per minimal-diff rule.
- `JobRepository.list_jobs` remote/role_category DB filters: not on the
  relevance path (service bypasses with `None` + Python filter); untouched.
- `requirements` / `responsibilities` have no DB columns (020 covers skills
  but not these); the UI hides empty sections truthfully. A future additive
  migration can persist them — not added here.
- Ranking, diversification, freshness, Redis/ARQ, scheduler, crawlers:
  untouched (feed-diversification + candidate-pool suites still green).

### Deployment note

- **Migration `020_job_feature_columns.sql` must be applied** to the live
  Supabase DB before numeric salary/remote/workplace/employment/experience/skills
  filtering can rely on persisted values. Additive + nullable, no backfill
  (NULL = source did not provide). `COMPLETE_SYSTEM.md §7` inventory (15
  files) predates migrations 018–020; they exist in `sql/migrations/`.

### Verification (2026-09-12)

- New `tests/test_job_stabilization.py`: 5 passed (numeric salary contract,
  salary-string passthrough, Fresher→Entry, search snake_case aliases,
  includeAts/include_ats both 200).
- Existing suites: 52 passed (`test_job_api`, `test_job_filtering`,
  `test_job_relevance_service`, `test_job_feed_fix`, `test_job_filter_audit`,
  `test_job_repository`) + 9 passed (`test_jobs_route_order`,
  `test_job_ingestion_service`, `test_job_intelligence_api`).
- Frontend: `npx tsc --noEmit` clean; Vitest `src/lib/__tests__`: 14 files /
  260 tests passed.

## 14. Frontend Truthfulness & Stability Pass (2026-09-12)

One comprehensive frontend-only pass (no backend/DB/migration changes, no new
architecture, no duplicate API layer). Every visible feature re-traced
UI → hook → API client → backend route → response → UI state.

### Fixes (all in `careeros-frontend`, 15 files, net −204 lines)

- **Dashboard fabrication removed:** deleted `fallbackData` (hardcoded 88
  health, 14/6/3/1 funnel, Stripe/Linear/Vercel activity) from
  `_app.dashboard.tsx`. The page now gates on the real `useDashboardData`
  `isLoading`, renders a truthful empty state when there is no workspace data,
  and shows only live counts (telemetry + aggregated queries). Directive cards
  carry real pool counts or plain next-actions — no fabricated roles/companies/
  score deltas. Health `delta` renders 0 (no measured-change source exists).
- **Copilot history de-faked:** `CopilotPanel` no longer seeds
  `mockConversations` as the user's own threads; history starts with one empty
  conversation and the existing empty `WelcomeState`. Deleted the now-unreferenced
  `mockConversations` + `generateMockResponse` exports from `lib/copilot-data.ts`
  (types/tools/module routing retained). Copilot page status badge flips to
  "Unavailable" after a failed request instead of a static "Online"; suggestion
  chips/buttons disable while a request is pending.
- **Auth infinite-spinner fixed:** `AuthProvider` exposes `profileFetchFailed`
  (+ `fetchProfile(force?)` retry). `_app.tsx` and `_auth.tsx` render a
  retryable error (Retry → `fetchProfile(true)`, Sign out) instead of spinning
  forever when the profile request fails.
- **Export 401 recovery:** `requestBlob` now shares the single
  `tryRefreshAndRetry` 401 path with `request()` (fresh AbortController +
  timeout). Resume PDF/DOCX export no longer fails on expired tokens while
  every JSON call recovers.
- **Job-feed race fix:** `RequestOptions.signal` linked to the internal timeout
  controller; `jobsApi.getJobs/searchJobs/getPersonalizedJobs/getJob` accept an
  optional signal and `useJobs/usePersonalizedJobs/useJob/useSearchJobs` forward
  TanStack's per-fetch signal. Fast typing/filter/pagination changes abort
  superseded fetches instead of resolving them over newer UI state.
  `keepPreviousData` + existing query keys unchanged; Job Intelligence
  filters/pagination/match/bookmark logic untouched.
- **Admin page de-faked:** orphan `/admin` (no nav entry) rendered hardcoded
  platform numbers (1,234 users…) plus fake activity and a dead `/api/admin/stats`
  fetch. Overview now renders the same honest "Not available yet" state as the
  other tabs until a real admin metrics endpoint exists.

### Deliberately left alone (verified, not user-facing defects)

- `components/ats/{left,center,right}-pane.tsx` + `lib/ats-data.ts` mocks: **dead
  code** — no route renders them (`_app.ats` redirects to `/resumes`,
  `_app.ats-history` uses real history + `useResumes`, Studio uses
  `components/resume/left-pane`). Left in tree per minimal-diff rule.
- Notifications `isLoading` full-page skeleton: initial-load only (TanStack
  `isLoading` is false during background refetch), so no blank-on-refetch bug.
- `useSearchJobs`/`useJob`/`buildSearchFilters`, dead `DASHBOARD/*` +
  `COPILOT/*` endpoint constants, duplicate `POST /api/optimization/tailor`
  wrappers, `api/auth.ts` stubs: unused-but-harmless; no user impact, no change.
- Copilot is **live** (`POST /api/copilot/chat`, truthful LLM_UNAVAILABLE/
  TIMEOUT handling) — earlier "stub" notes in §6/§10 are stale for the frontend
  client; backend `/api/copilot/chat` старше 404s in backend pytest
  (`test_copilot.py`) remain a backend-side matter.
- Interview Prep routes/hooks: fully wired to real endpoints with
  skeleton/error/empty/failed states — no change needed.

### Capability status after this pass

| Feature | Status | Evidence |
|---|---|---|
| Auth/onboarding/profile | WORKING (+retryable profile error) | `AuthProvider`, `_app.tsx`, `_auth.tsx` |
| Resume upload/parse/Studio/versions/export | WORKING | unchanged; export 401 fixed |
| ATS analyze/history/Studio dialog | WORKING | unchanged; dead 3-pane mocks unrendered |
| Optimization/improvement/tailoring | WORKING | unchanged |
| Jobs search/filter/pagination/detail/bookmarks | WORKING (+abort) | unchanged logic; signal only |
| Job intelligence/match | WORKING | unchanged (truthful fallbacks from prior pass) |
| Recommendations/dismiss/save | WORKING | unchanged |
| Notifications + preferences | WORKING | unchanged (optimistic + rollback intact) |
| Applications Kanban + stats | WORKING | unchanged |
| Interview Prep | WORKING | verified wired, untouched |
| Dashboard | WORKING (truthful empty) | fabrication removed |
| Copilot chat + panel | WORKING (truthful status) | live endpoint, history starts empty |
| Admin portal | UNAVAILABLE (honest) | no backend endpoint; placeholder UI |
| Dashboard `api/dashboard.ts` stubs, `api/auth.ts` stubs | DEAD (unreferenced) | no callers; left untouched |

### Verification (2026-09-12, this pass)

- `npx tsc --noEmit`: 0 errors.
- Vitest `src/lib/__tests__`: 14 files / 260 tests passed (incl.
  `job-intelligence-redesign` 14 tests — Job Intelligence regression green).
- Production build (`npm run build`, Vite 8 + Nitro): client + SSR + Nitro
  prebuilt successfully.
- No runtime browser verification (no live backend/credentials in this
  environment) — verification is static + unit + build only.

---

## 13. Final Production Job Feed Verification (2026-09-16)

### Objective
Final verification and targeted stabilization pass for the production job feed, inventory quality, saved jobs asynchronous execution, and daily refresh pipeline.

### 1. Live Database Inventory Audit
Queried against canonical Supabase PostgreSQL database:
- **Total active jobs:** 77
- **India-verified:** 58 (75.3%)
- **Foreign:** 0 (0.0%)
- **Ambiguous (Remote):** 7 (9.1%)
- **Unknown (Remote / Unspecified):** 12 (15.6%)
- **Target-role matches:** 77 / 77 (100.0%)
- **Distinct companies:** 51
- **Provider distribution:**
  - `adzuna`: 58
  - `ycombinator`: 19
- **Deactivated during audit:**
  - 1 synthetic test row (`e2ee6764-059d-4693-9cde-423c5e83c350`: "Test Firecrawl Engineer" at "TestCo")
  - 1 US YC posting (`1620986a-d17a-4e46-bc88-b23027605ee6`: "Forward Deployed AI Engineer, Backend - West Palm Beach" at "Draftwise")

### 2. Freshness & Staleness Distribution
- `<= 1 day old`: 19 jobs (refreshed via live YC crawl)
- `<= 3 days old`: 0 jobs
- `<= 7 days old`: 2 jobs
- `> 7 days old`: 56 jobs
- `Stale (> 30 days old)`: 0 jobs by `last_seen_at` observation window (all active jobs observed within the 30-day cutoff).

### 3. Production API Endpoints Verified
Verified against live production backend (`https://career-os-kr9m.onrender.com`):
- `GET /health` -> 200 OK (`{"status":"ok"}`)
- `GET /version` -> 200 OK (`{"version":"studio-qa-v2","commit":"71faf79"}`)
- `GET /jobs/personalized` -> 200 OK (20 jobs returned)
- `GET /recommendations` -> 200 OK (2 items returned)
- `GET /applications/stats` -> 200 OK (17 metrics returned)
- `GET /notifications` -> 200 OK
- `GET /api/dashboard` -> 200 OK
- `GET /jobs/saved` / `POST /jobs/save` / `DELETE /jobs/{id}/unsave`:
  - **Root cause of 500 on Render:** `AsyncQueryRequestBuilder` returned from async Supabase postgrest query has no `.single()` method and returns an awaitable coroutine. Calling `.single()` caused an `AttributeError`, and missing `await` on query execution returned un-awaited coroutines.
  - **Targeted fix:** Removed `.single()` call on upsert builder and properly handled `await res` across saved jobs endpoints in `app/api/routes/jobs.py`.

### 4. Saved Jobs End-to-End Verification
Executed authenticated lifecycle test using live test user (`careeros-test-user@example.com`):
1. Initial load: returned empty list `[]` (200 OK)
2. Save real job: `POST /jobs/save` with real UUID -> succeeded with 200 OK
3. Reload: `GET /jobs/saved` -> returned 1 saved job with correct `job_id`
4. Unsave: `DELETE /jobs/{job_id}/unsave` -> succeeded with `{"unsaved": true}` (200 OK)
5. Reload: `GET /jobs/saved` -> returned empty list `[]` (200 OK)
Zero 500s, zero 401s, zero unhandled coroutine warnings.

### 5. First-20 Personalized Feed Composition
Evaluated with representative candidate profile (Data Analyst, Python/SQL/Excel/Power BI, Bangalore):
- **Top 10:** 10 / 10 India-verified (100%), 10 distinct companies.
- **Top 20:** 18 India-verified, 1 ambiguous remote, 1 unknown remote, 0 foreign. 20 distinct companies.
- **Top 30:** 24 India-verified, 5 ambiguous remote, 1 unknown remote, 0 foreign. 30 distinct companies.

### 6. Daily Refresh & Scheduler Verification
- `ScheduledCrawlRunner` starts via FastAPI `lifespan` with per-provider 24-hour interval triggers.
- Live crawl execution verified on `ycombinator` target: 20 jobs discovered, 16 inserted, 4 updated, 16 not-seen deactivated in 28.2 seconds.
- **Infrastructure constraint identified:** The free-tier Upstash Redis instance (`sincere-hagfish-149579.upstash.io`) reached its 500,000 monthly request limit, causing Redis commands to raise `ResponseError: max requests limit exceeded`. Ingestion pipeline itself functions cleanly and can run scheduled passes directly.

### 7. Test Suites & Verification
- **Backend Targeted Regression Suite:** 51 tests passed (`tests/test_jobs_route_order.py`, `tests/test_job_feed_fix.py`, `tests/test_job_filter_audit.py`, `tests/test_job_stabilization.py`, `tests/test_job_ingestion_2o.py`, `tests/test_job_production_verification.py`).
- **Frontend Build:** `npm run build` (Vite 8 + Nitro) passed in 1.00s with zero errors.
- **Git Commits:**
  - `careeros-frontend`: `4c075cb` (enforce canonical production backend URL)
  - `careeros-backend-py`: `766f536` (saved jobs async fix, geographic precision, regression tests)

---

## 8. Job Intelligence Semantic Relevance Correction (Phase 7)

### 8.1 Root Causes Identified
1. **Generic Role Stopword Overlap in `_score_role_match`:**
   - Word overlap was unweighted and included generic stop words (`{"engineer", "software", "analyst", "developer", "senior", "lead", ...}`). If `desired` ("Data Analyst") and `title` ("Software Engineering Senior Analyst") had 1 word overlap ("analyst"), it returned `60.0`.
   - Truly unrelated role families had an inflated baseline floor (`return 30.0`).
2. **Ungated Skill Match:**
   - An unrelated Software Engineer requiring Python & SQL was awarded 50% skill match, which artificially elevated overall match score to 40-50% despite role mismatch.
3. **Broad Umbrella Category False Positives:**
   - Distant sub-disciplines sharing a broad category ("Software Engineering" covering Frontend, DevOps, DBA, QA) received 65% role match even with 0 semantic token overlap and no taxonomy relationship.
4. **Seniority Classification Incompleteness:**
   - Seniority mapping lacked `staff`, `fresher`, `associate`, causing "Staff Software Engineer" to fall back to mid level (diff 0 -> 100%).
5. **Static `/version` Commit:**
   - `app/main.py:294` hardcoded `"commit": "71faf79"`, preventing verification of deployed commits on Render.

### 8.2 Targeted Architectural Fixes
- **Role Taxonomy & Stopword Filtering (`personalized_job_service.py`):**
  - Added module-level `_GENERIC_ROLE_WORDS` to filter generic words (`engineer`, `analyst`, `developer`, `senior`, `staff`, etc.) from fallback token matching.
  - Substring match returns 100.0. Canonical match returns 100.0 for direct variants and 85.0 for alias variants (e.g. BI Analyst).
  - Related taxonomy roles: shared noun/anchor returns 85.0 (Tier 2); distinct disciplines (Data Scientist) return 70.0 (Tier 3).
  - Same broad category requires semantic token overlap (e.g., "data" in Data Analyst vs Data Engineer -> 65.0); zero-overlap sub-disciplines (Frontend vs DevOps) demoted to 15.0.
  - Unrelated role families return 5.0 (Tier 4: 0-15%).
- **Gated Skill Match (`calculate_match_score`):**
  - When `role_match < 40.0`, `effective_skill_match` is scaled down severely: `raw_skill_match * max(0.05, (role_match / 40.0) * 0.3)`.
  - Rebalanced scoring weights: `role_match: 0.30`, `skill_match: 0.20`, `experience_match: 0.15`, `location_match: 0.10`, `resume_match: 0.10`, `salary_match: 0.05`, `company_preference: 0.05`, `freshness: 0.05` (sum = 1.00).
- **Seniority & Experience Hardening (`_score_experience_match`):**
  - Added full ranks (`intern`, `fresher`, `associate`, `junior`, `mid`, `senior`, `staff`, `lead`, `principal`, `director`, `vp`) and regex years extraction.
  - Score diffs: 0 -> 100, 1 -> 75, 2 -> 40, >=3 -> 15.
- **Dynamic Production Version Probe (`app/main.py`):**
  - Reads `RENDER_GIT_COMMIT` or `GIT_COMMIT` to accurately report deployed commit SHA.

### 8.3 Verification & Live Inventory Truth
- **Fixture Suite (`tests/test_role_relevance_fixture.py`):**
  - 8/8 tests passed covering Tier 1-4 hierarchy, Hyderabad Data Analyst beating Bangalore Backend Engineer by >20 points, demotion of "Software Engineering Senior Analyst" to role_match <= 15, and gated skill matching.
- **Targeted Suite:** 145 passed in 22.48s with zero failures across all job intelligence tests.
- **Live Inventory Truth (77 active jobs):**
  - Only 1 genuine data role currently active in DB: `Senior Data Scientist` at Coulomb Ai (Ranked #1, Role: 70, Overall: 47).
  - Zero active "Data Analyst" jobs in DB (crawls were seeded for "software engineer").
  - `Software Engineering Senior Analyst` demoted to Role: 5, Overall: 22.
  - All software engineering jobs demoted to Role: 5, Skill: 0-2, Overall: 26-36.


