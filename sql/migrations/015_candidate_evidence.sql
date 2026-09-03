-- ============================================================================
-- Candidate Evidence table — Target 5.2
-- Backfills the table assumed by CandidateEvidenceRepository. Without it the
-- GET /api/improvement/resumes/{id}/candidate-evidence endpoint raises an
-- unhandled PostgREST PGRST205 error (404) which surfaces in the browser as a
-- header-less "CORS" failure.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.candidate_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id UUID NOT NULL REFERENCES public.resumes(id) ON DELETE CASCADE,
    requirement_id TEXT NOT NULL,
    requirement TEXT,
    has_evidence BOOLEAN NOT NULL DEFAULT FALSE,
    provenance TEXT,
    context JSONB,
    raw_description TEXT,
    candidate_claim TEXT,
    additional_details TEXT,
    status TEXT NOT NULL DEFAULT 'confirmed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_candidate_evidence_resume_requirement UNIQUE (resume_id, requirement_id)
);

CREATE INDEX IF NOT EXISTS idx_candidate_evidence_resume_id
    ON public.candidate_evidence(resume_id);

CREATE INDEX IF NOT EXISTS idx_candidate_evidence_requirement_id
    ON public.candidate_evidence(requirement_id);

-- ---------------------------------------------------------------------------
-- RLS: users can only read/write evidence attached to their own resumes.
-- ---------------------------------------------------------------------------

ALTER TABLE public.candidate_evidence ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can read own candidate evidence" ON public.candidate_evidence;
CREATE POLICY "Users can read own candidate evidence" ON public.candidate_evidence
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.resumes r
            WHERE r.id = candidate_evidence.resume_id
              AND r.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS "Users can insert own candidate evidence" ON public.candidate_evidence;
CREATE POLICY "Users can insert own candidate evidence" ON public.candidate_evidence
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.resumes r
            WHERE r.id = candidate_evidence.resume_id
              AND r.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS "Users can update own candidate evidence" ON public.candidate_evidence;
CREATE POLICY "Users can update own candidate evidence" ON public.candidate_evidence
    FOR UPDATE USING (
        EXISTS (
            SELECT 1 FROM public.resumes r
            WHERE r.id = candidate_evidence.resume_id
              AND r.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS "Users can delete own candidate evidence" ON public.candidate_evidence;
CREATE POLICY "Users can delete own candidate evidence" ON public.candidate_evidence
    FOR DELETE USING (
        EXISTS (
            SELECT 1 FROM public.resumes r
            WHERE r.id = candidate_evidence.resume_id
              AND r.user_id = auth.uid()
        )
    );
