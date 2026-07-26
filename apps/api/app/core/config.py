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
    redis_url: str = "redis://127.0.0.1:6379/0"

    secret_key: SecretStr = SecretStr(DEVELOPMENT_SECRET)
    session_cookie_name: str = "sio_session"
    session_cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=86_400, ge=900, le=2_592_000)
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    password_min_length: int = Field(default=12, ge=12, le=128)
    youtube_api_key: SecretStr | None = None
    platform_request_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    platform_request_max_attempts: int = Field(default=3, ge=1, le=5)
    sync_task_max_retries: int = Field(default=3, ge=0, le=10)
    task_stale_after_seconds: int = Field(default=2100, ge=1860, le=86_400)
    sync_page_limit: int = Field(default=20, ge=1, le=200)
    llm_openai_compatible_base_url: str | None = None
    llm_openai_compatible_api_key: SecretStr | None = None
    llm_default_model: str = "gpt-4.1-mini"
    llm_request_timeout_seconds: float = Field(default=60.0, ge=5.0, le=300.0)
    llm_request_max_attempts: int = Field(default=3, ge=1, le=5)
    notification_encryption_key: SecretStr | None = None
    notification_request_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    notification_request_max_attempts: int = Field(default=3, ge=1, le=5)

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
