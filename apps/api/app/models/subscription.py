"""Auditable account/content subscriptions and their trigger history."""

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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SubscriptionRule(TimestampMixin, Base):
    """A bounded subscription that turns observed facts into queued alerts."""

    __tablename__ = "subscription_rules"
    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('new_content', 'keyword_match', 'metric_spike')",
            name="subscription_rule_trigger_type",
        ),
        CheckConstraint("cooldown_seconds >= 0", name="subscription_rule_cooldown"),
        UniqueConstraint("workspace_id", "name", name="uq_subscription_rules_workspace_name"),
        Index(
            "ix_subscription_rules_workspace_enabled",
            "workspace_id",
            "enabled",
            "priority",
        ),
        Index(
            "ix_subscription_rules_target",
            "workspace_id",
            "account_id",
            "platform_id",
            "enabled",
        ),
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
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="new_content")
    platform_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platforms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    channel_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SubscriptionEvent(Base):
    """One immutable evaluation result for a subscription event key."""

    __tablename__ = "subscription_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('not_matched', 'suppressed', 'queued', 'partial', 'failed')",
            name="subscription_event_status",
        ),
        UniqueConstraint(
            "workspace_id",
            "subscription_id",
            "event_key",
            name="uq_subscription_events_event_key",
        ),
        Index("ix_subscription_events_subscription_time", "subscription_id", "evaluated_at"),
        Index("ix_subscription_events_entity_time", "entity_type", "entity_id", "evaluated_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subscription_id: Mapped[UUID] = mapped_column(
        ForeignKey("subscription_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    delivery_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
