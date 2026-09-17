"""Apply ``sql/migrations/021_mass_hiring.sql`` to the live Supabase database.

Established safe migration procedure
------------------------------------
``sql/migrations/README.md`` guarantees every migration is strictly idempotent
(``IF NOT EXISTS`` guards) and non-destructive, and ``COMPLETE_SYSTEM.md``
§14.10 records that migration 021 is applied either through the Supabase
Dashboard SQL Editor or, when a Postgres connection string is available,
through a short psycopg2 script — the pattern already established by
``scripts/add_last_seen_at.py``.

This script performs the programmatic path for migration 021:

1. Connect with ``DATABASE_URL`` (fallback: ``SUPABASE_URL`` + service role,
   exactly as ``scripts/add_last_seen_at.py`` does).
2. Fingerprint ``public.jobs`` (total rows, active rows, id/is_active digest)
   plus per-source row counts, so "existing jobs remain unaffected" is proven.
3. Execute the migration file verbatim — ``ADD COLUMN IF NOT EXISTS`` /
   ``CREATE INDEX IF NOT EXISTS`` only. No backfill, no UPDATE, no DELETE.
4. Re-verify: three columns, two partial indexes, unchanged fingerprint, and
   zero rows carrying a mass-hiring value (nothing fabricated/backfilled).

Usage::

    python scripts/apply_mass_hiring_migration.py --check
    python scripts/apply_mass_hiring_migration.py --snapshot-out before.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

MIGRATION_PATH = BACKEND_ROOT / "sql" / "migrations" / "021_mass_hiring.sql"

MASS_HIRING_COLUMNS = ("mass_hiring", "mass_hiring_status", "mass_hiring_details")
MASS_HIRING_INDEXES = ("idx_jobs_mass_hiring", "idx_jobs_mass_hiring_status")


def resolve_conn_string(explicit: Optional[str] = None) -> str:
    """Return the Postgres connection string (environment-driven only)."""
    dotenv.load_dotenv(BACKEND_ROOT / ".env")
    if explicit:
        return explicit
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return database_url
    supabase_url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
    project_ref = supabase_url.split("//")[-1].split(".")[0] if supabase_url else ""
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not project_ref or not service_key:
        raise SystemExit(
            "No database credentials available. Set DATABASE_URL (preferred) or "
            "SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY in careeros-backend-py/.env. "
            "If neither exists, apply sql/migrations/021_mass_hiring.sql in the "
            "Supabase Dashboard SQL Editor and run "
            "scripts/verify_mass_hiring_schema.py afterwards."
        )
    return f"postgresql://postgres:{service_key}@db.{project_ref}.supabase.co:5432/postgres"


def fingerprint(cur: Any) -> dict[str, Any]:
    """Row-count and content digest over ``public.jobs`` (ignores new columns)."""
    cur.execute(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE is_active) AS active,
               md5(coalesce(string_agg(
                   id::text || ':' || coalesce(is_active::text, ''),
                   ',' ORDER BY id
               ), '')) AS digest
        FROM public.jobs
        """
    )
    total, active, digest = cur.fetchone()
    return {"total": total, "active": active, "digest": digest}


