"""Reusable structured logging helpers for CareerOS background jobs."""

from __future__ import annotations

import logging
import time
from typing import Any


logger = logging.getLogger(__name__)


class JobLogger:
    """Structured logger wrapper for background jobs."""

    def __init__(self, job_id: str, job_type: str, **extra: Any) -> None:
        self.job_id = job_id
        self.job_type = job_type
        self.extra = extra
        self._start = time.monotonic()

    def _prefix(self, status: str, **fields: Any) -> str:
        parts = [
            f"job_id={self.job_id}",
            f"job_type={self.job_type}",
            f"status={status}",
        ]
        for key, value in fields.items():
            parts.append(f"{key}={value}")
        for key, value in self.extra.items():
            parts.append(f"{key}={value}")
        return " ".join(parts)

    def started(self) -> None:
        logger.info("JOB %s", self._prefix("started"))

    def processing(self, **fields: Any) -> None:
        logger.info("JOB %s", self._prefix("processing", **fields))

    def completed(self, duration_ms: int, status: str = "completed", **fields: Any) -> None:
        logger.info("JOB %s", self._prefix(status, duration_ms=duration_ms, **fields))

    def failed(self, duration_ms: int, error_type: str, **fields: Any) -> None:
        logger.error(
            "JOB %s",
            self._prefix("failed", duration_ms=duration_ms, error_type=error_type, **fields),
        )
