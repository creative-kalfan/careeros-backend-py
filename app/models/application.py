"""Application lifecycle domain model for CareerOS.

Defines the canonical status set (aligned with the Mission Control frontend
terminology), validated status transitions, and the Pydantic shapes for the
application plus its child entities (interviews, assessments, contacts,
follow-ups, timeline events, attachments).

The ``archived`` flag is an ORTHOGONAL boolean to ``status``: a user can
archive an application at any stage without losing its stage. The frontend
maps ``archived=true`` onto its "Archived" kanban column / sidebar filter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Canonical statuses
# ---------------------------------------------------------------------------
# Preserved from the original legacy enum: applied, assessment, interview,
# offer, rejected. Extended with lifecycle statuses required by the product and
# already used by the frontend (saved, accepted) plus screening / withdrawn.
APPLICATION_STATUSES = (
    "saved",
    "to_apply",
    "applied",
    "screening",
    "assessment",
    "interview",
    "offer",
    "accepted",
    "rejected",
    "withdrawn",
)

# Terminal statuses: no further transitions allowed.
TERMINAL_STATUSES = frozenset({"accepted", "rejected", "withdrawn"})

# Start statuses for a freshly tracked application that has not yet been
# officially submitted.
PRE_APPLY_STATUSES = frozenset({"saved", "to_apply"})


def is_valid_status(status: str) -> bool:
    return status in APPLICATION_STATUSES


# Valid transitions. A move is only valid if the new status is present in the
# set keyed by the current status. Terminal statuses have empty allowed sets,
# so any move out of them is rejected.
APPLICATION_TRANSITIONS: dict[str, frozenset[str]] = {
    "saved": frozenset(
        {"to_apply", "applied", "screening", "assessment", "interview", "offer",
         "accepted", "rejected", "withdrawn"}
    ),
    "to_apply": frozenset(
        {"saved", "applied", "screening", "assessment", "interview", "offer",
         "accepted", "rejected", "withdrawn"}
    ),
    "applied": frozenset(
        {"screening", "assessment", "interview", "offer", "accepted", "rejected", "withdrawn"}
    ),
    "screening": frozenset(
        {"applied", "assessment", "interview", "offer", "accepted", "rejected", "withdrawn"}
    ),
    "assessment": frozenset(
        {"applied", "screening", "interview", "offer", "accepted", "rejected", "withdrawn"}
    ),
    "interview": frozenset(
        {"applied", "screening", "assessment", "offer", "accepted", "rejected", "withdrawn"}
    ),
    "offer": frozenset({"accepted", "rejected", "withdrawn"}),
    "accepted": frozenset(),
    "rejected": frozenset(),
    "withdrawn": frozenset(),
}


class InvalidStatusTransition(Exception):
    """Raised when a status change is not permitted by the lifecycle rules."""


def validate_transition(current: str, new_status: str) -> None:
    """Validate that ``current -> new_status`` is a permitted lifecycle move.

    Raises :class:`InvalidStatusTransition` when the move is invalid.
    """
    allowed = APPLICATION_TRANSITIONS.get(current, frozenset())
    if new_status not in allowed:
        raise InvalidStatusTransition(
            f"Invalid status transition from '{current}' to '{new_status}'"
        )


# Pipeline progress used by the UI progress bar (0-100).
STAGE_PROGRESS: dict[str, int] = {
    "saved": 5,
    "to_apply": 10,
    "applied": 20,
    "screening": 35,
    "assessment": 45,
    "interview": 60,
    "offer": 85,
    "accepted": 100,
    "rejected": 100,
    "withdrawn": 100,
}


def progress_for_status(status: str) -> int:
    return STAGE_PROGRESS.get(status, 0)


def next_action_for(app: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Derive the next meaningful action from real application state.

    Returns ``None`` when there is no actionable next step (e.g. terminal
    statuses). Never fabricates progress.
    """
    status = app.get("status", "")
    if status in ("accepted", "rejected", "withdrawn"):
        return None

    if status == "offer":
        return {"label": "Respond to offer", "urgency": "today"}

    # Upcoming interview wins over follow-ups.
    interviews = app.get("interviews") or []
    upcoming = [
        i
        for i in interviews
        if (i.get("scheduled_at") or i.get("when")) and i.get("status") in ("scheduled", "upcoming")
    ]
    if upcoming:
        return {"label": "Prepare for interview", "urgency": "soon"}

    if status == "assessment":
        return {"label": "Complete assessment", "urgency": "soon"}

    if status in ("applied", "screening"):
        # Overdue follow-up triggers a follow-up next action.
        follow_ups = app.get("follow_ups") or []
        overdue = [
            f
            for f in follow_ups
            if f.get("status") not in ("completed", "done")
            and _parse_dt(f.get("due_at") or f.get("due")) is not None
            and _parse_dt(f.get("due_at") or f.get("due")) < datetime.utcnow()
        ]
        if overdue:
            return {"label": "Follow up", "urgency": "today"}

    if status in ("saved", "to_apply"):
        return {"label": "Apply", "urgency": "later"}

    return {"label": "Track application", "urgency": "later"}


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

