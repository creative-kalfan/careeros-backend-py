"""Regression tests: optimization data lifecycle (P1).

The optimization tables (migration 010) intentionally expose SELECT / INSERT /
UPDATE ownership-scoped policies but NO standalone DELETE policy:
  * There is no API endpoint that deletes a session/suggestion individually.
  * Sessions cascade-delete when their owning resume is deleted
    (``REFERENCES public.resumes(id) ON DELETE CASCADE``), and suggestions
    cascade when their session is deleted.
Adding public DELETE policies with no API consumer would unnecessarily widen
the attack surface, so omission is intentional and documented here.
"""

from __future__ import annotations

from pathlib import Path

_MIGRATION = Path(__file__).resolve().parents[1] / "sql" / "migrations" / "010_optimization_tables.sql"


def test_optimization_migration_has_ownership_policies():
    sql = _MIGRATION.read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in sql
    # Owner-scoped SELECT / INSERT / UPDATE for sessions & suggestions.
    assert "FOR SELECT" in sql
    assert "FOR INSERT" in sql
    assert "FOR UPDATE" in sql
    assert "user_id = auth.uid()" in sql


def test_no_public_delete_policy_for_optimization_tables():
    """Explicitly assert DELETE is NOT exposed for these tables."""
    sql = _MIGRATION.read_text(encoding="utf-8")
    for keyword in ("FOR DELETE", "DELETE POLICY", "delete_optimization"):
        assert keyword not in sql, f"Unexpected DELETE policy keyword: {keyword}"


def test_optimization_tables_cascade_from_resume():
    """Deletion happens through the owning resume via ON DELETE CASCADE."""
    sql = _MIGRATION.read_text(encoding="utf-8")
    # sessions ON DELETE CASCADE from resumes; suggestions cascade from sessions.
    assert "REFERENCES public.resumes(id) ON DELETE CASCADE" in sql
    assert "REFERENCES public.optimization_sessions(id) ON DELETE CASCADE" in sql