"""Verify the LIVE ``public.jobs`` schema against the columns the app uses.

Read-only: every check is a single-column ``select(...).limit(1)`` through the
repository's existing service-role Supabase client (PostgREST). PostgREST
answers ``42703`` ("column jobs.<name> does not exist") for a column the table
lacks, which is exactly how the production crawl-persistence failure surfaced
(``_find_many_by_identity`` projected ``jobs.salary``).

Checks:

  1. The exact bulk identity-lookup projection (``_EXISTING_ROW_COLUMNS``) —
     the production failure path. One probe request proves the whole
     projection is valid.
  2. Every referenced decision field group and the write whitelist
     (``NormalizedJob._DB_COLUMNS``).
  3. The candidate-universe projection used by feed queries.
  4. Absence proof for columns that must NOT be assumed (``salary``,
     ``salary_currency``): the canonical schema (migration 020) persists
     ``salary_min`` / ``salary_max`` only, and re-introducing the display
     column into a projection is what broke production.

Exit codes: 0 = every referenced column exists, 1 = at least one mismatch,
2 = could not verify (no credentials / unreachable, nothing is claimed).

Usage::

    python scripts/verify_jobs_schema.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.job import NormalizedJob  # noqa: E402
from app.repositories.job_repository import (  # noqa: E402
    _CONTENT_FIELDS,
    _EXISTING_ROW_COLUMNS,
    _MASS_HIRING_FIELDS,
    _PROVENANCE_FIELDS,
    JobRepository,
)

# Columns that must NOT be assumed to exist: migration 020 persists the
# structured salary columns only; these two are model-only display fields.
MUST_NOT_EXIST = ("salary", "salary_currency")

_results: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    _results.append((name, status, detail))


def probe_column(client: Any, column: str) -> Optional[str]:
    """Return None when *column* exists, else the failure detail."""
    try:
        client.table("jobs").select(column).limit(1).execute()
        return None
    except Exception as exc:  # APIError carries the Postgres code
        return f"{type(exc).__name__}: {getattr(exc, 'code', '?')} {exc}"


def split_columns(projection: str) -> list[str]:
    return [name.strip() for name in projection.split(",") if name.strip()]


def check_projection(client: Any, projection: str, label: str) -> None:
    """Probe the projection as a whole (one request), then each column."""
    try:
        client.table("jobs").select(projection).limit(1).execute()
        record(label, "PASS", f"{len(split_columns(projection))} columns projected")
    except Exception as exc:
        code = str(getattr(exc, "code", "") or "")
        detail = f"{code} {getattr(exc, 'message', exc)}"
        record(label, "FAIL", detail)
        for column in split_columns(projection):
            failure = probe_column(client, column)
            if failure:
                record(f"{label} :: {column}", "FAIL", failure)


def check_write_columns(client: Any) -> None:
    """Probe every write-whitelisted column (read-only SELECT)."""
    job = NormalizedJob(title="schema-probe", company="schema-probe")
    whitelist = sorted(set(job._DB_COLUMNS))
    missing = [column for column in whitelist if probe_column(client, column)]
    if missing:
        record("write whitelist (_DB_COLUMNS)", "FAIL", f"missing: {sorted(missing)}")
    else:
        record("write whitelist (_DB_COLUMNS)", "PASS", f"{len(whitelist)} columns")


def check_absent_columns(client: Any) -> None:
    """``salary`` / ``salary_currency`` must not be columns of ``jobs``."""
    present = [
        column for column in MUST_NOT_EXIST if probe_column(client, column) is None
    ]
    if present:
        record(
            "model-only columns are not projected",
            "FAIL",
            f"{present} unexpectedly EXIST on jobs; the canonical schema stores "
            "compensation as salary_min/salary_max (migration 020)",
        )
    else:
        record(
            "model-only columns are not projected",
            "PASS",
            f"{list(MUST_NOT_EXIST)} absent (expected)",
        )


def main() -> int:
    """Run every check against the live schema; return the exit code."""
    try:
        from app.config import get_settings

        settings = get_settings()
    except Exception as exc:
        print(f"CANNOT VERIFY: configuration unavailable ({exc})")
        print(
            "Set NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY / "
            "SUPABASE_SERVICE_ROLE_KEY (or .env) and re-run."
        )
        return 2

    key = settings.supabase_service_role_key or ""
    if not key or key.startswith(("your-", "test-")):
        print(
            "CANNOT VERIFY: SUPABASE_SERVICE_ROLE_KEY is a placeholder; "
            "nothing is claimed."
        )
        return 2

    from app.db.supabase import get_service_client

    client = get_service_client()
    JobRepository.clear_probe_cache()

    if (failure := probe_column(client, "id")) is not None:
        print(f"CANNOT VERIFY: jobs table unreachable ({failure})")
        return 2

    check_projection(client, _EXISTING_ROW_COLUMNS, "_find_many_by_identity projection")
    check_projection(client, ",".join(_CONTENT_FIELDS), "_CONTENT_FIELDS")
    check_projection(client, ",".join(_PROVENANCE_FIELDS), "_PROVENANCE_FIELDS")
    check_projection(client, ",".join(_MASS_HIRING_FIELDS), "_MASS_HIRING_FIELDS")
    check_write_columns(client)
    check_projection(
        client,
        JobRepository(client)._get_candidate_select_columns(),
        "candidate universe projection",
    )
    check_absent_columns(client)

    print("\nLIVE JOB SCHEMA VERIFICATION (read-only, PostgREST service client)")
    print("=" * 78)
    for name, status, detail in _results:
        print(f"  [{status:4}] {name}")
        if detail:
            print(f"             {detail}")
    print("-" * 78)
    failures = [row for row in _results if row[1] == "FAIL"]
    print(f"  PASS={len(_results) - len(failures)}  FAIL={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

