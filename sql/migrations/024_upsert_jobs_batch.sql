-- Migration 024: Batch jobs upsert and stale deactivation

CREATE TABLE IF NOT EXISTS public.crawl_run_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_platform TEXT NOT NULL,
    company_slug TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    discovered_count INT NOT NULL DEFAULT 0,
    valid_count INT NOT NULL DEFAULT 0,
    crawled_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.crawl_run_history ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE schemaname = 'public' 
          AND tablename = 'crawl_run_history' 
          AND policyname = 'Service role full access to crawl_run_history'
    ) THEN
        CREATE POLICY "Service role full access to crawl_run_history"
            ON public.crawl_run_history
            FOR ALL
            TO service_role
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_crawl_run_history_source_slug_time
    ON public.crawl_run_history(source_platform, company_slug, crawled_at DESC);


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
BEGIN
    WITH diffs AS (
        SELECT 
            x.external_job_id,
            x.source_platform,
            -- Determine if this is a real content update or just a touch
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
                      j.mass_hiring IS DISTINCT FROM x.mass_hiring OR
                      j.mass_hiring_status IS DISTINCT FROM x.mass_hiring_status OR
                      j.mass_hiring_details IS DISTINCT FROM x.mass_hiring_details OR
                      -- Arrays are tricky, use text representation
                      j.skills::text IS DISTINCT FROM x.skills::text 
                 THEN 'update'
                 ELSE 'touch'
            END AS action_type
        FROM jsonb_to_recordset(jobs_json) AS x (
            title text, company text, location text, description text, url text, posted_at timestamptz,
            role_category text, application_deadline date, source_platform text,
            external_job_id text, remote boolean, workplace_type text, employment_type text,
            salary_min numeric, salary_max numeric, experience_level text, skills jsonb,
            mass_hiring boolean, mass_hiring_status text, mass_hiring_details text
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
            mass_hiring, mass_hiring_status, mass_hiring_details
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
            mass_hiring, mass_hiring_status, mass_hiring_details
        FROM jsonb_to_recordset(jobs_json) AS x (
            title text, company text, location text, description text, url text, source text, posted_at timestamptz,
            role_category text, application_deadline date, is_active boolean, source_platform text,
            external_job_id text, remote boolean, workplace_type text, employment_type text,
            salary_min numeric, salary_max numeric, experience_level text, skills jsonb,
            source_tier int, source_provider text, canonical_url text, source_verified boolean,
            source_confidence numeric, company_website text, careers_url text, logo_url text,
            first_seen_at timestamptz, source_history jsonb,
            mass_hiring boolean, mass_hiring_status text, mass_hiring_details text
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
            updated_at = now()
    )
    SELECT 
        count(*) FILTER (WHERE action_type = 'insert'),
        count(*) FILTER (WHERE action_type = 'update'),
        count(*) FILTER (WHERE action_type = 'touch')
    INTO inserted_count, updated_count, unchanged_count
    FROM diffs;

    RETURN jsonb_build_object(
        'inserted', COALESCE(inserted_count, 0),
        'updated', COALESCE(updated_count, 0),
        'unchanged', COALESCE(unchanged_count, 0)
    );
END;
$$;

REVOKE ALL ON FUNCTION public.upsert_jobs_batch(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.upsert_jobs_batch(jsonb) TO service_role;


CREATE OR REPLACE FUNCTION public.deactivate_stale_jobs_batch(
    p_source_platform TEXT,
    p_company TEXT,
    p_careers_url TEXT,
    p_max_age_days INT
) RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_cutoff TIMESTAMPTZ := now() - (p_max_age_days || ' days')::interval;
    v_count INT;
BEGIN
    UPDATE public.jobs
    SET is_active = false
    WHERE is_active = true
      AND source_platform = p_source_platform
      AND (p_company IS NULL OR company = p_company)
      AND (p_careers_url IS NULL OR careers_url = p_careers_url)
      AND (
          (last_seen_at IS NOT NULL AND last_seen_at < v_cutoff)
          OR (last_seen_at IS NULL AND posted_at IS NOT NULL AND posted_at < v_cutoff)
      );
      
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION public.deactivate_stale_jobs_batch(TEXT, TEXT, TEXT, INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.deactivate_stale_jobs_batch(TEXT, TEXT, TEXT, INT) TO service_role;
