# CareerOS — Database Migrations Guide

## 1. Architecture & Provenance

The CareerOS schema originated across two phases:
1. **Foundational Schema (`000_baseline_schema.sql`)**: Consolidates the foundational tables created during early development:
   - User domain: `profiles` (with `handle_new_user` auth trigger), `work_experiences`, `education_entries`, `preferred_companies`
   - Jobs domain: `jobs` (base schema), `saved_jobs`
   - Application domain: `applications` (with `application_status` enum)
   - Intelligence & Communications: `ats_reports`, `notifications`, `recommendations`, `notification_preferences`, `company_ats_mapping`
   - Platform: Base RLS policies and Storage bucket registrations (`resumes`, `avatars`)
2. **Feature Delta Migrations (`001` through `017`)**: Represent incremental feature evolution in the canonical Python backend:
   - `001_resume_module.sql`: Resume import & versions
   - `002_resume_templates.sql`: Resume template registry
   - `006_resume_versions_extended.sql`: Job-specific resume versions & master constraints
   - `007_optimization_versions.sql`: Version-aware optimization session references
   - `008_resume_storage_rls.sql`: Storage RLS security policies for resume assets
   - `009_resume_ats_analyses.sql`: Comprehensive ATS analysis records
   - `010_optimization_tables.sql`: AI Resume optimization sessions & suggestions
   - `011_job_freshness.sql`: Job crawl freshness tracking (`last_seen_at`, indexes)
   - `012_job_intelligence.sql`: AI Job intelligence & extraction persistence
   - `013_job_ingestion_reliability.sql`: Partial unique index & crawl deactivation reliability
   - `014_proposal_decisions.sql`: Granular improvement proposal decisions
   - `015_candidate_evidence.sql`: Candidate evidence repository backing
   - `016_job_source_provenance.sql`: Source provenance & multi-tier tracking
   - `017_resume_version_sources.sql`: Version provenance metadata

---

## 2. Setting Up a Fresh Database

To initialize a new Supabase project or local PostgreSQL instance from scratch:
Execute all files in `sql/migrations/` in alphanumeric order:

```bash
# Order of execution:
000_baseline_schema.sql
001_resume_module.sql
002_resume_templates.sql
006_resume_versions_extended.sql
007_optimization_versions.sql
008_resume_storage_rls.sql
009_resume_ats_analyses.sql
010_optimization_tables.sql
011_job_freshness.sql
012_job_intelligence.sql
013_job_ingestion_reliability.sql
014_proposal_decisions.sql
015_candidate_evidence.sql
016_job_source_provenance.sql
017_resume_version_sources.sql
```

The resulting database contains all 21 canonical tables, all foreign-key relationships, triggers, and RLS policies.

---

## 3. Upgrading an Existing Environment

All migrations are designed to be **strictly idempotent**:
- Statements use `IF NOT EXISTS` / `IF EXISTS` guards.
- Triggers use `CREATE OR REPLACE FUNCTION` and `DROP TRIGGER IF EXISTS ... CREATE TRIGGER`.
- Types use `EXCEPTION WHEN duplicate_object THEN NULL;` exception blocks.
- Applying `000_baseline_schema.sql` against an existing, populated database is a non-destructive no-op. It does not overwrite data or drop existing tables.

---

## 4. Invariant Rules for Future Development

1. **Never renumber existing migrations**: Numbers `000` through `017` are fixed and immutable. New migrations must continue sequentially (e.g. `018_...`).
2. **Never rewrite already-applied migrations**: Delta migrations that have been applied to production must remain immutable.
3. **Always preserve idempotency**: Every future migration must guard against duplicate application using standard PostgreSQL idempotency patterns.
