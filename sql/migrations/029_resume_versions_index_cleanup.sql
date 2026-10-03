-- ============================================================================
-- Resume Versions — Index cleanup (corrective, additive only)
-- ============================================================================
-- Corrects COMPLETE_SYSTEM §11.4: migration 006 created a misnamed duplicate
--   CREATE INDEX idx_resume_versions_user_id ON public.resume_versions(resume_id)
-- `resume_versions` has no `user_id` column (ownership flows via
-- `resumes.user_id`); the index duplicates `idx_resume_versions_resume_id`.
--
-- History invariant: 000-028 are immutable and already applied in production,
-- so the fix lives here as an idempotent additive migration (IF EXISTS /
-- IF NOT EXISTS guards, no data touches).
-- ============================================================================

DROP INDEX IF EXISTS public.idx_resume_versions_user_id;

CREATE INDEX IF NOT EXISTS idx_resume_versions_resume_id
    ON public.resume_versions(resume_id);
