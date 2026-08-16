"""Auditable collaboration comments attached to editorial review items."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class EditorialComment(TimestampMixin, Base):
    """An immutable comment in an editorial item's collaboration thread.

    Comments are intentionally not editable or deletable in the first slice.
    This keeps the review trail reliable while ``resolved_at`` represents the
    current collaboration state without rewriting the original message.
    """

    __tablename__ = "editorial_comments"
    __table_args__ = (
        Index(
            "ix_editorial_comments_workspace_item_created",
            "workspace_id",
            "editorial_item_id",
            "created_at",
        ),
        Index("ix_editorial_comments_item_resolved", "editorial_item_id", "resolved_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    editorial_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("editorial_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
