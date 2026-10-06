-- Migration 033: Crawl Observability Data Model & Transition Events
-- Idempotent, safe migration with service-role-only RLS policies

BEGIN;

-- 1. Table: crawl_runs
CREATE TABLE IF NOT EXISTS public.crawl_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_id UUID REFERENCES public.crawl_targets(id) ON DELETE SET NULL,
    source TEXT NOT NULL,
    slug TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'unchanged', 'suspicious_empty', 'failed', 'anomaly')),
    discovered INT NOT NULL DEFAULT 0,
    inserted INT NOT NULL DEFAULT 0,
    updated INT NOT NULL DEFAULT 0,
    unchanged INT NOT NULL DEFAULT 0,
    deactivated INT NOT NULL DEFAULT 0,
    fetch_ms INT NOT NULL DEFAULT 0,
    persist_wait_ms INT NOT NULL DEFAULT 0,
    persist_hold_ms INT NOT NULL DEFAULT 0,
    error_type TEXT,
    anomaly_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for crawl_runs
CREATE INDEX IF NOT EXISTS idx_crawl_runs_target_started
    ON public.crawl_runs (target_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_crawl_runs_source_slug_started
    ON public.crawl_runs (source, slug, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_crawl_runs_status_started
    ON public.crawl_runs (status, started_at DESC);

-- Enable RLS (service-role only)
ALTER TABLE public.crawl_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crawl_runs_service_role_all ON public.crawl_runs;
CREATE POLICY crawl_runs_service_role_all ON public.crawl_runs
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- 2. Table: job_events
CREATE TABLE IF NOT EXISTS public.job_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN ('first_seen', 'changed', 'missing', 'reappeared', 'closed', 'reposted')),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    crawl_run_id UUID REFERENCES public.crawl_runs(id) ON DELETE SET NULL,
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for job_events
CREATE INDEX IF NOT EXISTS idx_job_events_job_occurred
    ON public.job_events (job_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_job_events_crawl_run
    ON public.job_events (crawl_run_id);

CREATE INDEX IF NOT EXISTS idx_job_events_type_occurred
    ON public.job_events (event_type, occurred_at DESC);

-- Enable RLS (service-role only)
ALTER TABLE public.job_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS job_events_service_role_all ON public.job_events;
CREATE POLICY job_events_service_role_all ON public.job_events
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- 3. Replace upsert_jobs_batch to accept optional p_crawl_run_id and emit transition events
-- Emits:
--   'first_seen' on initial insert
--   'changed' on content_hash change
--   'reappeared' when transitioning from is_active = false to is_active = true
CREATE OR REPLACE FUNCTION public.upsert_jobs_batch(
    jobs_json jsonb,
    p_crawl_run_id uuid DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    inserted_count int := 0;
    updated_count int := 0;
    unchanged_count int := 0;
    inserted_ids text[] := ARRAY[]::text[];
    analysis_ids text[] := ARRAY[]::text[];
BEGIN
    WITH diffs AS (
        SELECT
            x.external_job_id,
            x.source_platform,
            encode(sha256((COALESCE(x.title, '') || COALESCE(x.description, ''))::bytea), 'hex') AS new_content_hash,
            j.id AS existing_job_id,
            j.is_active AS existing_is_active,
            CASE WHEN j.id IS NULL THEN 'insert'
                 WHEN j.title IS DISTINCT FROM x.title OR
                      j.company IS DISTINCT FROM x.company OR
                      j.location IS DISTINCT FROM x.location OR
                      j.description IS DISTINCT FROM x.description OR
                      j.url IS DISTINCT FROM x.url OR
                      j.posted_at IS DISTINCT FROM COALESCE(j.posted_at, x.posted_at) OR
                      j.role_category IS DISTINCT FROM x.role_category OR
                      j.application_deadline IS DISTINCT FROM x.application_deadline OR
                      j.employment_type IS DISTINCT FROM x.employment_type OR
                      j.salary_min IS DISTINCT FROM x.salary_min OR
                      j.salary_max IS DISTINCT FROM x.salary_max OR
                      j.experience_level IS DISTINCT FROM x.experience_level OR
                      j.remote IS DISTINCT FROM x.remote OR
                      j.crawl_target_slug IS DISTINCT FROM x.crawl_target_slug OR
                      j.mass_hiring IS DISTINCT FROM x.mass_hiring OR
                      j.mass_hiring_status IS DISTINCT FROM x.mass_hiring_status OR
                      j.mass_hiring_details IS DISTINCT FROM x.mass_hiring_details OR
                      j.skills::text IS DISTINCT FROM x.skills::text
                 THEN 'update'
                 ELSE 'touch'
            END AS action_type,
            CASE WHEN j.id IS NULL OR j.content_hash IS DISTINCT FROM encode(sha256((COALESCE(x.title, '') || COALESCE(x.description, ''))::bytea), 'hex') THEN true ELSE false END AS hash_changed
        FROM jsonb_to_recordset(jobs_json) AS x (
            title text, company text, location text, description text, url text, posted_at timestamptz,
            role_category text, application_deadline date, source_platform text,
            external_job_id text, remote boolean, workplace_type text, employment_type text,
            salary_min numeric, salary_max numeric, experience_level text, skills jsonb,
            mass_hiring boolean, mass_hiring_status text, mass_hiring_details text,
            crawl_target_slug text
        )
        LEFT JOIN public.jobs j
          ON j.source_platform = x.source_platform AND j.external_job_id = x.external_job_id
    ),
    upsert AS (
        INSERT INTO public.jobs (
            title, company, location, description, url, source, posted_at,
            role_category, application_deadline, is_active, source_platform,
            external_job_id, remote, workplace_type, employment_type,
            salary_min, salary_max, experience_level, skills,
            source_tier, source_provider, canonical_url, source_verified,
            source_confidence, company_website, careers_url, logo_url,
            first_seen_at, last_seen_at, last_crawled_at, source_history,
            mass_hiring, mass_hiring_status, mass_hiring_details,
            crawl_target_slug, content_hash
        )
        SELECT
            x.title, x.company, x.location, x.description, x.url, x.source, x.posted_at,
            x.role_category, x.application_deadline, true AS is_active, x.source_platform,
            x.external_job_id, x.remote, x.workplace_type, x.employment_type,
            x.salary_min, x.salary_max, x.experience_level,
            (SELECT array_agg(trim(s)) FROM jsonb_array_elements_text(x.skills) s) AS skills,
            x.source_tier, x.source_provider, x.canonical_url, x.source_verified,
            x.source_confidence, x.company_website, x.careers_url, x.logo_url,
            COALESCE(x.first_seen_at, now()) AS first_seen_at,
            now() AS last_seen_at,
            now() AS last_crawled_at,
            x.source_history,
            x.mass_hiring, x.mass_hiring_status, x.mass_hiring_details,
            x.crawl_target_slug,
            d.new_content_hash
        FROM jsonb_to_recordset(jobs_json) AS x (
            title text, company text, location text, description text, url text, source text, posted_at timestamptz,
            role_category text, application_deadline date, is_active boolean, source_platform text,
            external_job_id text, remote boolean, workplace_type text, employment_type text,
            salary_min numeric, salary_max numeric, experience_level text, skills jsonb,
            source_tier int, source_provider text, canonical_url text, source_verified boolean,
            source_confidence numeric, company_website text, careers_url text, logo_url text,
            first_seen_at timestamptz, source_history jsonb,
            mass_hiring boolean, mass_hiring_status text, mass_hiring_details text,
            crawl_target_slug text
        )
        JOIN diffs d ON d.source_platform = x.source_platform AND d.external_job_id = x.external_job_id
        ON CONFLICT (source_platform, external_job_id) WHERE source_platform IS NOT NULL AND external_job_id IS NOT NULL
        DO UPDATE SET
            title = EXCLUDED.title,
            company = EXCLUDED.company,
            location = EXCLUDED.location,
            description = EXCLUDED.description,
            url = EXCLUDED.url,
            source = EXCLUDED.source,
            posted_at = COALESCE(jobs.posted_at, EXCLUDED.posted_at),
            role_category = EXCLUDED.role_category,
            application_deadline = EXCLUDED.application_deadline,
            is_active = true,
            remote = EXCLUDED.remote,
            workplace_type = EXCLUDED.workplace_type,
            employment_type = EXCLUDED.employment_type,
            salary_min = EXCLUDED.salary_min,
            salary_max = EXCLUDED.salary_max,
            experience_level = EXCLUDED.experience_level,
            skills = EXCLUDED.skills,
            source_tier = CASE WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.source_tier ELSE jobs.source_tier END,
            source_provider = CASE WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.source_provider ELSE jobs.source_provider END,
            canonical_url = CASE WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.canonical_url ELSE jobs.canonical_url END,
            source_verified = CASE WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.source_verified ELSE jobs.source_verified END,
            source_confidence = CASE WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.source_confidence ELSE jobs.source_confidence END,
            company_website = CASE WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.company_website ELSE jobs.company_website END,
            careers_url = CASE WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.careers_url ELSE jobs.careers_url END,
            logo_url = CASE WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.logo_url ELSE jobs.logo_url END,
            source_history = CASE WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN COALESCE(jobs.source_history, '[]'::jsonb) || jsonb_build_object('source_tier', jobs.source_tier, 'source_provider', jobs.source_provider, 'canonical_url', jobs.canonical_url, 'source_verified', jobs.source_verified, 'source_confidence', jobs.source_confidence, 'company_website', jobs.company_website, 'careers_url', jobs.careers_url, 'logo_url', jobs.logo_url, 'upgraded_at', now()) ELSE jobs.source_history END,
            last_seen_at = now(),
            last_crawled_at = now(),
            mass_hiring = EXCLUDED.mass_hiring,
            mass_hiring_status = EXCLUDED.mass_hiring_status,
            mass_hiring_details = EXCLUDED.mass_hiring_details,
            crawl_target_slug = COALESCE(EXCLUDED.crawl_target_slug, jobs.crawl_target_slug),
            content_hash = EXCLUDED.content_hash,
            updated_at = now()
        RETURNING id, external_job_id, source_platform, content_hash
    ),
    -- Set-based event generation
    events_to_emit AS (
        SELECT
            u.id AS job_id,
            CASE
                WHEN d.action_type = 'insert' THEN 'first_seen'
                WHEN d.existing_is_active IS FALSE THEN 'reappeared'
                WHEN d.hash_changed THEN 'changed'
                ELSE NULL
            END AS event_type,
            jsonb_build_object(
                'action_type', d.action_type,
                'content_hash', u.content_hash,
                'source_platform', u.source_platform,
                'external_job_id', u.external_job_id
            ) AS details
        FROM upsert u
        JOIN diffs d ON d.source_platform = u.source_platform AND d.external_job_id = u.external_job_id
    ),
    inserted_events AS (
        INSERT INTO public.job_events (job_id, event_type, occurred_at, crawl_run_id, details)
        SELECT e.job_id, e.event_type, now(), p_crawl_run_id, e.details
        FROM events_to_emit e
        WHERE e.event_type IS NOT NULL
        RETURNING id
    )
    SELECT
        count(*) FILTER (WHERE action_type = 'insert'),
        count(*) FILTER (WHERE action_type = 'update'),
        count(*) FILTER (WHERE action_type = 'touch'),
        COALESCE(array_agg(external_job_id) FILTER (WHERE action_type = 'insert'), ARRAY[]::text[]),
        COALESCE(array_agg(external_job_id) FILTER (WHERE hash_changed), ARRAY[]::text[])
    INTO inserted_count, updated_count, unchanged_count, inserted_ids, analysis_ids
    FROM diffs;

    RETURN jsonb_build_object(
        'inserted', COALESCE(inserted_count, 0),
        'updated', COALESCE(updated_count, 0),
        'unchanged', COALESCE(unchanged_count, 0),
        'inserted_ids', to_jsonb(COALESCE(inserted_ids, ARRAY[]::text[])),
        'analysis_ids', to_jsonb(COALESCE(analysis_ids, ARRAY[]::text[]))
    );
END;
$$;

REVOKE ALL ON FUNCTION public.upsert_jobs_batch(jsonb, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_jobs_batch(jsonb, uuid) TO service_role;

-- 4. Update deactivate_unseen_jobs_batch to accept optional p_crawl_run_id and emit transitions
-- Emits:
--   'missing' when missed_crawls increases
--   'closed' when missed_crawls reaches threshold and is_active transitions to false
CREATE OR REPLACE FUNCTION public.deactivate_unseen_jobs_batch(
    p_source TEXT,
    p_company TEXT,
    p_careers_url TEXT,
    p_since TIMESTAMPTZ,
    p_threshold SMALLINT,
    p_slug TEXT DEFAULT NULL,
    p_crawl_run_id UUID DEFAULT NULL
) RETURNS INT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE changed INT;
BEGIN
    WITH candidate_jobs AS (
        SELECT id, missed_crawls, is_active
        FROM public.jobs
        WHERE is_active = TRUE AND source_platform = p_source
          AND (
              CASE
                  WHEN p_slug IS NOT NULL
                      THEN crawl_target_slug = p_slug
                  WHEN p_company IS NOT NULL AND p_careers_url IS NOT NULL
                      THEN LOWER(company) = LOWER(p_company) AND careers_url = p_careers_url
                  WHEN p_company IS NOT NULL
                      THEN LOWER(company) = LOWER(p_company)
                  WHEN p_careers_url IS NOT NULL
                      THEN careers_url = p_careers_url
                  WHEN p_source NOT IN ('firecrawl', 'ashby', 'greenhouse', 'lever', 'smartrecruiters')
                      THEN TRUE
                  ELSE FALSE
              END
          )
          AND last_seen_at IS NOT NULL AND last_seen_at < p_since
    ),
    marked AS (
        UPDATE public.jobs j
        SET missed_crawls = j.missed_crawls + 1,
            is_active = CASE WHEN j.missed_crawls + 1 >= GREATEST(1, p_threshold) THEN FALSE ELSE j.is_active END
        FROM candidate_jobs c
        WHERE j.id = c.id
        RETURNING j.id, (j.missed_crawls + 1) AS new_missed, (j.missed_crawls + 1 >= GREATEST(1, p_threshold)) AS became_inactive
    ),
    inserted_events AS (
        INSERT INTO public.job_events (job_id, event_type, occurred_at, crawl_run_id, details)
        SELECT
            m.id,
            CASE WHEN m.became_inactive THEN 'closed' ELSE 'missing' END AS event_type,
            now(),
            p_crawl_run_id,
            jsonb_build_object('missed_crawls', m.new_missed, 'threshold', p_threshold)
        FROM marked m
        RETURNING id
    )
    SELECT count(*) FILTER (WHERE became_inactive) INTO changed FROM marked;
    RETURN changed;
END;
$$;

REVOKE ALL ON FUNCTION public.deactivate_unseen_jobs_batch(TEXT, TEXT, TEXT, TIMESTAMPTZ, SMALLINT, TEXT, UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.deactivate_unseen_jobs_batch(TEXT, TEXT, TEXT, TIMESTAMPTZ, SMALLINT, TEXT, UUID) TO service_role;

COMMIT;
