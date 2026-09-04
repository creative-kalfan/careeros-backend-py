"""Application service: orchestration/use-case layer for Application Tracking.

Routes stay thin; all business logic (lifecycle transitions, timeline event
generation, job → application bridging, notifications, statistics, ownership)
lives here. Persistence goes through :class:`ApplicationRepository` using the
RLS-authenticated Supabase client from ``AuthContext`` (never the service role).

Status changes publish :class:`ApplicationStatusChanged` on the in-process
EventBus and generate in-app notifications by REUSING the existing
``NotificationService`` — no new notification/worker infrastructure.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException

from app.models.application import (
    APPLICATION_STATUSES,
    event_payload,
    is_valid_status,
    next_action_for,
    progress_for_status,
    validate_transition,
)
from app.repositories.application_repository import ApplicationRepository

logger = logging.getLogger(__name__)

_UPDATABLE_APP_FIELDS = (
    "job_title",
    "company_name",
    "notes",
    "location",
    "salary",
    "match_score",
    "source_url",
)


def _clean(d: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k in keys and v is not None}


def _progress(status: str) -> int:
    return progress_for_status(status)


def _or_not_now(value: Any) -> Optional[datetime]:
    """Parse a datetime-ish value into a NAIVE UTC datetime (comparison-safe)."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


class ApplicationService:
    """Use-case layer for the application lifecycle and Mission Control data."""

    def __init__(
        self,
        repository: Optional[ApplicationRepository] = None,
        bus: Any = None,
        notification_service: Any = None,
    ) -> None:
        self.repository = repository or ApplicationRepository()
        self.bus = bus
        self.notification_service = notification_service

    # -- DI helpers -----------------------------------------------------------

    def _get_bus(self) -> Any:
        if self.bus is not None:
            return self.bus
        from app.events.runtime import get_event_bus

        return get_event_bus()

    def _get_notifications(self) -> Any:
        if self.notification_service is not None:
            return self.notification_service
        from app.services.notifications.notification_service import NotificationService

        return NotificationService()

    # -- Shared helpers -------------------------------------------------------

    async def _get_enriched(self, auth: Any, app_id: str) -> Optional[dict[str, Any]]:
        app = await self.repository.get_application(auth.supabase, auth.user.id, app_id)
        if app is None:
            return None
        (enriched,) = await self.repository.enrich_applications(
            auth.supabase, [app], [str(app["id"])]
        )
        return self._attach_derived(enriched)

    async def _get_owned_or_404(self, auth: Any, app_id: str) -> dict[str, Any]:
        app = await self._get_enriched(auth, app_id)
        if app is None:
            raise HTTPException(status_code=404, detail="Application not found")
        return app

    @staticmethod
    def _attach_derived(app: dict[str, Any]) -> dict[str, Any]:
        """Attach derived, non-persisted fields (progress + next action)."""
        app["next_action"] = next_action_for(app)
        app["progress"] = _progress(app.get("status", "applied"))
        return app

    # -- Retrieval ------------------------------------------------------------

    async def list(self, auth: Any, **filters: Any) -> dict[str, Any]:
        page = filters.pop("page", 1)
        page_size = filters.pop("page_size", 20)
        status = filters.pop("status", None)
        search = filters.pop("search", None)
        rows, total = await self.repository.list_applications(
            auth.supabase, auth.user.id, status=status, search=search, page=page, page_size=page_size
        )
        app_ids = [str(r["id"]) for r in rows]
        enriched = await self.repository.enrich_applications(auth.supabase, rows, app_ids)
        for app in enriched:
            self._attach_derived(app)
        return {"applications": enriched, "total": total}

    async def detail(self, auth: Any, app_id: str) -> dict[str, Any]:
        return await self._get_owned_or_404(auth, app_id)
