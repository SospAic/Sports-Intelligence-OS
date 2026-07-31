from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SavedTopic(TimestampMixin, Base):
    __tablename__ = "saved_topics"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('content', 'article', 'event', 'manual')",
            name="saved_topic_source_type",
        ),
        CheckConstraint(
            "status IN ('inbox', 'planned', 'in_progress', 'completed', 'archived')",
            name="saved_topic_status",
        ),
        CheckConstraint("priority >= 0 AND priority <= 100", name="saved_topic_priority"),
        UniqueConstraint("workspace_id", "source_type", "source_id"),
        Index("ix_saved_topics_workspace_status", "workspace_id", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="inbox", index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
