"""One-time cleanup: deactivate stale jobs (posted_date > 30 days old).

Scans the ``jobs`` table and sets ``is_active=False`` for any row where
``posted_at`` is more than 30 days old AND currently ``is_active=True``.
Reports how many rows were deactivated.
"""
import os
from datetime import datetime, timezone


def _load_env() -> None:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


_load_env()

from app.db.supabase import get_service_client

STALE_DAYS = 30


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def main() -> None:
    client = get_service_client()

    # Fetch all active jobs with their posted_at.
    result = (
        client.table("jobs")
        .select("id, posted_at, is_active")
        .eq("is_active", True)
        .execute()
    )
    rows = result.data or []
    print(f"Total active jobs scanned: {len(rows)}")

    cutoff = datetime.now(timezone.utc)
    stale_ids = []
    for row in rows:
        posted = _parse_date(row.get("posted_at"))
        if posted is None:
            continue  # no date → treat as fresh, don't deactivate
        age_days = (cutoff - posted).total_seconds() / 86400
        if age_days > STALE_DAYS:
            stale_ids.append(row["id"])

    print(f"Stale jobs (> {STALE_DAYS} days old, currently active): {len(stale_ids)}")

    if stale_ids:
        # Deactivate in batches of 100 to stay within URL length limits.
        deactivated = 0
        for i in range(0, len(stale_ids), 100):
            batch = stale_ids[i : i + 100]
            client.table("jobs").update({"is_active": False}).in_("id", batch).execute()
            deactivated += len(batch)
        print(f"Deactivated: {deactivated}")
    else:
        print("No stale jobs to deactivate.")


if __name__ == "__main__":
    main()