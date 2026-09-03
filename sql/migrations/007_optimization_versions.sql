-- ============================================================================
-- Optimization tables — Step 6: version-aware optimization
-- ============================================================================

-- If these tables were created outside of migrations, add version_id support.
-- Adjust column names if they differ from the repository expectations.

ALTER TABLE IF EXISTS public.optimization_sessions
    ADD COLUMN IF NOT EXISTS version_id uuid REFERENCES public.resume_versions(id) ON DELETE CASCADE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = 'optimization_sessions'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_optimization_sessions_version_id
            ON public.optimization_sessions(version_id);
    END IF;
END $$;

