from __future__ import annotations

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class AutomationRule(TimestampMixin, Base):
    __tablename__ = "automation_rules"
    __table_args__ = (
        CheckConstraint("cooldown_seconds >= 0", name="automation_rule_cooldown"),
        CheckConstraint("deduplication_window >= 0", name="automation_rule_dedup_window"),
        Index("ix_automation_rules_workspace_enabled", "workspace_id", "enabled", "priority"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    condition_tree: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deduplication_window: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    actions: Mapped[list[AutomationAction]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", order_by="AutomationAction.sort_order"
    )


class AutomationAction(TimestampMixin, Base):
    __tablename__ = "automation_actions"
    __table_args__ = (
        UniqueConstraint("rule_id", "sort_order"),
        Index("ix_automation_actions_workspace_rule", "workspace_id", "rule_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[UUID] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    rule: Mapped[AutomationRule] = relationship(back_populates="actions")


class AutomationEvaluation(Base):
    __tablename__ = "automation_evaluations"
    __table_args__ = (
        CheckConstraint(
            "execution_status IN ('not_matched', 'suppressed', 'queued', "
            "'completed', 'partial', 'failed')",
            name="automation_evaluation_status",
        ),
        UniqueConstraint("workspace_id", "rule_id", "event_key"),
        Index("ix_automation_evaluations_rule_time", "rule_id", "evaluated_at"),
        Index("ix_automation_evaluations_entity_time", "entity_type", "entity_id", "evaluated_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[UUID] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    condition_result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    deduplication_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    execution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluation_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class AutomationRuntimeState(TimestampMixin, Base):
    __tablename__ = "automation_runtime_states"
    __table_args__ = (
        UniqueConstraint("rule_id", "entity_type", "entity_id"),
        Index("ix_automation_runtime_cooldown", "workspace_id", "cooldown_until"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[UUID] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    consecutive_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_deduplication_key: Mapped[str | None] = mapped_column(String(255), nullable=True)


class NotificationChannel(TimestampMixin, Base):
    __tablename__ = "notification_channels"
    __table_args__ = (
        CheckConstraint(
            "health_status IN ('unknown', 'healthy', 'degraded', 'unhealthy')",
            name="notification_channel_health",
        ),
        UniqueConstraint("workspace_id", "name"),
        Index("ix_notification_channels_workspace_enabled", "workspace_id", "enabled"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    config_masked: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")


class NotificationDelivery(TimestampMixin, Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'sending', 'delivered', 'failed', 'cancelled')",
            name="notification_delivery_status",
        ),
        UniqueConstraint("workspace_id", "idempotency_key"),
        Index("ix_notification_deliveries_workspace_created", "workspace_id", "created_at"),
        Index("ix_notification_deliveries_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[UUID] = mapped_column(
        ForeignKey("notification_channels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subscription_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("subscription_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class NotificationDeliveryAttempt(Base):
    __tablename__ = "notification_delivery_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'failed', 'timeout')",
            name="delivery_attempt_status",
        ),
        Index("ix_delivery_attempts_delivery_number", "delivery_id", "attempt_number"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    delivery_id: Mapped[UUID] = mapped_column(
        ForeignKey("notification_deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    channel_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("notification_channels.id", ondelete="SET NULL"), nullable=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_detail_safe: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    request_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    response_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
