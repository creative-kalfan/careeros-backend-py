-- Migration 040: Campus Mode and Public Profiles
-- Adds career_stage, graduating_year to profiles and public_profiles table for opt-in portfolio showcase.

BEGIN;

-- 1. Extend profiles with career_stage and graduating_year
ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS career_stage TEXT CHECK (career_stage IN ('student', 'fresher', 'experienced')),
    ADD COLUMN IF NOT EXISTS graduating_year INT;

CREATE INDEX IF NOT EXISTS profiles_career_stage_idx ON public.profiles (career_stage);

-- 2. Public Profiles table (opt-in public profile page with user-chosen slug)
CREATE TABLE IF NOT EXISTS public.public_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID UNIQUE NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    slug TEXT UNIQUE NOT NULL,
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    headline TEXT,
    bio TEXT,
    sections JSONB NOT NULL DEFAULT '{"skills": true, "education": true, "experience": true, "projects": true}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS public_profiles_slug_idx ON public.public_profiles (slug);
CREATE INDEX IF NOT EXISTS public_profiles_user_id_idx ON public.public_profiles (user_id);

ALTER TABLE public.public_profiles ENABLE ROW LEVEL SECURITY;

-- Anonymous and authenticated read when published
DROP POLICY IF EXISTS "Public read on published profiles" ON public.public_profiles;
CREATE POLICY "Public read on published profiles" ON public.public_profiles
    FOR SELECT USING (is_public = TRUE);

-- Users manage own public profile
DROP POLICY IF EXISTS "Users manage own public profile" ON public.public_profiles;
CREATE POLICY "Users manage own public profile" ON public.public_profiles
    FOR ALL USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

COMMIT;
