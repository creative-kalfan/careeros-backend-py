-- Migration 039: Phase 6 Product Features
-- Market snapshots, Application analytics extensions, Notification outbox, Referral connections.

BEGIN;

-- 1. Extend applications table for analytics & version attribution
ALTER TABLE public.applications
    ADD COLUMN IF NOT EXISTS resume_version_id UUID REFERENCES public.resume_versions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS stage_timestamps JSONB DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS applications_resume_version_id_idx ON public.applications (resume_version_id);

-- 2. Market Snapshots table (daily aggregate snapshots)
CREATE TABLE IF NOT EXISTS public.market_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_date DATE NOT NULL,
    role_family TEXT NOT NULL,
    sample_size INT NOT NULL,
    top_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
    fresher_internship_share NUMERIC DEFAULT 0,
    top_locations JSONB NOT NULL DEFAULT '[]'::jsonb,
    salary_stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    weekly_trend JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT market_snapshots_date_family_key UNIQUE (snapshot_date, role_family)
);

CREATE INDEX IF NOT EXISTS market_snapshots_date_idx ON public.market_snapshots (snapshot_date DESC);
CREATE INDEX IF NOT EXISTS market_snapshots_family_idx ON public.market_snapshots (role_family);

ALTER TABLE public.market_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Public read market_snapshots" ON public.market_snapshots;
CREATE POLICY "Public read market_snapshots" ON public.market_snapshots FOR SELECT USING (true);
DROP POLICY IF EXISTS "Service role write market_snapshots" ON public.market_snapshots;
CREATE POLICY "Service role write market_snapshots" ON public.market_snapshots FOR ALL USING (auth.role() = 'service_role');

-- 3. Notification Outbox table (reliable multi-channel alerts surviving restarts)
CREATE TABLE IF NOT EXISTS public.notification_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    channel TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- pending, sent, failed, discarded
    attempts INT NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS notification_outbox_status_idx ON public.notification_outbox (status, attempts);
CREATE INDEX IF NOT EXISTS notification_outbox_user_idx ON public.notification_outbox (user_id);

ALTER TABLE public.notification_outbox ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users can read own notification outbox" ON public.notification_outbox;
CREATE POLICY "Users can read own notification outbox" ON public.notification_outbox FOR SELECT USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Service role manage notification outbox" ON public.notification_outbox;
CREATE POLICY "Service role manage notification outbox" ON public.notification_outbox FOR ALL USING (auth.role() = 'service_role');

-- 4. Referral Connections table (LinkedIn CSV upload with privacy protection)
CREATE TABLE IF NOT EXISTS public.referral_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    name TEXT NOT NULL,
    company TEXT NOT NULL,
    position TEXT,
    connected_on DATE,
    profile_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS referral_connections_user_company_idx ON public.referral_connections (user_id, company);
CREATE INDEX IF NOT EXISTS referral_connections_user_id_idx ON public.referral_connections (user_id);

ALTER TABLE public.referral_connections ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own referral connections" ON public.referral_connections;
CREATE POLICY "Users manage own referral connections" ON public.referral_connections FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

COMMIT;
