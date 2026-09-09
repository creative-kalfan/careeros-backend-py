"""Dashboard telemetry response schema."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field


class TimelineItem(BaseModel):
    action: str = ""
    description: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict)


class DashboardTelemetryResponse(BaseModel):
    total_resumes: int = 0
    tailored_versions: int = 0
    applications_tracked: int = 0
    average_ats_score: float | None = 0.0
    active_jobs_in_queue: int = 0
    activity_timeline: list[dict[str, Any]] = Field(default_factory=list)


EMPTY_TELEMETRY: dict[str, Any] = {
    "total_resumes": 0,
    "tailored_versions": 0,
    "applications_tracked": 0,
    "average_ats_score": 0.0,
    "active_jobs_in_queue": 0,
    "activity_timeline": [],
}
