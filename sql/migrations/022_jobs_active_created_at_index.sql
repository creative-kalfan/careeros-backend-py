-- Index for the default candidate-universe ordering used by get_candidate_universe
-- and list_jobs: WHERE is_active = true ORDER BY created_at DESC.
-- Without this, Postgres falls back to a full active-row sort each request
-- (observed multi-second statement timeouts under concurrent feed traffic).
-- Apply via Supabase Dashboard SQL Editor (service key cannot run DDL).

CREATE INDEX IF NOT EXISTS idx_jobs_is_active_created_at
  ON public.jobs (is_active, created_at DESC)
  WHERE is_active = true;
