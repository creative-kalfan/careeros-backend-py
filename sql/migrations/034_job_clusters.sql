-- Migration 034: Job Duplicate Clusters
-- Idempotent, safe migration with service-role-only RLS policies

BEGIN;

CREATE TABLE IF NOT EXISTS public.job_clusters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_key TEXT NOT NULL UNIQUE,
    preferred_job_id UUID REFERENCES public.jobs(id) ON DELETE SET NULL,
    member_count INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_job_clusters_cluster_key
    ON public.job_clusters (cluster_key);

CREATE INDEX IF NOT EXISTS idx_job_clusters_preferred_job
    ON public.job_clusters (preferred_job_id);

ALTER TABLE public.job_clusters ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS job_clusters_service_role_all ON public.job_clusters;
CREATE POLICY job_clusters_service_role_all ON public.job_clusters
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

CREATE TABLE IF NOT EXISTS public.job_cluster_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id UUID NOT NULL REFERENCES public.job_clusters(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
    reason TEXT NOT NULL CHECK (reason IN ('identical_canonical_url', 'identical_identity_and_content_hash')),
    confidence NUMERIC(3, 2) NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cluster_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_job_cluster_members_job
    ON public.job_cluster_members (job_id);

CREATE INDEX IF NOT EXISTS idx_job_cluster_members_cluster
    ON public.job_cluster_members (cluster_id);

ALTER TABLE public.job_cluster_members ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS job_cluster_members_service_role_all ON public.job_cluster_members;
CREATE POLICY job_cluster_members_service_role_all ON public.job_cluster_members
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

COMMIT;
