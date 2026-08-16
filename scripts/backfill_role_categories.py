"""One-time backfill: re-classify all existing jobs with the new taxonomy.

Reads every job from Supabase, re-classifies title (with description fallback)
using the updated RoleClassifier, and writes the new role_category back in
place.  No external APIs are touched.
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from app.db.supabase import get_service_client  # noqa: E402
from app.parsing.role_classifier import classify  # noqa: E402


BATCH_SIZE = 500
SLEEP_BETWEEN_BATCHES = 0.5


def classify_job(title: str | None, description: str | None) -> str:
    """Classify a job using title first, falling back to description."""
    text = (title or "").strip()
    if not text and description:
        text = description[:200]
    if not text:
        return "Other"
    return classify(text)


async def backfill() -> None:
    client = get_service_client()

    # --- Before snapshot ---
    total_res = (
        client.table("jobs")
        .select("id", count="exact")
        .execute()
    )
    total_before = total_res.count or 0

    other_res = (
        client.table("jobs")
        .select("id", count="exact")
        .eq("role_category", "Other")
        .execute()
    )
    other_before = other_res.count or 0
    other_pct_before = (other_before / total_before * 100) if total_before else 0.0

    print("=" * 60)
    print("ROLE CATEGORY BACKFILL")
    print("=" * 60)
    print(f"Total jobs:       {total_before}")
    print(f"Other (before):   {other_before}  ({other_pct_before:.1f}%)")
    print()

    # --- Fetch all jobs in batches ---
    all_jobs: list[dict] = []
    page = 0
    while True:
        start = page * BATCH_SIZE
        end = start + BATCH_SIZE - 1
        res = (
            client.table("jobs")
            .select("id, title, description, role_category")
            .order("id")
            .range(start, end)
            .execute()
        )
        rows = res.data or []
        if not rows:
            break
        all_jobs.extend(rows)
        page += 1
        if len(rows) < BATCH_SIZE:
            break

    print(f"Fetched {len(all_jobs)} jobs for re-classification.")

    # --- Re-classify ---
    new_category_counter: Counter = Counter()
    updates: list[dict] = []

    for job in all_jobs:
        new_cat = classify_job(job.get("title"), job.get("description"))
        new_category_counter[new_cat] += 1
        old_cat = job.get("role_category")
        if new_cat != old_cat:
            updates.append({
                "id": job["id"],
                "role_category": new_cat,
            })

    print(f"Jobs needing update: {len(updates)}")
    print()
    print("Re-classification distribution:")
    for cat, count in new_category_counter.most_common():
        print(f"  {cat:40s} {count:5d}")

    # --- Write back in batches ---
    updated_count = 0
    for i in range(0, len(updates), BATCH_SIZE):
        batch = updates[i : i + BATCH_SIZE]
        for upd in batch:
            client.table("jobs").update({"role_category": upd["role_category"]}).eq(
                "id", upd["id"]
            ).execute()
            updated_count += 1
        if SLEEP_BETWEEN_BATCHES:
            asyncio.get_event_loop().run_in_executor(
                None, lambda: __import__("time").sleep(SLEEP_BETWEEN_BATCHES)
            )
        print(f"  Updated {min(i + BATCH_SIZE, len(updates))}/{len(updates)}...", end="\r")

    print(f"\nUpdated {updated_count} jobs.")

    # --- After snapshot ---
    other_after_res = (
        client.table("jobs")
        .select("id", count="exact")
        .eq("role_category", "Other")
        .execute()
    )
    other_after = other_after_res.count or 0
    other_pct_after = (other_after / total_before * 100) if total_before else 0.0

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Total jobs:       {total_before}")
    print(f"Other (before):   {other_before}  ({other_pct_before:.1f}%)")
    print(f"Other (after):    {other_after}  ({other_pct_after:.1f}%)")
    print(f"Reduction:        {other_before - other_after} jobs  ({other_pct_before - other_pct_after:.1f} pp)")


if __name__ == "__main__":
    asyncio.run(backfill())
