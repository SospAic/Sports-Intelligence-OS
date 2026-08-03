from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class ConfigFieldDescriptor(BaseModel):
    key: str
    label: str
    value_type: Literal["text", "password", "number", "boolean", "select", "json", "list"]
    required: bool = False
    secret: bool = False
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    options: list[dict[str, str]] = Field(default_factory=list)
    placeholder: str | None = None
    help_text: str | None = None


class RuntimeSettingField(BaseModel):
    key: str
    label: str
    value: str | int | float | bool | None
    value_type: Literal["text", "number", "boolean"]
    env_var: str
    description: str
    secret: bool = False
    restart_required: bool = True
    minimum: float | None = None
    maximum: float | None = None


class RuntimeSettingSection(BaseModel):
    key: str
    title: str
    description: str
    fields: list[RuntimeSettingField]


class RuntimeSettingsRead(BaseModel):
    environment: str
    sections: list[RuntimeSettingSection]
    apply_mode: Literal["environment_restart"] = "environment_restart"
    warning: str


class LLMProviderSettingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="OpenAI 兼容接口", min_length=1, max_length=255)
    base_url: str = Field(min_length=8, max_length=2048)
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    organization: str | None = Field(default=None, max_length=255)
    project: str | None = Field(default=None, max_length=255)
    custom_headers: dict[str, str] | None = None
    default_model: str = Field(default="gpt-4.1-mini", min_length=1, max_length=160)
    temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    max_tokens: int = Field(default=4096, ge=1, le=131_072)
    timeout_seconds: float = Field(default=60.0, ge=5.0, le=300.0)
    max_attempts: int = Field(default=3, ge=1, le=5)
    input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    output_cost_per_million: Decimal | None = Field(default=None, ge=0)
    enabled: bool = True
    call_mode: Literal["api", "browser_proxy"] = "api"

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        from app.providers.news.utils import validate_source_url

        normalized = value.strip().rstrip("/")
        validate_source_url(normalized, allow_secret_query=False)
        return normalized

    @field_validator("custom_headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        if len(value) > 20:
            raise ValueError("custom_headers cannot contain more than 20 entries")
        forbidden = {"host", "content-length", "authorization"}
        for key, item in value.items():
            if not key.strip() or key.casefold() in forbidden:
                raise ValueError(f"custom header is not allowed: {key}")
            if len(key) > 120 or len(item) > 2048:
                raise ValueError("custom header is too long")
        return value

    @model_validator(mode="after")
    def validate_secret_action(self) -> LLMProviderSettingUpdate:
        if self.api_key is not None and self.clear_api_key:
            raise ValueError("api_key and clear_api_key cannot be used together")
        return self


class LLMProviderSettingRead(BaseModel):
    id: UUID | None = None
    provider_key: str
    name: str
    source: Literal["database", "environment", "unconfigured"]
    base_url: str | None
    api_key_configured: bool
    config_masked: dict[str, Any]
    default_model: str
    default_parameters: dict[str, Any]
    input_cost_per_million: Decimal | None
    output_cost_per_million: Decimal | None
    enabled: bool
    configured: bool
    last_tested_at: datetime | None
    health_status: str
    updated_at: datetime | None
    fields: list[ConfigFieldDescriptor]


class LLMProviderTestRead(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    detail: str
    tested_at: datetime


class PlatformCredentialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["api", "public_page", "authorized_login", "authorized_session"]
    config: dict[str, str] = Field(default_factory=dict)
    clear_fields: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True

    @field_validator("config")
    @classmethod
    def validate_config(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20:
            raise ValueError("config cannot contain more than 20 fields")
        cleaned: dict[str, str] = {}
        for key, item in value.items():
            normalized_key = key.strip()
            normalized_value = item.strip()
            if not normalized_key or len(normalized_key) > 80:
                raise ValueError("invalid platform credential field")
            if len(normalized_value) > 16_384:
                raise ValueError("platform credential value is too long")
            if normalized_value:
                cleaned[normalized_key] = normalized_value
        return cleaned


class PlatformCredentialRead(BaseModel):
    platform_key: str
    mode: Literal["api", "public_page", "authorized_login", "authorized_session"]
    source: Literal["database", "environment", "default"]
    enabled: bool
    configured: bool
    configured_fields: list[str]
    config_masked: dict[str, Any]
    updated_at: datetime | None


# -- Synchronisation settings (workspace-scoped fetch policy) ---------------

class YtDlpSettings(BaseModel):
    """yt-dlp parameters applied to every sync in a workspace.

    Structured fields are translated to yt-dlp CLI flags by the adapter (see
    ``YtDlpAdapter``). ``dateafter`` / ``datebefore`` / ``playlist_start`` feed
    the executor's windowing directly; the free-form ``extra_args`` passthrough
    covers any yt-dlp option not modelled here. Empty / ``None`` values mean
    "do not pass this flag", so the operator toggles only what they need.
    """

    model_config = ConfigDict(extra="forbid")

    # --- window (consumed by the sync executor, not as raw flags) ---
    # YYYYMMDD strings; empty means "no bound" so the full back-catalogue is fetched.
    dateafter: str = Field(default="", max_length=8)
    datebefore: str = Field(default="", max_length=8)
    playlist_start: int = Field(default=1, ge=1, le=100_000)

    # --- date range ---
    daterange: str = Field(default="", max_length=17)

    # --- playlist shape ---
    playlist_items: str = Field(default="", max_length=256)
    playlist_reverse: bool = False
    playlist_random: bool = False
    no_playlist: bool = False
    flat_playlist: bool = False

    # --- filtering / sorting ---
    sort: str = Field(default="", max_length=256)
    match_filter: str = Field(default="", max_length=1024)
    match_title: str = Field(default="", max_length=512)
    reject_title: str = Field(default="", max_length=512)
    age_limit: int | None = Field(default=None, ge=0, le=21)
    min_duration: int | None = Field(default=None, ge=0)
    max_duration: int | None = Field(default=None, ge=0)
    min_filesize: str = Field(default="", max_length=32)
    max_filesize: str = Field(default="", max_length=32)

    # --- network / throttling ---
    proxy: str = Field(default="", max_length=2048)
    socket_timeout: int | None = Field(default=None, ge=0)
    retries: int | None = Field(default=None, ge=0)
    fragment_retries: int | None = Field(default=None, ge=0)
    sleep_interval: int | None = Field(default=None, ge=0)
    max_sleep_interval: int | None = Field(default=None, ge=0)
    sleep_requests: int | None = Field(default=None, ge=0)
    limit_rate: str = Field(default="", max_length=64)
    geo_bypass: bool = False
    geo_bypass_country: str = Field(default="", max_length=8)
    geo_verification_proxy: str = Field(default="", max_length=2048)

    # --- extraction / output behaviour (default on to match prior behaviour) ---
    ignore_errors: bool = True
    no_warnings: bool = True

    extra_args: dict[str, Any] = Field(default_factory=dict)


class SyncSettingsConfig(BaseModel):
    """Global fetch policy shared by every account in a workspace.

    ``max_contents`` caps how many works a single sync run ingests (``None`` =
    unbounded, limited only by the platform pagination window). ``skip_existing``
    controls whether already-known works are refreshed or left untouched. The
    ``yt_dlp`` sub-object carries the yt-dlp-specific window / passthrough args.
    """

    model_config = ConfigDict(extra="forbid")

    max_contents: int | None = Field(default=None, ge=1, le=5000)
    skip_existing: bool = True
    yt_dlp: YtDlpSettings = Field(default_factory=YtDlpSettings)


class SyncSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: SyncSettingsConfig


class SyncSettingsRead(BaseModel):
    config: SyncSettingsConfig


#: Merged with whatever the workspace has stored so the UI always sees every key.
DEFAULT_SYNC_SETTINGS_CONFIG: dict[str, Any] = {
    "max_contents": None,
    "skip_existing": True,
    "yt_dlp": {
        "dateafter": "",
        "datebefore": "",
        "playlist_start": 1,
        "daterange": "",
        "playlist_items": "",
        "playlist_reverse": False,
        "playlist_random": False,
        "no_playlist": False,
        "flat_playlist": False,
        "sort": "",
        "match_filter": "",
        "match_title": "",
        "reject_title": "",
        "age_limit": None,
        "min_duration": None,
        "max_duration": None,
        "min_filesize": "",
        "max_filesize": "",
        "proxy": "",
        "socket_timeout": None,
        "retries": None,
        "fragment_retries": None,
        "sleep_interval": None,
        "max_sleep_interval": None,
        "sleep_requests": None,
        "limit_rate": "",
        "geo_bypass": False,
        "geo_bypass_country": "",
        "geo_verification_proxy": "",
        "ignore_errors": True,
        "no_warnings": True,
        "extra_args": {},
    },
}

