-- ============================================================================
-- Resume Module — Step 2: Template Registry
-- ============================================================================

-- ---------------------------------------------------------------------------
-- resume_templates table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.resume_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE,
    name text NOT NULL,
    description text,
    source_repository text,
    source_url text,
    author text,
    license text,
    license_url text,
    attribution_required boolean NOT NULL DEFAULT false,
    modification_allowed boolean NOT NULL DEFAULT true,
    redistribution_allowed boolean NOT NULL DEFAULT true,
    layout_type text NOT NULL DEFAULT 'single-column',
    column_count integer NOT NULL DEFAULT 1,
    page_preference text NOT NULL DEFAULT 'one-page'
        CHECK (page_preference IN ('one-page','two-page','flexible')),
    ats_characteristics jsonb DEFAULT '{}'::jsonb,
    target_roles text[] NOT NULL DEFAULT '{}',
    target_industries text[] NOT NULL DEFAULT '{}',
    target_experience_levels text[] NOT NULL DEFAULT '{}',
    evidence_type text,
    evidence_description text,
    preview_url text,
    template_path text NOT NULL,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','deprecated','draft')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_resume_templates_slug
    ON public.resume_templates(slug);

CREATE INDEX IF NOT EXISTS idx_resume_templates_status
    ON public.resume_templates(status);

CREATE INDEX IF NOT EXISTS idx_resume_templates_layout_type
    ON public.resume_templates(layout_type);

-- ---------------------------------------------------------------------------
-- RLS policies (templates are publicly readable, admin-writable)
-- ---------------------------------------------------------------------------
ALTER TABLE public.resume_templates ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can view active templates"
    ON public.resume_templates FOR SELECT
    USING (status = 'active');

CREATE POLICY "Admins can insert templates"
    ON public.resume_templates FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM auth.users u
            WHERE u.id = auth.uid() AND u.raw_user_meta_data->>'role' = 'admin'
        )
    );

CREATE POLICY "Admins can update templates"
    ON public.resume_templates FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM auth.users u
            WHERE u.id = auth.uid() AND u.raw_user_meta_data->>'role' = 'admin'
        )
    );

CREATE POLICY "Admins can delete templates"
    ON public.resume_templates FOR DELETE
    USING (
        EXISTS (
            SELECT 1 FROM auth.users u
            WHERE u.id = auth.uid() AND u.raw_user_meta_data->>'role' = 'admin'
        )
    );

-- ---------------------------------------------------------------------------
-- updated_at trigger
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_resume_templates_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_resume_templates_updated_at ON public.resume_templates;
CREATE TRIGGER trg_resume_templates_updated_at
    BEFORE UPDATE ON public.resume_templates
    FOR EACH ROW EXECUTE FUNCTION public.set_resume_templates_updated_at();
