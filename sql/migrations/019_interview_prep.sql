
-- ============================================================================
-- 019: Interview Preparation
--
-- Adds the Interview Preparation vertical slice on top of Application Tracking:
--
--   * interview_prep_sessions  — one preparation session per application /
--     interview round. Tracks source context (resume version, JD fingerprint,
--     interview type) so the UI can detect stale preparation.
--   * interview_prep_questions — the generated, resume-grounded questions for
--     a session, with talking points, answer frameworks, JD mapping, and
--     per-question practice state (prepared / bookmarked).
--
-- Ownership is enforced through the parent application row (auth.uid()), the
-- same pattern as 018 child tables. Sessions additionally carry a direct
-- user_id so list queries stay single-`eq` (mock/RLS friendly).
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Interview prep sessions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.interview_prep_sessions (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                   UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    application_id            UUID NOT NULL REFERENCES public.applications (id) ON DELETE CASCADE,
    interview_id              UUID REFERENCES public.application_interviews (id) ON DELETE SET NULL,
    job_id                    UUID REFERENCES public.jobs (id) ON DELETE SET NULL,
    status                    TEXT NOT NULL DEFAULT 'generating'
                              CHECK (status IN ('generating', 'ready', 'failed')),
    interview_type            TEXT NOT NULL DEFAULT 'general',
    interview_name            TEXT,
    source_resume_id          UUID REFERENCES public.resumes (id) ON DELETE SET NULL,
    source_resume_version_id  TEXT,
    source_fingerprint        TEXT,
    source_metadata           JSONB NOT NULL DEFAULT '{}'::jsonb,
    question_count            INTEGER NOT NULL DEFAULT 0,
    prepared_count            INTEGER NOT NULL DEFAULT 0,
    version                   INTEGER NOT NULL DEFAULT 1,
    error                     TEXT,
    generated_at              TIMESTAMPTZ,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS interview_prep_sessions_user_idx
    ON public.interview_prep_sessions (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS interview_prep_sessions_app_idx
    ON public.interview_prep_sessions (application_id, created_at DESC);

CREATE INDEX IF NOT EXISTS interview_prep_sessions_interview_idx
    ON public.interview_prep_sessions (interview_id);

-- ---------------------------------------------------------------------------
-- 2. Interview prep questions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.interview_prep_questions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id              UUID NOT NULL REFERENCES public.interview_prep_sessions (id) ON DELETE CASCADE,
    category                TEXT NOT NULL CHECK (category IN (
                                'behavioral', 'technical', 'role_specific',
                                'resume_deep_dive', 'situational', 'company_context'
                            )),
    question                TEXT NOT NULL,
    difficulty              TEXT NOT NULL DEFAULT 'intermediate' CHECK (difficulty IN (
                                'foundational', 'intermediate', 'advanced'
                            )),
    rationale               TEXT,
    resume_evidence         JSONB NOT NULL DEFAULT '[]'::jsonb,
    talking_points          JSONB NOT NULL DEFAULT '[]'::jsonb,
    answer_framework        JSONB NOT NULL DEFAULT '{}'::jsonb,
    star_guidance           TEXT,
    expected_signals        JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_jd_requirements JSONB NOT NULL DEFAULT '[]'::jsonb,
    gaps                    JSONB NOT NULL DEFAULT '[]'::jsonb,
    question_order          INTEGER NOT NULL DEFAULT 0,
    is_prepared             BOOLEAN NOT NULL DEFAULT FALSE,
    is_bookmarked           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS interview_prep_questions_session_idx
    ON public.interview_prep_questions (session_id, question_order);

-- ---------------------------------------------------------------------------
-- 3. Row Level Security
-- ---------------------------------------------------------------------------
ALTER TABLE public.interview_prep_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.interview_prep_questions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users manage own interview prep sessions" ON public.interview_prep_sessions;
CREATE POLICY "Users manage own interview prep sessions"
    ON public.interview_prep_sessions FOR ALL
    USING (
        auth.uid() = user_id
        AND application_id IN (
            SELECT id FROM public.applications WHERE user_id = auth.uid()
        )
    )
    WITH CHECK (
        auth.uid() = user_id
        AND application_id IN (
            SELECT id FROM public.applications WHERE user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS "Users manage own interview prep questions" ON public.interview_prep_questions;
CREATE POLICY "Users manage own interview prep questions"
    ON public.interview_prep_questions FOR ALL
    USING (session_id IN (
        SELECT id FROM public.interview_prep_sessions WHERE user_id = auth.uid()
    ))
    WITH CHECK (session_id IN (
        SELECT id FROM public.interview_prep_sessions WHERE user_id = auth.uid()
    ));

COMMIT;
