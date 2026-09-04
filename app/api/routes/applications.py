"""Applications API routes for Application Tracking / Mission Control.

Routes are kept thin: all business logic (lifecycle transitions, timeline
events, job → application bridging, statistics, notifications, ownership) is
handled by :class:`ApplicationService`. Repositories own persistence.

ROUTE ORDERING: fixed-path routes (``/applications/stats``) are declared BEFORE
parameterized ``/{application_id}`` routes so ``stats`` is never captured as an
application id.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.service import AuthContext
from app.dependencies import get_current_user
from app.schemas.common import ErrorResponse, SuccessResponse, build_meta
from app.services.applications import ApplicationService

router = APIRouter(prefix="/applications", tags=["applications"])

SERVICE = ApplicationService()


# ── Fixed-path routes MUST come before /{application_id} parameterized routes ──


@router.get(
    "",
    response_model=SuccessResponse[list[dict]],
    responses={401: {"model": ErrorResponse}},
)
async def list_applications(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[list[dict]]:
    """List all applications for the authenticated user (enriched with children)."""
    result = await SERVICE.list(
        auth, page=page, page_size=page_size, status=status, search=search
    )
    return SuccessResponse(
        data=result["applications"],
        meta=build_meta(page, page_size, result["total"]),
    )


@router.get(
    "/stats",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}},
)
async def get_application_stats(
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Get aggregate statistics for the authenticated user's applications."""
    return SuccessResponse(data=await SERVICE.stats(auth))


@router.post(
    "",
    response_model=SuccessResponse[dict],
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def create_application(
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Create a new application (manual 'Add Application' flow)."""
    app = await SERVICE.create(auth, body)
    return SuccessResponse(data=app, status_code=201)


# ── Parameterized /{application_id} routes below ──


@router.get(
    "/{application_id}",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_application(
    application_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Get a single application (enriched with children)."""
    return SuccessResponse(data=await SERVICE.detail(auth, application_id))


@router.patch(
    "/{application_id}",
    response_model=SuccessResponse[dict],
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def update_application(
    application_id: str,
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Update application fields (notes, location, salary, favorite, archived...)."""
    return SuccessResponse(data=await SERVICE.update(auth, application_id, body))


@router.patch(
    "/{application_id}/status",
    response_model=SuccessResponse[dict],
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def update_application_status(
    application_id: str,
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Change the application stage (validated lifecycle transition)."""
    new_status = (body or {}).get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="status is required")
    return SuccessResponse(data=await SERVICE.change_status(auth, application_id, new_status))


@router.delete(
    "/{application_id}",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def delete_application(
    application_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    """Delete an application (and, via CASCADE, all its children/events)."""
    await SERVICE.delete(auth, application_id)
    return SuccessResponse(data={"id": application_id, "deleted": True})
@router.post(
    "/{application_id}/favorite",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def favorite_application(
    application_id: str,
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    value = bool((body or {}).get("favorite", True))
    return SuccessResponse(data=await SERVICE.set_favorite(auth, application_id, value))


@router.post(
    "/{application_id}/archive",
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def archive_application(
    application_id: str,
    body: dict,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[dict]:
    value = bool((body or {}).get("archived", True))
    return SuccessResponse(data=await SERVICE.set_archived(auth, application_id, value))


@router.get(
    "/{application_id}/events",
    response_model=SuccessResponse[list[dict]],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def list_application_events(
    application_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> SuccessResponse[list[dict]]:
    """Return the persisted application timeline."""
    return SuccessResponse(data=await SERVICE.list_events(auth, application_id))


# ── Child entity routes (interviews / assessments / contacts / follow-ups / attachments) ──

_CHILD_ROUTES = {
    "interviews": "interviews",
    "assessments": "assessments",
    "contacts": "contacts",
    "follow-ups": "follow_ups",
    "attachments": "attachments",
}


def _register_child_routes() -> None:
    """Register thin CRUD routes for each child entity type."""
    for path_segment, service_key in _CHILD_ROUTES.items():

        @router.post(
            f"/{{application_id}}/{path_segment}",
            response_model=SuccessResponse[dict],
            responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
            include_in_schema=False,
        )
        async def add_child(
            application_id: str,
            body: dict,
            auth: AuthContext = Depends(get_current_user),
            _key: str = service_key,
        ) -> SuccessResponse[dict]:
            return SuccessResponse(
                data=await SERVICE.add_child(auth, application_id, _key, body),
                status_code=201,
            )

        @router.patch(
            f"/{{application_id}}/{path_segment}/{{child_id}}",
            response_model=SuccessResponse[dict],
            responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
            include_in_schema=False,
        )
        async def update_child(
            application_id: str,
            child_id: str,
            body: dict,
            auth: AuthContext = Depends(get_current_user),
            _key: str = service_key,
        ) -> SuccessResponse[dict]:
            return SuccessResponse(
                data=await SERVICE.update_child(auth, application_id, _key, child_id, body)
            )

        @router.delete(
            f"/{{application_id}}/{path_segment}/{{child_id}}",
            response_model=SuccessResponse[dict],
            responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
            include_in_schema=False,
        )
        async def delete_child(
            application_id: str,
            child_id: str,
            auth: AuthContext = Depends(get_current_user),
            _key: str = service_key,
        ) -> SuccessResponse[dict]:
            return SuccessResponse(
                data=await SERVICE.delete_child(auth, application_id, _key, child_id)
            )


_register_child_routes()