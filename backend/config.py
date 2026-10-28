"""Central configuration for the Queryable Chatbot backend.

All secrets are read from the server-side environment (``.env`` in the
project root). Nothing in this module is ever sent to the browser.
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(name, default=False):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _list(name, default=""):
    raw = os.getenv(name, default) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # VeloDB (Apache Doris; MySQL wire protocol on the FE query port).
    # Works unchanged against VeloDB Cloud, VeloDB Enterprise or the local
    # Doris container in docker-compose.yml.
    velodb_host: str = os.getenv("VELODB_HOST", "127.0.0.1")
    velodb_port: int = _int("VELODB_PORT", 9030)
    velodb_user: str = os.getenv("VELODB_USER", "root")
    velodb_password: str = os.getenv("VELODB_PASSWORD", "")
    velodb_db: str = os.getenv("VELODB_DB", "queryable_chatbot")
    # Stream Load / FE web UI port, used by the loader only.
    velodb_http_port: int = _int("VELODB_HTTP_PORT", 8030)
    velodb_connect_timeout: int = _int("VELODB_CONNECT_TIMEOUT", 5)
    velodb_query_timeout_seconds: int = _int("VELODB_QUERY_TIMEOUT_SECONDS", 15)

    # Tables the chatbot may query. Empty means "every business table".
    queryable_collections: list = field(
        default_factory=lambda: _list("QUERYABLE_COLLECTIONS")
    )
    max_result_rows: int = _int("MAX_RESULT_ROWS", 200)

    # Operational state (users, sessions, API keys, usage, chat threads)
    # lives in SQLite, not in VeloDB: that workload is a point read plus a
    # point write on every request, which a columnar MPP engine handles
    # badly. See backend/docstore.py.
    app_state_db: str = os.getenv("APP_STATE_DB", "")

    # LLM providers
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_base_url: str = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )
    agent_model: str = os.getenv("AGENT_MODEL", "google/gemini-2.5-flash")

    # OpenUI generation: "openrouter" (default) or "thesys" (OpenUI Gateway)
    openui_provider: str = os.getenv("OPENUI_PROVIDER", "openrouter").lower()
    openui_model: str = os.getenv("OPENUI_MODEL", "google/gemini-2.5-flash")
    openui_model_options: list = field(
        default_factory=lambda: _list(
            "OPENUI_MODEL_OPTIONS",
            "google/gemini-2.5-flash,openai/gpt-4.1-mini,anthropic/claude-sonnet-4.5",
        )
    )
    thesys_api_key: str = os.getenv("THESYS_API_KEY", "")
    thesys_base_url: str = os.getenv(
        "THESYS_BASE_URL", "https://api.thesys.dev/v1/embed"
    )
    thesys_model: str = os.getenv("THESYS_MODEL", "openai/gpt-5")
    llm_timeout_seconds: float = _float("LLM_TIMEOUT_SECONDS", 60)
    # Fast mode: skip the model's hidden "thinking" pass. Measured on query
    # generation with gemini-2.5-flash (interleaved runs): median 4.8 s
    # instead of 8.9 s, same output. OpenRouter's provider "sort: latency"
    # was measured too and made things slower, so it is not used.
    llm_fast_mode: bool = _bool("LLM_FAST_MODE", True)

    # JEV routing
    jev_enabled: bool = _bool("JEV_ENABLED", True)
    jev_model: str = os.getenv("JEV_MODEL", "typesafe/jev-1.13")
    jev_timeout_seconds: float = _float("JEV_TIMEOUT_SECONDS", 8)
    jev_min_confidence: float = _float("JEV_MIN_CONFIDENCE", 0.6)

    # Authentication
    session_cookie_name: str = os.getenv("SESSION_COOKIE_NAME", "qc_session")
    session_ttl_minutes: int = _int("SESSION_TTL_MINUTES", 480)
    session_idle_minutes: int = _int("SESSION_IDLE_MINUTES", 60)
    cookie_secure: bool = _bool("COOKIE_SECURE", False)
    login_max_attempts: int = _int("LOGIN_MAX_ATTEMPTS", 5)
    login_lockout_seconds: int = _int("LOGIN_LOCKOUT_SECONDS", 300)
    # Self-service sign-up from the login page. Turn off for deployments
    # where accounts are issued with scripts/create_user.py only.
    allow_signup: bool = _bool("ALLOW_SIGNUP", True)
    signup_max_per_hour: int = _int("SIGNUP_MAX_PER_HOUR", 5)

    # Plans and API keys (Settings page). Billing is simulated: no payment
    # processor is connected, so switching plan only changes the limits.
    plan_limits_enforced: bool = _bool("PLAN_LIMITS_ENFORCED", True)
    default_plan: str = os.getenv("DEFAULT_PLAN", "free").lower()

    # Guardrails
    max_question_chars: int = _int("MAX_QUESTION_CHARS", 2000)
    redact_pii: bool = _bool("REDACT_PII", True)

    # Optional services
    graphiti_enabled: bool = _bool("GRAPHITI_ENABLED", False)
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "")
    langfuse_public_key: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    langfuse_secret_key: str = os.getenv("LANGFUSE_SECRET_KEY", "")
    langfuse_host: str = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:3100")


settings = Settings()


def openrouter_speed_options():
    """Extra OpenRouter request fields for LLM_FAST_MODE (empty when off)."""

    if not settings.llm_fast_mode:
        return {}
    return {"reasoning": {"enabled": False}}


# Collections that belong to the application itself. They are never exposed
# to schema discovery, query generation or the query validator.
INTERNAL_COLLECTIONS = frozenset(
    {"app_users", "app_sessions", "chat_threads", "audit_log", "app_api_keys", "app_usage"}
)
