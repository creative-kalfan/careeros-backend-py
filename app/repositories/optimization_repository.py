"""Optimization repository for database operations (Step 5)."""

from __future__ import annotations

import logging
from typing import Any, Optional, List, Dict
from datetime import datetime

from app.db.supabase import get_service_client, get_authenticated_client

logger = logging.getLogger(__name__)


class OptimizationRepository:
    """Repository managing optimization sessions & suggestions in Supabase."""

    def __init__(self, client: Optional[Any] = None) -> None:
        self._client = client or get_service_client()

    # ---- Session Operations ----

    def create_session(self, session: Dict[str, Any], jwt: Optional[str] = None) -> str:
        client = get_authenticated_client(jwt) if jwt else self._client
        result = client.table("optimization_sessions").insert(session).execute()
        if not result.data:
            raise RuntimeError("Failed to create optimization session")
        return result.data[0]["id"]

    def get_session(self, session_id: str, jwt: Optional[str] = None) -> Optional[Dict[str, Any]]:
        client = get_authenticated_client(jwt) if jwt else self._client
        result = client.table("optimization_sessions").select("*").eq("id", session_id).single().execute()
        return result.data

    def update_session(self, session_id: str, updates: Dict[str, Any], jwt: Optional[str] = None) -> bool:
        client = get_authenticated_client(jwt) if jwt else self._client
        updates["updated_at"] = datetime.utcnow().isoformat()
        result = client.table("optimization_sessions").update(updates).eq("id", session_id).execute()
        return bool(result.data)

    def list_sessions_for_resume(self, resume_id: str, jwt: Optional[str] = None) -> List[Dict[str, Any]]:
        client = get_authenticated_client(jwt) if jwt else self._client
        result = client.table("optimization_sessions")\
            .select("*")\
            .eq("resume_id", resume_id)\
            .order("created_at", desc=True)\
            .execute()
        return result.data or []

    # ---- Suggestion Operations ----

    def create_suggestion(self, record: Dict[str, Any], jwt: Optional[str] = None) -> str:
        client = get_authenticated_client(jwt) if jwt else self._client
        result = client.table("optimization_suggestions").insert(record).execute()
        if not result.data:
            raise RuntimeError("Failed to create suggestion record")
        return result.data[0]["id"]

    def get_suggestion(self, suggestion_id: str, jwt: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get suggestion by database record ID (primary key)."""
        client = get_authenticated_client(jwt) if jwt else self._client
        result = client.table("optimization_suggestions").select("*").eq("id", suggestion_id).single().execute()
        return result.data

    def update_suggestion(self, suggestion_id: str, updates: Dict[str, Any], jwt: Optional[str] = None) -> bool:
        client = get_authenticated_client(jwt) if jwt else self._client
        updates["updated_at"] = datetime.utcnow().isoformat()
        result = client.table("optimization_suggestions").update(updates).eq("id", suggestion_id).execute()
        return bool(result.data)

    def list_suggestions_for_session(self, session_id: str, jwt: Optional[str] = None) -> List[Dict[str, Any]]:
        client = get_authenticated_client(jwt) if jwt else self._client
        result = client.table("optimization_suggestions")\
            .select("*")\
            .eq("session_id", session_id)\
            .order("created_at", desc=False)\
            .execute()
        return result.data or []

    def list_suggestions_for_resume(self, resume_id: str, jwt: Optional[str] = None) -> List[Dict[str, Any]]:
        client = get_authenticated_client(jwt) if jwt else self._client
        sessions = self.list_sessions_for_resume(resume_id, jwt)
        session_ids = [s["id"] for s in sessions]
        if not session_ids:
            return []
        result = client.table("optimization_suggestions")\
            .select("*")\
            .in_("session_id", session_ids)\
            .order("created_at", desc=False)\
            .execute()
        return result.data or []

    def get_optimization_history(self, resume_id: str, jwt: Optional[str] = None) -> List[Dict[str, Any]]:
        client = get_authenticated_client(jwt) if jwt else self._client
        sessions = self.list_sessions_for_resume(resume_id, jwt)
        history = []
        for session in sessions:
            suggestions = self.list_suggestions_for_session(session["id"], jwt)
            accepted = sum(1 for s in suggestions if (s.get("suggestion") or {}).get("status") == "accepted")
            rejected = sum(1 for s in suggestions if (s.get("suggestion") or {}).get("status") == "rejected")
            history.append({
                "session_id": session["id"],
                "job_title": session.get("job_title"),
                "company": session.get("company"),
                "baseline_score": session.get("baseline_ats_score"),
                "final_score": session.get("current_ats_score"),
                "suggestions_count": len(suggestions),
                "accepted_count": accepted,
                "rejected_count": rejected,
                "created_at": session.get("created_at"),
                "status": session.get("status"),
            })
        return history


# Singleton instance
optimization_repo = OptimizationRepository()
