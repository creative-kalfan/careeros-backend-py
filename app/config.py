"""Application configuration loaded from environment variables."""

from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (env vars are read once)."""
    return Settings()