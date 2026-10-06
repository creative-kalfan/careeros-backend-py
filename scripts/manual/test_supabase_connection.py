"""Test Supabase connection and inspect jobs table state."""

from app.db.supabase import get_service_client
from app.repositories.job_repository import JobRepository

def test_supabase_connection():
    """Test if we can connect to Supabase and read the jobs table."""
    print("Testing Supabase connection...")

    try:
        # Test the service client
        client = get_service_client()
        print("✅ Service client created successfully")

        # Test reading jobs table
        result = client.table("jobs").select("*", count="exact").eq("is_active", True).execute()
        print(f"✅ Jobs table query executed successfully")

        jobs = result.data or []
        total = result.count or 0

        print(f"📊 Total active jobs: {total}")
        print(f"📊 Retrieved {len(jobs)} jobs")

        # Analyze the data
        if jobs:
            source_platforms = set(job.get("source_platform") for job in jobs)
            role_categories = set(job.get("role_category") for job in jobs if job.get("role_category"))
            external_ids = [(job.get("external_job_id"), job.get("source_platform")) for job in jobs]

            print(f"📊 Source platforms: {sorted(source_platforms)}")
            print(f"📊 Role categories: {sorted(role_categories)}")
            print(f"📊 Unique external_job_id + source_platform combinations: {len(set(external_ids))}")

            # Check for duplicates
            if len(external_ids) != len(set(external_ids)):
                print("⚠️  WARNING: Duplicate external_job_id + source_platform combinations found!")
                from collections import Counter
                duplicates = [item for item, count in Counter(external_ids).items() if count > 1]
                print(f"⚠️  Duplicates: {duplicates}")
            else:
                print("✅ No duplicate external_job_id + source_platform combinations")

        return True, total, len(jobs), jobs

    except Exception as e:
        print(f"❌ Supabase connection failed: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False, 0, 0, []

def test_repository():
    """Test the JobRepository methods."""
    print("\nTesting JobRepository...")

    try:
        repo = JobRepository()

        # Test count_active
        active_count = repo.count_active()
        print(f"✅ count_active(): {active_count}")

        # Test list_jobs
        jobs, total = repo.list_jobs(page=1, page_size=10)
        print(f"✅ list_jobs(): {len(jobs)} jobs, total: {total}")

        # Test get_job (if any jobs exist)
        if jobs:
            job_id = jobs[0]["id"]
            job = repo.get_job(job_id)
            if job:
                print(f"✅ get_job({job_id}): Found job with title '{job.get('title')}'")
            else:
                print(f"❌ get_job({job_id}): Job not found")

        return True

    except Exception as e:
        print(f"❌ Repository test failed: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("CHECKPOINT 2: REAL SUPABASE DATABASE STATE")
    print("=" * 60)

    # Test connection and read jobs
    success, total, retrieved, jobs = test_supabase_connection()

    if success:
        # Test repository
        repo_success = test_repository()

        if repo_success:
            print("\n" + "=" * 60)
            print("✅ CHECKPOINT 2: PASS")
            print("=" * 60)
            print("Supabase connection works")
            print(f"Total active jobs: {total}")
            print(f"Jobs retrieved: {retrieved}")
            print("Repository methods work")
        else:
            print("\n" + "=" * 60)
            print("❌ CHECKPOINT 2: BLOCKED")
            print("=" * 60)
            print("Repository methods failed")
    else:
        print("\n" + "=" * 60)
        print("❌ CHECKPOINT 2: BLOCKED")
        print("=" * 60)
        print("Supabase connection failed")