# -- Creation -----------------------------------------------------------------

    async def create(self, auth: Any, data: dict[str, Any]) -> dict[str, Any]:
        job_title = (data.get("job_title") or "").strip()
        company_name = (data.get("company_name") or "").strip()
        if not job_title or not company_name:
            raise HTTPException(status_code=400, detail="job_title and company_name are required")

        status = data.get("status") or "applied"
        if not is_valid_status(status):
            raise HTTPException(status_code=400, detail=f"Invalid status '{status}'")

        job_id = data.get("job_id")
        if job_id:
            dup = await self.repository.find_by_job(auth.supabase, auth.user.id, job_id)
            if dup is not None:
                raise HTTPException(
                    status_code=409, detail="This job is already tracked as an application"
                )

        app_data = {
            "job_title": job_title,
            "company_name": company_name,
            "status": status,
            "application_date": data.get("application_date")
            or datetime.utcnow().date().isoformat(),
            "notes": data.get("notes"),
            "job_id": job_id,
            "company_id": data.get("company_id"),
            "location": data.get("location"),
            "salary": data.get("salary"),
            "match_score": data.get("match_score"),
            "source_url": data.get("source_url"),
            "source_platform": data.get("source_platform"),
            "external_job_id": data.get("external_job_id"),
        }
        app = await self.repository.create_application(auth.supabase, auth.user.id, app_data)
        app_id = str(app["id"])
        await self._record_event(
            auth, app_id, "application_created",
            {"job_title": job_title, "company_name": company_name},
        )
        (enriched,) = await self.repository.enrich_applications(auth.supabase, [app], [app_id])
        return self._attach_derived(enriched)

    async def create_from_job(self, auth: Any, job: dict[str, Any]) -> dict[str, Any]:
        """Track a real job as an application (the Job → Application bridge)."""
        job_id = str(job["id"])
        dup = await self.repository.find_by_job(auth.supabase, auth.user.id, job_id)
        if dup is not None:
            (enriched,) = await self.repository.enrich_applications(
                auth.supabase, [dup], [str(dup["id"])]
            )
            self._attach_derived(enriched)
            enriched["duplicate"] = True
            return enriched

        match_score: Optional[int] = None
        ats_score = job.get("ats_score")
        if isinstance(ats_score, (int, float)):
            match_score = int(ats_score)
        elif isinstance(job.get("match"), dict) and isinstance(
            job["match"].get("total"), (int, float)
        ):
            match_score = int(job["match"]["total"])

        app_data = {
            "job_title": job.get("title") or "Untitled role",
            "company_name": job.get("company") or "Unknown company",
            "job_id": job_id,
            "company_id": job.get("company_id"),
            "status": "applied",
            "application_date": datetime.utcnow().date().isoformat(),
            "location": job.get("location"),
            "salary": job.get("salary"),
            "match_score": match_score,
            "source_url": job.get("url") or job.get("canonical_url") or job.get("apply_url"),
            "source_platform": job.get("source_platform") or job.get("source"),
            "external_job_id": job.get("external_job_id"),
        }
        app = await self.repository.create_application(auth.supabase, auth.user.id, app_data)
        app_id = str(app["id"])
        await self._record_event(
            auth, app_id, "application_created",
            {"job_title": app_data["job_title"], "company_name": app_data["company_name"]},
        )
        (enriched,) = await self.repository.enrich_applications(auth.supabase, [app], [app_id])
        return self._attach_derived(enriched)
