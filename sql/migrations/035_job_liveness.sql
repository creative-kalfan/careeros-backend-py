-- Migration 035: Job Liveness & Ghost Risk Signals
-- Idempotent, safe migration with service-role-only RLS policies

BEGIN;

CREATE TABLE IF NOT EXISTS public.job_liveness (
    job_id UUID PRIMARY KEY REFERENCES public.jobs(id) ON DELETE CASCADE,
    last_verified_live_at TIMESTAMPTZ,
    verified_ats_source TEXT,
    liveness_status TEXT NOT NULL DEFAULT 'unknown' CHECK (liveness_status IN ('verified_live', 'active_unverified', 'stale', 'closed', 'unknown')),
    ghost_risk_score INT NOT NULL DEFAULT 0 CHECK (ghost_risk_score >= 0 AND ghost_risk_score <= 100),
    ghost_signals JSONB NOT NULL DEFAULT '{}'::jsonb,
    apply_url_status TEXT,
    apply_url_checked_at TIMESTAMPTZ,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_job_liveness_status
    ON public.job_liveness (liveness_status);

CREATE INDEX IF NOT EXISTS idx_job_liveness_ghost_risk
    ON public.job_liveness (ghost_risk_score);

CREATE INDEX IF NOT EXISTS idx_job_liveness_checked
    ON public.job_liveness (apply_url_checked_at);

ALTER TABLE public.job_liveness ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS job_liveness_service_role_all ON public.job_liveness;
CREATE POLICY job_liveness_service_role_all ON public.job_liveness
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

COMMIT;
