-- Phase 7A: Job Intelligence foundation
-- Adds the job_intelligence table for storing structured intelligence
-- extracted from job descriptions.

BEGIN;

-- Main job intelligence table.
CREATE TABLE IF NOT EXISTS public.job_intelligence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
    intelligence_version TEXT NOT NULL DEFAULT '1.0',
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seniority JSONB,
    skills JSONB,
    requirements JSONB,
    education JSONB,
    certifications JSONB,
    keywords JSONB,
    responsibilities JSONB,
    industries JSONB,
    work_arrangement JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT job_intelligence_job_id_key UNIQUE (job_id)
);

-- Indexes.
CREATE INDEX IF NOT EXISTS idx_job_intelligence_job_id
    ON public.job_intelligence(job_id);

CREATE INDEX IF NOT EXISTS idx_job_intelligence_generated_at
    ON public.job_intelligence(generated_at);

-- GIN indexes for JSONB fields used in filtering/search.
CREATE INDEX IF NOT EXISTS idx_job_intelligence_skills_gin
    ON public.job_intelligence USING GIN (skills);

CREATE INDEX IF NOT EXISTS idx_job_intelligence_keywords_gin
    ON public.job_intelligence USING GIN (keywords);

-- Trigger to maintain updated_at.
CREATE OR REPLACE FUNCTION public.set_job_intelligence_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_job_intelligence_updated_at ON public.job_intelligence;
CREATE TRIGGER trigger_job_intelligence_updated_at
    BEFORE UPDATE ON public.job_intelligence
    FOR EACH ROW EXECUTE FUNCTION public.set_job_intelligence_updated_at();

COMMIT;