def source_counts(cur: Any) -> dict[str, int]:
    """Rows per ``source_platform`` (baseline for the "no broad recrawl" check)."""
    cur.execute(
        "SELECT coalesce(source_platform, 'unknown'), count(*) "
        "FROM public.jobs GROUP BY 1 ORDER BY 1"
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def column_exists(cur: Any, column: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'jobs' AND column_name = %s",
        (column,),
    )
    return cur.fetchone() is not None


def index_exists(cur: Any, index: str) -> bool:
    cur.execute(
        "SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = %s",
        (index,),
    )
    return cur.fetchone() is not None


def persisted_counts(cur: Any) -> dict[str, int]:
    """Existing rows per ``mass_hiring`` value (empty when the column is absent)."""
    if not column_exists(cur, "mass_hiring"):
        return {}
    cur.execute(
        "SELECT coalesce(mass_hiring, 'NULL'), count(*) FROM public.jobs GROUP BY 1 ORDER BY 1"
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def report(cur: Any) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "columns": {c: column_exists(cur, c) for c in MASS_HIRING_COLUMNS},
        "indexes": {i: index_exists(cur, i) for i in MASS_HIRING_INDEXES},
        "fingerprint": fingerprint(cur),
        "source_counts": source_counts(cur),
        "persisted_mass_hiring": persisted_counts(cur),
    }


def print_report(title: str, state: dict[str, Any]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    for column, present in state["columns"].items():
        print(f"  column  {column:26} {'present' if present else 'MISSING'}")
    for index, present in state["indexes"].items():
        print(f"  index   {index:26} {'present' if present else 'MISSING'}")
    fp = state["fingerprint"]
    print(f"  jobs    total={fp['total']} active={fp['active']} digest={fp['digest']}")
    if state["persisted_mass_hiring"]:
        print(f"  persisted mass_hiring values: {state['persisted_mass_hiring']}")
    else:
        print("  persisted mass_hiring values: none")


def verify(after: dict[str, Any], before: Optional[dict[str, Any]] = None) -> list[str]:
    """Return the list of verification failures (empty list = every check passed)."""
    problems = [f"column {c} missing" for c, present in after["columns"].items() if not present]
    problems += [f"index {i} missing" for i, present in after["indexes"].items() if not present]
    if before:
        if after["fingerprint"] != before["fingerprint"]:
            problems.append(
                f"jobs fingerprint changed: {before['fingerprint']} -> {after['fingerprint']}"
            )
        if after["source_counts"] != before["source_counts"]:
            problems.append(
                f"per-source row counts changed: {before['source_counts']} -> {after['source_counts']}"
            )
    unexpected = {k: v for k, v in after["persisted_mass_hiring"].items() if k != "NULL"}
    if unexpected:
        problems.append(
            f"rows carry a mass-hiring value (no backfill was requested): {unexpected}"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply migration 021 (mass hiring) idempotently.")
    parser.add_argument("--check", action="store_true", help="read-only: report the live schema and exit")
    parser.add_argument("--snapshot-out", help="write the pre-migration state to this JSON file")
    parser.add_argument("--database-url", help="override DATABASE_URL for this run")
    args = parser.parse_args()

    import psycopg2

    if not MIGRATION_PATH.exists():
        raise SystemExit(f"Migration file not found: {MIGRATION_PATH}")

    try:
        conn = psycopg2.connect(resolve_conn_string(args.database_url), connect_timeout=20)
    except Exception as exc:
        raise SystemExit(
            f"Could not connect to the live database ({type(exc).__name__}: {exc}).\n"
            "Set DATABASE_URL to the Supabase Postgres connection string "
            "(Dashboard → Project Settings → Database → Connection string), or apply "
            "sql/migrations/021_mass_hiring.sql in the Supabase Dashboard SQL Editor "
            "and run scripts/verify_mass_hiring_schema.py afterwards."
        )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            before = report(cur)
            print_report("Live schema BEFORE migration 021", before)
            if all(before["columns"].values()):
                print("\nMigration 021 already applied: all three columns are present.")
            if args.snapshot_out:
                Path(args.snapshot_out).write_text(json.dumps(before, indent=2), encoding="utf-8")
                print(f"\nPre-migration snapshot written to {args.snapshot_out}")
            if args.check:
                print("\n--check: read-only run, no DDL executed.")
                return 0

            print(f"\nExecuting {MIGRATION_PATH.name} verbatim (idempotent DDL only) ...")
            cur.execute(MIGRATION_PATH.read_text(encoding="utf-8"))
            print("Migration executed and committed.")

            after = report(cur)
            print_report("Live schema AFTER migration 021", after)

            problems = verify(after, before)
            if problems:
                print("\nVERIFICATION FAILED")
                for problem in problems:
                    print(f"  - {problem}")
                return 1

            print("\nVERIFICATION PASSED: 3 columns present, 2 partial indexes present,")
            print("existing jobs unchanged (row counts + content digest), nothing backfilled.")
            return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())