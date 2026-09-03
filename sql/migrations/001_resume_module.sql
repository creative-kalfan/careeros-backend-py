-- ============================================================================
-- Resume Module — Step 1: Data Collection & Resume Import
-- ============================================================================

-- ---------------------------------------------------------------------------
-- resumes table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.resumes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title text NOT NULL DEFAULT 'Untitled Resume',
    file_url text,
    original_filename text,
    storage_path text,
    parse_status text NOT NULL DEFAULT 'pending'
        CHECK (parse_status IN ('pending','processing','completed','failed')),
    content jsonb DEFAULT '{}'::jsonb,
    meta jsonb DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_resumes_user_id
    ON public.resumes(user_id);

CREATE INDEX IF NOT EXISTS idx_resumes_parse_status
    ON public.resumes(parse_status);

-- ---------------------------------------------------------------------------
-- resume_versions table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.resume_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id uuid NOT NULL REFERENCES public.resumes(id) ON DELETE CASCADE,
    version_name text NOT NULL DEFAULT 'v1',
    source text NOT NULL DEFAULT 'manual'
        CHECK (source IN ('manual','upload_parse','reparse','import')),
    content jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_resume_versions_resume_id
    ON public.resume_versions(resume_id);

-- ---------------------------------------------------------------------------
-- RLS policies
-- ---------------------------------------------------------------------------
ALTER TABLE public.resumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.resume_versions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own resumes"
    ON public.resumes FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own resumes"
    ON public.resumes FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own resumes"
    ON public.resumes FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own resumes"
    ON public.resumes FOR DELETE
    USING (auth.uid() = user_id);

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

-- ---------------------------------------------------------------------------
-- updated_at trigger
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_resumes_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_resumes_updated_at ON public.resumes;
CREATE TRIGGER trg_resumes_updated_at
    BEFORE UPDATE ON public.resumes
    FOR EACH ROW EXECUTE FUNCTION public.set_resumes_updated_at();
