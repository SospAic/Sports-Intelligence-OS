"""Persistent per-user acknowledgement state for the operations inbox."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InboxReadState(Base):
    """A durable read receipt for one user and one operational record.

    ``item_id`` is intentionally polymorphic because the inbox aggregates
    task records from several tables and notification deliveries. The API
    validates the key shape and always scopes reads/writes by workspace and
    authenticated user.
    """

    __tablename__ = "inbox_read_states"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "user_id",
            "item_kind",
            "item_id",
            name="uq_inbox_read_states_user_item",
        ),
        CheckConstraint(
            "item_kind IN ("
            "'task', 'notification', 'editorial_comment', 'subscription_event', 'dead_letter')",
            name="inbox_read_state_item_kind",
        ),
        Index("ix_inbox_read_states_workspace_user_read", "workspace_id", "user_id", "read_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    item_id: Mapped[UUID] = mapped_column(nullable=False)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
