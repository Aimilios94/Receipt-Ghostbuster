"""Environment-driven configuration.

All secrets live server-side and are loaded from backend/.env (git-ignored).
The app must *import and run* even when secrets are missing, so that the health
check and the pure-logic endpoints work before the user supplies keys. Code that
needs a secret checks `settings.supabase_configured` / `settings.llm_configured`
and fails with a clear message only when actually invoked.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Load backend/.env into the real process environment (not just pydantic Settings).
# Pydantic's env_file only feeds the Settings object; the LangSmith SDK and our
# llm_trace.langsmith_enabled() read os.environ directly, so without this live
# tracing (LANGSMITH_*) would silently never fire. Idempotent; never overrides a
# var already set in the environment.
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
try:  # python-dotenv is a transitive dep; absence must not break import
    from dotenv import load_dotenv

    load_dotenv(_ENV_FILE)
except Exception:  # noqa: BLE001
    pass

# Some Python builds on this platform can't locate a usable CA bundle, which breaks
# the `requests`-based LangSmith client (OpenAI/Supabase use httpx, which bundles
# certifi, so they're unaffected). Point TLS at certifi unless the operator already
# set a bundle — setdefault keeps a real deployment's custom/OS trust store intact.
try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except Exception:  # noqa: BLE001
    pass


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
    llm_provider: str = "anthropic"          # anthropic | openai | ollama | mock
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"
    openai_api_key: str = ""
    # gpt-5-mini (a reasoning model) reads dense multi-rate VAT tables far more
    # reliably than gpt-4o (93% vs 84% on the eval set) — see eval/RESULTS.md. The
    # OpenAI call path handles its max_completion_tokens requirement automatically.
    openai_model: str = "gpt-5-mini"
    # Output-token ceiling for Anthropic (Claude) reads. A dense multi-rate
    # ExtractionResult (line_items + tax_lines) can exceed the old 1024 default and
    # truncate the JSON, which penalises Claude unfairly in a model comparison. Claude
    # models aren't reasoning models (no hidden-reasoning budget), so a single raised
    # ceiling is enough — unlike the gpt-5*/o* path which needs max_completion_tokens.
    anthropic_max_tokens: int = 4096

    # --- Ollama (local, privacy-first vision model) ---
    # Ollama exposes an OpenAI-compatible endpoint, so the OpenAI call path is reused
    # with this base_url and no API key — the receipt image never leaves the machine.
    # Needs a VISION model pulled locally first: `ollama pull qwen2.5vl:7b`. Slower
    # than the cloud, but the privacy-maximising option for personal financial data.
    ollama_base_url: str = "http://localhost:11434/v1"
    # A full-res receipt image tokenises to ~5-8k vision tokens, but Ollama's default
    # context window is 4096 and its OpenAI endpoint ignores a per-request num_ctx, so
    # a plain `qwen2.5vl:7b` read 400s. We use a derived model with num_ctx baked in via
    # backend/ollama/Modelfile (one-time: `ollama create qwen2.5vl-receipt -f
    # backend/ollama/Modelfile`, after `ollama pull qwen2.5vl:7b`).
    ollama_model: str = "qwen2.5vl-receipt"
    # Best-effort per-request num_ctx (honoured by Ollama versions that support it on
    # the OpenAI endpoint; the Modelfile is the reliable path). Headroom for image+JSON.
    ollama_num_ctx: int = 16384

    # --- Confidence gate ---
    confidence_threshold: float = 0.8

    # --- Structured output (Instructor) ---
    # How many times Instructor re-prompts the model when its output fails schema
    # validation before we fall back to tolerant JSON parsing.
    instructor_max_retries: int = 2

    # --- LangSmith tracing (optional, opt-in) ---
    # When enabled with a key, every LLM call is also traced to the user's LangSmith
    # project (prompt, response, tokens). Off by default so the app runs with no
    # external dependency; sends data to LangSmith's cloud when on.
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "receipt-ghostbuster"

    # --- Sentry error tracking (optional, opt-in) ---
    # App-layer error tracking: unhandled 500s plus the exceptions the pipeline
    # currently swallows (provider calls, Supabase/n8n, PDF/CSV import). Off unless a
    # DSN is set, so the app runs with no external dependency. Performance tracing is
    # off by default (sample rate 0.0) — errors only — to stay inside the free tier.
    # Privacy: no receipt/bank/PII is sent (send_default_pii=False + a body/header
    # scrubber in services/monitoring.py); see docs/MONITORING.md.
    sentry_dsn: str = ""
    sentry_environment: str = "local"
    sentry_traces_sample_rate: float = 0.0

    # --- Reconciliation tuning ---
    reconcile_amount_tolerance: float = 0.01
    reconcile_date_window_days: int = 3
    reconcile_vendor_min_score: int = 70

    # --- App ---
    default_currency: str = "EUR"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- n8n (Phase 2 delivery: push an approved draft to Gmail drafts) ---
    # The webhook URL of the imported "refund-draft-to-gmail" workflow, e.g.
    # http://localhost:5678/webhook/refund-draft . Draft-only; never sends.
    n8n_webhook_url: str = ""

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "mock":
            return True
        if self.llm_provider == "ollama":
            return True  # local; no API key required (needs Ollama running + model pulled)
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        return False

    @property
    def n8n_configured(self) -> bool:
        return bool(self.n8n_webhook_url)

    @property
    def langsmith_configured(self) -> bool:
        return bool(self.langsmith_tracing and self.langsmith_api_key)

    @property
    def sentry_configured(self) -> bool:
        return bool(self.sentry_dsn)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
