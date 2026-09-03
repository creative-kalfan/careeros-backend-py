-- ============================================================================
-- Proposal Review & Approval Workflow — Target 5.4
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.proposal_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id UUID NOT NULL REFERENCES public.resumes(id) ON DELETE CASCADE,
    report_id UUID NOT NULL,
    proposal_id TEXT NOT NULL,
    requirement_id TEXT NOT NULL,
    decision TEXT NOT NULL DEFAULT 'pending',
    eligibility TEXT NOT NULL DEFAULT 'eligible',
    eligibility_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    target_section TEXT,
    target_entry_id TEXT,
    original_text TEXT,
    proposed_wording TEXT,
    rationale TEXT,
    diff_summary TEXT,
    metrics_prompt TEXT,
    provenance TEXT,
    evidence_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_candidate_evidence BOOLEAN NOT NULL DEFAULT FALSE,
    safety_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence FLOAT NOT NULL DEFAULT 0.0,
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_report_proposal UNIQUE (report_id, proposal_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_proposal_decisions_resume_id
    ON public.proposal_decisions(resume_id);

CREATE INDEX IF NOT EXISTS idx_proposal_decisions_report_id
    ON public.proposal_decisions(report_id);

CREATE INDEX IF NOT EXISTS idx_proposal_decisions_decision
    ON public.proposal_decisions(decision);

-- Row Level Security
ALTER TABLE public.proposal_decisions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own proposal decisions"
    ON public.proposal_decisions
    FOR SELECT
    USING (
        resume_id IN (
            SELECT id FROM public.resumes WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can insert own proposal decisions"
    ON public.proposal_decisions
    FOR INSERT
    WITH CHECK (
        resume_id IN (
            SELECT id FROM public.resumes WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can update own proposal decisions"
    ON public.proposal_decisions
    FOR UPDATE
    USING (
        resume_id IN (
            SELECT id FROM public.resumes WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can delete own proposal decisions"
    ON public.proposal_decisions
    FOR DELETE
    USING (
        resume_id IN (
            SELECT id FROM public.resumes WHERE user_id = auth.uid()
        )
    );
