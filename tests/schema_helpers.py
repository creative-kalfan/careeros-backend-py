"""Canonical ``public.jobs`` schema derived from the repository migrations.

The migrations under ``sql/migrations/`` ARE the canonical schema definition
(there is no ORM and no generated schema file). Tests use this module to prove
that every column the application puts in a PostgREST **projection** or write
payload actually exists — PostgREST rejects an entire request with ``42703``
("column jobs.<name> does not exist") when a projection names a column the
table does not have, which is exactly how the production
``crawl_company_job -> upsert_jobs -> _find_many_by_identity`` failure
surfaced.

Deliberately a *parser*, not a hand-maintained list: adding a column in a
migration automatically updates what the tests consider valid, and a column
referenced without a migration can never be silently blessed.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "sql" / "migrations"

# Column definitions look like ``name TYPE ...``; skip table-level clauses.
_NON_COLUMN_KEYWORDS = {
    "primary",
    "constraint",
    "unique",
    "foreign",
    "check",
    "exclude",
    "like",
}

_ADD_COLUMN_RE = re.compile(
    r"ADD\s+COLUMN(?:\s+IF\s+NOT\s+EXISTS)?\s+([a-z_][a-z0-9_]*)", re.IGNORECASE
)
_ALTER_JOBS_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?public\.jobs\b", re.IGNORECASE
)
_CREATE_JOBS_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?public\.jobs\s*\(", re.IGNORECASE
)
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$", re.IGNORECASE)


def _strip_comments(sql: str) -> str:
    """Remove ``--`` line comments and ``/* */`` blocks from a migration."""
    without_block = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", without_block)


def _split_statements(sql: str) -> list[str]:
    """Split a migration into statements (``;`` terminated)."""
    return [stmt for stmt in _strip_comments(sql).split(";") if stmt.strip()]


def _split_top_level(body: str) -> list[str]:
    """Split a parenthesis body on top-level commas."""
    parts: list[str] = []
    current = ""
    depth = 0
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return parts


def _baseline_columns(statement: str) -> set[str]:
    """Parse the column list of ``CREATE TABLE public.jobs (...)``."""
    match = _CREATE_JOBS_RE.search(statement)
    if match is None:
        return set()
    start = match.end() - 1
    depth = 0
    end = len(statement)
    for index in range(start, len(statement)):
        char = statement[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                end = index
                break
    body = statement[start + 1 : end]

    columns: set[str] = set()
    for part in _split_top_level(body):
        tokens = part.split()
        if not tokens:
            continue
        name = tokens[0].strip('"').lower()
        if name in _NON_COLUMN_KEYWORDS or not _IDENTIFIER_RE.match(name):
            continue
        columns.add(name)
    return columns


@lru_cache(maxsize=1)
def canonical_jobs_columns() -> frozenset[str]:
    """Every column ``public.jobs`` can be assumed to have.

    Baseline ``CREATE TABLE`` (000) plus every ``ALTER TABLE public.jobs ADD
    COLUMN`` across all migrations, in migration order.
    """
    columns: set[str] = set()
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = migration.read_text(encoding="utf-8")
        for statement in _split_statements(sql):
            if _CREATE_JOBS_RE.search(statement):
                columns |= _baseline_columns(statement)
            if _ALTER_JOBS_RE.search(statement):
                columns |= {
                    match.group(1).lower()
                    for match in _ADD_COLUMN_RE.finditer(statement)
                }
    if not columns:
        raise AssertionError(f"no public.jobs columns parsed from {MIGRATIONS_DIR}")
    return frozenset(columns)


def projection_columns(projection: str) -> list[str]:
    """Split a PostgREST ``select`` projection string into column names.

    ``"*"`` and embedded resource selects (``"a(...)"``) are ignored — only
    plain top-level column names are relevant to the 42703 class of failure.
    """
    columns: list[str] = []
    for raw in projection.split(","):
        name = raw.strip()
        if not name or name == "*" or "(" in name:
            continue
        columns.append(name.split(":")[-1].strip())
    return columns


def missing_jobs_columns(*projections: str) -> set[str]:
    """Column names referenced by *projections* that do not exist on ``jobs``."""
    known = canonical_jobs_columns()
    referenced = {
        column for projection in projections for column in projection_columns(projection)
    }
    return {column for column in referenced if column not in known}
