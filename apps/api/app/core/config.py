from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_SECRET = "local-development-secret-replace-before-production-2026"  # noqa: S105
DEVELOPMENT_DATABASE_PASSWORD = "sio-local-development-only"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SIO_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "Sports Intelligence OS"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"  # noqa: S104 - container listener, not an auth boundary
    api_port: int = 8000

    database_url: str = (
        "postgresql+asyncpg://sio:sio-local-development-only@127.0.0.1:5432/sports_intelligence"
    )
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=200)
    database_pool_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86_400)
    database_command_timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0)
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_connect_timeout_seconds: float = Field(default=5.0, ge=0.5, le=60.0)
    redis_socket_timeout_seconds: float = Field(default=5.0, ge=0.5, le=60.0)
    redis_max_connections: int = Field(default=50, ge=5, le=1000)
    redis_health_check_interval_seconds: int = Field(default=30, ge=0, le=300)
    redis_retry_on_timeout: bool = True

    secret_key: SecretStr = SecretStr(DEVELOPMENT_SECRET)
    session_cookie_name: str = "sio_session"
    session_cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=86_400, ge=900, le=2_592_000)
    auth_login_window_seconds: int = Field(default=900, ge=60, le=86_400)
    auth_login_max_attempts_per_identity: int = Field(default=10, ge=3, le=100)
    auth_login_max_attempts_per_ip: int = Field(default=100, ge=10, le=10_000)
    auth_attempt_retention_seconds: int = Field(default=604_800, ge=3600, le=7_776_000)
    session_cleanup_retention_seconds: int = Field(default=604_800, ge=3600, le=7_776_000)
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    password_min_length: int = Field(default=12, ge=12, le=128)
    youtube_api_key: SecretStr | None = None
    platform_request_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    platform_request_max_attempts: int = Field(default=3, ge=1, le=5)
    sync_task_max_retries: int = Field(default=3, ge=0, le=10)
    task_stale_after_seconds: int = Field(default=2100, ge=1860, le=86_400)
    task_dispatch_timeout_seconds: int = Field(
        default=180,
        ge=30,
        le=1800,
        description=(
            "A sync run left in 'queued' with no worker pickup beyond this window is "
            "treated as stuck and auto-released, so an account is never permanently "
            "locked by a task the worker failed to dispatch."
        ),
    )
    sync_page_limit: int = Field(default=20, ge=1, le=200)
    sync_run_timeout_seconds: int = Field(
        default=1800,
        ge=120,
        le=7200,
        description=(
            "Hard wall-clock budget for a single account sync run. When exceeded "
            "the run stops paging, commits whatever it has ingested, and finishes "
            "as success/degraded instead of running unbounded. Keep this below "
            "SIO_TASK_STALE_AFTER_SECONDS (default 2100) so healthy-but-slow runs "
            "are never wrongly flagged as crashed by the stale-recovery watchdog."
        ),
    )
    llm_openai_compatible_base_url: str | None = None
    llm_openai_compatible_api_key: SecretStr | None = None
    llm_default_model: str = "gpt-4.1-mini"
    llm_default_temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    llm_default_top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    llm_default_max_tokens: int = Field(default=4096, ge=1, le=131_072)
    llm_request_timeout_seconds: float = Field(default=60.0, ge=5.0, le=300.0)
    llm_request_max_attempts: int = Field(default=3, ge=1, le=5)
    notification_encryption_key: SecretStr | None = None
    notification_request_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    notification_request_max_attempts: int = Field(default=3, ge=1, le=5)
    news_ssrf_check_enabled: bool = Field(
        default=True,
        description=(
            "Enable SSRF protection for news source URLs. Disable only in an isolated "
            "environment whose DNS intentionally resolves through non-global ranges."
        ),
    )
    llm_internal_hosts_allowlist: list[str] = Field(
        default_factory=lambda: ["llm-gateway", "llm-experimental"],
        description=(
            "Hostnames permitted to bypass SSRF public-endpoint validation for LLM "
            "base URLs. Used for Docker-internal gateway services such as New API or "
            "Chat2API sidecars."
        ),
    )
    browser_first_mode: bool = Field(
        default=False,
        description=(
            "When enabled, platform sync prefers browser adapters over API adapters "
            "to save API quota/costs. The browser adapter is used regardless of "
            "credential mode unless mode is explicitly 'api' with valid credentials."
        ),
    )
    llm_fallback_base_url: str | None = Field(
        default=None,
        description=(
            "Optional OpenAI-compatible base URL used as a fallback when the primary "
            "LLM provider fails with rate-limit or authentication errors. Typically "
            "points to the llm-experimental (gpt4free) service, e.g. "
            "'http://llm-experimental:8000/v1'."
        ),
    )

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> "Settings":
        if self.environment != "production":
            return self

        secret = self.secret_key.get_secret_value()
        if secret == DEVELOPMENT_SECRET or len(secret) < 32:
            raise ValueError(
                "production requires a unique SIO_SECRET_KEY of at least 32 characters"
            )
        if DEVELOPMENT_DATABASE_PASSWORD in self.database_url:
            raise ValueError("production database URL cannot use the local development password")
        if not self.session_cookie_secure:
            raise ValueError("production requires SIO_SESSION_COOKIE_SECURE=true")
        encryption_key = (
            self.notification_encryption_key.get_secret_value()
            if self.notification_encryption_key is not None
            else ""
        )
        if len(encryption_key) < 32:
            raise ValueError(
                "production requires a unique SIO_NOTIFICATION_ENCRYPTION_KEY "
                "of at least 32 characters"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
