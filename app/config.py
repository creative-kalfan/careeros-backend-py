"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed access to environment variables for the CareerOS backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Supabase project credentials.
    supabase_url: str = Field(alias="NEXT_PUBLIC_SUPABASE_URL")
    supabase_anon_key: str = Field(alias="NEXT_PUBLIC_SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field(alias="SUPABASE_SERVICE_ROLE_KEY")

    # Optional: enables extra debug logging from the auth service.
    auth_debug_enabled: bool = Field(default=False, alias="AUTH_DEBUG_ENABLED")

    # Redis / ARQ background worker configuration.
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")

    # Crawl concurrency-lock TTL (seconds). Must exceed the maximum expected
    # crawl duration so a stale lock never permanently blocks a company.
    crawl_lock_ttl_seconds: int = Field(default=300, alias="CRAWL_LOCK_TTL_SECONDS")

    # LLM Gateway (backend-only credentials; empty key = provider unconfigured).
    llm_default_provider: str = Field(default="groq", alias="LLM_DEFAULT_PROVIDER")
    llm_groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    llm_groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    llm_gemini_api_key: str = Field(default="", alias="GOOGLE_GEMINI_API_KEY")
    llm_gemini_model: str = Field(default="gemini-2.0-flash", alias="GOOGLE_GEMINI_MODEL")
    llm_mistral_api_key: str = Field(default="", alias="MISTRAL_API_KEY")
    llm_mistral_model: str = Field(default="mistral-small-latest", alias="MISTRAL_MODEL")
    llm_openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    llm_openrouter_model: str = Field(default="openai/gpt-4o-mini", alias="OPENROUTER_MODEL")

    # Job lifecycle: jobs not seen (or posted) within this window are deactivated.
    job_stale_after_days: int = Field(default=30, alias="JOB_STALE_AFTER_DAYS")

    # ---- Scheduled job-refresh orchestration ----
    # Master switch for the scheduled crawl runner (FastAPI process).
    job_crawl_enabled: bool = Field(default=True, alias="JOB_CRAWL_ENABLED")
    # YC Work at a Startup: high-priority, frequent.
    yc_crawl_enabled: bool = Field(default=True, alias="YC_CRAWL_ENABLED")
    yc_crawl_interval_hours: float = Field(default=24, alias="YC_CRAWL_INTERVAL_HOURS")
    # Firecrawl official company career pages: daily.
    firecrawl_enabled: bool = Field(default=True, alias="FIRECRAWL_ENABLED")
    firecrawl_crawl_interval_hours: float = Field(default=24, alias="FIRECRAWL_CRAWL_INTERVAL_HOURS")
    # Direct official ATS boards: daily.
    ats_crawl_interval_hours: float = Field(default=24, alias="ATS_CRAWL_INTERVAL_HOURS")
    # Aggregators: least frequent.
    aggregator_crawl_interval_hours: float = Field(default=24, alias="AGGREGATOR_CRAWL_INTERVAL_HOURS")
    # Legacy single-interval override: when set, it wins over the per-provider
    # intervals above (kept for existing deployments).
    crawl_interval_hours: Optional[float] = Field(default=None, alias="CRAWL_INTERVAL_HOURS")

    # Firecrawl (backend-only credential; empty key = Firecrawl unconfigured).
    firecrawl_api_key: str = Field(default="", alias="FIRECRAWL_API_KEY")
    firecrawl_api_url: str = Field(default="https://api.firecrawl.dev/v1", alias="FIRECRAWL_API_URL")
    firecrawl_timeout_seconds: float = Field(default=30.0, alias="FIRECRAWL_TIMEOUT_SECONDS")
    firecrawl_max_retries: int = Field(default=3, alias="FIRECRAWL_MAX_RETRIES")
    firecrawl_max_pages_per_crawl: int = Field(default=15, alias="FIRECRAWL_MAX_PAGES_PER_CRAWL")

    # Observability.
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")
    sentry_environment: str = Field(default="development", alias="SENTRY_ENVIRONMENT")

    # CORS: comma-separated list of allowed origins for production.
    # Falls back to localhost dev origins when empty.
    cors_allowed_origins: str = Field(default="", alias="CORS_ALLOWED_ORIGINS")

    # Resume upload size guard (bytes). Files larger than this are rejected
    # before the expensive text-extraction / parsing step. Configurable via
    # MAX_RESUME_UPLOAD_BYTES (default 10 MB).
    max_resume_upload_bytes: int = Field(
        default=10 * 1024 * 1024,
        alias="MAX_RESUME_UPLOAD_BYTES",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (env vars are read once)."""
    return Settings()