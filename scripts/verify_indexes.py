from app.db.supabase import get_service_client

client = get_service_client()

# Try to query using the indexes to verify they exist
# Index 1: idx_jobs_last_seen_at
result = client.table('jobs').select('id, last_seen_at').order('last_seen_at', desc=True).limit(3).execute()
print('Ordered by last_seen_at (uses idx_jobs_last_seen_at):')
for row in result.data or []:
    print(f"  {row['id'][:8]}... {row['last_seen_at']}")

# Index 2: idx_jobs_is_active_posted_at (partial index on is_active=true)
result2 = client.table('jobs').select('id, posted_at').eq('is_active', True).order('posted_at', desc=True).limit(3).execute()
print('\nActive jobs ordered by posted_at (uses idx_jobs_is_active_posted_at):')
for row in result2.data or []:
    print(f"  {row['id'][:8]}... {row['posted_at']}")
