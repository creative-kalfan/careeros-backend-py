-- ============================================================================
-- Resume Module — Storage RLS Policies for the `resumes` bucket
--
-- The bucket itself must be created as PRIVATE in the Supabase dashboard
-- (or via an existing admin migration).  These policies enforce that a user
-- can only upload/read objects inside their own folder:
--
--     {auth.uid()}/{uuid}.{ext}
--
-- We use storage.foldername(name) so that the first folder in the object
-- path is compared against the authenticated user's id.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. Ensure the bucket exists and is private.
--    This is idempotent: it will not change an existing bucket's settings.
-- ---------------------------------------------------------------------------
INSERT INTO storage.buckets (id, name, public)
VALUES ('resumes', 'resumes', false)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. INSERT policy: a user may upload only into their own first-level folder.
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS "Users can insert own resume objects"
    ON storage.objects;

CREATE POLICY "Users can insert own resume objects"
    ON storage.objects FOR INSERT
    TO authenticated
    WITH CHECK (
        bucket_id = 'resumes'
        AND (storage.foldername(name))[1] = auth.uid()::text
    );

-- ---------------------------------------------------------------------------
-- 3. SELECT/download policy: a user may only read objects in their own folder.
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS "Users can select own resume objects"
    ON storage.objects;

CREATE POLICY "Users can select own resume objects"
    ON storage.objects FOR SELECT
    TO authenticated
    USING (
        bucket_id = 'resumes'
        AND (storage.foldername(name))[1] = auth.uid()::text
    );

-- ---------------------------------------------------------------------------
-- 4. UPDATE policy: a user may only update objects in their own folder.
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS "Users can update own resume objects"
    ON storage.objects;

CREATE POLICY "Users can update own resume objects"
    ON storage.objects FOR UPDATE
    TO authenticated
    USING (
        bucket_id = 'resumes'
        AND (storage.foldername(name))[1] = auth.uid()::text
    );

-- ---------------------------------------------------------------------------
-- 5. DELETE policy: a user may only remove objects in their own folder.
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS "Users can delete own resume objects"
    ON storage.objects;

CREATE POLICY "Users can delete own resume objects"
    ON storage.objects FOR DELETE
    TO authenticated
    USING (
        bucket_id = 'resumes'
        AND (storage.foldername(name))[1] = auth.uid()::text
    );