"""Shared operational queue state for the unified inbox."""

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
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class InboxQueueState(TimestampMixin, Base):
    """Workspace-shared handling metadata for a task or notification."""

    __tablename__ = "inbox_queue_states"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "item_kind",
            "item_id",
            name="uq_inbox_queue_states_item",
        ),
        CheckConstraint(
            "item_kind IN ('task', 'notification')",
            name="inbox_queue_item_kind",
        ),
        CheckConstraint(
            "state IN ('open', 'in_progress', 'completed')",
            name="inbox_queue_state",
        ),
        Index("ix_inbox_queue_states_workspace_updated", "workspace_id", "updated_at"),
        Index("ix_inbox_queue_states_workspace_assignee", "workspace_id", "assignee_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    item_id: Mapped[UUID] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    labels: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    assignee_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class InboxSavedView(TimestampMixin, Base):
    """Workspace-shared filter preset for the unified operations inbox."""

    __tablename__ = "inbox_saved_views"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "name",
            name="uq_inbox_saved_views_workspace_name",
        ),
        Index("ix_inbox_saved_views_workspace_name", "workspace_id", "name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    filters_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
