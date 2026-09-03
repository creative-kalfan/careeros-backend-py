-- Phase 5: Add job freshness tracking
-- Run this migration against the live Supabase database

ALTER TABLE public.jobs
ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NULL;

COMMENT ON COLUMN public.jobs.last_seen_at IS 'Timestamp of the last successful crawl that observed this job';

-- Backfill existing jobs: set last_seen_at = updated_at for jobs that don't have it
UPDATE public.jobs
SET last_seen_at = updated_at
WHERE last_seen_at IS NULL AND updated_at IS NOT NULL;

-- Index for freshness queries
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen_at ON public.jobs(last_seen_at);

-- Index for stale job queries
CREATE INDEX IF NOT EXISTS idx_jobs_is_active_posted_at ON public.jobs(is_active, posted_at) WHERE is_active = true;
