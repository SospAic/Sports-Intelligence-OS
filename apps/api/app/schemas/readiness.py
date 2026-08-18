"""Schemas for configuration and capability readiness diagnostics.

Readiness is deliberately separate from a health check: a configured
credential still needs a live platform probe, and an implemented public
adapter does not imply private analytics or publishing permission.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ReadinessStatus = Literal["ready", "unverified", "degraded", "needs_setup", "blocked"]
CanaryStatus = Literal["passed", "degraded", "failed", "blocked"]


class ReadinessItemRead(BaseModel):
    key: str
    title: str
    status: ReadinessStatus
    detail: str
    conditions: list[str] = Field(default_factory=list)
    next_action: str


class PlatformCanaryRead(BaseModel):
    platform_key: str
    adapter_key: str
    trigger: Literal["manual", "scheduled"]
    mode: Literal["api", "public_page", "authorized_login", "authorized_session"]
    credential_source: Literal["database", "environment", "default"]
    status: CanaryStatus
    checked_at: datetime
    detail: str
    error_code: str | None = None
    duration_ms: int | None = None
    response_summary: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class PlatformReadinessRead(ReadinessItemRead):
    platform_key: str
    platform_name: str
    adapter_key: str
    adapter_implementation_status: Literal["implemented", "skeleton"]
    credential_mode: Literal["api", "public_page", "authorized_login", "authorized_session"]
    credential_source: Literal["database", "environment", "default"]
    configured_fields: list[str] = Field(default_factory=list)
    missing_configuration: list[str] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    source_kinds: list[str] = Field(default_factory=list)
    last_probe: PlatformCanaryRead | None = None


class ReadinessReportRead(BaseModel):
    generated_at: datetime
    platforms: list[PlatformReadinessRead] = Field(default_factory=list)
    features: list[ReadinessItemRead] = Field(default_factory=list)
