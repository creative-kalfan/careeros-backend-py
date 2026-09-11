-- ============================================================================
-- 020: Job Feature Columns
--
-- Persists normalized job features that lived only on the Pydantic model
-- (NormalizedJob.to_db_row emitted them, but _DB_COLUMNS dropped them, so
-- they never reached the database):
--
--   remote, workplace_type, employment_type, salary_min, salary_max,
--   experience_level, skills
--
-- All columns are NULLABLE with no backfill: a NULL means "the source did
-- not provide a value" (never fabricated). Existing repository filters on
-- employment_type / experience_level / salary_max already assume these
-- columns; this migration makes that assumption true.
--
-- No RLS changes: jobs is system-owned ingestion data with an existing
-- read-for-authenticated policy.
-- ============================================================================

BEGIN;

ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS remote BOOLEAN;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS workplace_type TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS employment_type TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS salary_min NUMERIC;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS salary_max NUMERIC;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS experience_level TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS skills JSONB;

COMMIT;
