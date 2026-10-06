-- Migration 037: Evidence Bank for truthful resume generation
-- Schema: evidence_items (user_id, type, title, content, origin, user_verified)
--         bullet_evidence (version_id, bullet_ref, evidence_id)
-- Security: Owner-only RLS on all user tables.

CREATE TABLE IF NOT EXISTS public.evidence_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('experience', 'project', 'tool', 'metric', 'coursework', 'certification', 'achievement')),
    title TEXT NOT NULL,
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    origin TEXT NOT NULL CHECK (origin IN ('resume_import', 'user_entered')),
    user_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_evidence_items_user_id ON public.evidence_items(user_id);
CREATE INDEX IF NOT EXISTS idx_evidence_items_type ON public.evidence_items(type);
CREATE INDEX IF NOT EXISTS idx_evidence_items_origin ON public.evidence_items(origin);

-- Owner-only RLS for evidence_items
ALTER TABLE public.evidence_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users own their evidence items" ON public.evidence_items;
CREATE POLICY "Users own their evidence items"
    ON public.evidence_items
    FOR ALL
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Bullet citations: Every generated bullet must cite >=1 evidence id
CREATE TABLE IF NOT EXISTS public.bullet_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id UUID NOT NULL REFERENCES public.resume_versions(id) ON DELETE CASCADE,
    bullet_ref TEXT NOT NULL,
    evidence_id UUID NOT NULL REFERENCES public.evidence_items(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT uq_bullet_evidence_ref_item UNIQUE (version_id, bullet_ref, evidence_id)
);

CREATE INDEX IF NOT EXISTS idx_bullet_evidence_version ON public.bullet_evidence(version_id);
CREATE INDEX IF NOT EXISTS idx_bullet_evidence_item ON public.bullet_evidence(evidence_id);

-- Owner-only RLS for bullet_evidence through resume_versions -> resumes -> user_id
ALTER TABLE public.bullet_evidence ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users own their bullet evidence" ON public.bullet_evidence;
CREATE POLICY "Users own their bullet evidence"
    ON public.bullet_evidence
    FOR ALL
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.resume_versions rv
            JOIN public.resumes r ON r.id = rv.resume_id
            WHERE rv.id = bullet_evidence.version_id AND r.user_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.resume_versions rv
            JOIN public.resumes r ON r.id = rv.resume_id
            WHERE rv.id = bullet_evidence.version_id AND r.user_id = auth.uid()
        )
    );
