"""Centralized registry of CareerOS background jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional


from enum import Enum


class WorkloadClass(str, Enum):
    """Centralized classification of background job workloads."""

    CRITICAL_USER = "critical_user"
    CRAWL = "crawl"
    ANALYSIS = "analysis"
    EMBEDDING = "embedding"
    MAINTENANCE = "maintenance"
    NOTIFICATION = "notification"
    OTHER = "other"


@dataclass(frozen=True)
class JobDefinition:
    """Metadata for a registered background job."""

    name: str
    callable: Callable[..., Awaitable[dict[str, Any]]]
    timeout: int = 300
    max_tries: int = 2
    retry: bool = True
    description: str = ""
    workload_class: WorkloadClass = WorkloadClass.OTHER


# Registry of all known CareerOS background jobs.
_REGISTRY: dict[str, JobDefinition] = {}


def register_job(
    name: str,
    *,
    timeout: int = 300,
    max_tries: int = 2,
    retry: bool = True,
    description: str = "",
    workload_class: WorkloadClass = WorkloadClass.OTHER,
) -> Callable[[Callable[..., Awaitable[dict[str, Any]]]], Callable[..., Awaitable[dict[str, Any]]]]:
    """Decorator to register a background job in the CareerOS registry."""
    def decorator(func: Callable[..., Awaitable[dict[str, Any]]]) -> Callable[..., Awaitable[dict[str, Any]]]:
        _REGISTRY[name] = JobDefinition(
            name=name,
            callable=func,
            timeout=timeout,
            max_tries=max_tries,
            retry=retry,
            description=description or func.__doc__ or "",
            workload_class=workload_class,
        )
        return func
    return decorator


def get_job_definition(name: str) -> JobDefinition:
    """Return the job definition for *name*, or raise ``KeyError``."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown job: {name}. Registered jobs: {list(_REGISTRY.keys())}")
    return _REGISTRY[name]


def get_registered_jobs() -> list[JobDefinition]:
    """Return all registered job definitions."""
    return list(_REGISTRY.values())


def clear_registry() -> None:
    """Clear the registry (test helper)."""
    _REGISTRY.clear()

