"""Interview preparation repository: persistence for prep sessions/questions.

All queries are scoped to a user through the RLS-authenticated Supabase
client (the per-request ``AuthContext``). Every read/write filters on
``user_id`` (sessions) or resolves ownership through the parent session
(questions), complementing the RLS policies so a user can never read or
mutate another user's preparation data. Business logic lives in the service
layer; this class owns raw persistence only.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _first(data: Any) -> Optional[dict[str, Any]]:
    if isinstance(data, list):
        return data[0] if data else None
    return data if isinstance(data, dict) and data else None


class InterviewPrepRepository:
    """Data-access layer for the interview preparation domain."""

    # -- Sessions --------------------------------------------------------

    async def create_session(
        self, supabase: Any, user_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        payload = {"user_id": user_id, **data}
        result = await supabase.table("interview_prep_sessions").insert(payload).execute()
        row = _first(result.data)
        if row is None:
            raise RuntimeError("Interview prep session insert returned no row")
        return row

    async def get_session(
        self, supabase: Any, user_id: str, session_id: str
    ) -> Optional[dict[str, Any]]:
        result = await (
            supabase.table("interview_prep_sessions")
            .select("*")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .execute()
        )
        return _first(result.data)

    async def get_session_by_id(self, supabase: Any, session_id: str) -> Optional[dict[str, Any]]:
        """Fetch a session without a user filter (worker path).

        Callers MUST verify ``row["user_id"]`` matches the expected owner
        before proceeding — the worker boundary enforces ownership here.
        """
        result = await (
            supabase.table("interview_prep_sessions").select("*").eq("id", session_id).execute()
        )
        return _first(result.data)

    async def list_sessions(
        self,
        supabase: Any,
        user_id: str,
        application_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        query = (
            supabase.table("interview_prep_sessions")
            .select("*", count="exact")
            .eq("user_id", user_id)
        )
        if application_id:
            query = query.eq("application_id", application_id)
        query = query.order("created_at", desc=True)
        offset = (page - 1) * page_size
        query = query.range(offset, offset + page_size - 1)
        result = await query.execute()
        total = (
            result.count
            if hasattr(result, "count") and result.count is not None
            else len(result.data or [])
        )
        return (result.data or []), (total or 0)

    async def update_session(
        self, supabase: Any, user_id: str, session_id: str, updates: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        result = await (
            supabase.table("interview_prep_sessions")
            .update(updates)
            .eq("id", session_id)
            .eq("user_id", user_id)
            .select("*")
            .execute()
        )
        return _first(result.data)

    # -- Questions -------------------------------------------------------

    async def replace_questions(
        self, supabase: Any, session_id: str, questions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        await supabase.table("interview_prep_questions").delete().eq(
            "session_id", session_id
        ).execute()
        if not questions:
            return []
        payload = [{**q, "session_id": session_id} for q in questions]
        result = await supabase.table("interview_prep_questions").insert(payload).execute()
        return result.data or []

    async def list_questions(
        self, supabase: Any, session_id: str
    ) -> list[dict[str, Any]]:
        result = await (
            supabase.table("interview_prep_questions")
            .select("*")
            .eq("session_id", session_id)
            .order("question_order", desc=False)
            .execute()
        )
        return result.data or []

    async def get_question(
        self, supabase: Any, question_id: str
    ) -> Optional[dict[str, Any]]:
        result = await (
            supabase.table("interview_prep_questions")
            .select("*")
            .eq("id", question_id)
            .execute()
        )
        return _first(result.data)

    async def update_question(
        self, supabase: Any, question_id: str, updates: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        result = await (
            supabase.table("interview_prep_questions")
            .update(updates)
            .eq("id", question_id)
            .select("*")
            .execute()
        )
        return _first(result.data)
