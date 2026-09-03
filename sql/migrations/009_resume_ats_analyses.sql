-- ATS Analysis Reports table (Step 4)
-- Stores persistent ATS analysis results linked to resumes and versions.

CREATE TABLE IF NOT EXISTS public.resume_ats_analyses (
    id UUID PRIMARY KEY,
    resume_id UUID NOT NULL REFERENCES public.resumes(id) ON DELETE CASCADE,
    version_id UUID REFERENCES public.resume_versions(id) ON DELETE SET NULL,
    job_title TEXT,
    company TEXT,
    job_description TEXT NOT NULL,
    parsed_job_data JSONB,
    overall_score FLOAT NOT NULL,
    keyword_match_score FLOAT NOT NULL,
    skills_match_score FLOAT NOT NULL,
    experience_relevance_score FLOAT NOT NULL,
    qualification_match_score FLOAT NOT NULL,
    structure_format_score FLOAT NOT NULL,
    matched_keywords TEXT[] NOT NULL DEFAULT '{}',
    missing_keywords TEXT[] NOT NULL DEFAULT '{}',
    partial_keywords TEXT[] NOT NULL DEFAULT '{}',
    matched_skills TEXT[] NOT NULL DEFAULT '{}',
    missing_skills TEXT[] NOT NULL DEFAULT '{}',
    partial_skills TEXT[] NOT NULL DEFAULT '{}',
    requirement_analysis JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommendations TEXT[] NOT NULL DEFAULT '{}',
    high_priority_recommendations TEXT[] NOT NULL DEFAULT '{}',
    medium_priority_recommendations TEXT[] NOT NULL DEFAULT '{}',
    low_priority_recommendations TEXT[] NOT NULL DEFAULT '{}',
    template_analysis JSONB NOT NULL DEFAULT '{}'::jsonb,
    section_analysis JSONB NOT NULL DEFAULT '{}'::jsonb,
    analysis_explanation JSONB NOT NULL DEFAULT '{}'::jsonb,
    scoring_version TEXT NOT NULL DEFAULT '1.0',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_resume_ats_analyses_resume_id
    ON public.resume_ats_analyses(resume_id);

CREATE INDEX IF NOT EXISTS idx_resume_ats_analyses_version_id
    ON public.resume_ats_analyses(version_id);

CREATE INDEX IF NOT EXISTS idx_resume_ats_analyses_created_at
    ON public.resume_ats_analyses(created_at DESC);

-- RLS policies (user can only access their own resume's analyses)
ALTER TABLE public.resume_ats_analyses ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own resume analyses"
    ON public.resume_ats_analyses
    FOR SELECT
    USING (
        resume_id IN (
            SELECT id FROM public.resumes WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can insert own resume analyses"
    ON public.resume_ats_analyses
    FOR INSERT
    WITH CHECK (
        resume_id IN (
            SELECT id FROM public.resumes WHERE user_id = auth.uid()
        )
    );
