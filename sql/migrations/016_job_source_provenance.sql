-- ============================================================================
-- 016: Job Source Provenance & Official-Source Priority
--
-- Adds the canonical source-provenance model so every job can answer
-- "Where did CareerOS actually get this job?" and so OFFICIAL company
-- career postings can outrank aggregated/secondary listings in ranking:
--
--   source_tier        1 official_company_career (highest)
--                      2 official_ats
--                      3 verified_yc_startup
--                      4 other_verified_source
--                      5 aggregator (lowest)
--   source_provider    retrieval/ATS provider (firecrawl, greenhouse, ...)
--   canonical_url      de-duplicated canonical job URL
--   source_verified    domain verification status (official check passed)
--   source_confidence  0-1 verification confidence
--   company_website    official company website
--   careers_url        official careers page used for crawling
--   logo_url           official logo/favicon asset (never fabricated)
--   first_seen_at      first discovery timestamp
--   last_crawled_at    last successful crawl that observed this job
--   source_history     provenance audit trail (secondary -> official upgrades)
--
-- Backfills are conservative: rows without evidence stay NULL/unverified
-- rather than being fabricated as official.
-- ============================================================================

BEGIN;

ALTER TABLE public.jobs
    ADD COLUMN IF NOT EXISTS source_tier smallint,
    ADD COLUMN IF NOT EXISTS source_provider text,
    ADD COLUMN IF NOT EXISTS canonical_url text,
    ADD COLUMN IF NOT EXISTS source_verified boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS source_confidence double precision,
    ADD COLUMN IF NOT EXISTS company_website text,
    ADD COLUMN IF NOT EXISTS careers_url text,
    ADD COLUMN IF NOT EXISTS logo_url text,
    ADD COLUMN IF NOT EXISTS first_seen_at timestamptz,
    ADD COLUMN IF NOT EXISTS last_crawled_at timestamptz,
    ADD COLUMN IF NOT EXISTS source_history jsonb NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN public.jobs.source_tier IS
    '1=official_company_career, 2=official_ats, 3=verified_yc_startup, 4=other_verified_source, 5=aggregator';

-- Conservative backfill: lifecycle timestamps from existing columns.
UPDATE public.jobs SET first_seen_at = created_at WHERE first_seen_at IS NULL;
UPDATE public.jobs
SET last_crawled_at = COALESCE(last_seen_at, updated_at)
WHERE last_crawled_at IS NULL;

-- Conservative backfill of source tier from the existing source_platform
-- values. Everything NOT listed stays tier 4 (other_verified_source).
UPDATE public.jobs SET source_tier = 5, source_verified = true
WHERE source_platform = 'adzuna' AND source_tier IS NULL;
UPDATE public.jobs SET source_tier = 2, source_verified = true
WHERE source_platform IN ('greenhouse', 'lever', 'ashby', 'smartrecruiters', 'workday', 'icims')
  AND source_tier IS NULL;
UPDATE public.jobs SET source_tier = 3, source_verified = true
WHERE source_platform = 'ycombinator' AND source_tier IS NULL;
UPDATE public.jobs SET source_tier = 4 WHERE source_tier IS NULL;

-- Canonical URL defaults to the existing url column.
UPDATE public.jobs SET canonical_url = url WHERE canonical_url IS NULL AND url IS NOT NULL;

-- Ranking support: source-quality-first ordering over active jobs.
CREATE INDEX IF NOT EXISTS idx_jobs_source_tier_active
    ON public.jobs (source_tier, is_active) WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_jobs_source_verified_active
    ON public.jobs (source_verified, is_active) WHERE is_active = true;

COMMIT;