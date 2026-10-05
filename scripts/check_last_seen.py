from app.db.supabase import get_service_client

client = get_service_client()

# Check jobs with last_seen_at populated using filter
result = client.table('jobs').select('id, last_seen_at, updated_at, source_platform').filter('last_seen_at', 'not.is', 'null').limit(5).execute()
print('Jobs with last_seen_at:')
for row in result.data or []:
    print(f"  ID: {row['id'][:8]}... Source: {row['source_platform']} Updated: {row['updated_at']} LastSeen: {row['last_seen_at']}")

# Count jobs with/without last_seen_at
total = client.table('jobs').select('id', count='exact').execute()
with_last_seen = client.table('jobs').select('id', count='exact').filter('last_seen_at', 'not.is', 'null').execute()
without_last_seen = client.table('jobs').select('id', count='exact').filter('last_seen_at', 'is', 'null').execute()

print(f'\nTotal jobs: {total.count}')
print(f'With last_seen_at: {with_last_seen.count}')
print(f'Without last_seen_at: {without_last_seen.count}')
