-- Migration 038: LLM Cost Control & Usage Ledger
-- Tables: llm_usage (user_id, feature, model, tokens_in, tokens_out, cost_estimate_usd, created_at)
-- RLS: Owner can read own usage; service role can insert.

CREATE TABLE IF NOT EXISTS public.llm_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    feature TEXT NOT NULL,
    model TEXT NOT NULL,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cost_estimate_usd NUMERIC(10, 6) NOT NULL DEFAULT 0.000000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_user_id ON public.llm_usage(user_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at ON public.llm_usage(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_feature ON public.llm_usage(feature);

ALTER TABLE public.llm_usage ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users read own LLM usage" ON public.llm_usage;
CREATE POLICY "Users read own LLM usage"
    ON public.llm_usage
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Service role manages LLM usage" ON public.llm_usage;
CREATE POLICY "Service role manages LLM usage"
    ON public.llm_usage
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
