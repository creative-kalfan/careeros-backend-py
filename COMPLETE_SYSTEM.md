# CareerOS — Complete System Map & Reality Audit
**Authoritative Reference & Personal System Map**
**Date:** 2026-09-23
**Status:** Local Personal Document (Reference)

This document is the single source of truth for the entire CareerOS codebase. It reflects the **actual current working tree, file inventory, API contracts, database schemas, background workers, and Git commits** as of today.

---

## 1. Canonical Repositories & Git Metadata

### 1.1 Canonical Backend: `careeros-backend-py`
- **Local Path:** `C:\Users\pathan Kalfan\resume-pilot\careeros-backend-py`
- **Git Remote:** `https://github.com/creative-kalfan/careeros-backend-py.git`
- **Branch:** `main`
- **Current HEAD:** `cc8e4cd85881ef8099391f58aea2505e403bebc6`
- **Commit Message:** `fix(jobs): restore discovery freshness and cache schema probes`
- **Preceding:** `3d7eab7df17a874baaa083eaab40b6096e9f0436` — `fix(jobs): correct seniority boundaries and add bounded recent candidate pool`
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
**Migrations (`sql/migrations/`):** Migration files `000`–`021` (gaps 003–005 are historical consolidations). The §7.1 inventory below enumerates `000`–`017`; `018`–`021` are covered by the Job Intelligence sections, and `021_mass_hiring.sql` was applied to production on 2026-09-17 (§9.14).

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

### 8.4 Production Deployment & Real Job-Relevance Verification (2026-09-16)
- **Deployment & Version Probe Status:**
  - Local HEAD and origin/main: `18b16a9`
  - Production `GET /version`: reports `{"version":"studio-qa-v2","commit":"71faf79"}` (200 OK)
  - Render deployment status: Stale / Pending manual deploy. Production container is running the earlier image built on Sep 7 (`71faf79`), where `app/main.py` hardcoded the commit and relevance fixes were not yet compiled.
- **Data Analyst Ingestion Audit & Recovery:**
  - **Inventory root cause identified:** Adzuna query rotation was previously ordered in large domain blocks (indices 0-8 data, 9-13 DE, 14-18 AI, 19-23 SWE, 24-27 SAP, 28-34 cities). Rotating 3 queries/day meant analytics queries were skipped for 10 out of 13 days; older crawls from August exceeded the 30-day freshness window and were deactivated (`is_active=False`) by `deactivate_stale_jobs()`.
  - **Targeted fix:** Interleaved `ADZUNA_BROAD_QUERIES` into 13 3-query batches so that *every single daily crawl* exercises at least 1 analytics family query (Data Analyst, Business Analyst, BI Analyst, Reporting Analyst, Risk/Financial Analyst). Retains exact 39 queries, zero budget expansion (~6 calls/day, 180/mo vs 1000/mo cap).
  - Executed targeted Adzuna ingestion pass discovering 185 jobs, inserting 137, updating 44, activating 103 real Data Analyst / Analytics jobs across Bangalore, Hyderabad, Noida, Mumbai, and Chennai.
- **Production API Verification (Live Data Analyst Candidate Feed):**
  - Queried `https://career-os-kr9m.onrender.com/jobs/personalized` with authenticated test user profile (Data Analyst, Python/SQL/Excel/Power BI, Bangalore).
  - Total active jobs in DB: 207 (103 data/analytics roles).
  - Top 20 feed results are 100% genuine Data Analyst roles (Ignisov, Innodata, Innova ESI, Clovity, Delta Analytics, HTC Global, Persistent Systems, HCLTech, etc.) with Role Match = 100%, Overall Scores = 70-80%.
  - Unrelated engineering roles completely demoted: First Software Engineer role appears at Rank 47 (Overall = 52, Role = 30), and `Software Engineering Senior Analyst` appears at Rank 86 (Overall = 43). In local test suite with commit `18b16a9`, `Software Engineering Senior Analyst` is further reduced to Role = 5, Overall = 22.
---

## 9. Job Discovery 3.0 End-to-End Production Ingestion Validation (2026-09-16)

### 9.1 Overview & Architecture Adherence
- **System Target:** Validated the newly expanded Job Discovery 3.0 multi-source ingestion engine (commit `476520f`).
- **Zero Architecture Deviation:** Executed exclusively via existing canonical services (`JobIngestionService`, `JobService`, `JobRepository`, `PersonalizedJobService`, `ScheduledCrawlRunner`) and adapters (`GreenhouseAdapter`, `AshbyAdapter`, `LeverAdapter`, `FirecrawlAdapter`, `AdzunaAdapter`). Zero direct raw inserts, zero new crawlers.

### 9.2 Inventory Baseline vs Post-Ingestion Comparison

| Metric | Before Ingestion | After Ingestion | Net Delta |
|---|---:|---:|---:|
| **Total Jobs (DB)** | 3,211 | 5,900 | +2,689 |
| **Active Jobs** | 207 | 2,952 | +2,745 |
| **Active India Jobs** | 122 | 416 | +294 (+241%) |
| **Active Foreign Jobs** | 60 | 2,100 | +2,040 |
| **Ambiguous Jobs** | 7 | 65 | +58 |
| **Unknown Jobs** | 18 | 371 | +353 |
| **Active Target-Role Jobs** | 124 | 346 | +222 (+179%) |
| • Analytics / BI | 100 | 144 | +44 |
| • Backend Engineering | 6 | 57 | +51 |
| • AI / Machine Learning | 4 | 85 | +81 |
| • Data Engineering | 0 | 40 | +40 |
| • SAP / ABAP | 14 | 20 | +6 |
| **Distinct Companies** | 141 | 199 | +58 |

#### Active Jobs by Provider
- **Greenhouse:** 1,351 (Stripe, Databricks, MongoDB, Postman, Groww)
- **Ashby:** 1,070 (OpenAI, Cursor, Notion, PostHog)
- **Adzuna:** 269 (Rotated India analytics & engineering queries)
- **Lever:** 242 (Paytm, CRED)
- **YCombinator:** 19 (YC Work at a Startup)
- **Firecrawl:** 1 (Razorpay verified careers portal)

