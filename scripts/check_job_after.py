from app.db.supabase import get_service_client

client = get_service_client()

# Check the same job after the crawl
job_id = 'e8a6d312-3fb8-4a67-ad8a-6d87ed2be462'
result = client.table('jobs').select('id, external_job_id, source_platform, last_seen_at, updated_at, title, company').eq('id', job_id).execute()
if result.data:
    job = result.data[0]
    print("AFTER CRAWL:")
    print(f"  job_id: {job['id']}")
    print(f"  external_job_id: {job['external_job_id']}")
    print(f"  source_platform: {job['source_platform']}")
    print(f"  last_seen_at: {job['last_seen_at']}")
    print(f"  updated_at: {job['updated_at']}")
    print(f"  title: {job['title'][:60]}...")
    print(f"  company: {job['company']}")
else:
    print("Job not found")
