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
