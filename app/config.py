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

    # ARQ worker queue-poll interval (seconds). Each poll issues one
    # ZRANGEBYSCORE, so this single value dominates the monthly request
    # count on metered plans: 86400/poll_delay requests/day when idle.
    # Default 10s keeps one idle worker at ~8.6k req/day (~259k/month,
    # safe for request-billed plans), leaving headroom for real jobs.
    # The 0.5s ARQ upstream default costs ~173k req/day (~5.2M/month)
    # and must not be restored on metered plans. Non-metered backends
    # (e.g. Aiven Valkey free tier) may lower it via env for faster pickup.
    arq_poll_delay_seconds: float = Field(default=10.0, alias="ARQ_POLL_DELAY_SECONDS")
    arq_poll_delay: float = Field(default=2.0, alias="ARQ_POLL_DELAY")
    arq_connect_timeout: float = Field(default=5.0, alias="ARQ_CONNECT_TIMEOUT")

    # Crawl concurrency-lock TTL (seconds). Must exceed the maximum expected
    # crawl duration so a stale lock never permanently blocks a company.
    crawl_lock_ttl_seconds: int = Field(default=300, alias="CRAWL_LOCK_TTL_SECONDS")
    legacy_apscheduler_enabled: bool = Field(default=False, alias="LEGACY_APSCHEDULER_ENABLED")
    run_scheduler_in_web: bool = Field(default=False, alias="RUN_SCHEDULER_IN_WEB")
    dispatch_tick_seconds: int = Field(default=60, alias="DISPATCH_TICK_SECONDS")
    dispatch_batch: int = Field(default=2, alias="DISPATCH_BATCH")
    crawl_lease_seconds: int = Field(default=900, alias="CRAWL_LEASE_SECONDS")
    # crawl_targets migration 025 re-probe interval (seconds). The dispatcher
    # re-probes the table once the cached result is this old, so applying
    # migration 025 after deploy re-enables dispatch without a restart.
    migration_probe_recheck_seconds: int = Field(default=300, alias="MIGRATION_PROBE_RECHECK_SECONDS")
    crawl_dead_after_failures: int = Field(default=10, alias="CRAWL_DEAD_AFTER_FAILURES")
    crawl_min_interval_minutes: int = Field(default=360, alias="CRAWL_MIN_INTERVAL_MINUTES")
    crawl_max_interval_minutes: int = Field(default=2880, alias="CRAWL_MAX_INTERVAL_MINUTES")
    job_miss_threshold: int = Field(default=2, alias="JOB_MISS_THRESHOLD")
    ats_fetch_concurrency: int = Field(default=10, alias="ATS_FETCH_CONCURRENCY")
    ats_connect_timeout_seconds: float = Field(default=5.0, alias="ATS_CONNECT_TIMEOUT_SECONDS")
    ats_read_timeout_seconds: float = Field(default=20.0, alias="ATS_READ_TIMEOUT_SECONDS")
    discovery_max_probes_per_day: int = Field(default=50, alias="DISCOVERY_MAX_PROBES_PER_DAY")
    slo_overdue_minutes: int = Field(default=120, alias="SLO_OVERDUE_MINUTES")
    admin_status_token: str = Field(default="", alias="ADMIN_STATUS_TOKEN")
    alert_webhook_url: str = Field(default="", alias="ALERT_WEBHOOK_URL")
    heartbeat_url: str = Field(default="", alias="HEARTBEAT_URL")
    # In-worker HTTP health listener on $PORT. Defaults to false and must stay false on
    # Render worker services, where start.sh already binds $PORT -- enabling both
    # double-binds the same port. Only true when the worker runs without start.sh.
    worker_http_health: bool = Field(default=False, alias="WORKER_HTTP_HEALTH")

    # LLM Gateway (backend-only credentials; empty key = provider unconfigured).
    llm_default_provider: str = Field(default="groq", alias="LLM_DEFAULT_PROVIDER")
    llm_groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    llm_groq_model: str = Field(default="openai/gpt-oss-120b", alias="GROQ_MODEL")
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

    # Adzuna India budget (free-tier friendly; ~1000 calls/month).
    adzuna_queries_per_crawl: int = Field(default=3, alias="ADZUNA_QUERIES_PER_CRAWL")
    adzuna_results_per_page: int = Field(default=50, alias="ADZUNA_RESULTS_PER_PAGE")

    # JobSpy broad discovery layer (python-jobspy==1.1.82; missing dep =
    # graceful empty crawl). Bounded rotation: each scheduled run executes
    # only max(query_batch, location_batch) + optional extra searches —
    # never the full query matrix simultaneously.
    jobspy_enabled: bool = Field(default=True, alias="JOBSPY_ENABLED")
    jobspy_results_wanted: int = Field(default=50, alias="JOBSPY_RESULTS_WANTED")
    jobspy_timeout_seconds: float = Field(default=60.0, alias="JOBSPY_TIMEOUT_SECONDS")
    # Provider/site allowlist (comma-separated subset of
    # indeed,naukri,glassdoor,linkedin). Indeed carries broad recurring
    # searches; Naukri adds India-specific coverage; LinkedIn is
    # rate-limit sensitive and gets the longer delay below.
    jobspy_sites: str = Field(default="indeed,naukri,linkedin", alias="JOBSPY_SITES")
    # Bounded concurrency for JobSpy searches within one scheduled run.
    jobspy_max_concurrent: int = Field(default=2, alias="JOBSPY_MAX_CONCURRENT")
    # Minimum delay between consecutive searches per provider (seconds).
    jobspy_per_provider_delay_seconds: float = Field(
        default=5.0, alias="JOBSPY_PER_PROVIDER_DELAY_SECONDS"
    )
    # Conservative spacing for LinkedIn (rate-limit sensitive).
    jobspy_linkedin_delay_seconds: float = Field(
        default=15.0, alias="JOBSPY_LINKEDIN_DELAY_SECONDS"
    )
    # Rotation batch sizes (queries x locations pair round-robin).
    jobspy_query_batch_size: int = Field(default=4, alias="JOBSPY_QUERY_BATCH_SIZE")
    jobspy_location_batch_size: int = Field(default=2, alias="JOBSPY_LOCATION_BATCH_SIZE")
    # Freshness buckets (hours_old rotation: very recent / recent / rolling).
    jobspy_freshness_buckets: str = Field(default="24,72,168", alias="JOBSPY_FRESHNESS_BUCKETS")
    # Provider cooldown after repeated failures + consecutive-failure
    # threshold that opens the circuit (429s back off exponentially).
    jobspy_provider_cooldown_seconds: float = Field(
        default=600.0, alias="JOBSPY_PROVIDER_COOLDOWN_SECONDS"
    )
    jobspy_circuit_threshold: int = Field(default=3, alias="JOBSPY_CIRCUIT_THRESHOLD")
    # Identical query/location/provider/freshness combos are skipped inside
    # this window (freshness-aware skipping, hours).
    jobspy_search_cache_ttl_hours: float = Field(
        default=24.0, alias="JOBSPY_SEARCH_CACHE_TTL_HOURS"
    )

    # Firecrawl (backend-only credential; empty key = Firecrawl unconfigured).
    firecrawl_api_key: str = Field(default="", alias="FIRECRAWL_API_KEY")
    firecrawl_api_url: str = Field(default="https://api.firecrawl.dev/v1", alias="FIRECRAWL_API_URL")
    firecrawl_timeout_seconds: float = Field(default=30.0, alias="FIRECRAWL_TIMEOUT_SECONDS")
    firecrawl_max_retries: int = Field(default=3, alias="FIRECRAWL_MAX_RETRIES")
    firecrawl_max_pages_per_crawl: int = Field(default=15, alias="FIRECRAWL_MAX_PAGES_PER_CRAWL")
    # Firecrawl 429 circuit breaker: process-local cooldown (seconds) during
    # which Firecrawl is skipped after a rate-limit. No Redis state.
    firecrawl_circuit_cooldown_seconds: float = Field(
        default=300.0, alias="FIRECRAWL_CIRCUIT_COOLDOWN_SECONDS"
    )

    # Crawl4AI self-hosted generic crawler (primary generic provider when on).
    # Default OFF: the slim worker image has no Chromium until the Dockerfile
    # browser layer lands AND CRAWL4AI_ENABLED=true is set in the environment.
    crawl4ai_enabled: bool = Field(default=False, alias="CRAWL4AI_ENABLED")
    crawl4ai_max_concurrency: int = Field(default=2, alias="CRAWL4AI_MAX_CONCURRENCY")
    crawl4ai_timeout_seconds: float = Field(default=60.0, alias="CRAWL4AI_TIMEOUT_SECONDS")

    # Observability.
    crawl_anomaly_ratio: float = Field(default=0.5, alias="CRAWL_ANOMALY_RATIO")
    crawl_observability_retention_days: int = Field(default=90, alias="CRAWL_OBSERVABILITY_RETENTION_DAYS")
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

    # Friendly batch evidence discovery: maximum improvement opportunities
    # surfaced in ONE collective interaction (default 5, hard cap 6).
    # Configurable via TAILORING_MAX_OPPORTUNITIES; per-request override wins.
    tailoring_max_opportunities: int = Field(
        default=5,
        alias="TAILORING_MAX_OPPORTUNITIES",
    )

    # Persistence concurrency & crawl pacing
    persistence_max_concurrency: int = Field(default=2, alias="PERSISTENCE_MAX_CONCURRENCY")
    crawl_stagger_seconds: float = Field(default=2.0, alias="CRAWL_STAGGER_SECONDS")
    # Forensics telemetry: when true, persistence paths emit payload-free
    # structured timing (async wait/hold vs sync wait/hold vs HTTP vs CPU).
    # Default off; zero behaviour change when off.
    persistence_telemetry_verbose: bool = Field(
        default=False, alias="PERSISTENCE_TELEMETRY_VERBOSE"
    )
    analysis_max_ids_per_crawl: int = Field(
        default=200, alias="ANALYSIS_MAX_IDS_PER_CRAWL"
    )
    analysis_batch_chunk_size: int = Field(
        default=25, alias="ANALYSIS_BATCH_CHUNK_SIZE"
    )
    firecrawl_min_interval_hours: int = Field(
        default=72, alias="FIRECRAWL_MIN_INTERVAL_HOURS"
    )
    firecrawl_consecutive_zero_pause: int = Field(
        default=3, alias="FIRECRAWL_CONSECUTIVE_ZERO_PAUSE"
    )
    analysis_queue_name: str = Field(
        default="arq:queue:analysis", alias="ANALYSIS_QUEUE_NAME"
    )
    analysis_backfill_limit_per_tick: int = Field(
        default=50, alias="ANALYSIS_BACKFILL_LIMIT_PER_TICK"
    )
    worker_consume_analysis_queue: bool = Field(
        default=True, alias="WORKER_CONSUME_ANALYSIS_QUEUE"
    )
    crawl_rate_limit_tokens: int = Field(
        default=5, alias="CRAWL_RATE_LIMIT_TOKENS"
    )
    crawl_rate_limit_window_seconds: int = Field(
        default=300, alias="CRAWL_RATE_LIMIT_WINDOW_SECONDS"
    )

    # WhatsApp-Native Alert System (Twilio or Meta WhatsApp API)
    whatsapp_provider: str = Field(default="twilio", alias="WHATSAPP_PROVIDER")
    twilio_account_sid: str = Field(default="", alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field(default="", alias="TWILIO_AUTH_TOKEN")
    twilio_whatsapp_from: str = Field(default="whatsapp:+14155238886", alias="TWILIO_WHATSAPP_FROM")
    meta_whatsapp_token: str = Field(default="", alias="META_WHATSAPP_TOKEN")
    meta_whatsapp_phone_number_id: str = Field(default="", alias="META_WHATSAPP_PHONE_NUMBER_ID")

    # Semantic Retrieval & Embeddings (Phase 4, default OFF)
    semantic_retrieval_enabled: bool = Field(default=False, alias="SEMANTIC_RETRIEVAL_ENABLED")
    embedding_provider: str = Field(default="gemini", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="text-embedding-004", alias="EMBEDDING_MODEL")
    embed_dims: int = Field(default=768, alias="EMBED_DIMS")
    embed_max_age_days: int = Field(default=90, alias="EMBED_MAX_AGE_DAYS")
    embed_max_rows_cap: int = Field(default=10000, alias="EMBED_MAX_ROWS_CAP")
    embed_batch_size: int = Field(default=25, alias="EMBED_BATCH_SIZE")
    semantic_top_k: int = Field(default=50, alias="SEMANTIC_TOP_K")
    semantic_min_similarity: float = Field(default=0.6, alias="SEMANTIC_MIN_SIMILARITY")

    # Phase 6 Product Features (User-visible features default OFF)
    market_demand_enabled: bool = Field(default=False, alias="MARKET_DEMAND_ENABLED")
    apply_kit_enabled: bool = Field(default=False, alias="APPLY_KIT_ENABLED")
    notification_outbox_enabled: bool = Field(default=False, alias="NOTIFICATION_OUTBOX_ENABLED")
    referral_assistant_enabled: bool = Field(default=False, alias="REFERRAL_ASSISTANT_ENABLED")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (env vars are read once)."""
    return Settings()
