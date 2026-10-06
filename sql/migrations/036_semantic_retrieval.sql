-- Migration 036: Semantic Retrieval & Job Embeddings
-- Feature flag: SEMANTIC_RETRIEVAL_ENABLED (default off)
-- Storage footprint estimate:
-- 10,000 active jobs x 768 dims x 4 bytes/float = ~30.7 MB (+ index overhead ~15 MB = ~45 MB total).
-- Well within Supabase free-tier limits (500 MB database).

-- 1. Enable pgvector extension (Supabase dashboard may require extension toggled on)
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Vector extension could not be enabled automatically: %', SQLERRM;
END $$;

-- 2. Create job_embeddings table if vector extension is present
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector') THEN
        CREATE TABLE IF NOT EXISTS public.job_embeddings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            job_id UUID NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
            model TEXT NOT NULL,
            dims INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            embedding vector(768),
            created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
            CONSTRAINT uq_job_embeddings_job_model UNIQUE (job_id, model)
        );

        -- 3. Service-role-only RLS
        ALTER TABLE public.job_embeddings ENABLE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS "Service role access on job_embeddings" ON public.job_embeddings;
        CREATE POLICY "Service role access on job_embeddings"
            ON public.job_embeddings
            FOR ALL
            TO service_role
            USING (true)
            WITH CHECK (true);

        -- 4. Vector index: Try HNSW first, fall back to ivfflat
        BEGIN
            CREATE INDEX IF NOT EXISTS idx_job_embeddings_vector_hnsw
                ON public.job_embeddings
                USING hnsw (embedding vector_cosine_ops);
        EXCEPTION
            WHEN OTHERS THEN
                CREATE INDEX IF NOT EXISTS idx_job_embeddings_vector_ivfflat
                    ON public.job_embeddings
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100);
        END;

        CREATE INDEX IF NOT EXISTS idx_job_embeddings_content_hash
            ON public.job_embeddings (content_hash);
        CREATE INDEX IF NOT EXISTS idx_job_embeddings_created_at
            ON public.job_embeddings (created_at DESC);
    ELSE
        RAISE NOTICE 'pgvector extension not installed; skipping table creation. Code will fail open.';
    END IF;
END $$;

-- 5. RPC for similarity search: top-K nearest neighbors
CREATE OR REPLACE FUNCTION match_job_embeddings(
    query_embedding vector(768),
    match_threshold float,
    match_count int,
    filter_active boolean DEFAULT true,
    filter_newer_than_days int DEFAULT 90
)
RETURNS TABLE (
    job_id UUID,
    similarity float
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT
        je.job_id,
        1 - (je.embedding <=> query_embedding) AS similarity
    FROM public.job_embeddings je
    JOIN public.jobs j ON j.id = je.job_id
    WHERE (filter_active IS FALSE OR j.is_active IS TRUE)
      AND (
          filter_newer_than_days IS NULL 
          OR j.posted_at >= (NOW() - (filter_newer_than_days || ' days')::interval)
          OR j.created_at >= (NOW() - (filter_newer_than_days || ' days')::interval)
      )
      AND (1 - (je.embedding <=> query_embedding)) >= match_threshold
    ORDER BY je.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
