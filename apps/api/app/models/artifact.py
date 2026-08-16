"""Physical media artifacts owned by a work or an on-demand download.

The JSON media manifest is intentionally kept for backwards compatibility and
fast adapter merges.  ``MediaArtifact`` is the durable integrity record used
for operator-facing status: a manifest entry is not considered ready merely
because a filename was written to JSON.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class MediaArtifact(TimestampMixin, Base):
    """One physical file referenced by a content/download media manifest."""

    __tablename__ = "media_artifacts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'ready', 'missing', 'corrupt', 'failed', 'stale')",
            name="media_artifact_status",
        ),
        CheckConstraint(
            "content_item_id IS NOT NULL OR download_id IS NOT NULL",
            name="media_artifact_owner_required",
        ),
        CheckConstraint(
            "retention_class IN ('managed', 'temporary', 'protected')",
            name="media_artifact_retention_class",
        ),
        Index("ix_media_artifacts_workspace_status", "workspace_id", "status"),
        Index("ix_media_artifacts_workspace_retention", "workspace_id", "retention_class"),
        Index("ix_media_artifacts_content_kind", "content_item_id", "artifact_kind"),
        Index("ix_media_artifacts_download_kind", "download_id", "artifact_kind"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), nullable=True, index=True
    )
    download_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("downloads.id", ondelete="CASCADE"), nullable=True, index=True
    )
    artifact_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    file_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    retention_class: Mapped[str] = mapped_column(
        String(16), nullable=False, default="managed"
    )
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_mtime_ns: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="live")
    source_provider: Mapped[str] = mapped_column(String(120), nullable=False, default="media")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )

    content_item: Mapped[Any] = relationship("ContentItem", back_populates="artifacts")
    download: Mapped[Any] = relationship("Download", back_populates="artifacts")
