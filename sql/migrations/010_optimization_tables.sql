-- ============================================================================
-- Optimization tables — Step 5: AI Resume Optimization
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.optimization_sessions (
    id UUID PRIMARY KEY,
    resume_id UUID NOT NULL REFERENCES public.resumes(id) ON DELETE CASCADE,
    version_id UUID REFERENCES public.resume_versions(id) ON DELETE SET NULL,
    ats_report_id UUID,
    job_title TEXT,
    company TEXT,
    job_description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    suggestions_generated INTEGER NOT NULL DEFAULT 0,
    suggestions_accepted INTEGER NOT NULL DEFAULT 0,
    suggestions_rejected INTEGER NOT NULL DEFAULT 0,
    current_ats_score FLOAT,
    baseline_ats_score FLOAT,
    target_job_title TEXT,
    target_company TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.optimization_suggestions (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES public.optimization_sessions(id) ON DELETE CASCADE,
    suggestion JSONB NOT NULL DEFAULT '{}'::jsonb,
    resume_snapshot JSONB,
    applied BOOLEAN NOT NULL DEFAULT FALSE,
    applied_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_optimization_sessions_resume_id
    ON public.optimization_sessions(resume_id);

CREATE INDEX IF NOT EXISTS idx_optimization_sessions_version_id
    ON public.optimization_sessions(version_id);

CREATE INDEX IF NOT EXISTS idx_optimization_suggestions_session_id
    ON public.optimization_suggestions(session_id);

-- RLS
ALTER TABLE public.optimization_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.optimization_suggestions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own optimization sessions"
    ON public.optimization_sessions
    FOR SELECT
    USING (
        resume_id IN (
            SELECT id FROM public.resumes WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can insert own optimization sessions"
    ON public.optimization_sessions
    FOR INSERT
    WITH CHECK (
        resume_id IN (
            SELECT id FROM public.resumes WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can update own optimization sessions"
    ON public.optimization_sessions
    FOR UPDATE
    USING (
        resume_id IN (
            SELECT id FROM public.resumes WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can view own optimization suggestions"
    ON public.optimization_suggestions
    FOR SELECT
    USING (
        session_id IN (
            SELECT id FROM public.optimization_sessions
            WHERE resume_id IN (
                SELECT id FROM public.resumes WHERE user_id = auth.uid()
            )
        )
    );

CREATE POLICY "Users can insert own optimization suggestions"
    ON public.optimization_suggestions
    FOR INSERT
    WITH CHECK (
        session_id IN (
            SELECT id FROM public.optimization_sessions
            WHERE resume_id IN (
                SELECT id FROM public.resumes WHERE user_id = auth.uid()
            )
        )
    );

CREATE POLICY "Users can update own optimization suggestions"
    ON public.optimization_suggestions
    FOR UPDATE
    USING (
        session_id IN (
            SELECT id FROM public.optimization_sessions
            WHERE resume_id IN (
                SELECT id FROM public.resumes WHERE user_id = auth.uid()
            )
        )
    );
