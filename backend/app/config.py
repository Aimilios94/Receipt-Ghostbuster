"""Environment-driven configuration.

All secrets live server-side and are loaded from backend/.env (git-ignored).
The app must *import and run* even when secrets are missing, so that the health
check and the pure-logic endpoints work before the user supplies keys. Code that
needs a secret checks `settings.supabase_configured` / `settings.llm_configured`
and fails with a clear message only when actually invoked.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Supabase ---
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_receipts_bucket: str = "receipts"
    # Used to verify the frontend's JWT. Found in Supabase > Settings > API > JWT Secret.
    supabase_jwt_secret: str = ""
    # Local/demo fallback owner id, used only when no JWT is verified. Lets the
    # app run end-to-end before auth is wired. Leave blank in production.
    dev_user_id: str = ""

    # --- Vision LLM ---
    llm_provider: str = "anthropic"          # anthropic | openai | mock
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # --- Confidence gate ---
    confidence_threshold: float = 0.8

    # --- Reconciliation tuning ---
    reconcile_amount_tolerance: float = 0.01
    reconcile_date_window_days: int = 3
    reconcile_vendor_min_score: int = 70

    # --- App ---
    default_currency: str = "EUR"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "mock":
            return True
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        return False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
