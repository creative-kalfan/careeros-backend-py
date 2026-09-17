-- ============================================================================
-- 021: Mass Hiring Intelligence
--
-- Persists mass hiring campaign classification, lifecycle status, and
-- structured evidence on the jobs table:
--
--   mass_hiring         TEXT ('VERIFIED_MASS_HIRING', 'POSSIBLE_MASS_HIRING', 'NOT_MASS_HIRING')
--   mass_hiring_status  TEXT ('ACTIVE', 'ENDING_SOON', 'EXPIRED', 'UNKNOWN')
--   mass_hiring_details JSONB (evidence, vacancy_count, campaign_url, deadline, signals, detected_at)
--
-- All columns are NULLABLE with no destructive backfill.
-- ============================================================================

BEGIN;

ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS mass_hiring TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS mass_hiring_status TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS mass_hiring_details JSONB;

CREATE INDEX IF NOT EXISTS idx_jobs_mass_hiring ON public.jobs (mass_hiring) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_jobs_mass_hiring_status ON public.jobs (mass_hiring_status) WHERE is_active = true;

COMMIT;
