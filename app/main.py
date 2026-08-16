"""FastAPI application entrypoint for the CareerOS backend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.jobs import router as jobs_router
from app.api.routes.applications import router as applications_router
from app.api.routes.recommendations import router as recommendations_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.notification_preferences import router as notification_preferences_router
from app.api.routes.profile import router as profile_router
from app.auth.router import router as auth_router
from app.auth.service import AuthError
from app.services.jobs.scheduled_crawl_runner import (
    DEFAULT_INTERVAL_HOURS,
    ScheduledCrawlRunner,
)

logger = logging.getLogger(__name__)

_scheduled_runner: ScheduledCrawlRunner | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the scheduled crawl runner on server startup, stop on shutdown."""
    global _scheduled_runner
    interval_hours = DEFAULT_INTERVAL_HOURS
    _scheduled_runner = ScheduledCrawlRunner(interval_hours=interval_hours)
    _scheduled_runner.start()
    logger.info("Scheduled crawl runner started (every %s hours)", interval_hours)
    yield
    if _scheduled_runner is not None:
        _scheduled_runner.shutdown()
        _scheduled_runner = None

app = FastAPI(
    title="CareerOS Backend (Python)",
    version="0.1.0",
    description="Feature-by-feature reimplementation of the TypeScript CareerOS backend.",
    lifespan=lifespan,
)

# Allow the TanStack frontend (dev server + production) to call this API.
# The frontend runs on a different port during development, so CORS is required.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    """Translate :class:`AuthError` into a JSON HTTP response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Translate :class:`HTTPException` into the standard CareerOS error envelope."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": str(exc.status_code),
                "message": exc.detail,
            },
        },
    )


app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(applications_router)
app.include_router(recommendations_router)
app.include_router(notifications_router)
app.include_router(notification_preferences_router)
app.include_router(profile_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Simple liveness probe."""
    return {"status": "ok"}