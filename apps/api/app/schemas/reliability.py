"""Pydantic schemas for reliability, discovery and dashboard endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Re-export notification template schemas from the service module so that
# route handlers can import everything from one place.
from app.services.notification_template import (
    TemplateCreate as NotificationTemplateCreate,
)
from app.services.notification_template import (
    TemplateRead as NotificationTemplateRead,
)
from app.services.notification_template import (
    TemplateUpdate as NotificationTemplateUpdate,
)
from app.services.notification_template import (
    TemplateVersionRead as NotificationTemplateVersionRead,
)

# Re-export search schemas from the search service.
from app.services.search import SearchPage, SearchResult


class SloMetricRead(BaseModel):
    """A bounded derived reliability metric, not external platform data."""

    key: str
    metric_kind: Literal["derived"] = "derived"
    observations: int
    successes: int
    failures: int
    in_progress: int
    success_rate: float | None = None
    average_latency_ms: float | None = None
    latest_at: datetime | None = None
    notes: list[str] = Field(default_factory=list)


class SloSummaryRead(BaseModel):
    window_minutes: int
    generated_at: datetime
    metrics: list[SloMetricRead]

# ---------------------------------------------------------------------------
# Dead letter schemas
# ---------------------------------------------------------------------------


class DeadLetterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    outbox_event_id: UUID
    workspace_id: UUID | None = None
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    payload_json: dict[str, Any]
    original_occurred_at: datetime
    total_attempts: int
    last_error_code: str | None = None
    last_error_detail: str | None = None
    last_error_hint: str | None = None
    dead_at: datetime
    replay_status: str
    replayed_at: datetime | None = None


class DeadLetterPage(BaseModel):
    items: list[DeadLetterRead]
    page: int
    page_size: int
    total: int


# ---------------------------------------------------------------------------
# Outbox event attempt schemas
# ---------------------------------------------------------------------------


class OutboxEventAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    outbox_event_id: UUID
    attempt_number: int
    status: str
    consumer: str
    started_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None
    error_detail_safe: str | None = None
    error_hint: str | None = None
    duration_ms: int | None = None


# ---------------------------------------------------------------------------
# Notification delivery attempt schemas
# ---------------------------------------------------------------------------


class NotificationDeliveryAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    delivery_id: UUID
    workspace_id: UUID
    channel_id: UUID | None = None
    attempt_number: int
    status: str
    provider_key: str | None = None
    provider_message_id: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_detail_safe: str | None = None
    error_hint: str | None = None
    retryable: bool | None = None
    request_summary: dict[str, Any] | None = None
    response_summary: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# External call attempt schemas
# ---------------------------------------------------------------------------


class ExternalCallAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID | None = None
    call_type: str
    provider_key: str
    entity_type: str | None = None
    entity_id: UUID | None = None
    attempt_number: int
    status: str
    target_url: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    http_status: int | None = None
    error_code: str | None = None
    error_detail_safe: str | None = None
    error_hint: str | None = None
    retryable: bool | None = None
    request_summary: dict[str, Any] | None = None
    response_summary: dict[str, Any] | None = None


class ExternalCallAttemptPage(BaseModel):
    items: list[ExternalCallAttemptRead]
    page: int
    page_size: int
    total: int


# ---------------------------------------------------------------------------
# Notification template schemas (re-exported + composite)
# ---------------------------------------------------------------------------


class NotificationTemplateDetailRead(BaseModel):
    """Template read model enriched with its version history."""

    id: UUID
    name: str
    description: str | None = None
    category: str
    created_at: datetime
    updated_at: datetime
    current_version: int | None = None
    published_version: int | None = None
    versions: list[NotificationTemplateVersionRead] = Field(default_factory=list)


class NotificationTemplatePage(BaseModel):
    items: list[NotificationTemplateRead]
    page: int
    page_size: int
    total: int


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: UUID


# ---------------------------------------------------------------------------
# Dashboard stats schemas
# ---------------------------------------------------------------------------


class DashboardStatsRead(BaseModel):
    stats: dict[str, Any]


# ---------------------------------------------------------------------------
# Search schemas (re-exported for route-level import convenience)
# ---------------------------------------------------------------------------

__all__ = [
    "DeadLetterRead",
    "DeadLetterPage",
    "OutboxEventAttemptRead",
    "NotificationDeliveryAttemptRead",
    "ExternalCallAttemptRead",
    "ExternalCallAttemptPage",
    "NotificationTemplateCreate",
    "NotificationTemplateUpdate",
    "NotificationTemplateRead",
    "NotificationTemplateVersionRead",
    "NotificationTemplateDetailRead",
    "NotificationTemplatePage",
    "RollbackRequest",
    "DashboardStatsRead",
    "SearchPage",
    "SearchResult",
]
