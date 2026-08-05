from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    queue: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(nullable=False, default=3)
    progress_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_detail_safe: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False, index=True)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_pending", "publish_status", "next_attempt_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    event_id: Mapped[UUID] = mapped_column(nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    schema_version: Mapped[int] = mapped_column(nullable=False, default=1)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trace_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    publish_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboxEventAttempt(Base):
    __tablename__ = "outbox_event_attempts"
    __table_args__ = (
        CheckConstraint("status IN ('success', 'failed', 'timeout')", name="outbox_attempt_status"),
        Index("ix_outbox_attempts_event_number", "outbox_event_id", "attempt_number"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    outbox_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("outbox_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    consumer: Mapped[str] = mapped_column(String(120), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_detail_safe: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DeadLetterEvent(Base):
    __tablename__ = "dead_letter_events"
    __table_args__ = (
        CheckConstraint(
            "replay_status IN ('pending', 'replaying', 'replayed', 'discarded')",
            name="dead_letter_replay_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    outbox_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("outbox_events.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    workspace_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    original_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    dead_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    replay_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExternalCallAttempt(Base):
    __tablename__ = "external_call_attempts"
    __table_args__ = (
        CheckConstraint("status IN ('success', 'failed', 'timeout')", name="external_call_status"),
        CheckConstraint(
            "call_type IN ('notification', 'webhook', 'news_sync', 'platform_api', 'llm', 'other')",
            name="external_call_type",
        ),
        Index("ix_external_calls_provider_time", "provider_key", "started_at"),
        Index("ix_external_calls_workspace_time", "workspace_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    call_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    target_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_detail_safe: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    request_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    response_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class DashboardStat(Base):
    __tablename__ = "dashboard_stats"
    __table_args__ = (UniqueConstraint("workspace_id", "stat_key", "period"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stat_key: Mapped[str] = mapped_column(String(120), nullable=False)
    stat_value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SystemEvent(Base):
    __tablename__ = "system_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_safe_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    trace_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_hint: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEntry(Base):
    __tablename__ = "audit_entries"
    __table_args__ = (
        UniqueConstraint("id", "created_at"),
        Index("ix_audit_workspace_created", "workspace_id", "created_at"),
        CheckConstraint(
            "status IN ('success', 'failed')",
            name="ck_audit_entries_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(nullable=True)
    action: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(nullable=True)
    before_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    change_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
