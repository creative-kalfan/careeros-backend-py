-- Migration 032: Backfill crawl_target_slug for existing ATS and Firecrawl jobs
-- Derives slug strictly from careers_url and apply_url URL patterns (never guesses).

BEGIN;

-- 1. Ashby: jobs.ashbyhq.com/{slug}/...
UPDATE public.jobs
SET crawl_target_slug = (regexp_match(COALESCE(careers_url, apply_url), 'jobs\.ashbyhq\.com/([^/?#]+)'))[1]
WHERE crawl_target_slug IS NULL
  AND (careers_url ~ 'jobs\.ashbyhq\.com/[^/?#]+' OR apply_url ~ 'jobs\.ashbyhq\.com/[^/?#]+');

-- 2. Greenhouse: boards.greenhouse.io/{slug}/... or job-boards.greenhouse.io/{slug}/...
UPDATE public.jobs
SET crawl_target_slug = (regexp_match(COALESCE(careers_url, apply_url), '(?:boards|job-boards)\.greenhouse\.io/([^/?#]+)'))[1]
WHERE crawl_target_slug IS NULL
  AND (careers_url ~ '(?:boards|job-boards)\.greenhouse\.io/[^/?#]+' OR apply_url ~ '(?:boards|job-boards)\.greenhouse\.io/[^/?#]+');

-- 3. Lever: jobs.lever.co/{slug}/...
UPDATE public.jobs
SET crawl_target_slug = (regexp_match(COALESCE(careers_url, apply_url), 'jobs\.lever\.co/([^/?#]+)'))[1]
WHERE crawl_target_slug IS NULL
  AND (careers_url ~ 'jobs\.lever\.co/[^/?#]+' OR apply_url ~ 'jobs\.lever\.co/[^/?#]+');

-- 4. SmartRecruiters: (careers|jobs)\.smartrecruiters\.com/{slug}/... or smartrecruiters\.com/{slug}/...
UPDATE public.jobs
SET crawl_target_slug = (regexp_match(COALESCE(careers_url, apply_url), 'smartrecruiters\.com/([^/?#]+)'))[1]
WHERE crawl_target_slug IS NULL
  AND (careers_url ~ 'smartrecruiters\.com/[^/?#]+' OR apply_url ~ 'smartrecruiters\.com/[^/?#]+');

-- 5. Firecrawl: match crawl_targets where ct.source = 'firecrawl' and url matches
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'crawl_targets') THEN
        UPDATE public.jobs j
        SET crawl_target_slug = ct.slug
        FROM public.crawl_targets ct
        WHERE ct.source = 'firecrawl'
          AND j.source_platform = 'firecrawl'
          AND j.crawl_target_slug IS NULL
          AND (j.careers_url = ct.url OR (ct.company IS NOT NULL AND ct.company <> '' AND LOWER(j.company) = LOWER(ct.company)));
    END IF;
END $$;

COMMIT;