# -- Update -------------------------------------------------------------------

    async def update(self, auth: Any, app_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        await self._get_owned_or_404(auth, app_id)
        allowed = dict(_clean(updates, _UPDATABLE_APP_FIELDS))
        for flag in ("favorite", "archived"):
            if flag in updates and isinstance(updates[flag], bool):
                allowed[flag] = updates[flag]
        if not allowed:
            raise HTTPException(status_code=400, detail="No valid fields to update")
        allowed["updated_at"] = datetime.utcnow().isoformat()
        updated = await self.repository.update_application(
            auth.supabase, auth.user.id, app_id, allowed
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Application not found")
        (enriched,) = await self.repository.enrich_applications(
            auth.supabase, [updated], [app_id]
        )
        return self._attach_derived(enriched)

    async def change_status(self, auth: Any, app_id: str, new_status: str) -> dict[str, Any]:
        if not is_valid_status(new_status):
            raise HTTPException(status_code=400, detail=f"Invalid status '{new_status}'")

        # Authoritative status comes from the raw owned row (never the enriched copy).
        raw = await self.repository.get_application(auth.supabase, auth.user.id, app_id)
        if raw is None:
            raise HTTPException(status_code=404, detail="Application not found")
        previous = raw.get("status", "applied")
        if previous == new_status:
            raise HTTPException(status_code=400, detail=f"Status is already '{new_status}'")
        try:
            validate_transition(previous, new_status)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        updated = await self.repository.update_application(
            auth.supabase,
            auth.user.id,
            app_id,
            {"status": new_status, "updated_at": datetime.utcnow().isoformat()},
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Application not found")

        await self._record_event(
            auth, app_id, "status_changed",
            {"previous_status": previous, "new_status": new_status},
        )
        event_mapping = {
            "offer": "offer_received",
            "accepted": "application_accepted",
            "rejected": "application_rejected",
        }
        if new_status in event_mapping:
            await self._record_event(auth, app_id, event_mapping[new_status], {})

        await self._publish_status_change(auth, app_id, previous, new_status)

        (enriched,) = await self.repository.enrich_applications(
            auth.supabase, [updated], [app_id]
        )
        enriched = self._attach_derived(enriched)
        logger.info("Application %s status changed %s -> %s", app_id, previous, new_status)
        return enriched

    async def set_favorite(self, auth: Any, app_id: str, favorite: bool) -> dict[str, Any]:
        return await self.update(auth, app_id, {"favorite": favorite})

    async def set_archived(self, auth: Any, app_id: str, archived: bool) -> dict[str, Any]:
        return await self.update(auth, app_id, {"archived": archived})

    async def delete(self, auth: Any, app_id: str) -> None:
        await self._get_owned_or_404(auth, app_id)
        deleted = await self.repository.delete_application(auth.supabase, auth.user.id, app_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Application not found")
# -- Child entity CRUD --------------------------------------------------------

    _CHILD_TABLE = {
        "interviews": "application_interviews",
        "assessments": "application_assessments",
        "contacts": "application_contacts",
        "follow_ups": "application_follow_ups",
        "attachments": "application_attachments",
    }

    _CHILD_KEYS = {
        "interviews": ("name", "scheduled_at", "status", "interviewer", "notes"),
        "assessments": ("name", "due_at", "status", "notes", "result"),
        "contacts": ("name", "role", "email", "phone", "notes"),
        "follow_ups": ("title", "due_at", "status", "notes"),
        "attachments": ("name", "kind", "size_bytes", "storage_path"),
    }

    def _event_for(self, child_type: str, op: str) -> str:
        mapping = {
            "interviews": {"add": "interview_added", "update": "interview_updated", "delete": "interview_deleted"},
            "assessments": {"add": "assessment_added", "update": "assessment_updated", "delete": "assessment_deleted"},
            "contacts": {"add": "contact_added"},
            "follow_ups": {"add": "follow_up_created", "complete": "follow_up_completed"},
        }
        return mapping.get(child_type, {}).get(op, f"{child_type}_{op}")

    async def add_child(self, auth: Any, app_id: str, child_type: str, data: dict[str, Any]) -> dict[str, Any]:
        table = self._CHILD_TABLE.get(child_type)
        if table is None:
            raise HTTPException(status_code=400, detail=f"Unknown child entity '{child_type}'")
        await self._get_owned_or_404(auth, app_id)
        keys = self._CHILD_KEYS[child_type]
        payload = _clean(data, keys)
        if child_type in ("interviews", "contacts") and not payload.get("name"):
            raise HTTPException(status_code=400, detail=f"{child_type} requires name")
        if child_type == "follow_ups" and not payload.get("title"):
            raise HTTPException(status_code=400, detail="follow_ups requires title")
        if not payload:
            raise HTTPException(status_code=400, detail="No valid fields to add")
        row = await self.repository.create_child(auth.supabase, app_id, table, payload)
        await self._record_event(auth, app_id, self._event_for(child_type, "add"), payload)
        if child_type == "interviews":
            await self._maybe_notify_upcoming_interview(auth, payload)
        return row

    async def update_child(
        self, auth: Any, app_id: str, child_type: str, child_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        table = self._CHILD_TABLE.get(child_type)
        if table is None:
            raise HTTPException(status_code=400, detail=f"Unknown child entity '{child_type}'")
        await self._get_owned_or_404(auth, app_id)
        existing = await self.repository.get_child(auth.supabase, app_id, table, child_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"{child_type[:-1]} not found")
        payload = _clean(data, self._CHILD_KEYS[child_type])
        if not payload:
            raise HTTPException(status_code=400, detail="No valid fields to update")
        payload["updated_at"] = datetime.utcnow().isoformat()
        row = await self.repository.update_child(auth.supabase, app_id, table, child_id, payload)
        if row is None:
            raise HTTPException(status_code=404, detail=f"{child_type[:-1]} not found")
        if child_type == "follow_ups" and payload.get("status") == "completed":
            await self._record_event(auth, app_id, "follow_up_completed", {"title": row.get("title")})
        else:
            await self._record_event(auth, app_id, self._event_for(child_type, "update"), payload)
        return row

    async def delete_child(self, auth: Any, app_id: str, child_type: str, child_id: str) -> dict[str, Any]:
        table = self._CHILD_TABLE.get(child_type)
        if table is None:
            raise HTTPException(status_code=400, detail=f"Unknown child entity '{child_type}'")
        await self._get_owned_or_404(auth, app_id)
        existing = await self.repository.get_child(auth.supabase, app_id, table, child_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"{child_type[:-1]} not found")
        await self.repository.delete_child(auth.supabase, app_id, table, child_id)
        await self._record_event(auth, app_id, self._event_for(child_type, "delete"), {})
        return {"id": child_id, "deleted": True}

    async def list_events(self, auth: Any, app_id: str) -> list[dict[str, Any]]:
        await self._get_owned_or_404(auth, app_id)
        return await self.repository.list_events(auth.supabase, app_id)
# -- Statistics ---------------------------------------------------------------

    async def stats(self, auth: Any) -> dict[str, Any]:
        """Compute statistics from real application data.

        Conversion rates fall back to ``0`` (never a fake 100%) when the
        relevant sample (denominator) is zero.
        """
        rows = await self.repository.get_status_counts(auth.supabase, auth.user.id, archived=False)
        total = len(rows)

        by_status: dict[str, int] = {s: 0 for s in APPLICATION_STATUSES}
        for row in rows:
            st = row.get("status", "")
            if st in by_status:
                by_status[st] += 1

        active = total - by_status["rejected"] - by_status["withdrawn"]
        with_interviews = by_status["interview"] + by_status["offer"] + by_status["accepted"]
        with_offers = by_status["offer"] + by_status["accepted"]
        accepted = by_status["accepted"]

        active_this_week = self._count_this_week(rows)

        interview_rate = round((with_interviews / total) * 100) if total > 0 else 0
        offer_rate = round((with_offers / with_interviews) * 100) if with_interviews > 0 else 0
        acceptance_rate = round((accepted / with_offers) * 100) if with_offers > 0 else 0

        return {
            "total": total,
            "active": active,
            "byStatus": by_status,
            "applied": by_status["applied"],
            "screening": by_status["screening"],
            "assessment": by_status["assessment"],
            "interview": by_status["interview"],
            "offer": by_status["offer"],
            "accepted": accepted,
            "rejected": by_status["rejected"],
            "withdrawn": by_status["withdrawn"],
            "saved": by_status["saved"],
            "interviewRate": interview_rate,
            "offerRate": offer_rate,
            "acceptanceRate": acceptance_rate,
            "activeThisWeek": active_this_week,
            "streakDays": self._streak_days(rows),
        }

    @staticmethod
    def _count_this_week(rows: list[dict[str, Any]]) -> int:
        from datetime import timedelta

        now = datetime.utcnow()
        monday = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        count = 0
        for row in rows:
            dt = _or_not_now(row.get("application_date"))
            if dt is not None and monday <= dt <= now:
                count += 1
        return count

    @staticmethod
    def _streak_days(rows: list[dict[str, Any]]) -> int:
        from datetime import timedelta

        dates: set[str] = set()
        for row in rows:
            dt = _or_not_now(row.get("application_date"))
            if dt is not None:
                dates.add(dt.date().isoformat())
        if not dates:
            return 0
        current = datetime.utcnow().date()
        streak = 0
        for _ in range(366):
            if current.isoformat() in dates:
                streak += 1
                current -= timedelta(days=1)
            else:
                break
        return streak

    # -- Internal helpers ------------------------------------------------------

    async def _record_event(
        self, auth: Any, app_id: str, event_type: str, context: dict[str, Any]
    ) -> None:
        payload = event_payload(event_type, context)
        try:
            await self.repository.create_event(
                auth.supabase,
                app_id,
                event_type,
                payload.get("title", event_type),
                payload.get("detail"),
                metadata=context,
            )
        except Exception as exc:  # noqa: BLE001 - must not break the mutation
            logger.debug("record_event %s failed: %s", event_type, exc)

    async def _publish_status_change(
        self, auth: Any, app_id: str, previous: str, new_status: str
    ) -> None:
        from app.events import ApplicationStatusChanged

        try:
            await self._get_bus().publish(
                ApplicationStatusChanged(
                    application_id=app_id,
                    previous_status=previous,
                    new_status=new_status,
                    aggregate_id=app_id,
                    user_id=auth.user.id,
                ),
                context=auth,
            )
        except Exception as exc:  # noqa: BLE001 - handler failures are isolated by design
            logger.debug("publish status change for %s failed: %s", app_id, exc)

    async def _maybe_notify_upcoming_interview(self, auth: Any, payload: dict[str, Any]) -> None:
        when = _or_not_now(payload.get("scheduled_at"))
        if when is None or when <= datetime.utcnow():
            return
        app_title = payload.get("name", "Interview")
        try:
            svc = self._get_notifications()
            await svc.create_notification(
                auth,
                "APPLICATION_EVENT",
                f"Upcoming interview: {app_title}",
                f"Your interview is scheduled for {when.isoformat()}.",
                payload={"kind": "interview_upcoming", "scheduled_at": when.isoformat()},
                priority="medium",
            )
        except Exception as exc:  # noqa: BLE001 - notifications must not break interviews
            logger.debug("upcoming interview notification failed: %s", exc)
