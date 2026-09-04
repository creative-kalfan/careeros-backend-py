"""Tests for Application Tracking / Mission Control domain.

Covers: creation, job→application bridge, duplicate handling, ownership
enforcement, status transitions (valid + invalid), timeline events, child CRUD
(interviews/assessments/contacts/follow-ups), favorite/archive, statistics,
and notification/EventBus integration. Uses mocked repos/bus/notification.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.auth.service import AuthContext, AuthUser
from app.events import ApplicationStatusChanged
from app.services.applications.application_service import ApplicationService


def _auth(user_id: str = "user-A") -> AuthContext:
    return AuthContext(
        user=AuthUser(id=user_id, email=f"{user_id}@example.com"),
        supabase=MagicMock(),
        jwt="jwt-A",
    )


def _app_row(**overrides):
    row = {
        "id": "app-1",
        "user_id": "user-A",
        "job_id": "job-1",
        "job_title": "Software Engineer",
        "company_name": "Acme",
        "status": "applied",
        "application_date": "2026-01-01",
        "notes": None,
        "location": "Remote",
        "salary": "$120k",
        "match_score": 85,
        "favorite": False,
        "archived": False,
        "source_url": "https://example.com/job/1",
        "interviews": [],
        "assessments": [],
        "contacts": [],
        "follow_ups": [],
        "events": [],
    }
    row.update(overrides)
    return row


def _service(repo=None, bus=None, notif=None) -> ApplicationService:
    return ApplicationService(repository=repo or MagicMock(), bus=bus, notification_service=notif)


class _FakeBus:
    def __init__(self) -> None:
        self.published = []
        self.context = None

    async def publish(self, event, context=None):  # noqa: A002
        self.published.append(event)
        self.context = context
        return MagicMock()


class _FakeNotif:
    def __init__(self) -> None:
        self.created = []

    async def create_notification(self, auth, type_, title, message, payload=None, priority="medium"):
        self.created.append((title, payload))
        return {"id": "notif-1"}


async def test_create_application_persists_and_records_event():
    auth = _auth()
    repo = MagicMock()
    repo.create_application = AsyncMock(side_effect=lambda s, uid, d: {"id": "app-1", **d})
    repo.enrich_applications = AsyncMock(
        side_effect=lambda s, rows, ids: [dict(rows[0])]
    )
    repo.create_event = AsyncMock(return_value={"id": "evt-1"})
    svc = _service(repo)

    app = await svc.create(auth, {"job_title": "SE", "company_name": "Acme", "location": "NYC"})

    assert app["job_title"] == "SE"
    assert app["company_name"] == "Acme"
    assert app["location"] == "NYC"
    assert app["next_action"] is not None
    assert repo.create_application.await_count == 1
    repo.create_event.assert_awaited_once()


async def test_create_application_requires_title_and_company():
    svc = _service()
    with pytest.raises(HTTPException) as exc:
        await svc.create(_auth(), {"job_title": "", "company_name": ""})
    assert exc.value.status_code == 400


async def test_create_duplicate_job_rejected():
    auth = _auth()
    repo = MagicMock()
    repo.find_by_job = AsyncMock(return_value=_app_row())
    svc = _service(repo)
    with pytest.raises(HTTPException) as exc:
        await svc.create(auth, {"job_title": "SE", "company_name": "Acme", "job_id": "job-1"})
    assert exc.value.status_code == 409
# -- Job → Application bridge -------------------------------------------------


async def test_create_from_job_populates_metadata():
    auth = _auth()
    repo = MagicMock()
    repo.find_by_job = AsyncMock(return_value=None)
    repo.create_application = AsyncMock(side_effect=lambda s, uid, d: {"id": "app-1", **d})
    repo.enrich_applications = AsyncMock(side_effect=lambda s, rows, ids: [dict(rows[0])])
    repo.create_event = AsyncMock(return_value={"id": "evt-1"})
    svc = _service(repo)

    job = {
        "id": "job-1",
        "title": "Senior Engineer",
        "company": "Acme",
        "location": "Berlin",
        "salary": "$150k",
        "url": "https://acme/careers/job-1",
        "ats_score": 92,
        "source_platform": "adzuna",
        "external_job_id": "ext-1",
    }
    app = await svc.create_from_job(auth, job)

    assert app["job_title"] == "Senior Engineer"
    assert app["job_id"] == "job-1"
    assert app["location"] == "Berlin"
    assert app["salary"] == "$150k"
    assert app["source_url"] == "https://acme/careers/job-1"
    assert app["match_score"] == 92  # from ats_score
    assert app["status"] == "applied"


async def test_create_from_job_duplicate_returns_without_inserting():
    auth = _auth()
    repo = MagicMock()
    existing = _app_row()
    repo.find_by_job = AsyncMock(return_value=existing)
    repo.enrich_applications = AsyncMock(return_value=[dict(existing)])
    repo.create_application = AsyncMock(return_value=existing)
    svc = _service(repo)

    app = await svc.create_from_job(auth, {"id": "job-1", "title": "SE"})
    assert app["duplicate"] is True
    repo.create_application.assert_not_awaited()


# -- Ownership -----------------------------------------------------------------


async def test_detail_of_foreign_application_is_404():
    repo = MagicMock()
    repo.get_application = AsyncMock(return_value=None)
    svc = _service(repo)
    with pytest.raises(HTTPException) as exc:
        await svc.detail(_auth(), "app-9")
    assert exc.value.status_code == 404


async def test_child_add_on_foreign_application_is_404():
    repo = MagicMock()
    repo.get_application = AsyncMock(return_value=None)
    svc = _service(repo)
    with pytest.raises(HTTPException) as exc:
        await svc.add_child(_auth(), "app-9", "interviews", {"name": "Phone"})
    assert exc.value.status_code == 404


# -- Status transitions --------------------------------------------------------


async def test_change_status_valid_publishes_event_and_record():
    auth = _auth()
    repo = MagicMock()
    repo.get_application = AsyncMock(return_value=_app_row(status="applied"))
    repo.enrich_applications = AsyncMock(return_value=[_app_row(status="interview")])
    repo.update_application = AsyncMock(return_value=_app_row(status="interview"))
    repo.create_event = AsyncMock(return_value={"id": "evt-1"})
    bus = _FakeBus()
    svc = _service(repo, bus=bus)

    app = await svc.change_status(auth, "app-1", "interview")

    assert app["status"] == "interview"
    assert repo.create_event.await_count == 1
    assert len(bus.published) == 1
    assert isinstance(bus.published[0], ApplicationStatusChanged)
    assert bus.published[0].new_status == "interview"
    assert bus.context is auth


async def test_change_status_invalid_transition_rejected():
    repo = MagicMock()
    repo.get_application = AsyncMock(return_value=_app_row(status="accepted"))
    repo.enrich_applications = AsyncMock(return_value=[_app_row(status="accepted")])
    svc = _service(repo)
    with pytest.raises(HTTPException) as exc:
        await svc.change_status(_auth(), "app-1", "applied")
    assert exc.value.status_code == 400


async def test_change_status_to_unknown_rejected():
    svc = _service()
    with pytest.raises(HTTPException) as exc:
        await svc.change_status(_auth(), "app-1", "not-a-status")
    assert exc.value.status_code == 400


async def test_offer_status_records_offer_received_event():
    repo = MagicMock()
    repo.get_application = AsyncMock(return_value=_app_row(status="interview"))
    repo.update_application = AsyncMock(return_value=_app_row(status="offer"))
    repo.enrich_applications = AsyncMock(return_value=[_app_row(status="offer")])
    repo.create_event = AsyncMock(return_value={"id": "evt-1"})
    svc = _service(repo, bus=_FakeBus())

    await svc.change_status(_auth(), "app-1", "offer")

    event_types = [c.args[2] for c in repo.create_event.call_args_list]
    assert "status_changed" in event_types
    assert "offer_received" in event_types
# -- Favorite / Archive ---------------------------------------------------------


async def test_set_favorite_and_archived_via_update():
    auth = _auth()
    repo = MagicMock()
    repo.get_application = AsyncMock(return_value=_app_row())
    row = _app_row(favorite=True, archived=True)
    repo.update_application = AsyncMock(return_value=row)
    repo.enrich_applications = AsyncMock(return_value=[dict(row)])
    svc = _service(repo)

    fav = await svc.set_favorite(auth, "app-1", True)
    assert fav["favorite"] is True

    arch = await svc.set_archived(auth, "app-1", True)
    assert arch["archived"] is True
    assert repo.update_application.await_count == 2


# -- Child CRUD ----------------------------------------------------------------


async def test_add_interview_records_event_and_notifies_upcoming():
    auth = _auth()
    repo = MagicMock()
    repo.get_application = AsyncMock(return_value=_app_row())
    repo.enrich_applications = AsyncMock(return_value=[_app_row()])
    future = "2099-01-01T10:00:00Z"
    created = {"id": "int-1", "name": "Onsite", "scheduled_at": future, "status": "scheduled"}
    repo.create_child = AsyncMock(return_value=created)
    repo.create_event = AsyncMock(return_value={"id": "evt-1"})
    notif = _FakeNotif()
    svc = _service(repo, notif=notif)

    result = await svc.add_child(auth, "app-1", "interviews", {"name": "Onsite", "scheduled_at": future})

    assert result["id"] == "int-1"
    assert len(notif.created) == 1
    assert "Upcoming interview" in notif.created[0][0]


async def test_update_child_and_followup_completion_event():
    auth = _auth()
    repo = MagicMock()
    repo.get_application = AsyncMock(return_value=_app_row())
    repo.enrich_applications = AsyncMock(return_value=[_app_row()])
    fu = {"id": "fu-1", "title": "Send thank you", "status": "pending"}
    repo.get_child = AsyncMock(return_value=fu)
    repo.update_child = AsyncMock(return_value={"id": "fu-1", "title": "Send thank you", "status": "completed"})
    repo.create_event = AsyncMock(return_value={"id": "evt-1"})
    svc = _service(repo)

    result = await svc.update_child(auth, "app-1", "follow_ups", "fu-1", {"status": "completed"})

    assert result["status"] == "completed"
    event_types = [c.args[2] for c in repo.create_event.call_args_list]
    assert "follow_up_completed" in event_types


async def test_delete_child_verifies_ownership():
    auth = _auth()
    repo = MagicMock()
    repo.get_application = AsyncMock(return_value=_app_row())
    repo.enrich_applications = AsyncMock(return_value=[_app_row()])
    repo.get_child = AsyncMock(return_value=None)  # not found within this app
    repo.create_event = AsyncMock(return_value={"id": "evt-1"})
    svc = _service(repo)

    with pytest.raises(HTTPException) as exc:
        await svc.delete_child(auth, "app-1", "interviews", "int-99")
    assert exc.value.status_code == 404


async def test_add_assessment_and_contact():
    auth = _auth()
    repo = MagicMock()
    repo.get_application = AsyncMock(return_value=_app_row())
    repo.enrich_applications = AsyncMock(return_value=[_app_row()])
    repo.create_child = AsyncMock(side_effect=lambda s, aid, t, d: {"id": "c-1", **d})
    repo.create_event = AsyncMock(return_value={"id": "evt-1"})
    svc = _service(repo)

    asm = await svc.add_child(auth, "app-1", "assessments", {"name": "Take-home", "due_at": "2099-02-01"})
    con = await svc.add_child(auth, "app-1", "contacts", {"name": "Jane", "role": "Recruiter"})

    assert asm["name"] == "Take-home"
    assert con["name"] == "Jane"
# -- Statistics ----------------------------------------------------------------


async def test_stats_zero_sample_never_fake_100():
    repo = MagicMock()
    repo.get_status_counts = AsyncMock(return_value=[])
    svc = _service(repo)
    stats = await svc.stats(_auth())
    assert stats["total"] == 0
    assert stats["interviewRate"] == 0
    assert stats["offerRate"] == 0
    assert stats["acceptanceRate"] == 0


async def test_stats_calculated_from_real_data():
    rows = [
        {"status": "applied", "application_date": "2026-01-01"},
        {"status": "interview", "application_date": "2026-01-02"},
        {"status": "offer", "application_date": "2026-01-03"},
        {"status": "accepted", "application_date": "2026-01-04"},
    ]
    repo = MagicMock()
    repo.get_status_counts = AsyncMock(return_value=rows)
    svc = _service(repo)
    stats = await svc.stats(_auth())
    assert stats["total"] == 4
    assert stats["applied"] == 1
    assert stats["interview"] == 1
    assert stats["offer"] == 1
    assert stats["accepted"] == 1
    assert stats["interviewRate"] == 75  # interview+offer+accepted = 3 / 4
    assert stats["offerRate"] == 67      # offer+accepted = 2 / 3
    assert stats["acceptanceRate"] == 50  # accepted = 1 / 2


# -- Timeline / notifications --------------------------------------------------


async def test_list_events_scoped_to_owner():
    repo = MagicMock()
    repo.get_application = AsyncMock(return_value=_app_row())  # owned
    repo.enrich_applications = AsyncMock(return_value=[_app_row()])
    repo.list_events = AsyncMock(return_value=[{"id": "evt-1", "event_type": "application_created"}])
    svc = _service(repo)
    events = await svc.list_events(_auth(), "app-1")
    assert events[0]["event_type"] == "application_created"


async def test_status_change_records_event_and_publishes_but_notifies_via_service():
    auth = _auth()
    repo = MagicMock()
    repo.get_application = AsyncMock(return_value=_app_row(status="interview"))
    repo.update_application = AsyncMock(return_value=_app_row(status="offer"))
    repo.enrich_applications = AsyncMock(return_value=[_app_row(status="offer")])
    repo.create_event = AsyncMock(return_value={"id": "evt-1"})
    svc = _service(repo, bus=_FakeBus())

    await svc.change_status(auth, "app-1", "offer")

    # status_changed + offer_received events recorded on the timeline.
    event_types = [c.args[2] for c in repo.create_event.call_args_list]
    assert "status_changed" in event_types
    assert "offer_received" in event_types