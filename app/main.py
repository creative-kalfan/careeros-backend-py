"""FastAPI application entrypoint for the CareerOS backend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class ExceptionEnvelopeMiddleware:
    """Convert unhandled exceptions into the CareerOS JSON error envelope.

    Starlette installs ``@app.exception_handler(Exception)`` into
    ``ServerErrorMiddleware``, which sits OUTSIDE ``CORSMiddleware``. A bare
    500 produced there has no CORS headers, so the browser misleadingly
    reports the failure as "blocked by CORS policy" instead of showing the
    real backend error. This middleware runs INSIDE the CORS layer, so its
    responses always carry ``Access-Control-Allow-Origin``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except Exception:
            logger.exception(
                "Unhandled exception on %s %s", scope.get("method"), scope.get("path")
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": {
                        "code": "internal_error",
                        "message": "Internal server error. Please try again.",
                    },
                },
            )
            await response(scope, receive, send)

from app.api.routes.jobs import router as jobs_router
from app.api.routes.applications import router as applications_router
from app.api.routes.recommendations import router as recommendations_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.notification_preferences import router as notification_preferences_router
from app.api.routes.profile import router as profile_router
from app.auth.router import router as auth_router

from app.api.routes.export import router as export_router
from app.api.routes.ats import router as ats_router
from app.api.routes.resumes import router as resumes_router
from app.api.routes.versions import router as versions_router
from app.api.routes.improvement import router as improvement_router
from app.api.routes.optimization import router as optimization_router
from app.api.routes.interview_prep import router as interview_prep_router
from app.api.routes.resume_templates import router as templates_router
from app.auth.service import AuthError
from app.config import get_settings
from app.services.jobs.scheduled_crawl_runner import (
    ScheduledCrawlRunner,
)

logger = logging.getLogger(__name__)

_scheduled_runner: ScheduledCrawlRunner | None = None


def _init_sentry() -> None:
    """Initialize Sentry SDK if SENTRY_DSN is configured."""
    settings = get_settings()
    if not settings.sentry_dsn:
        logger.info("SENTRY_DSN not set, backend Sentry disabled")
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            integrations=[
                StarletteIntegration(transaction_style="endpoint"),
                FastApiIntegration(transaction_style="endpoint"),
            ],
            traces_sample_rate=0.1,
            send_default_pii=False,
            before_send=_scrub_pii,
        )
        logger.info("Sentry initialized (env=%s)", settings.sentry_environment)
    except ImportError:
        logger.warning("sentry-sdk not installed, skipping Sentry init")


def _scrub_pii(event: dict, hint: dict) -> dict:
    """Remove sensitive fields from Sentry events."""
    if "request" in event and "headers" in event["request"]:
        headers = event["request"]["headers"]
        sensitive = {"authorization", "cookie", "x-api-key"}
        event["request"]["headers"] = {
            k: "[Filtered]" if k.lower() in sensitive else v
            for k, v in (headers.items() if isinstance(headers, dict) else [])
        }
    return event


DEFAULT_CORS_ORIGINS = [
    "https://careeros-frontend-three.vercel.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]


def _get_cors_origins() -> list[str]:
    """Build CORS origins from env or fall back to canonical defaults.

    Normalizes whitespace and trailing slashes so slight env var
    discrepancies (e.g. trailing slash on Vercel domain) never cause
    silent preflight 400 rejections.
    """
    settings = get_settings()
    origins = [o.rstrip("/") for o in DEFAULT_CORS_ORIGINS]
    if settings.cors_allowed_origins:
        for origin in settings.cors_allowed_origins.split(","):
            cleaned = origin.strip().rstrip("/")
            if cleaned and cleaned not in origins:
                origins.append(cleaned)
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the scheduled crawl runner on server startup, stop on shutdown."""
    global _scheduled_runner
    _init_sentry()
    _scheduled_runner = ScheduledCrawlRunner()
    _scheduled_runner.start()
    logger.info("Scheduled crawl runner started")
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

# ExceptionEnvelopeMiddleware must be registered BEFORE CORSMiddleware so the
# CORS layer wraps it (Starlette's last-added middleware is outermost) and its
# error responses always receive CORS headers.
app.add_middleware(ExceptionEnvelopeMiddleware)

# Explicit, safe CORS allowlist. We never use wildcard `*` for methods/headers:
# a wildcard combined with ``allow_credentials=True`` is rejected by browsers
# and is too permissive anyway. We allow only the HTTP methods and request
# headers the CareerOS frontend actually sends (JSON API + Bearer auth + Sentry distributed tracing).
ALLOWED_CORS_METHODS = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
ALLOWED_CORS_HEADERS = [
    "Authorization",
    "Content-Type",
    "sentry-trace",
    "baggage",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=ALLOWED_CORS_METHODS,
    allow_headers=ALLOWED_CORS_HEADERS,
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert unhandled exceptions into a JSON error envelope.

    Without this, Starlette's ServerErrorMiddleware (which sits OUTSIDE
    CORSMiddleware) returns a bare 500 with no CORS headers, and the browser
    misleadingly reports the failure as "blocked by CORS policy". Returning
    the envelope through the app's exception-handler path keeps the response
    inside the CORS-covered middleware stack.
    """
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": "internal_error",
                "message": "Internal server error. Please try again.",
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
app.include_router(export_router)
app.include_router(ats_router)
app.include_router(resumes_router)
app.include_router(versions_router)
app.include_router(improvement_router)
app.include_router(optimization_router)
app.include_router(interview_prep_router)
app.include_router(templates_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Simple liveness probe."""
    return {"status": "ok"}


@app.get("/version")
async def version() -> dict[str, str]:
    """Version probe to verify deployment."""
    return {"version": "jobs-perf-fix-v1"}