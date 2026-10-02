-- Migration 028: Crawl target slug column, scoped deactivation on (source, slug), and active jobs missing intelligence RPC

BEGIN;

-- 1. Add crawl_target_slug column to public.jobs
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS crawl_target_slug TEXT;

CREATE INDEX IF NOT EXISTS idx_jobs_source_target_slug
    ON public.jobs (source_platform, crawl_target_slug)
    WHERE crawl_target_slug IS NOT NULL;

-- 2. Best-effort backfill from crawl_targets and registry conventions
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'crawl_targets') THEN
        UPDATE public.jobs j
        SET crawl_target_slug = ct.slug
        FROM public.crawl_targets ct
        WHERE j.source_platform = ct.source
          AND j.crawl_target_slug IS NULL
          AND (
              (ct.company IS NOT NULL AND ct.company <> '' AND LOWER(j.company) = LOWER(ct.company))
              OR (ct.url IS NOT NULL AND ct.url <> '' AND j.careers_url = ct.url)
          );
    END IF;
END $$;

-- Backfill YCombinator
UPDATE public.jobs
SET crawl_target_slug = 'ycombinator'
WHERE source_platform = 'ycombinator' AND crawl_target_slug IS NULL;

-- Best-effort fallback for ATS sources matching common slug format
UPDATE public.jobs
SET crawl_target_slug = lower(regexp_replace(company, '[^a-zA-Z0-9]+', '-', 'g'))
WHERE crawl_target_slug IS NULL
  AND source_platform IN ('ashby', 'greenhouse', 'lever', 'smartrecruiters')
  AND company IS NOT NULL AND company <> '';

COMMIT;

-- 3. Update upsert_jobs_batch to accept and store crawl_target_slug
CREATE OR REPLACE FUNCTION public.upsert_jobs_batch(jobs_json jsonb)
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
BEGIN
    WITH diffs AS (
        SELECT
            x.external_job_id,
            x.source_platform,
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
            END AS action_type
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
            crawl_target_slug
        )
        SELECT
            title, company, location, description, url, source, posted_at,
            role_category, application_deadline, true AS is_active, source_platform,
            external_job_id, remote, workplace_type, employment_type,
            salary_min, salary_max, experience_level,
            (SELECT array_agg(trim(s)) FROM jsonb_array_elements_text(skills) s) AS skills,
            source_tier, source_provider, canonical_url, source_verified,
            source_confidence, company_website, careers_url, logo_url,
            COALESCE(first_seen_at, now()) AS first_seen_at,
            now() AS last_seen_at,
            now() AS last_crawled_at,
            source_history,
            mass_hiring, mass_hiring_status, mass_hiring_details,
            crawl_target_slug
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
            source_tier = CASE
                WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.source_tier
                ELSE jobs.source_tier
            END,
            source_provider = CASE
                WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.source_provider
                ELSE jobs.source_provider
            END,
            canonical_url = CASE
                WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.canonical_url
                ELSE jobs.canonical_url
            END,
            source_verified = CASE
                WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.source_verified
                ELSE jobs.source_verified
            END,
            source_confidence = CASE
                WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.source_confidence
                ELSE jobs.source_confidence
            END,
            company_website = CASE
                WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.company_website
                ELSE jobs.company_website
            END,
            careers_url = CASE
                WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.careers_url
                ELSE jobs.careers_url
            END,
            logo_url = CASE
                WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN EXCLUDED.logo_url
                ELSE jobs.logo_url
            END,
            source_history = CASE
                WHEN EXCLUDED.source_tier IS NOT NULL AND (jobs.source_tier IS NULL OR EXCLUDED.source_tier < jobs.source_tier) THEN
                    COALESCE(jobs.source_history, '[]'::jsonb) || jsonb_build_object(
                        'source_tier', jobs.source_tier,
                        'source_provider', jobs.source_provider,
                        'canonical_url', jobs.canonical_url,
                        'source_verified', jobs.source_verified,
                        'source_confidence', jobs.source_confidence,
                        'company_website', jobs.company_website,
                        'careers_url', jobs.careers_url,
                        'logo_url', jobs.logo_url,
                        'upgraded_at', now()
                    )
                ELSE jobs.source_history
            END,
            last_seen_at = now(),
            last_crawled_at = now(),
            mass_hiring = EXCLUDED.mass_hiring,
            mass_hiring_status = EXCLUDED.mass_hiring_status,
            mass_hiring_details = EXCLUDED.mass_hiring_details,
            crawl_target_slug = COALESCE(EXCLUDED.crawl_target_slug, jobs.crawl_target_slug),
            updated_at = now()
        RETURNING external_job_id
    )
    SELECT
        count(*) FILTER (WHERE action_type = 'insert'),
        count(*) FILTER (WHERE action_type = 'update'),
        count(*) FILTER (WHERE action_type = 'touch'),
        COALESCE(array_agg(external_job_id) FILTER (WHERE action_type = 'insert'), ARRAY[]::text[])
    INTO inserted_count, updated_count, unchanged_count, inserted_ids
    FROM diffs;

    RETURN jsonb_build_object(
        'inserted', COALESCE(inserted_count, 0),
        'updated', COALESCE(updated_count, 0),
        'unchanged', COALESCE(unchanged_count, 0),
        'inserted_ids', to_jsonb(COALESCE(inserted_ids, ARRAY[]::text[]))
    );
END;
$$;

REVOKE ALL ON FUNCTION public.upsert_jobs_batch(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_jobs_batch(jsonb) TO service_role;

-- 4. Update deactivate_unseen_jobs_batch to accept p_slug and scope by crawl_target_slug
DROP FUNCTION IF EXISTS public.deactivate_unseen_jobs_batch(TEXT, TEXT, TEXT, TIMESTAMPTZ, SMALLINT);

CREATE OR REPLACE FUNCTION public.deactivate_unseen_jobs_batch(
    p_source TEXT,
    p_company TEXT,
    p_careers_url TEXT,
    p_since TIMESTAMPTZ,
    p_threshold SMALLINT,
    p_slug TEXT DEFAULT NULL
) RETURNS INT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE changed INT;
BEGIN
    WITH marked AS (
        UPDATE public.jobs SET missed_crawls = missed_crawls + 1,
            is_active = CASE WHEN missed_crawls + 1 >= GREATEST(1, p_threshold) THEN FALSE ELSE is_active END
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
        RETURNING is_active
    )
    SELECT count(*) FILTER (WHERE NOT is_active) INTO changed FROM marked;
    RETURN changed;
END;
$$;

REVOKE ALL ON FUNCTION public.deactivate_unseen_jobs_batch(TEXT, TEXT, TEXT, TIMESTAMPTZ, SMALLINT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.deactivate_unseen_jobs_batch(TEXT, TEXT, TEXT, TIMESTAMPTZ, SMALLINT, TEXT) TO service_role;

-- 5. RPC to fetch active jobs missing structured intelligence
CREATE OR REPLACE FUNCTION public.get_active_jobs_missing_intelligence(p_limit INT DEFAULT 50)
RETURNS TABLE(id UUID, external_job_id TEXT, source_platform TEXT)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT j.id, j.external_job_id, j.source_platform
    FROM public.jobs j
    LEFT JOIN public.job_intelligence ji ON j.id = ji.job_id
    WHERE j.is_active = TRUE AND ji.id IS NULL
    ORDER BY j.created_at DESC
    LIMIT p_limit;
$$;

REVOKE ALL ON FUNCTION public.get_active_jobs_missing_intelligence(INT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_active_jobs_missing_intelligence(INT) TO service_role;
