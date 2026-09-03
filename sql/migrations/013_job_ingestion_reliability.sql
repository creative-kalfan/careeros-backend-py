-- ============================================================================
-- 013: Job Ingestion Reliability
--
-- Adds database-level protection that complements the Python-side
-- deduplication in JobRepository.upsert_jobs:
--
--   1. Removes pre-existing duplicate rows (same source_platform +
--      external_job_id), keeping the oldest row so downstream references
--      (saved_jobs, applications, job_intelligence) keep resolving.
--   2. Adds a PARTIAL UNIQUE INDEX on (source_platform, external_job_id) so a
--      concurrent crawl can never create a second row for the same job —
--      closing the SELECT-then-INSERT race window. Partial because rows with
--      NULL identity are rejected at the repository layer anyway.
--   3. Adds an index supporting NO-LONGER-SEEN deactivation queries
--      (source + active + last_seen_at) used by deactivate_stale_jobs.
--
-- No RLS changes: jobs is system-owned ingestion data with an existing
-- read-for-authenticated policy.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Collapse existing duplicates (keep lowest id per identity pair).
-- ---------------------------------------------------------------------------
DELETE FROM public.jobs a
USING public.jobs b
WHERE a.id > b.id
  AND a.source_platform IS NOT DISTINCT FROM b.source_platform
  AND a.external_job_id IS NOT DISTINCT FROM b.external_job_id
  AND a.source_platform IS NOT NULL
  AND a.external_job_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. Unique identity constraint (partial unique index).
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_source_platform_external_job_id
    ON public.jobs (source_platform, external_job_id)
    WHERE source_platform IS NOT NULL AND external_job_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 3. Lifecycle / freshness index for stale-source deactivation.
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_jobs_source_active_last_seen
    ON public.jobs (source_platform, is_active, last_seen_at)
    WHERE is_active = true;

COMMIT;
