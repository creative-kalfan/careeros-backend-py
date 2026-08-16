"""User profile repository: reads and writes profile rows in Supabase.

Two client modes are supported:

- **Sync service-role mode** (default): used by internal services such as
  ``JobRelevanceService`` which run outside the request/RLS context. This
  client bypasses RLS (intended for backend repositories).
- **Async RLS mode** (via ``aget_profile`` / ``aupdate_profile``): used by the
  authenticated profile API. The caller passes the RLS-authenticated
  ``AsyncClient`` from ``AuthContext`` so every query is scoped to
  ``auth.uid() = id`` and each user can only touch their own row.
"""

from __future__ import annotations

from typing import Any, Optional

from app.db.supabase import get_service_client
from app.models.profile import UserProfile

# Projected columns read from the profiles table.
_PROFILE_COLUMNS = (
    "id, email, full_name, role, current_role, desired_role, skills, location, "
    "preferred_locations, remote_preference, preferred_companies, "
    "salary_expectation_min, salary_expectation_max, salary_currency, "
    "experience, education, onboarding_completed, onboarding_step"
)


class ProfileRepository:
    """Data-access layer for the Supabase ``profiles`` table."""

    def __init__(self, client: Optional[Any] = None) -> None:
        # ``client`` may be either the sync service-role ``Client`` (internal
        # services) or the async RLS-authenticated ``AsyncClient`` (profile
        # API via AuthContext). ``Any`` is used deliberately — callers select
        # sync vs async methods based on the client they pass in.
        self._client = client or get_service_client()

    def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Fetch a user's profile by id (sync / service-role client).

        Returns None if not found.
        """
        result = (
            self._client.table("profiles")
            .select(_PROFILE_COLUMNS)
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return UserProfile.from_db_row(rows[0]) if rows else None

    def update_profile(
        self, user_id: str, update_data: dict[str, Any]
    ) -> Optional[UserProfile]:
        """Update a user's profile by id (sync / service-role client).

        Returns the updated profile or None on failure.
        """
        result = (
            self._client.table("profiles")
            .update(update_data)
            .eq("id", user_id)
            .execute()
        )
        rows = result.data or []
        return UserProfile.from_db_row(rows[0]) if rows else None

    async def aget_profile(self, user_id: str) -> Optional[UserProfile]:
        """Fetch a user's profile by id using the async RLS-authenticated client.

        Returns None if not found.
        """
        result = await (
            self._client.table("profiles")
            .select(_PROFILE_COLUMNS)
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return UserProfile.from_db_row(rows[0]) if rows else None

    async def aupdate_profile(
        self, user_id: str, update_data: dict[str, Any]
    ) -> Optional[UserProfile]:
        """Update a user's profile by id using the async RLS-authenticated client.

        Returns the updated profile or None on failure.
        """
        result = await (
            self._client.table("profiles")
            .update(update_data)
            .eq("id", user_id)
            .execute()
        )
        rows = result.data or []
        return UserProfile.from_db_row(rows[0]) if rows else None
