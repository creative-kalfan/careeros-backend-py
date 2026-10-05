from app.db.supabase import get_service_client

client = get_service_client()

# Pick a real existing job from Greenhouse/Stripe for freshness verification
result = client.table('jobs').select('id, external_job_id, source_platform, last_seen_at, updated_at, title, company').eq('source_platform', 'greenhouse').limit(1).execute()
if result.data:
    job = result.data[0]
    print("BEFORE CRAWL:")
    print(f"  job_id: {job['id']}")
    print(f"  external_job_id: {job['external_job_id']}")
    print(f"  source_platform: {job['source_platform']}")
    print(f"  last_seen_at: {job['last_seen_at']}")
    print(f"  updated_at: {job['updated_at']}")
    print(f"  title: {job['title'][:60]}...")
    print(f"  company: {job['company']}")
else:
    print("No Greenhouse jobs found")
