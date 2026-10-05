from app.db.supabase import get_service_client
from collections import defaultdict

client = get_service_client()

# Get all jobs
result = client.table('jobs').select('external_job_id, source_platform, id').execute()
if result.data:
    seen = defaultdict(list)
    for row in result.data:
        key = (row['external_job_id'], row['source_platform'])
        seen[key].append(row['id'])
    
    # Find duplicates (more than one job with same external_job_id + source_platform)
    duplicates = {k: v for k, v in seen.items() if len(v) > 1}
    
    if duplicates:
        print(f"FOUND {len(duplicates)} duplicate combinations:")
        for key, ids in list(duplicates.items())[:5]:
            print(f"  {key}: {ids}")
    else:
        print("No duplicate external_job_id + source_platform combinations found")
        print(f"Total unique combinations: {len(seen)}")
else:
    print("No jobs found")
