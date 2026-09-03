-- ============================================================================
-- Resume Versions — Step 6: Job-Specific Resume Versions
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Extend resume_versions with job-specific metadata
-- ---------------------------------------------------------------------------
ALTER TABLE public.resume_versions
    ADD COLUMN IF NOT EXISTS version_name text NOT NULL DEFAULT 'Untitled Version',
    ADD COLUMN IF NOT EXISTS target_job_title text,
    ADD COLUMN IF NOT EXISTS target_company text,
    ADD COLUMN IF NOT EXISTS target_job_id text,
    ADD COLUMN IF NOT EXISTS target_job_url text,
    ADD COLUMN IF NOT EXISTS job_description text,
    ADD COLUMN IF NOT EXISTS template text DEFAULT 'minimal',
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','archived','deleted')),
    ADD COLUMN IF NOT EXISTS is_master boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS parent_version_id uuid REFERENCES public.resume_versions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS meta jsonb DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS last_ats_score double precision,
    ADD COLUMN IF NOT EXISTS last_analyzed_at timestamptz,
    ADD COLUMN IF NOT EXISTS sections_config jsonb DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS content_json jsonb DEFAULT '{}'::jsonb;

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_resume_versions_resume_id
    ON public.resume_versions(resume_id);

CREATE INDEX IF NOT EXISTS idx_resume_versions_user_id
    ON public.resume_versions(resume_id);

CREATE INDEX IF NOT EXISTS idx_resume_versions_status
    ON public.resume_versions(status);

-- ---------------------------------------------------------------------------
-- Ensure one master per resume
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uq_resume_versions_master_per_resume
    ON public.resume_versions(resume_id)
    WHERE (is_master = true);

-- ---------------------------------------------------------------------------
-- RLS policies
-- ---------------------------------------------------------------------------
ALTER TABLE public.resume_versions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view versions of own resumes" ON public.resume_versions;
DROP POLICY IF EXISTS "Users can insert versions of own resumes" ON public.resume_versions;
DROP POLICY IF EXISTS "Users can update versions of own resumes" ON public.resume_versions;
DROP POLICY IF EXISTS "Users can delete versions of own resumes" ON public.resume_versions;

CREATE POLICY "Users can view versions of own resumes"
    ON public.resume_versions FOR SELECT
    USING (EXISTS (
        SELECT 1 FROM public.resumes r
        WHERE r.id = resume_id AND r.user_id = auth.uid()
    ));

CREATE POLICY "Users can insert versions of own resumes"
    ON public.resume_versions FOR INSERT
    WITH CHECK (EXISTS (
        SELECT 1 FROM public.resumes r
        WHERE r.id = resume_id AND r.user_id = auth.uid()
    ));

CREATE POLICY "Users can update versions of own resumes"
    ON public.resume_versions FOR UPDATE
    USING (EXISTS (
        SELECT 1 FROM public.resumes r
        WHERE r.id = resume_id AND r.user_id = auth.uid()
    ));

CREATE POLICY "Users can delete versions of own resumes"
    ON public.resume_versions FOR DELETE
    USING (EXISTS (
        SELECT 1 FROM public.resumes r
        WHERE r.id = resume_id AND r.user_id = auth.uid()
    ));

-- ---------------------------------------------------------------------------
-- Auto-update updated_at on resume_versions (reuse existing function pattern)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_resume_versions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_resume_versions_updated_at ON public.resume_versions;
CREATE TRIGGER trg_resume_versions_updated_at
    BEFORE UPDATE ON public.resume_versions
    FOR EACH ROW EXECUTE FUNCTION public.set_resume_versions_updated_at();

-- ---------------------------------------------------------------------------
-- Backfill: ensure every resume has a master version
-- ---------------------------------------------------------------------------
INSERT INTO public.resume_versions (resume_id, version_name, source, content, is_master, status, created_at)
SELECT 
    r.id,
    COALESCE(r.title, 'Master Resume'),
    'manual',
    COALESCE(r.content, '{}'::jsonb),
    true,
    'active',
    now()
FROM public.resumes r
WHERE NOT EXISTS (
    SELECT 1 FROM public.resume_versions v
    WHERE v.resume_id = r.id AND v.is_master = true
)
ON CONFLICT DO NOTHING;
