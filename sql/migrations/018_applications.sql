
-- ============================================================================
-- 018: Application Tracking / Mission Control
--
-- Turns the legacy `applications` table (a single status + title/company row)
-- into a proper application-lifecycle domain and adds the child entities the
-- Mission Control UI consumes (interviews, assessments, contacts, follow-ups,
-- timeline events, attachments).
--
-- Changes to `applications`:
--   * status relaxes from the `application_status` ENUM to TEXT so new lifecycle
--     statuses (saved, to_apply, screening, accepted, withdrawn) are accepted
--     without painful ENUM ALTERs. Existing values are preserved verbatim.
--   * New columns: job_id (FK, SET NULL), company_id, location, salary,
--     match_score, favorite, archived, source_url, source_platform,
--     external_job_id, created_at, updated_at.
--
-- Child tables all key off `application_id` with ON DELETE CASCADE and carry
-- RLS policies scoped through the parent application's owner (auth.uid()).
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Widen the status column to TEXT (preserves existing enum values).
-- ---------------------------------------------------------------------------
ALTER TABLE public.applications
    ALTER COLUMN status TYPE TEXT USING status::text;

-- ---------------------------------------------------------------------------
-- 2. Extend the applications table.
-- ---------------------------------------------------------------------------
ALTER TABLE public.applications
    ADD COLUMN IF NOT EXISTS job_id          UUID REFERENCES public.jobs (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS company_id      TEXT,
    ADD COLUMN IF NOT EXISTS location        TEXT,
    ADD COLUMN IF NOT EXISTS salary          TEXT,
    ADD COLUMN IF NOT EXISTS match_score     INTEGER,
    ADD COLUMN IF NOT EXISTS favorite        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS archived        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS source_url      TEXT,
    ADD COLUMN IF NOT EXISTS source_platform TEXT,
    ADD COLUMN IF NOT EXISTS external_job_id TEXT,
    ADD COLUMN IF NOT EXISTS created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS applications_job_id_idx       ON public.applications (job_id);
CREATE INDEX IF NOT EXISTS applications_user_status_idx ON public.applications (user_id, status);
CREATE INDEX IF NOT EXISTS applications_user_fav_idx     ON public.applications (user_id, favorite);
CREATE INDEX IF NOT EXISTS applications_user_arch_idx    ON public.applications (user_id, archived);

-- ---------------------------------------------------------------------------
-- 3. Application Interviews
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.application_interviews (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL REFERENCES public.applications (id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    scheduled_at   TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'scheduled',
    interviewer    TEXT,
    notes          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS application_interviews_app_idx
    ON public.application_interviews (application_id, scheduled_at);

-- ---------------------------------------------------------------------------
-- 4. Application Assessments
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.application_assessments (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL REFERENCES public.applications (id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    due_at         TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'pending',
    notes          TEXT,
    result         TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS application_assessments_app_idx
    ON public.application_assessments (application_id, due_at);
-- ---------------------------------------------------------------------------
-- 5. Application Contacts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.application_contacts (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL REFERENCES public.applications (id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    role           TEXT,
    email          TEXT,
    phone          TEXT,
    notes          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS application_contacts_app_idx
    ON public.application_contacts (application_id);

-- ---------------------------------------------------------------------------
-- 6. Application Follow-ups
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.application_follow_ups (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL REFERENCES public.applications (id) ON DELETE CASCADE,
    title          TEXT NOT NULL,
    due_at         TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'pending',
    notes          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS application_follow_ups_app_idx
    ON public.application_follow_ups (application_id, due_at);

-- ---------------------------------------------------------------------------
-- 7. Application Timeline Events
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.application_events (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL REFERENCES public.applications (id) ON DELETE CASCADE,
    event_type     TEXT NOT NULL,
    title          TEXT NOT NULL,
    detail         TEXT,
    metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS application_events_app_created_idx
    ON public.application_events (application_id, created_at);

-- ---------------------------------------------------------------------------
-- 8. Application Attachments (references, not raw blobs)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.application_attachments (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL REFERENCES public.applications (id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'other',
    size_bytes     BIGINT,
    storage_path   TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS application_attachments_app_idx
    ON public.application_attachments (application_id);
-- ---------------------------------------------------------------------------
-- 9. Row Level Security
-- ---------------------------------------------------------------------------
-- Owner-based RLS for every child table. Ownership is resolved through the
-- parent application row, so a user can never touch another user's child rows
-- even if they know the child id. FKs cascade on parent delete.
-- ---------------------------------------------------------------------------
ALTER TABLE public.applications ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.application_interviews   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_assessments  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_contacts     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_follow_ups   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_events       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_attachments  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users manage own applications" ON public.applications;
CREATE POLICY "Users manage own applications"
    ON public.applications FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users manage own application interviews" ON public.application_interviews;
CREATE POLICY "Users manage own application interviews"
    ON public.application_interviews FOR ALL
    USING (application_id IN (
        SELECT id FROM public.applications WHERE user_id = auth.uid()
    ))
    WITH CHECK (application_id IN (
        SELECT id FROM public.applications WHERE user_id = auth.uid()
    ));

DROP POLICY IF EXISTS "Users manage own application assessments" ON public.application_assessments;
CREATE POLICY "Users manage own application assessments"
    ON public.application_assessments FOR ALL
    USING (application_id IN (
        SELECT id FROM public.applications WHERE user_id = auth.uid()
    ))
    WITH CHECK (application_id IN (
        SELECT id FROM public.applications WHERE user_id = auth.uid()
    ));

DROP POLICY IF EXISTS "Users manage own application contacts" ON public.application_contacts;
CREATE POLICY "Users manage own application contacts"
    ON public.application_contacts FOR ALL
    USING (application_id IN (
        SELECT id FROM public.applications WHERE user_id = auth.uid()
    ))
    WITH CHECK (application_id IN (
        SELECT id FROM public.applications WHERE user_id = auth.uid()
    ));

DROP POLICY IF EXISTS "Users manage own application follow-ups" ON public.application_follow_ups;
CREATE POLICY "Users manage own application follow-ups"
    ON public.application_follow_ups FOR ALL
    USING (application_id IN (
        SELECT id FROM public.applications WHERE user_id = auth.uid()
    ))
    WITH CHECK (application_id IN (
        SELECT id FROM public.applications WHERE user_id = auth.uid()
    ));

DROP POLICY IF EXISTS "Users manage own application events" ON public.application_events;
CREATE POLICY "Users manage own application events"
    ON public.application_events FOR ALL
    USING (application_id IN (
        SELECT id FROM public.applications WHERE user_id = auth.uid()
    ))
    WITH CHECK (application_id IN (
        SELECT id FROM public.applications WHERE user_id = auth.uid()
    ));

DROP POLICY IF EXISTS "Users manage own application attachments" ON public.application_attachments;
CREATE POLICY "Users manage own application attachments"
    ON public.application_attachments FOR ALL
    USING (application_id IN (
        SELECT id FROM public.applications WHERE user_id = auth.uid()
    ))
    WITH CHECK (application_id IN (
        SELECT id FROM public.applications WHERE user_id = auth.uid()
    ));

COMMIT;