"""Profile API routes.

Both endpoints operate exclusively on the currently authenticated user — the
user id is derived from the verified JWT via ``Depends(get_current_user)`` and
is never accepted from the client. All Supabase access goes through the
RLS-authenticated async client attached to ``AuthContext``, so RLS still
enforces ``auth.uid() = id`` for every row read or written.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.repositories.profile_repository import ProfileRepository
from app.schemas.common import ErrorResponse, SuccessResponse
from app.schemas.profile import ProfileUpdate, ProfileResponse

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _to_response(profile):
    """Serialize a UserProfile into the standard ProfileResponse."""
    return ProfileResponse(**profile.model_dump())


@router.get(
    "/me",
    response_model=SuccessResponse[ProfileResponse],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_my_profile(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ProfileResponse]:
    """Get the current authenticated user's profile."""
    repo = ProfileRepository(auth.supabase)
    profile = await repo.aget_profile(auth.user.id)

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )

    return SuccessResponse(data=_to_response(profile))


@router.patch(
    "/me",
    response_model=SuccessResponse[ProfileResponse],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def update_my_profile(
    update_data: ProfileUpdate,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[ProfileResponse]:
    """Update the current authenticated user's profile.

    Only the fields explicitly provided in the request body are updated;
    unspecified fields are preserved. ``id``/``user_id`` are not part of the
    request schema, and any attempt to smuggle them in is ignored because
    ``ProfileUpdate.model_dump(exclude_unset=True)`` only contains declared,
    provided fields.
    """
    repo = ProfileRepository(auth.supabase)

    existing = await repo.aget_profile(auth.user.id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )

    update_payload = update_data.model_dump(exclude_unset=True)

    # Defensive: never allow a client to change the user id even if a future
    # schema change accidentally exposes it.
    update_payload.pop("id", None)

    if not update_payload:
        return SuccessResponse(data=_to_response(existing))

    updated = await repo.aupdate_profile(auth.user.id, update_payload)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile",
        )

    return SuccessResponse(data=_to_response(updated))
