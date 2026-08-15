"""Workspace-scoped saved views for the editorial workbench."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class EditorialSavedView(TimestampMixin, Base):
    """A named, shareable filter preset for the editorial queue."""

    __tablename__ = "editorial_saved_views"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_editorial_saved_views_workspace_name"),
        CheckConstraint(
            "status IS NULL OR status IN ("
            "'draft', 'in_review', 'approved', 'rejected', 'archived')",
            name="editorial_saved_view_status",
        ),
        CheckConstraint(
            "priority_min IS NULL OR (priority_min >= 0 AND priority_min <= 100)",
            name="editorial_saved_view_priority_min",
        ),
        CheckConstraint(
            "priority_max IS NULL OR (priority_max >= 0 AND priority_max <= 100)",
            name="editorial_saved_view_priority_max",
        ),
        Index("ix_editorial_saved_views_workspace", "workspace_id", "name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assignee_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    overdue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unassigned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
