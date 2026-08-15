"""Auditable editorial review items for generated content packages."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
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


class EditorialItem(TimestampMixin, Base):
    """A reviewable snapshot of a completed generation run."""

    __tablename__ = "editorial_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'rejected', 'archived')",
            name="editorial_item_status",
        ),
        CheckConstraint("priority >= 0 AND priority <= 100", name="editorial_item_priority"),
        UniqueConstraint("generation_run_id", name="uq_editorial_items_generation_run"),
        Index(
            "ix_editorial_items_workspace_status_priority",
            "workspace_id",
            "status",
            "priority",
            "updated_at",
        ),
        Index(
            "ix_editorial_items_workspace_assignee_status",
            "workspace_id",
            "assignee_id",
            "status",
        ),
        Index("ix_editorial_items_workspace_due_at", "workspace_id", "due_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    generation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assignee_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
