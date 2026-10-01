"""Production-schema regression: the identity lookup must only touch real columns.

Production failure (Render): every crawl that reached persistence died with::

    postgrest.exceptions.APIError: {"message": "column jobs.salary does not
    exist", "code": "42703"}

along ``crawl_company_job -> JobIngestionService._persist_offloop() ->
asyncio.to_thread(call_serialized) -> JobRepository.upsert_jobs() ->
JobRepository._find_many_by_identity() -> PostgREST``.

Root cause: the bulk existence fetch projects ``",".join(_CONTENT_FIELDS)``
verbatim, and ``_CONTENT_FIELDS`` still listed ``salary`` — a model-only
display string with no ``jobs`` column (migration 020 persists ``salary_min`` /
``salary_max`` only). ``select("*")`` never failed because a wildcard simply
omits a non-existent column; the explicit bulk projection turned the dead
reference into a hard ``42703``.

These tests use a STRICT in-memory PostgREST stand-in that rejects unknown
projection columns exactly like production does, so the failure class cannot
return silently.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pytest
from postgrest.exceptions import APIError

from app.models.job import NormalizedJob
from app.repositories import job_repository as job_repository_module
from app.repositories.job_repository import (
    _CONTENT_FIELDS,
    _EXISTING_ROW_COLUMNS,
    _MASS_HIRING_FIELDS,
    _PROVENANCE_FIELDS,
    JobRepository,
)
from tests.schema_helpers import (
    canonical_jobs_columns,
    missing_jobs_columns,
    projection_columns,
)

REPO_PATH = Path(job_repository_module.__file__)
_SELECT_LITERAL_RE = re.compile(r"""\.select\(\s*(["'])(?P<projection>[^"']*)\1""")

# Fixed posting timestamp: two NormalizedJob instances of the "same" job must
# compare equal, so the fixture cannot use a per-call ``now()``.
_POSTED_ISO = (
    datetime.now(timezone.utc) - timedelta(days=3)
).replace(microsecond=0).isoformat()

# The projected existence-fetch column list, as PostgREST would return it.
_EXISTING_ROW_COLUMN_LIST = projection_columns(_EXISTING_ROW_COLUMNS)




# ---------------------------------------------------------------------------
# Strict in-memory PostgREST stand-in
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, data: list[dict[str, Any]], count: Optional[int] = None) -> None:
        self.data = data
        self.count = count if count is not None else len(data)


class _StrictQuery:
    """Chainable fake table that fails unknown projection columns (42703)."""

    def __init__(self, client: "_StrictClient") -> None:
        self._client = client
        self._eq: list[tuple[str, Any]] = []
        self._in: list[tuple[str, list[Any]]] = []
        self._ilike: list[tuple[str, str]] = []
        self._lt: list[tuple[str, str]] = []
        self._columns: Optional[list[str]] = None
        self._insert_rows: Optional[list[dict[str, Any]]] = None
        self._update_values: Optional[dict[str, Any]] = None
        self._limit: Optional[int] = None

    # -- builders --
    def select(self, columns: str = "*", **_: Any) -> "_StrictQuery":
        self._columns = self._client.validate_projection(columns)
        return self

    def eq(self, field: str, value: Any) -> "_StrictQuery":
        self._eq.append((field, value))
        return self

    def in_(self, field: str, values: list[Any]) -> "_StrictQuery":
        self._in.append((field, list(values)))
        return self

    def ilike(self, field: str, value: str) -> "_StrictQuery":
        self._ilike.append((field, value))
        return self

    def lt(self, field: str, value: Any) -> "_StrictQuery":
        self._lt.append((field, value))
        return self

    def limit(self, count: int) -> "_StrictQuery":
        self._limit = count
        return self

    def insert(self, rows: Any) -> "_StrictQuery":
        self._insert_rows = rows if isinstance(rows, list) else [rows]
        return self

    def update(self, values: dict[str, Any]) -> "_StrictQuery":
        self._update_values = values
        return self

    # -- execution --
    def _matches(self, row: dict[str, Any]) -> bool:
        for field, value in self._eq:
            if row.get(field) != value:
                return False
        for field, values in self._in:
            if row.get(field) not in values:
                return False
        for field, value in self._ilike:
            current = row.get(field)
            if current is None or str(current).lower() != str(value).lower():
                return False
        for field, value in self._lt:
            current = row.get(field)
            if current is None or str(current) >= str(value):
                return False
        return True

    def execute(self) -> _Result:
        self._client.executes += 1
        if self._insert_rows is not None:
            return self._client._insert(self._insert_rows)
        if self._update_values is not None:
            return self._client._update(self._update_values, self._matches)
        self._client.select_calls.append(self._columns)
        rows = [row for row in self._client.rows if self._matches(row)]
        if self._limit is not None:
            rows = rows[: self._limit]
        if self._columns is not None:
            rows = [{key: row.get(key) for key in self._columns} for row in rows]
        else:
            rows = [dict(row) for row in rows]
        return _Result(rows)


class _StrictClient:
    """Minimal Supabase client whose projections are schema-checked."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.executes = 0
        self.select_calls: list[Optional[list[str]]] = []
        self._next_id = 1
        self.rest_url = f"https://strict-test-{id(self)}.supabase.co"

    @staticmethod
    def validate_projection(columns: str) -> Optional[list[str]]:
        """Return the projected columns, raising 42703 for unknown ones."""
        if columns.strip() == "*":
            return None
        names = projection_columns(columns)
        unknown = [name for name in names if name not in canonical_jobs_columns()]
        if unknown:
            raise APIError(
                {
                    "message": f"column jobs.{unknown[0]} does not exist",
                    "code": "42703",
                }
            )
        return names

    def table(self, _name: str) -> _StrictQuery:
        return _StrictQuery(self)

    def _insert(self, rows: list[dict[str, Any]]) -> _Result:
        inserted: list[dict[str, Any]] = []
        for row in rows:
            identity = (row.get("source_platform"), row.get("external_job_id"))
            if identity[0] and identity[1] and any(
                (existing.get("source_platform"), existing.get("external_job_id")) == identity
                for existing in self.rows
            ):
                raise APIError(
                    {
                        "message": "duplicate key value violates unique constraint",
                        "code": "23505",
                    }
                )
            stored = {key: value for key, value in row.items() if value is not None}
            stored["id"] = f"row-{self._next_id}"
            self._next_id += 1
            self.rows.append(stored)
            inserted.append(dict(stored))
        return _Result(inserted)

    def _update(self, values: dict[str, Any], matcher: Any) -> _Result:
        updated: list[dict[str, Any]] = []
        for row in self.rows:
            if matcher(row):
                row.update(values)
                updated.append(dict(row))
        return _Result(updated)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job(
    ext_id: str,
    platform: str = "ashby",
    title: str = "Engineer",
    posted_date: Optional[str] = None,
    **extra: Any,
) -> NormalizedJob:
    return NormalizedJob(
        title=title,
        company="Co",
        external_job_id=ext_id,
        source_platform=platform,
        posted_date=posted_date or _POSTED_ISO,
        apply_url=f"https://co.example/jobs/{ext_id}",
        **extra,
    )


def _seed(client: _StrictClient, job: NormalizedJob, row_id: str) -> dict[str, Any]:
    """Append a stored row (the fake client mutates its own copy on update)."""
    row = job.to_db_row()
    row.update(
        {"id": row_id, "last_seen_at": "2026-09-01T00:00:00+00:00", "is_active": True}
    )
    client.rows.append(dict(row))
    return row


@pytest.fixture()
def strict_client() -> _StrictClient:
    JobRepository.clear_probe_cache()
    client = _StrictClient()
    yield client
    JobRepository.clear_probe_cache()


@pytest.fixture()
def repo(strict_client: _StrictClient) -> JobRepository:
    return JobRepository(strict_client)



# ---------------------------------------------------------------------------
# 1. The canonical schema (and what it says about salary)
# ---------------------------------------------------------------------------


def test_canonical_jobs_schema_has_no_salary_column():
    """``jobs.salary``/``jobs.salary_currency`` were never part of the schema.

    Explanation (A)/(D) of the incident: the repository referenced a column
    that has never existed. Compensation is persisted structurally by
    migration 020 as ``salary_min``/``salary_max`` (alongside
    ``employment_type``, ``experience_level``, ``skills``, ``remote``,
    ``workplace_type``); ``salary`` and ``salary_currency`` exist only on
    ``NormalizedJob``.
    """
    columns = canonical_jobs_columns()
    assert "salary" not in columns
    assert "salary_currency" not in columns
    assert {"salary_min", "salary_max"} <= columns
    assert {
        "source_history",
        "source_tier",
        "first_seen_at",
        "last_crawled_at",
        "mass_hiring",
        "mass_hiring_status",
        "mass_hiring_details",
        "last_seen_at",
    } <= columns


def test_identity_lookup_projection_references_only_existing_columns():
    """The acceptance condition: every projected column must exist."""
    assert missing_jobs_columns(_EXISTING_ROW_COLUMNS) == set()
    assert "salary" not in projection_columns(_EXISTING_ROW_COLUMNS)


def test_decision_field_groups_reference_only_existing_columns():
    """_is_same_job / provenance / mass-hiring fields are all real columns."""
    for group in (_CONTENT_FIELDS, _PROVENANCE_FIELDS, _MASS_HIRING_FIELDS):
        assert missing_jobs_columns(",".join(group)) == set(), group


def test_normalized_job_db_columns_are_real():
    """The write whitelist can never name a column the table does not have."""
    whitelist = _job("whitelist-check")._DB_COLUMNS
    assert missing_jobs_columns(",".join(sorted(whitelist))) == set()


def test_every_literal_select_projection_in_job_repository_is_valid():
    """Guard the module: no literal projection may name an unknown column."""
    source = REPO_PATH.read_text(encoding="utf-8")
    projections = [
        match.group("projection") for match in _SELECT_LITERAL_RE.finditer(source)
    ]
    assert projections, "expected literal select projections in job_repository.py"
    assert missing_jobs_columns(*projections) == set()


def test_candidate_select_projection_is_valid(repo: JobRepository):
    assert missing_jobs_columns(repo._get_candidate_select_columns()) == set()


def test_to_db_row_never_emits_model_only_columns():
    job = _job(
        "to-db-1",
        salary="$120,000 - $150,000",
        salary_currency="USD",
        salary_min=120000.0,
        salary_max=150000.0,
        skills=["python"],
    )
    row = job.to_db_row()
    assert "salary" not in row
    assert "salary_currency" not in row
    assert row["salary_min"] == 120000.0
    assert row["salary_max"] == 150000.0
    assert missing_jobs_columns(",".join(row)) == set()


# ---------------------------------------------------------------------------
# 2. Reproduce the exact production failure mode
# ---------------------------------------------------------------------------


def test_projection_naming_missing_salary_column_raises_42703(strict_client: _StrictClient):
    """A projection that includes ``salary`` fails the whole request, as in prod."""
    with pytest.raises(APIError) as excinfo:
        strict_client.table("jobs").select("id,is_active,source_platform,salary").execute()
    assert excinfo.value.code == "42703"
    assert "jobs.salary" in excinfo.value.message


def test_identity_lookup_query_hits_no_schema_error(
    repo: JobRepository, strict_client: _StrictClient
):
    """_find_many_by_identity() itself executes cleanly against the real schema."""
    _seed(strict_client, _job("ident-1"), "row-1")
    found = repo._find_many_by_identity("ashby", ["ident-1", "ident-2"])
    assert set(found) == {("ident-1", "ashby")}


def test_bulk_lookup_chunks_identities(strict_client: _StrictClient, repo: JobRepository):
    """250 identities -> ceil(250/200) projected fetches (bulk lookup intact)."""
    repo._find_many_by_identity("ashby", [f"chunk-{i}" for i in range(250)])
    fetch_calls = [
        call for call in strict_client.select_calls if call == _EXISTING_ROW_COLUMN_LIST
    ]
    assert len(fetch_calls) == 2


# ---------------------------------------------------------------------------
# 3. upsert_jobs behaviour on the real schema
# ---------------------------------------------------------------------------


def test_upsert_jobs_inserts_new_job(repo: JobRepository, strict_client: _StrictClient):
    result = repo.upsert_jobs([_job("new-1")])
    assert result == {
        "discovered": 1,
        "inserted": 1,
        "updated": 0,
        "unchanged": 0,
        "deduplicated": 0,
        "skipped": 0,
    }
    assert len(strict_client.rows) == 1
    # one projected existence fetch + one bulk insert
    assert repo.last_db_requests == 2
    assert "salary" not in strict_client.rows[0]


def test_upsert_jobs_unchanged_existing_job(repo: JobRepository, strict_client: _StrictClient):
    job = _job("same-1")
    seeded = _seed(strict_client, job, "row-1")
    result = repo.upsert_jobs([job])
    assert result["unchanged"] == 1
    assert result["updated"] == 0 and result["inserted"] == 0
    assert len(strict_client.rows) == 1
    assert strict_client.rows[0]["last_seen_at"] != seeded["last_seen_at"]
    assert repo.last_db_requests == 2  # 1 existence fetch + 1 bulk last_seen touch


def test_upsert_jobs_changed_existing_job(repo: JobRepository, strict_client: _StrictClient):
    _seed(strict_client, _job("changed-1"), "row-1")
    result = repo.upsert_jobs([_job("changed-1", title="Senior Engineer")])
    assert result["updated"] == 1
    assert result["inserted"] == 0 and result["unchanged"] == 0
    assert len(strict_client.rows) == 1
    assert strict_client.rows[0]["title"] == "Senior Engineer"


def test_upsert_jobs_matches_identity_without_salary_column(
    repo: JobRepository, strict_client: _StrictClient
):
    """A salary-string-only difference must not create a duplicate row."""
    _seed(
        strict_client,
        _job("dup-1", salary="$100k - $120k", salary_min=100000.0, salary_max=120000.0),
        "row-1",
    )
    result = repo.upsert_jobs(
        [_job("dup-1", salary="100000-120000 USD", salary_min=100000.0, salary_max=120000.0)]
    )
    assert result["inserted"] == 0
    assert result["unchanged"] == 1
    assert len(strict_client.rows) == 1


def test_upsert_jobs_reactivates_not_seen_row(repo: JobRepository, strict_client: _StrictClient):
    job = _job("re-1")
    seeded = _seed(strict_client, job, "row-1")
    seeded["is_active"] = False
    result = repo.upsert_jobs([job])
    assert result["unchanged"] == 1
    assert strict_client.rows[0]["is_active"] is True


def test_upsert_jobs_deduplicates_keys_within_batch(
    repo: JobRepository, strict_client: _StrictClient
):
    result = repo.upsert_jobs([_job("batch-1"), _job("batch-1")])
    assert result["deduplicated"] == 1
    assert result["inserted"] == 1
    assert len(strict_client.rows) == 1


def test_upsert_jobs_keeps_platforms_distinct(repo: JobRepository, strict_client: _StrictClient):
    result = repo.upsert_jobs(
        [_job("multi-1", platform="ashby"), _job("multi-1", platform="lever")]
    )
    assert result["inserted"] == 2
    assert len(strict_client.rows) == 2


# ---------------------------------------------------------------------------
# 4. Salary semantics under the ACTUAL schema
# ---------------------------------------------------------------------------


def test_salary_change_is_detected_through_structured_columns(
    repo: JobRepository, strict_client: _StrictClient
):
    """A real compensation change (salary_min/max) is persisted as an update."""
    _seed(
        strict_client,
        _job("sal-1", salary="$100k - $120k", salary_min=100000.0, salary_max=120000.0),
        "row-1",
    )
    result = repo.upsert_jobs(
        [_job("sal-1", salary="$130k - $150k", salary_min=130000.0, salary_max=150000.0)]
    )
    assert result["updated"] == 1
    assert strict_client.rows[0]["salary_min"] == 130000.0
    assert strict_client.rows[0]["salary_max"] == 150000.0
    assert "salary" not in strict_client.rows[0]


def test_display_salary_string_alone_is_not_persistable(
    repo: JobRepository, strict_client: _StrictClient
):
    """Nothing is written for a display-string-only difference: no DB column.

    Deliberate consequence of migration 020: the formatted string is derived
    for the API (``JobOut.from_db_row``), so a reformatted string with
    identical structured bounds must not produce an UPDATE.
    """
    _seed(
        strict_client,
        _job("sal-2", salary="$100k - $120k", salary_min=100000.0, salary_max=120000.0),
        "row-1",
    )
    result = repo.upsert_jobs(
        [_job("sal-2", salary="100000 - 120000 USD", salary_min=100000.0, salary_max=120000.0)]
    )
    assert result == {
        "discovered": 1,
        "inserted": 0,
        "updated": 0,
        "unchanged": 1,
        "deduplicated": 0,
        "skipped": 0,
    }


def test_job_without_any_salary_data_still_persists(
    repo: JobRepository, strict_client: _StrictClient
):
    result = repo.upsert_jobs([_job("nosal-1")])
    assert result["inserted"] == 1
    assert strict_client.rows[0].get("salary_min") is None
    assert strict_client.rows[0].get("salary_max") is None


# ---------------------------------------------------------------------------
# 5. Throughput contract preserved on the strict schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "board_size, expected_fetch, expected_touch",
    [(200, 1, 1), (500, 3, 1), (1000, 5, 2)],
)
def test_unchanged_board_bulk_requests(
    repo: JobRepository,
    strict_client: _StrictClient,
    board_size: int,
    expected_fetch: int,
    expected_touch: int,
):
    jobs = [_job(f"board-{i}") for i in range(board_size)]
    for index, job in enumerate(jobs):
        _seed(strict_client, job, f"row-{index}")

    result = repo.upsert_jobs(jobs)

    assert result["unchanged"] == board_size
    assert result["updated"] == 0 and result["inserted"] == 0
    assert repo.last_db_requests == expected_fetch + expected_touch
    fetch_calls = [
        call for call in strict_client.select_calls if call == _EXISTING_ROW_COLUMN_LIST
    ]
    assert len(fetch_calls) == expected_fetch

