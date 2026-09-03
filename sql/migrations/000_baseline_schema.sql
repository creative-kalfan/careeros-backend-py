-- ============================================================================
-- CareerOS — Migration 000: Foundational Baseline Schema
-- ============================================================================
-- Purpose:
-- Establishes the foundational schema objects originally created in the legacy
-- environment (profiles, jobs, applications, notifications, recommendations,
-- etc.) before Python backend delta migrations (001-017) execute.
--
-- Safety & Idempotency:
-- All statements use IF NOT EXISTS / IF EXISTS guards.
-- Safe to execute against:
--   1. A clean database (creates all foundational tables, types, triggers, RLS)
--   2. An existing production database (idempotent no-op, preserves existing data)
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- 2. Auth & Storage compatibility schemas (for non-Supabase / local test DBs)
-- In live Supabase, these schemas and tables already exist.
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS storage;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS auth.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE,
    raw_user_meta_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE OR REPLACE FUNCTION auth.uid()
RETURNS UUID AS $$
    SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$ LANGUAGE sql STABLE;

CREATE TABLE IF NOT EXISTS storage.buckets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    public BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS storage.objects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bucket_id TEXT REFERENCES storage.buckets(id),
    name TEXT,
    owner UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    last_accessed_at TIMESTAMPTZ DEFAULT now(),
    metadata JSONB DEFAULT '{}'::jsonb
);
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION storage.foldername(name TEXT)
RETURNS TEXT[] AS $$
    SELECT string_to_array(name, '/');
$$ LANGUAGE sql IMMUTABLE;


-- ---------------------------------------------------------------------------
-- 3. Profiles table (extends auth.users)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    name TEXT,
    email TEXT NOT NULL,
    avatar TEXT,
    full_name TEXT,
    avatar_url TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    phone TEXT,
    location TEXT,
    "current_role" TEXT,
    "desired_role" TEXT,
    preferred_locations JSONB DEFAULT '[]'::jsonb,
    remote_preference TEXT CHECK (remote_preference IN ('remote', 'hybrid', 'onsite', 'any')),
    experience JSONB DEFAULT '[]'::jsonb,
    education JSONB DEFAULT '[]'::jsonb,
    skills JSONB DEFAULT '[]'::jsonb,
    preferred_companies JSONB DEFAULT '[]'::jsonb,
    salary_expectation_min INTEGER,
    salary_expectation_max INTEGER,
    salary_currency TEXT DEFAULT 'USD',
    notice_period TEXT,
    notice_period_days INTEGER,
    onboarding_completed BOOLEAN NOT NULL DEFAULT false,
    onboarding_step INTEGER NOT NULL DEFAULT 0,
    headline TEXT,
    linkedin_url TEXT,
    github_url TEXT,
    portfolio_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'profiles_role_check'
    ) THEN
        ALTER TABLE public.profiles
            ADD CONSTRAINT profiles_role_check CHECK (role IN ('user', 'admin'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS profiles_role_idx ON public.profiles (role);

-- Auto-create profile trigger function
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profiles (id, name, email, avatar, full_name, avatar_url, role, created_at, updated_at)
    VALUES (
        NEW.id,
        COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.raw_user_meta_data->>'name', split_part(COALESCE(NEW.email, ''), '@', 1), 'User'),
        COALESCE(NEW.email, ''),
        NEW.raw_user_meta_data->>'avatar_url',
        COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.raw_user_meta_data->>'name'),
        NEW.raw_user_meta_data->>'avatar_url',
        'user',
        now(),
        now()
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ---------------------------------------------------------------------------
-- 4. Jobs table (base schema)
-- Freshness and ingestion columns are extended by migrations 011, 013, 016.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    description TEXT,
    url TEXT,
    source TEXT,
    posted_at TIMESTAMPTZ,
    role_category TEXT,
    application_deadline DATE,
    is_active BOOLEAN NOT NULL DEFAULT true,
    source_platform TEXT,
    external_job_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_company_idx ON public.jobs (company);

-- ---------------------------------------------------------------------------
-- 5. Applications table & status enum
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE public.application_status AS ENUM (
        'applied', 'assessment', 'interview', 'offer', 'rejected'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
    job_title TEXT NOT NULL,
    company_name TEXT NOT NULL,
    status public.application_status NOT NULL DEFAULT 'applied',
    application_date DATE NOT NULL DEFAULT CURRENT_DATE,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS applications_user_id_idx ON public.applications (user_id);

-- ---------------------------------------------------------------------------
-- 6. Work Experiences table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.work_experiences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    start_date DATE,
    end_date DATE,
    current BOOLEAN NOT NULL DEFAULT false,
    description TEXT,
    achievements JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS work_experiences_user_id_idx ON public.work_experiences (user_id);

-- ---------------------------------------------------------------------------
-- 7. Education Entries table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.education_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
    institution TEXT NOT NULL,
    degree TEXT,
    field_of_study TEXT,
    start_date DATE,
    end_date DATE,
    current BOOLEAN NOT NULL DEFAULT false,
    grade TEXT,
    activities TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS education_entries_user_id_idx ON public.education_entries (user_id);

-- ---------------------------------------------------------------------------
-- 8. Preferred Companies table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.preferred_companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, company_name)
);

