from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class UserViewPreference(TimestampMixin, Base):
    """Per-user, per-workspace view preferences (filters, sort, layout, column visibility)."""

    __tablename__ = "user_view_preferences"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", "view_key"),
        Index("ix_user_view_preferences_workspace_user", "workspace_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    view_key: Mapped[str] = mapped_column(String(64), nullable=False)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
