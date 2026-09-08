"""Dashboard telemetry response schema."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class TimelineItem(BaseModel):
    action: str
    description: str
    timestamp: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DashboardTelemetryResponse(BaseModel):
    total_resumes: int
    tailored_versions: int
    applications_tracked: int
    average_ats_score: float | None = None
    active_jobs_in_queue: int
    activity_timeline: list[dict[str, Any]] = Field(default_factory=list)
