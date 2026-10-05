"""Phase 5 verification tests."""

import asyncio

from app.workers.enqueue import enqueue_crawl_company
from app.db.supabase import get_service_client


def count_jobs(source: str) -> int:
    client = get_service_client()
    result = (
        client.table("jobs")
        .select("id", count="exact")
        .eq("source_platform", source)
        .execute()
    )
    return result.count or 0


async def test_duplicate_protection() -> dict[str, any]:
    """Test that concurrent crawls for the same company are protected."""
    print("\n=== Test: Duplicate Crawl Protection ===")
    
    # Enqueue two crawls for the same company simultaneously
    job_id_1 = await enqueue_crawl_company("greenhouse", "stripe")
    job_id_2 = await enqueue_crawl_company("greenhouse", "stripe")
    
    result = {
        "first_enqueued": job_id_1 is not None,
        "second_skipped": job_id_2 is None,
        "first_job_id": job_id_1,
        "second_job_id": job_id_2,
    }
    
    print(f"First crawl enqueued: {job_id_1 is not None} (job_id={job_id_1})")
    print(f"Second crawl skipped: {job_id_2 is None} (job_id={job_id_2})")
    
    return result


async def main() -> None:
    print("Phase 5 Verification Tests")
    print("=" * 50)
    
    # Test 1: Duplicate protection
    dup_result = await test_duplicate_protection()
    
    print("\n=== Summary ===")
    print(f"Duplicate protection: {'PASS' if dup_result.get('second_skipped') else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