EVENT_TYPES = (
    "application_created",
    "status_changed",
    "interview_added",
    "interview_updated",
    "interview_deleted",
    "assessment_added",
    "assessment_updated",
    "assessment_deleted",
    "contact_added",
    "follow_up_created",
    "follow_up_updated",
    "follow_up_completed",
    "offer_received",
    "application_rejected",
    "application_accepted",
    "attachment_added",
)


class ApplicationCreate(BaseModel):
    job_title: str
    company_name: str
    job_id: Optional[str] = None
    company_id: Optional[str] = None
    status: str = "applied"
    application_date: Optional[str] = None
    notes: Optional[str] = None
    location: Optional[str] = None
    salary: Optional[str] = None
    match_score: Optional[int] = None
    source_url: Optional[str] = None
    source_platform: Optional[str] = None
    external_job_id: Optional[str] = None


class ApplicationUpdate(BaseModel):
    job_title: Optional[str] = None
    company_name: Optional[str] = None
    notes: Optional[str] = None
    location: Optional[str] = None
    salary: Optional[str] = None
    match_score: Optional[int] = None
    source_url: Optional[str] = None
    favorite: Optional[bool] = None
    archived: Optional[bool] = None


class InterviewCreate(BaseModel):
    name: str
    scheduled_at: Optional[str] = None
    status: str = "scheduled"
    interviewer: Optional[str] = None
    notes: Optional[str] = None


class InterviewUpdate(BaseModel):
    name: Optional[str] = None
    scheduled_at: Optional[str] = None
    status: Optional[str] = None
    interviewer: Optional[str] = None
    notes: Optional[str] = None


class AssessmentCreate(BaseModel):
    name: str
    due_at: Optional[str] = None
    status: str = "pending"
    notes: Optional[str] = None
    result: Optional[str] = None


class AssessmentUpdate(BaseModel):
    name: Optional[str] = None
    due_at: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    result: Optional[str] = None


class ContactCreate(BaseModel):
    name: str
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


class FollowUpCreate(BaseModel):
    title: str
    due_at: Optional[str] = None
    status: str = "pending"
    notes: Optional[str] = None


class FollowUpUpdate(BaseModel):
    title: Optional[str] = None
    due_at: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class ApplicationEvent(BaseModel):
    event_type: str
    title: str
    detail: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat()


# Event titles/details for automatic timeline generation.
def event_payload(event_type: str, context: dict[str, Any]) -> dict[str, Any]:
    """Map an event type + context to a human-readable timeline entry."""
    if event_type == "application_created":
        return {
            "title": "Application started",
            "detail": f"Tracking {context.get('job_title', 'a role')} at {context.get('company_name', '')}",
        }
    if event_type == "status_changed":
        return {
            "title": f"Stage changed to {context.get('new_status', '')}",
            "detail": f"Moved from {context.get('previous_status', 'unknown')} to {context.get('new_status', '')}",
        }
    if event_type == "offer_received":
        return {"title": "Offer received", "detail": "The company extended an offer"}
    if event_type == "application_accepted":
        return {"title": "Application accepted", "detail": "Offer accepted — congratulations!"}
    if event_type == "application_rejected":
        return {"title": "Application rejected", "detail": "The company closed this application"}
    if event_type == "interview_added":
        return {
            "title": context.get("name", "Interview scheduled"),
            "detail": f"Interview for {context.get('company_name', '')}",
        }
    if event_type == "assessment_added":
        return {
            "title": context.get("name", "Assessment scheduled"),
            "detail": "Assessment added for this application",
        }
    if event_type == "contact_added":
        return {
            "title": f"Added contact {context.get('name', '')}",
            "detail": context.get("role", "Contact added"),
        }
    if event_type == "follow_up_created":
        return {
            "title": context.get("title", "Follow-up"),
            "detail": "Follow-up task created",
        }
    if event_type == "follow_up_completed":
        return {"title": "Follow-up completed", "detail": context.get("title", "Follow-up task done")}
    return {"title": event_type.replace("_", " ").title(), "detail": context.get("detail") or ""}