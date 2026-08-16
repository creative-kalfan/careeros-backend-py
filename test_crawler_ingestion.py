"""Test real crawler ingestion through JobIngestionService."""

import asyncio
import pytest
from app.services.jobs.job_ingestion_service import JobIngestionService
from app.repositories.job_repository import JobRepository

@pytest.mark.asyncio
async def test_ashby_ingestion():
    """Test Ashby ingestion with real API calls."""
    print("Testing Ashby ingestion...")

    try:
        service = JobIngestionService()
        repo = JobRepository()

        # Get count before ingestion
        before_count = repo.count_active()
        print(f"📊 Jobs before Ashby ingestion: {before_count}")

        # Ingest from Ashby
        result = await service.ingest_ashby_jobs("notion")
        print(f"✅ Ashby ingestion completed: {result}")

        # Get count after ingestion
        after_count = repo.count_active()
        print(f"📊 Jobs after Ashby ingestion: {after_count}")

        # Calculate what was added
        discovered = result.get("inserted", 0) + result.get("updated", 0)
        inserted = result.get("inserted", 0)
        updated = result.get("updated", 0)
        skipped = result.get("skipped", 0)

        print(f"📊 Ashby: Discovered={discovered}, Inserted={inserted}, Updated={updated}, Skipped={skipped}")

        return True, before_count, after_count, result

    except Exception as e:
        print(f"❌ Ashby ingestion failed: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False, 0, 0, {}

@pytest.mark.asyncio
async def test_adzuna_ingestion():
    """Test Adzuna ingestion with real API calls."""
    print("\nTesting Adzuna ingestion...")

    try:
        service = JobIngestionService()
        repo = JobRepository()

        # Get count before ingestion
        before_count = repo.count_active()
        print(f"📊 Jobs before Adzuna ingestion: {before_count}")

        # Ingest from Adzuna
        result = await service.ingest_adzuna_jobs("software engineer")
        print(f"✅ Adzuna ingestion completed: {result}")

        # Get count after ingestion
        after_count = repo.count_active()
        print(f"📊 Jobs after Adzuna ingestion: {after_count}")

        # Calculate what was added
        discovered = result.get("inserted", 0) + result.get("updated", 0)
        inserted = result.get("inserted", 0)
        updated = result.get("updated", 0)
        skipped = result.get("skipped", 0)

        print(f"📊 Adzuna: Discovered={discovered}, Inserted={inserted}, Updated={updated}, Skipped={skipped}")

        return True, before_count, after_count, result

    except Exception as e:
        print(f"❌ Adzuna ingestion failed: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False, 0, 0, {}

@pytest.mark.asyncio
async def test_duplicate_safety():
    """Test that repeated ingestion doesn't create duplicates."""
    print("\nTesting duplicate safety...")

    try:
        service = JobIngestionService()
        repo = JobRepository()

        # Get count before first run
        before_first = repo.count_active()
        print(f"📊 Jobs before first ingestion: {before_first}")

        # First ingestion
        result1 = await service.ingest_ashby_jobs("notion")
        after_first = repo.count_active()
        print(f"📊 Jobs after first ingestion: {after_first}")
        print(f"📊 First run: {result1}")

        # Second ingestion (should not create duplicates)
        result2 = await service.ingest_ashby_jobs("notion")
        after_second = repo.count_active()
        print(f"📊 Jobs after second ingestion: {after_second}")
        print(f"📊 Second run: {result2}")

        # Analyze results
        if after_first == after_second:
            print("✅ No duplicates created - count unchanged")
            return True, before_first, after_first, after_second, result1, result2
        elif after_second > after_first:
            # Check if new jobs were genuinely discovered
            new_jobs = after_second - after_first
            print(f"📊 Count increased by {new_jobs} - checking if genuine new jobs...")
            if result2.get("inserted", 0) > 0:
                print(f"✅ {result2.get('inserted')} new jobs discovered (not duplicates)")
                return True, before_first, after_first, after_second, result1, result2
            else:
                print("❌ Count increased but no new jobs reported - possible duplicate bug")
                return False, before_first, after_first, after_second, result1, result2
        else:
            print("⚠️  Count decreased - unexpected behavior")
            return False, before_first, after_first, after_second, result1, result2

    except Exception as e:
        print(f"❌ Duplicate safety test failed: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        return False, 0, 0, 0, {}, {}

async def main():
    """Run all ingestion tests."""
    print("=" * 60)
    print("CHECKPOINT 3: REAL CRAWLER → DATABASE")
    print("=" * 60)

    # Test Ashby
    ashby_success, ashby_before, ashby_after, ashby_result = await test_ashby_ingestion()

    if ashby_success:
        # Test Adzuna
        adzuna_success, adzuna_before, adzuna_after, adzuna_result = await test_adzuna_ingestion()

        if adzuna_success:
            # Test duplicate safety
            dup_success, dup_before, dup_first, dup_second, dup_result1, dup_result2 = await test_duplicate_safety()

            if dup_success:
                print("\n" + "=" * 60)
                print("✅ CHECKPOINT 3: PASS")
                print("=" * 60)
                print("Ashby ingestion works")
                print(f"Ashby: {ashby_result}")
                print("Adzuna ingestion works")
                print(f"Adzuna: {adzuna_result}")
                print("Duplicate safety verified")
                print(f"First run: {dup_result1}")
                print(f"Second run: {dup_result2}")
            else:
                print("\n" + "=" * 60)
                print("❌ CHECKPOINT 3: BLOCKED")
                print("=" * 60)
                print("Duplicate safety test failed")
                print(f"Before: {dup_before}, After first: {dup_first}, After second: {dup_second}")
        else:
            print("\n" + "=" * 60)
            print("❌ CHECKPOINT 3: BLOCKED")
            print("=" * 60)
            print("Adzuna ingestion failed")
    else:
        print("\n" + "=" * 60)
        print("❌ CHECKPOINT 3: BLOCKED")
        print("=" * 60)
        print("Ashby ingestion failed")

if __name__ == "__main__":
    asyncio.run(main())