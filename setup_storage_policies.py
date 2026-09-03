"""Create storage RLS policies for the resumes bucket."""
import httpx
import os

from app.config import get_settings

settings = get_settings()

headers = {
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type": "application/json",
}

project_ref = "wjayvttrifpqtjloeunc"

sql = """
-- Storage RLS policies for resumes bucket
-- Ensure RLS is enabled on storage.objects
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;

-- Policy: Users can upload to their own user_id/ folder in the resumes bucket
CREATE POLICY "Allow users to upload resumes"
ON storage.objects
FOR INSERT
TO authenticated
WITH CHECK (
    bucket_id = 'resumes' AND
    auth.uid()::text = SPLIT_PART(name, '/', 1)
);

-- Policy: Users can read their own files
CREATE POLICY "Allow users to read own resumes"
ON storage.objects
FOR SELECT
TO authenticated
USING (
    bucket_id = 'resumes' AND
    auth.uid()::text = SPLIT_PART(name, '/', 1)
);

-- Policy: Users can update their own files
CREATE POLICY "Allow users to update own resumes"
ON storage.objects
FOR UPDATE
TO authenticated
USING (
    bucket_id = 'resumes' AND
    auth.uid()::text = SPLIT_PART(name, '/', 1)
)
WITH CHECK (
    bucket_id = 'resumes' AND
    auth.uid()::text = SPLIT_PART(name, '/', 1)
);

-- Policy: Users can delete their own files
CREATE POLICY "Allow users to delete own resumes"
ON storage.objects
FOR DELETE
TO authenticated
USING (
    bucket_id = 'resumes' AND
    auth.uid()::text = SPLIT_PART(name, '/', 1)
);
"""

print("Attempting Management API SQL execution...")
try:
    resp = httpx.post(
        f"https://api.supabase.com/v1/projects/{project_ref}/sql",
        headers=headers,
        json={"query": sql},
        timeout=30,
    )
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text[:500]}")
except Exception as e:
    print(f"Error: {e}")