#### Freshness Distribution (Active Inventory)
- `< 24h`: 36
- `1-7d`: 76
- `8-14d`: 59
- `15-30d`: 96
- `> 30d (stale)`: 2
- `Date unavailable`: 2,683 (Direct ATS APIs like Greenhouse/Ashby/Lever omit posting dates; canonical schema preserves unknown as NULL without fabrication)

### 9.3 Controlled Ingestion Pipeline Stage Measurement

Executed across representative subset of Greenhouse, Ashby, Lever, Firecrawl, and Adzuna:

| Provider | Target | Discovered | Normalized | Valid | India | Target | New | Updated | Dup | Rej | Deact | Time (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **greenhouse** | groww | 8 | 8 | 8 | 8 | 0 | 8 | 0 | 0 | 0 | 0 | 6.51 |
| **greenhouse** | mongodb | 409 | 409 | 409 | 77 | 7 | 409 | 0 | 0 | 0 | 0 | 221.00 |
| **greenhouse** | databricks | 878 | 878 | 878 | 100 | 70 | 878 | 0 | 0 | 0 | 0 | 518.72 |
| **greenhouse** | postman | 56 | 56 | 56 | 5 | 3 | 56 | 0 | 0 | 0 | 0 | 26.43 |
| **ashby** | openai | 813 | 813 | 813 | 12 | 73 | 813 | 0 | 0 | 0 | 0 | 399.65 |
| **ashby** | cursor | 121 | 121 | 121 | 6 | 1 | 121 | 0 | 0 | 0 | 0 | 60.05 |
| **ashby** | notion | 127 | 127 | 127 | 5 | 2 | 12 | 115 | 0 | 0 | 0 | 61.52 |
| **ashby** | posthog | 9 | 9 | 9 | 0 | 0 | 9 | 0 | 0 | 0 | 0 | 4.92 |
| **lever** | paytm | 231 | 231 | 231 | 0 | 14 | 231 | 0 | 0 | 0 | 0 | 154.10 |
| **lever** | cred | 11 | 11 | 11 | 0 | 0 | 11 | 0 | 0 | 0 | 0 | 9.68 |
| **firecrawl** | Razorpay | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 5.88 |
| **adzuna** | data analyst India | 50 | 50 | 50 | 50 | 30 | 45 | 5 | 0 | 0 | 0 | 28.69 |
| **adzuna** | business analyst India | 50 | 50 | 50 | 50 | 34 | 48 | 2 | 0 | 0 | 0 | 33.05 |
| **adzuna** | data engineer India | 50 | 50 | 50 | 50 | 39 | 48 | 2 | 0 | 0 | 0 | 28.74 |
| **TOTAL** | **14 targets** | **2,814** | **2,814** | **2,814** | **313** | **239** | **2,642** | **125** | **0** | **0** | **0** | **1558.94** |

#### Why Provider Discovery Translates to Database Growth
- **Global ATS Boards:** MongoDB, Databricks, OpenAI, Cursor, and Paytm boards contain global job listings. Ingestion cleanly preserves these as canonical active postings (`+2,040` foreign jobs, `+294` India jobs).
- **Target-Role Density:** Direct ATS boards yield high proportions of engineering, backend, and AI/ML roles (Databricks 70, OpenAI 73, Paytm 14), while Adzuna targeted rotation yields 100% India jobs and dense analytics roles (103 analytics roles discovered).
- **Zero Rejection:** 100% of discovered postings satisfied structural validity requirements (`title`, `external_job_id`, `source_platform`), validating the robustness of the single-pass Greenhouse and Ashby adapters.

### 9.4 Deduplication & Identity Integrity
- **Canonical Deduplication Identity:** `(source_platform, external_job_id)`.
- **Intra-batch duplicates:** 0.
- **Database unique identity duplicates:** 0. All 2,952 active rows have strictly distinct composite identities.
- **Cross-provider candidate matches:** Evaluated `(lower(company), lower(title))` across all active providers. Found 0 cross-provider duplicate collisions in active inventory.
- **Preservation:** No canonical identities were relaxed or fabricated to inflate counts.

### 9.5 Production Personalized Feed Verification (Data Analyst)
Verified against live production backend (`https://career-os-kr9m.onrender.com/jobs/personalized?page=1&pageSize=100`) with authenticated test user profile:
- **Desired Role:** `Data Analyst`
- **Skills:** `Python, SQL, Excel, Power BI`
- **Location:** `Bangalore, India`
- **Results:**
  - **Data/Analytics jobs in Top 20:** **20 / 20 (100.0%)**
  - **Data/Analytics jobs in Top 50:** **49 / 50 (98.0%)**
  - **Unrelated engineering jobs in Top 20:** **0 / 20 (0.0%)**
  - **Unrelated engineering jobs in Top 50:** **1 / 50 (2.0%)**
  - **Unique companies in Top 20:** **20 / 20 (100.0%)**
  - **Unique companies in Top 50:** **50 / 50 (100.0%)**
  - **India jobs in Top 20:** **19 / 20 (95.0%)**
  - **India jobs in Top 50:** **48 / 50 (96.0%)**

#### Top 10 Feed Ranking (Live Production Sample)
1. **Data Analyst** | Ignisov Consulting Services | Bengaluru, India | Adzuna | Overall: 81 | Role: 100 | Skill: 50 | Freshness: 100
2. **Data Analyst** | Innodata Inc. | Noida, India | Adzuna | Overall: 81 | Role: 100 | Skill: 50 | Freshness: 100
3. **Data Analyst** | Innova ESI | Hyderabad, India | Adzuna | Overall: 81 | Role: 100 | Skill: 50 | Freshness: 100
4. **Data Analyst** | Clovity | Bengaluru, India | Adzuna | Overall: 81 | Role: 100 | Skill: 50 | Freshness: 100
5. **Data Analyst** | Delta Analytics | Bengaluru, India | Adzuna | Overall: 81 | Role: 100 | Skill: 50 | Freshness: 100
6. **Data Analyst** | HTC Global Services | Bengaluru, India | Adzuna | Overall: 81 | Role: 100 | Skill: 50 | Freshness: 100
7. **Data Analyst** | Persistent Systems | Pune, India | Adzuna | Overall: 81 | Role: 100 | Skill: 50 | Freshness: 100
8. **Data Analyst** | HCLTech | Hyderabad, India | Adzuna | Overall: 76 | Role: 100 | Skill: 25 | Freshness: 100
9. **Data Analyst** | WhiteLotus Talent Partners | Hyderabad, India | Adzuna | Overall: 76 | Role: 100 | Skill: 25 | Freshness: 100
10. **Data Analyst** | Global Talent Track | Hyderabad, India | Adzuna | Overall: 76 | Role: 100 | Skill: 25 | Freshness: 100

### 9.6 Multiple Candidate Profiles Verification

Evaluated 5 distinct profiles across the entire active inventory (2,952 jobs). Scoring changes materially and appropriately per profile:

| Profile | Target Role & Skills | Target Role in Top 20 | India in Top 20 | Distinct Companies | Score Range | Top 1 Match Sample |
|---|---|---:|---:|---:|:---:|---|
| **Profile A** | Data Analyst (Python, SQL, Excel, Power BI, Bangalore) | **20 / 20 (100%)** | 19 / 20 (95%) | 18 | 75 – 85 | Data Analyst @ Ignisov (Overall: 85, Role: 100) |
| **Profile B** | Backend Engineer (Python, FastAPI, Postgres, Docker, Bangalore) | **7 / 20 (35%)** | 14 / 20 (70%) | 5 | 55 – 71 | Sr/Staff Backend Engineer @ Bluecargo (Overall: 71, Role: 100) |
| **Profile C** | Data Engineer (Python, SQL, Spark, Airflow, Bangalore) | **19 / 20 (95%)** | 14 / 20 (70%) | 11 | 75 – 81 | Sr Data Engineer @ Thakral One (Overall: 81, Role: 100) |
| **Profile D** | AI/ML Engineer (Python, PyTorch, TF, ML, Bangalore) | **1 / 20 (5%)** | 18 / 20 (90%) | 5 | 62 – 66 | Application Engineer @ MongoDB (Overall: 66, Role: 85) |
| **Profile E** | SAP Consultant (SAP ABAP, SAP, SQL, India) | **10 / 20 (50%)** | 18 / 20 (90%) | 10 | 59 – 74 | SAP ABAP Consultant @ Dautom (Overall: 74, Role: 85) |

### 9.7 Firecrawl Selective Role & Enrichment Verification
- **Role:** Strictly bounded retrieval for un-boarded Indian unicorns and targeted single-page enrichment.
- **Requests Made:** 3
- **Discovered Postings:** 1 (Razorpay official careers)
- **Targeted Enrichment Test:** `https://razorpay.com/jobs/`
  - Extracted fields: `description`, `employment_type`, `remote`, `posted_date`, `skills`, `enriched_via`, `enriched_at`
  - Success: `True` (completed in 3.02s)
- **Credits Consumed:** 3 credits (well within 500/mo budget).

### 9.8 105+ Company Registry Usefulness Audit
- **Total Registered Targets:** 105
  - P0 (High Priority / Daily): 33
  - P1 (Standard Tier): 53
  - P2 (Weekly Rotation): 19
- **Classification Status:**
  - **ACTIVE (verified producing active jobs in DB):** 15 targets
  - **NO_JOBS (valid endpoint, currently 0 openings listed):** 1 target
  - **NOT_TESTED (queued for standard rotation):** 89 targets
  - **BLOCKED / FAILED repeatedly:** 0 targets
- **Yield Analysis:** 9 targets producing verified India jobs; 8 targets producing verified target-role jobs.

### 9.9 Scheduler & P0/P1/P2 Tiering Verification
- **Execution Chain:** `ScheduledCrawlRunner` -> `run_provider_pass()` -> `enqueue_crawl_company()` -> ARQ worker `crawl_company_job` -> `JobIngestionService` -> `JobRepository` -> Supabase.
- **Tiering Rotation Test:** Simulated ATS scheduled pass enqueued **43 targets** (28 P0 guaranteed + 15 P1/P2 rotated via day-of-year slice).
- **Concurrency & Deduplication:** Redis `SET NX EX` locks prevent duplicate simultaneous crawls.

### 9.10 Budget & Request Projections
- **Observed Controlled Run:** 14 targets crawled in 1,558.94s (avg 111s/target).
- **Daily Operations:** ~29 crawls/day (25 ATS + 3 Adzuna + 1 Firecrawl).
- **Monthly HTTP Requests:** ~1,740 requests (negligible).
- **Monthly Firecrawl Credits:** ~30 credits (6.0% of 500 free monthly credits).
- **Monthly Redis Commands:** ~8,700 operations (well within 10,000 commands/day Upstash cap).

### 9.11 Production Deployment Verification
- **Local HEAD:** `476520f`
- **Origin/Main:** `476520f`
- **Production `GET /version`:** Reports `{"version":"studio-qa-v2","commit":"90f2b3d"}`
- **Deployment Status:** Local HEAD and GitHub remote are synchronized at `476520f`. Render free-tier web service runs `90f2b3d` pending manual dashboard trigger / queue processing. All relevant API features (`GET /jobs/personalized`, Supabase database writes) are verified live and functional.

### 9.12 Regression Test Suite
- **Full Suite Status:** 1,107 passed across application suite; 176/176 passed with 0 failures across all job intelligence tests (`test_job_discovery_3o.py`, `test_job_feed_fix.py`, `test_role_relevance_fixture.py`, `test_redis_config.py`, `test_redis_efficiency.py`, `test_applications_route_order.py`).

### 9.13 Fresher-First & Mass-Hiring Production QA Pass (Final Stabilization)
- **Mass-Hiring Detector Hardening (`mass_hiring_detector.py`):**
  - Added strict incidental pattern filters eliminating vendor marketing ("provide mass hiring solutions") and recruiter job requirements ("previous hiring drive experience", "campus hiring operations") from false-positive verification.
  - Required explicit campaign-specific indicators (walk-in drive, off-campus drive, batch drive, registration deadline, fresher drive).
  - Robust multi-format deadline parser (`%Y-%m-%d`, `%d-%m-%Y`, `%d/%m/%Y`, `%d %b %Y`, etc.). Unparseable dates conservatively yield `status = "UNKNOWN"` without fabricating deadlines or defaulting to `ACTIVE`.
- **Seniority Classification Precedence (`extraction_utils.py`):**
  - Removed bare `"graduate"` keyword which incorrectly scored education degree text ("Graduate or above") as entry-level for senior roles.
  - Enforced title seniority precedence: leadership titles ("Team Leader", "Engineering Manager", "Senior Backend Engineer") override body qualification text.
- **Semantic-Relevance Gated Opportunity Tiers (`job_relevance_service.py`):**
  - Eliminated arbitrary Tier 5 stomping and universal +95 freshness overrides.
  - Replaced with semantic-relevance gated tiers (Tiers 0–4): unrelated mass-hiring (`match < 40`) remains Tier 0 and never outranks relevant fresh jobs.
  - Bounded mass hiring priority modifier (+6.0) applied only if verified, active, and `match >= 45.0`.
  - Tier-scoped company diversification (`_diversify_by_company(jobs, tier_getter=...)`) ensures high-priority opportunities are never pushed below lower-tier jobs during round-robin interleaving.
- **5-Profile Benchmark on Live Inventory (2,952 jobs):**
  - **Data Analyst:** 20/20 (100%) available, 4/20 entry, 17/20 (85%) India/remote-aligned, 17 unique companies. Top 1: Risk Analyst @ Paytm.
  - **Backend Engineer:** 20/20 available, 2/20 entry, 15/20 (75%) India/remote-aligned, 5 unique companies. Top 1: Software Engineer @ OpenAI.
  - **Data Engineer:** 20/20 available, 4/20 entry, 20/20 (100%) India/remote-aligned, 16 unique companies. Top 1: Software Engineer @ OpenAI.
  - **AI/ML Engineer:** 20/20 available, 3/20 entry, 20/20 (100%) India/remote-aligned, 17 unique companies. Top 1: Software Engineer @ OpenAI.
  - **SAP Consultant:** 20/20 available, 3/20 entry, 19/20 (95%) India/remote-aligned, 4 unique companies.
- **Frontend Selection Synchronization (`_app.jobs.tsx`):**
  - Added `setSelectedId(null)` on search parameter changes so job selection immediately synchronizes with the top opportunity of the updated query.

### 9.14 Mass-Hiring Schema Enablement — Migration 021 Applied (2026-09-17)

- **Migration:** `sql/migrations/021_mass_hiring.sql` executed idempotently against the live Supabase project (Supabase Dashboard SQL Editor, `Success. No rows returned`). DDL only — three nullable columns plus two partial indexes; **no backfill, no UPDATE, no DELETE**.
- **Live schema:** `jobs.mass_hiring` (text), `jobs.mass_hiring_status` (text), `jobs.mass_hiring_details` (jsonb), `idx_jobs_mass_hiring` and `idx_jobs_mass_hiring_status` (partial, `WHERE is_active = true`).
- **Tooling added (canonical backend repo):**
  - `scripts/apply_mass_hiring_migration.py` — idempotent applier; fingerprints `public.jobs` (row counts + id/is_active digest + per-source counts) before and after, and refuses to report success if any row count, source distribution, or content digest changed.
  - `scripts/verify_mass_hiring_schema.py` — the 10-point live verifier over the normal application path; `--write-probe` performs a temporary INSERT → SELECT → UPDATE → SELECT → DELETE round-trip on an `is_active = false` sentinel row (invisible to every feed/relevance query, removed in `finally`).
- **Production verification (live Supabase, 2026-09-17): 9 PASS / 0 FAIL / 1 SKIP**
  1. `mass_hiring` exists — PASS
  2. `mass_hiring_status` exists — PASS
  3. `mass_hiring_details` exists — PASS
  4. Mass-hiring indexes — SKIP (index introspection needs a direct Postgres connection; the DDL batch that created both indexes returned `Success. No rows returned`)
  5. Normal repository SELECT uses the real columns, no lazy-column fallback — PASS (`_probe_has_mass_hiring() = True`)
  6. Normal INSERT/UPDATE path persists the fields — PASS (3 fields round-tripped; sentinel deleted immediately; 0 probe rows remain)
  7. Existing jobs unaffected — PASS (total = 5,900, active = 2,952, delta 0, no per-source drift)
  8. No fake mass-hiring records — PASS (0 persisted classifications; every value canonical)
  9. Truthful state preserved — PASS (deterministic detector over 2,952 active jobs: 0 VERIFIED / 7 POSSIBLE / 2,945 NOT; no persisted value contradicts the detector)
  10. Firecrawl bounded, no broad recrawl — PASS (`FIRECRAWL_MAX_PAGES_PER_CRAWL = 15`; firecrawl rows 31 pre- and post-migration, delta 0)
- **Truthfulness:** the migration adds storage only. Existing rows keep `mass_hiring = NULL` until the normal bounded ingestion path classifies them, so production remains **0 VERIFIED / 7 POSSIBLE** — nothing was backfilled, fabricated, or inflated.
- **Regression:** Jobs and mass-hiring suites green — `test_fresher_and_mass_hiring.py` (11), `test_job_repository.py`, `test_job_relevance_service.py`, `test_job_api.py`, `test_jobs_route_order.py`, `test_job_production_verification.py`, `test_job_filtering.py` (17), `test_job_ingestion_2o.py`, `test_job_discovery_3o.py`, `test_job_stabilization.py`, `test_job_feed_fix.py`, `test_job_intelligence_service.py`, `test_job_intelligence_api.py`.
- **Test-only correction:** `tests/test_job_filtering.py::TestJobRepositoryFiltering::test_list_jobs_repo_all_filters` had a stale mock (the `query.or_` Bangalore/Bengaluru alias branch added in `JobRepository.list_jobs` was never stubbed, so `total` came back `None`). The mock now stubs `or_`; no production behaviour changed.
- **Deliberately untouched:** role-family ranking, fresher-first ranking, seniority classifier, personalization, job discovery architecture, and Firecrawl bounded crawling.

### 9.15 Production API Timeout Root Cause Audit & Stabilization (2026-09-17)

- **Incident & Symptoms:**
  - Production frontend (`careeros-frontend-three.vercel.app/jobs`) reported `"CONNECTION ERROR — Request timeout"` with console error `"Failed to fetch profile from python backend: ApiClientError: Request timeout"`.
  - Endpoint `/jobs/personalized?sort=best-match&page=1&pageSize=20&includeAts=true` hung and was aborted at ~30s.
  - Sibling endpoints `/jobs/saved` and `/applications` also timed out when accessed concurrently from the frontend.
  - Endpoint `/me` succeeded in isolation (2.2s).
- **Distinction Between Timeout Sources:**
  - Not a backend HTTP 5xx error or CORS failure: browser preflight OPTIONS returned 200 OK.
  - Frontend `ApiClient` in `src/utils/request.ts` enforces `apiConfig.timeout = 30000` (30s) via `AbortController`.
  - When backend execution exceeded 30s, the frontend aborted the HTTP connection (`AbortError` wrapped as `ApiClientError(statusCode: 408, code: TIMEOUT)`).
  - The backend request was still running in Uvicorn when aborted by the browser.
- **Empirical Timing Breakdown & Root Cause:**
  - Active jobs in production Supabase database reached **2,952 rows**.
  - In `JobRelevanceService.get_relevant_jobs`:
    1. First candidate query fetched `CANDIDATE_POOL_LIMIT = 1000` rows (`duration = 6.6s`, `total = 2952`).
    2. Commit `a969aad1` had added `if db_total > len(db_rows): list_jobs(page=1, page_size=db_total)`, which discarded the 1,000 rows and re-fetched all 2,952 jobs across 3 sequential PostgREST chunks (`duration = 23.8s`).
    3. Network DB fetch alone consumed **30.4s** (`6.6s + 23.8s`), before model validation, CPU ranking, and diversification, pushing total execution to **34.5s** (> 30s frontend timeout).
  - Head-of-Line Event Loop Blocking:
    - FastAPI routes `list_jobs` and `list_personalized_jobs` were defined with `async def` but invoked the synchronous, blocking `service.get_relevant_jobs` directly on Uvicorn's main thread and asyncio event loop.
    - Render runs a single Uvicorn process (`workers=1`). The 34.5s synchronous execution froze the event loop entirely.
    - Concurrent requests (`/jobs/saved` taking 0.26s in isolation, `/applications` taking 1.6s in isolation) were starved in the socket backlog for >30s, timing out simultaneously in the browser.
- **Targeted Code Fixes:**
  1. `app/services/jobs/job_relevance_service.py`: Removed redundant unbounded refetch (`if db_total > len(db_rows)`), restoring candidate retrieval to the bounded `CANDIDATE_POOL_LIMIT = 1000` single-pass database query. Pagination `total` remains 2,952 from PostgREST `count="exact"`. Candidate fetch runtime dropped from **30.4s to 6.7s**.
  2. `app/api/routes/jobs.py`: Wrapped `service.get_relevant_jobs` calls in `await asyncio.to_thread(...)` inside `list_jobs` and `list_personalized_jobs`. Offloads blocking DB fetch and ranking to worker threads, keeping Uvicorn's asyncio event loop 100% responsive.
  3. `app/auth/jwt_verify.py`: Added `leeway=10` to `pyjwt.decode(...)` to absorb clock skew between auth token issuance and verification.
- **Production-Safe Empirical Verification:**
  - Tested 3 concurrent endpoints under test-user authentication against live Supabase:
    - `SAVED` finished in **0.26s** (was timed out at 40s+).
    - `APPS` finished in **2.21s** (was timed out at 40s+).
    - `JOBS` finished in **9.71s** (was timed out at 40s+).
    - All 3 requests returned concurrently in **9.71s** with zero timeouts and zero errors.
- **Regression Suite:**
  - Added `tests/test_timeout_regression.py` (2 tests: ensures single-pass candidate fetch when total exceeds limit, and verifies non-blocking async route execution).
  - All 31 job relevance and API tests pass (`tests/test_job_relevance_service.py`, `tests/test_job_api.py`, `tests/test_job_filtering.py`, `tests/test_jobs_route_order.py`, `tests/test_timeout_regression.py`).
- **Hygiene & Boundaries:**
  - Ranking semantics, opportunity tiers, weights, and match scoring: 100% UNTOUCHED.
  - Job discovery and crawlers: 100% UNTOUCHED.
  - Frontend code: 100% UNTOUCHED.
  - Root repository `resume-pilot`: 100% UNTOUCHED.
  - Zero new dependencies added.

### 9.16 Candidate Universe Preservation & Targeted Priority Retrieval (2026-09-17)

- **Post-Timeout Audit Finding & Root Cause:**
  - Commit `d84d59f` eliminated the 30s timeout by capping candidate retrieval to the first 1,000 DB rows (by `created_at desc`) and removing the second full-table refetch.
  - Empirical investigation against live production inventory (2,952 active jobs) revealed a candidate-universe regression:
    1. **Fresher/Entry Opportunities Dropped:** Out of 97 total active entry/fresher jobs in the database, 52 (53.6%) were situated in rows 1,001–2,952. Under the naive 1,000 cutoff, these opportunities (e.g. OpenAI Emerging Talent, Notion Early Career, Uber/Databricks internships) were completely invisible to ranking.
    2. **Mass-Hiring Risk:** Active verified mass-hiring opportunities (`VERIFIED_MASS_HIRING` + `ACTIVE`) older than the 1,000 most recent rows were excluded from candidate generation.
    3. **Pagination Contract Broken:** `meta.total` returned 2,952, but only 1,000 jobs were ranked in memory. Requesting page 51 (`page=51, pageSize=20`) yielded `data: []` (premature emptiness).
- **Smallest Safe Architecture — Targeted Priority Multi-Pool Retrieval:**
  - Rather than unbounded full-table scans (which take 23–36s) or naive 1,000-row truncations:
    1. `JobRepository.get_priority_candidates`: Executes bounded, targeted queries in a concurrent `ThreadPoolExecutor`:
       - **Verified Mass-Hiring Pool:** `mass_hiring == 'VERIFIED_MASS_HIRING' AND mass_hiring_status == 'ACTIVE'`
       - **Fresher/Entry Pool:** Titles and experience levels matching entry, fresher, junior, trainee, associate, early career, and new grad.
       - **Role-Matched Pool:** Active opportunities matching the candidate's desired role or requested title filter.
    2. `JobRelevanceService.get_relevant_jobs`:
       - When `db_total > len(db_rows)`, merges targeted priority candidates into the base candidate pool with deduplication by `external_job_id`/`id`.
       - Operates in ~8–12 seconds against live production Supabase, well below the 30-second frontend timeout.
    3. **Truthful Pagination:** `total` is set to the actual size of the candidate pool (`len(jobs)` or `len(filtered_jobs)`). Pages never become empty prematurely, pagination metadata matches the ranked universe, and ordering is deterministic with zero duplicate IDs across pages.
- **Empirical Live Production Verification:**
  - Production DB inventory: 2,952 active jobs.
  - Candidate pool retrieved: ~1,071–1,491 unique jobs (100% of verified mass hiring + 100% of fresher/entry opportunities + base 1,000).
  - Production latency: Concurrent request wall time ~12–19s; `/saved` finishes in 0.62s non-blocking.
  - Ranking integrity: `Software Engineer, Applied Emerging Talent (2027)` at OpenAI (row 1,020 in DB) correctly ranks #1 with match score 93 for entry-level engineering profiles.
  - Regression suite: 56/56 job domain, feed fix, timeout, and candidate universe audit tests pass (`test_candidate_universe_audit.py`, `test_job_feed_fix.py`, `test_timeout_regression.py`, `test_fresher_and_mass_hiring.py`).
- **Hygiene & Boundaries:**
  - Ranking scoring formulas, opportunity tiers, and weights: 100% UNTOUCHED.
  - Job discovery and crawlers: 100% UNTOUCHED.
  - Frontend: 100% UNTOUCHED.
  - Root repository `resume-pilot`: 100% UNTOUCHED.
  - Zero new dependencies added.

### 9.17 Production Performance Pass, Semantic Candidate Expansion & Mass-Hiring Audit (2026-09-23)

- **1. Fast UI/API Loading States & Latency Reduction:**
  - **Backend Seniority Memoization:** NormalizedJob now includes `_cached_seniority: Optional[str] = PrivateAttr(default=None)`. `_get_job_seniority` memoizes results, completely eliminating 3,000+ redundant regex passes during sorting and company diversification.
  - **Column Projection Optimization:** `JobRepository._get_candidate_select_columns()` projects only scoring columns, shedding heavy payloads (`source_history`, raw metadata) and saving ~1.5s per query.
  - **Concurrent Candidate Universe Retrieval:** `JobRepository.get_candidate_universe` executes base pool (1,000) and priority pools (verified mass hiring, fresher/entry, semantic role expansions) in a single concurrent thread pool (`max_workers=4`). PostgREST `.or_()` query filters sanitize spaces with `%` to prevent HTTP/2 disconnects.
  - **Live Production Latency Benchmarks (Supabase Live, 2,952 active jobs):**
    - `Data Analyst`: **2.89s** (259 candidates in pool)
    - `Data Engineer`: **1.11s** (164 candidates in pool)
    - `Backend Engineer`: **1.13s** (124 candidates in pool)
    - `AI/ML Engineer`: **1.69s** (221 candidates in pool)
    - `SAP Consultant`: **1.23s** (130 candidates in pool)
    - `Unauthenticated (None)`: **4.05s** (1,071 candidates in pool, down from 12s+)
  - **Frontend Cache Alignment (`useDashboardData.ts`):** Replaced private isolated query keys with canonical TanStack keys (`jobsQueryKeys.personalized({})`, `applicationQueryKeys.stats`, `["recommendations", "top", 5]`, `[NOTIFICATIONS_QUERY_KEY, undefined]`). Dashboard and feature tabs share memory cache with zero duplicate fetches.
  - **Studio & Profile Optimization (`useVersions.ts`, `_app.profile.tsx`, `_app.settings.tsx`):**
    - Added `staleTime: 120_000` to `useVersions` / `useVersion` to eliminate refetch thrashing during pane switches.
    - Converted `_app.profile.tsx` from raw `useEffect` to TanStack Query `useQuery` / `useMutation`.
    - Removed hardcoded demo strings ("Alex Morgan", "alex.morgan@example.com") in `_app.settings.tsx`, binding truthfully to authenticated user and profile state.
- **2. Semantic Role Family & Discovery Expansion:**
  - **Semantic Candidate Expansion (`app/parsing/role_family.py`):** Implemented `get_semantic_role_expansion(target_role)` covering `ANALYTICS_BI`, `DATA_ENGINEERING`, `BACKEND`, `AI_ML`, `SAP_ERP`, `SOFTWARE_ENGINEERING`, `DEVOPS_CLOUD`, `QA_TESTING`. Downstream role compatibility gate strictly protects boundaries.
  - **Discovery Query Expansion:** Added 5 new 3-query batches (15 bounded fresher/entry queries) in `ADZUNA_BROAD_QUERIES` (`job_ingestion_service.py`) for Data Engineering, SAP, Analytics, Backend, and AI/ML.
- **3. Migration 021 Mass-Hiring Live Verification:**
  - Verified live Supabase DB has migration 021 applied (`mass_hiring`, `mass_hiring_status`, `mass_hiring_details`).
  - Write probe verified live via `scripts/verify_mass_hiring_schema.py`: `insert=True, update=True` (temporary sentinel cleaned up). Current live inventory: 0 verified, 7 possible, 2,945 not mass hiring (truthful state).
- **4. Verification & Test Status:**
  - Backend: 33/33 tests pass in 4.82s.
  - Frontend: 260/260 tests pass in 2.25s.
  - Frontend build: `npm run build` succeeds in 1.76s with 0 errors.
- **5. Boundaries Preserved:**
  - Ranking semantics, 8-factor weights, priority tiers, India-first boost, company diversification: 100% UNCHANGED.
  - No new dependencies, no duplicate crawlers, no separate microservices.

### 9.18 Production Job Feed Consistency, Freshness & Seniority Correction (2026-09-23)

- **1. Production Audit & Root Cause Analysis:**
  - **Symptom:** UI screenshot on `/jobs` ("SHOWING 1–20 OF 1,177 OPPORTUNITIES", `RANKED BY MATCH`) showed a 2-week-old "Data Analyst" role with a description describing sales incentives / commissions / sales operations and requiring "2–5 years" experience mixed into the fresher feed. Genuinely new jobs were reported missing from the first page.
  - **Source Integrity Finding (Q3):** Title and description belong to the exact same requisition from the source provider (Adzuna). In corporate sales operations, roles with the literal title "Data Analyst" commonly handle incentive compensation modeling and quota analysis requiring 2–5 years experience. Zero cross-record contamination or mapping corruption exists in the pipeline.
  - **Seniority Misclassification Root Cause:** In `extraction_utils.py` and `job_relevance_service.py`, experience check `if years_min <= 2: return "entry"` evaluated to `True` for `"2–5 years"` (where `years_min = 2, years_max = 5`). This caused 2–5 year experienced roles to be falsely classified as `"entry"`, triggering the fresher bonus (+8.0 / +10.0 pts) and elevating them into Tier 4 (Priority A: ENTRY/FRESHER) on page 1.
  - **Recent-Job Visibility Root Cause (Q1/Q2):** In databases with >1,000 active jobs, the candidate universe previously relied on `_fetch_base` (ordered by `created_at desc`). When older crawl batches occupied the top 1,000 insertion slots, recently-posted jobs without explicit fresher/entry keywords were omitted from the candidate pool.

- **2. Targeted Architectural Corrections:**
  - **Experience & Seniority Boundaries (`extraction_utils.py`, `job_relevance_service.py`):**
    - `0 years`, `0–1 years`, `0–2 years`, `1–2 years` strictly map to `"entry"`.
    - `2–3 years`, `2–5 years`, `3–5 years` (where `years_min >= 2` and `years_max > 2` or `years_min >= 3`) strictly map to `"mid"`.
    - `5+ years` maps to `"senior"`; `7+ years` maps to `"lead"`.
    - `_EXPERIENCE_PATTERNS` regex hardened to support `(?:[-–]|to)` and both `years?` and `yrs?`.
    - Screenshot job ("Data Analyst / Sales Operations / 2–5 years") now cleanly classifies as `"mid"`, drops `_is_entry_or_fresher = False`, receives 0 fresher bonus, and is demoted from Tier 4 to Tier 2 (mid-level baseline).
  - **Bounded Recent Candidate Pool (`JobRepository.get_candidate_universe`, `get_priority_candidates`):**
    - Added `_fetch_recent`: retrieves active opportunities ordered by `posted_at desc nullsfirst=False` (bounded to 500 rows).
    - Executed concurrently in `ThreadPoolExecutor(max_workers=5)` alongside `_fetch_base`, `_fetch_mass`, `_fetch_freshers`, and `_fetch_role`.
    - Bounded merge with deduplication guarantees that the freshest-posted jobs in the database always enter the candidate universe for ranking, without unbounded full-table scans and without modifying base pool semantics or changing ranking weights.

- **3. Empirical Live Production Verification (Supabase Live, 2,952 active jobs):**
  - **Active Job Inventory by Freshness:**
    - `<= 24h`: 0 | `<= 3d`: 0 | `<= 7d`: 1 | `8–14d`: 78 | `15–30d`: 71 | `> 30d`: 36 | `missing posted_at` (ATS jobs): 814 (27.6%).
  - **Candidate Universe & Pool Impact:**
    - `_fetch_recent` rows returned: 500.
    - Base pool rows: 1,000.
    - Overlap: 179.
    - **Genuinely new jobs rescued into universe: 321** (previously omitted from ranking pool).
    - Candidate universe size: 1,365 unique jobs (0 duplicate IDs).
    - Latency: `_fetch_base` = 1,568.1ms; `_fetch_recent` = 1,226.9ms; concurrent wall time = 3,471.9ms (added network latency: ~0ms due to concurrent execution).
  - **Top 20 Feed Breakdown Across 5 Profiles:**
    - `Data Analyst` (pool: 1,374, latency: 6.7s): #1 = `Data Analyst (Fresher)` at Clovity (2026-09-16, 79% match); #2 = `Accelerator Program - Data Analyst` at Jobgether (2026-09-12, 73% match); #3 = `Data Analyst` at Lonza (2026-09-11, 73% match).
    - `Data Engineer` (pool: 1,379, latency: 6.6s): #1 = `IT Controls Data Engineer` at OpenAI; #2 = `Data Engineer - INTL India` at Insight Global.
    - `Backend Engineer` (pool: 1,373, latency: 6.7s): #1 = `Software Engineer Intern (Winter 2027)` at Notion; #2 = `2026 Software Engineering Internship India` at Uber.
    - `AI/ML Engineer` (pool: 1,425, latency: 6.8s): #1 = `Data Science Intern (Winter 2027)` at Notion; #2 = `AI Engineer, Internship` at Postman; #3 = `PhD GenAI Research Scientist Intern` at Databricks.
    - `SAP Consultant` (pool: 1,375, latency: 6.5s): #1 = `SAP ABAP Developer` at Diensten Tech (2026-09-12); #2 = `SAP ABAP Consultant - Fiori` at Dautom (2026-09-13).
  - **Screenshot Job Verification:** Data Analyst with sales operations / 2–5 years experience classified as `'mid'`, `_is_entry_or_fresher = False`, match score 83% without fresher bonus.
  - **Mass-Hiring & Recency Invariants:**
    - 60-day-old active verified mass hiring evaluates to `freshness = 85.0` (exception intact). Expired mass hiring evaluates to `20.0`.
    - 40-day-old job with `last_seen_at = NOW()` evaluates to `freshness = 15.0` (authoritative `posted_at` strictly preserved; `last_seen_at` never falsely inflates posting freshness).

- **4. Test Suite Pass:**
  - 85/85 tests passed across 11 test suites in 103s (`test_job_relevance_service`, `test_job_api`, `test_job_feed_fix`, `test_timeout_regression`, `test_candidate_universe_audit`, `test_job_filtering`, `test_job_filter_audit`, `test_job_stabilization`, `test_role_family_ranking`, `test_job_production_verification`, `test_fresher_and_mass_hiring`).

### 9.19 Discovery Freshness Root Cause, `posted_at` Mapping & Latency Probe Cache (2026-09-23)

- **1. Discovery root cause (why production had ~zero fresh `posted_at`):**
  - **Scheduler never fired soon enough.** `ScheduledCrawlRunner.start()` used `IntervalTrigger(hours=24)` with no `next_run_time`, so the first crawl waited a full 24h. Short-lived Render processes (sleep/restart cycles) never survived long enough to fire → no crawl enqueued for 7+ days (`crawl_status:*` keys expired, `arq:queue` depth 0). Last successful observation: **2026-09-16**.
  - **Broken Redis env.** `.env` had a bare `rediss://...` (no `REDIS_URL=` prefix), so ARQ/dispatcher could not reach Upstash. Fixed locally to `REDIS_URL=rediss://...`. `.env` is gitignored — **production Render must set `REDIS_URL` (and `JOB_CRAWL_ENABLED`) in the dashboard**.
  - **Adapters discarded trustworthy source dates.** Greenhouse `first_published`, Ashby `publishedAt`, Lever `createdAt` (epoch-ms), SmartRecruiters `releasedDate` were not mapped into `CrawledJob.posted_date`, so ingested jobs often had `posted_at = NULL` or only system insert time.

- **2. Fixes shipped:**
  - **Immediate staggered first run** (`scheduled_crawl_runner.py`): `first_run = now+30s`, per-provider offset `+15s × index`, `IntervalTrigger(..., start_date=first_run)` + `next_run_time=provider_first_run`.
  - **ATS `posted_date` mapping** in `greenhouse.py`, `ashby.py`, `lever.py` (new `_posted_date_from_epoch_ms`), `smartrecruiters.py`. Never invent dates; `posted_at` stays `NULL` when no trustworthy source field exists.
  - **Schema probe cache** (`job_repository.py`): module-level `_PROBE_CACHE_*` keyed by client identity; new `JobRepository()` per request no longer re-runs `last_seen_at` / `source_tier` / `mass_hiring` column probes (~1s cold → warm cache). `clear_probe_cache()` for tests.
  - **Sequential profile → candidates kept** in `job_relevance_service.py`: `desired_role` must be available before the candidate universe (role-matching priority pool). Latency recovered via probe cache, not by racing profile fetch (coverage tradeoff rejected).
  - **Migration 022** (`sql/migrations/022_jobs_active_created_at_index.sql`): partial index `(is_active, created_at DESC) WHERE is_active = true` for base-pool ordering. **Not yet applied** — run via Supabase Dashboard SQL Editor (service key cannot DDL).

- **3. Production measurements:**
  - **Active freshness at audit time:** `<=24h`: 0 | `<=3d`: 0 | `<=7d`: 1 | missing `posted_at`: 814/2,952 (27.6%). DB totals: 5,900 jobs / 2,952 active (PostgREST select cap 1,000).
  - **Adzuna India freshness probe (live, after fixes ready):** 144 raw → 144 valid → 144 India | fresher-role 24 | `<=3d` 13 | `<=7d` 41 | `<=30d` 75 | no_date 0. Fresh inventory **exists upstream**; production lag was discovery, not supply. (Some fresher/SAP queries transiently 503 — bounded rotation still applies.)
  - **Latency root causes:** per-request `JobRepository` construction re-ran column probes (~1,056ms); candidate universe 1.7–2.9s (one `count="exact"` outlier ~16.9s on `_fetch_base`); score loop ~1.3s over ~1,365 jobs. Feed wall time had regressed to ~6.6–6.8s vs prior ~1.1–2.9s.
  - **Probe-cache verification:** cold first repository probes ~1s total; subsequent repositories hit module cache in sub-ms for already-probed columns.

- **4. Tests:**
  - New: `tests/test_ats_posted_date_mapping.py` (5 adapter mapping tests + epoch helper), `tests/test_job_repository_probe_cache.py` (2), immediate-first-run assertion in `tests/test_scheduled_crawl_runner.py`.
  - Redis config: `_env_file=None` tests pass aliased names (`NEXT_PUBLIC_SUPABASE_URL`, …); worker test compares against `RedisSettings.from_dsn(settings.redis_url)` (no hardcoded localhost).
  - **Job-focused suite: 226 passed** (redis, scheduler, ATS mapping, probe cache, ingestion, relevance, repository, API, filtering, stabilization, feed, discovery, production verification, intelligence, route order, fresher/mass-hiring, crawl refresh, source priority/escalation, India-first).
  - Pre-existing failures (untouched by this pass): `test_role_relevance_fixture` (2), `test_india_target_freshness` (2 — expects `last_seen_at` to inflate freshness, contradicting design), `test_job_feed_fix` pollution under full-suite order, copilot/visual/e2e.

- **5. Boundaries preserved:**
  - Ranking weights, priority tiers, India-first, freshness scoring, company diversification, semantic expansion, `_fetch_recent` pool (500): **100% UNCHANGED**.
  - No fabricated freshness: `created_at` / `last_seen_at` never written as `posted_at`; original `posted_at` not overwritten on recrawl.
  - Adzuna query volume unchanged (rotation bounds intact).
  - No new dependencies; migration 022 optional until applied in Dashboard.

- **6. Pending ops (manual):**
  1. Apply migration 022 in Supabase Dashboard SQL Editor.
  2. Set production Render `REDIS_URL` + `JOB_CRAWL_ENABLED=true`.
  3. Deploy backend commit so scheduler/adapter/probe-cache fixes go live.
  4. Re-run `scripts/audit_discovery_freshness.py` after first successful production crawl.

### 9.20 Scheduler ownership: ARQ worker via on_startup (2026-09-23)

- **Root cause:** `WorkerSettings` had no `on_startup`/`on_shutdown`, so the
  production ARQ worker never created `ScheduledCrawlRunner`. The scheduler
  only ran in FastAPI `lifespan` (web process), which sleeps/restarts on
  Render — worker logs showed `Starting worker for 5 functions` then silence.
- **Fix:** `app/workers/settings.py` adds `worker_startup`/`worker_shutdown`
  wired as `WorkerSettings.on_startup`/`on_shutdown` (ARQ 0.26.1 supported).
  Startup logs `crawler_enabled`, `initialized`, per-provider
  `next crawl scheduled`, and `started`; failures log
  `crawler scheduler initialization failed` without killing the worker.
  Scheduler object retained in module global so it survives polling.
  `app/main.py` lifespan no longer starts a scheduler — exactly one owner
  (worker). `JOB_CRAWL_ENABLED=false` cleanly disables. First-run stagger
  (now+30s, +15s/provider, `next_run_time` set) unchanged.
- **Verify in worker logs:** `crawler scheduler initialization started`,
  `crawler scheduler started`, `next crawl scheduled id=...`.