CREATE INDEX IF NOT EXISTS preferred_companies_user_id_idx ON public.preferred_companies (user_id);

-- ---------------------------------------------------------------------------
-- 9. Notifications table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    message TEXT,
    type TEXT NOT NULL DEFAULT 'info',
    is_read BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS notifications_user_id_idx ON public.notifications (user_id);
CREATE INDEX IF NOT EXISTS notifications_unread_idx ON public.notifications (user_id, is_read);

-- ---------------------------------------------------------------------------
-- 10. Recommendations table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
    job_id TEXT,
    match_score INTEGER NOT NULL DEFAULT 0,
    priority TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS recommendations_user_id_idx ON public.recommendations (user_id);

-- ---------------------------------------------------------------------------
-- 11. Saved Jobs table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.saved_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES public.jobs (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, job_id)
);

CREATE INDEX IF NOT EXISTS saved_jobs_user_id_idx ON public.saved_jobs (user_id);

-- ---------------------------------------------------------------------------
-- 12. Notification Preferences table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.notification_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles (id) ON DELETE CASCADE UNIQUE,
    email_notifications BOOLEAN NOT NULL DEFAULT true,
    push_notifications BOOLEAN NOT NULL DEFAULT true,
    job_alerts BOOLEAN NOT NULL DEFAULT true,
    ats_updates BOOLEAN NOT NULL DEFAULT true,
    application_updates BOOLEAN NOT NULL DEFAULT true,
    marketing_emails BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 13. Company ATS Mapping table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.company_ats_mapping (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name TEXT NOT NULL,
    ats_platform TEXT,
    board_url TEXT,
    slug TEXT,
    confidence NUMERIC,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    jobs_found_at_verification INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_company_ats_mapping_company_name
    ON public.company_ats_mapping (company_name);

CREATE INDEX IF NOT EXISTS idx_company_ats_mapping_verified_at
    ON public.company_ats_mapping (verified_at);

-- ---------------------------------------------------------------------------
-- 14. ATS Reports table (legacy ATS schema)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.ats_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id UUID,
    job_description TEXT NOT NULL,
    ats_score INTEGER NOT NULL CHECK (ats_score >= 0 AND ats_score <= 100),
    skill_match_score INTEGER NOT NULL CHECK (skill_match_score >= 0 AND skill_match_score <= 100),
    keyword_match_score INTEGER NOT NULL CHECK (keyword_match_score >= 0 AND keyword_match_score <= 100),
    missing_skills JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommendations JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ats_reports_resume_id_idx ON public.ats_reports (resume_id);

-- ---------------------------------------------------------------------------
-- 15. Row Level Security & Policies
-- ---------------------------------------------------------------------------
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.work_experiences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.education_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.preferred_companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.recommendations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.saved_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notification_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.company_ats_mapping ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ats_reports ENABLE ROW LEVEL SECURITY;

-- Drop and recreate policies idempotently
DROP POLICY IF EXISTS "Users can view own profile" ON public.profiles;
CREATE POLICY "Users can view own profile"
    ON public.profiles FOR SELECT USING (auth.uid() = id);

DROP POLICY IF EXISTS "Users can update own profile" ON public.profiles;
CREATE POLICY "Users can update own profile"
    ON public.profiles FOR UPDATE USING (auth.uid() = id);

DROP POLICY IF EXISTS "Users manage own applications" ON public.applications;
CREATE POLICY "Users manage own applications"
    ON public.applications FOR ALL USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users manage own work experiences" ON public.work_experiences;
CREATE POLICY "Users manage own work experiences"
    ON public.work_experiences FOR ALL USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users manage own education entries" ON public.education_entries;
CREATE POLICY "Users manage own education entries"
    ON public.education_entries FOR ALL USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users manage own preferred companies" ON public.preferred_companies;
CREATE POLICY "Users manage own preferred companies"
    ON public.preferred_companies FOR ALL USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users manage own notifications" ON public.notifications;
CREATE POLICY "Users manage own notifications"
    ON public.notifications FOR ALL USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users manage own recommendations" ON public.recommendations;
CREATE POLICY "Users manage own recommendations"
    ON public.recommendations FOR ALL USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can view jobs" ON public.jobs;
CREATE POLICY "Users can view jobs"
    ON public.jobs FOR SELECT USING (true);

DROP POLICY IF EXISTS "Users manage own saved jobs" ON public.saved_jobs;
CREATE POLICY "Users manage own saved jobs"
    ON public.saved_jobs FOR ALL USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users manage own notification preferences" ON public.notification_preferences;
CREATE POLICY "Users manage own notification preferences"
    ON public.notification_preferences FOR ALL USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Authenticated users can read company_ats_mapping" ON public.company_ats_mapping;
CREATE POLICY "Authenticated users can read company_ats_mapping"
    ON public.company_ats_mapping FOR SELECT USING (true);

-- ---------------------------------------------------------------------------
-- 16. Storage Buckets
-- ---------------------------------------------------------------------------
INSERT INTO storage.buckets (id, name, public)
VALUES ('resumes', 'resumes', false)
ON CONFLICT (id) DO NOTHING;

INSERT INTO storage.buckets (id, name, public)
VALUES ('avatars', 'avatars', true)
ON CONFLICT (id) DO NOTHING;
