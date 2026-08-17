"""Auditable rights and availability review for one media artifact."""

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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class MediaArtifactRights(TimestampMixin, Base):
    __tablename__ = "media_artifact_rights"
    __table_args__ = (
        CheckConstraint(
            "rights_status IN ('unknown', 'pending_review', 'approved', 'restricted', 'expired')",
            name="media_rights_status",
        ),
        CheckConstraint("source_kind IN ('live', 'imported')", name="media_rights_source_kind"),
        UniqueConstraint("artifact_id", name="uq_media_artifact_rights_artifact"),
        Index("ix_media_rights_workspace_id", "workspace_id"),
        Index("ix_media_rights_artifact_id", "artifact_id"),
        Index("ix_media_rights_workspace_status", "workspace_id", "rights_status"),
        Index("ix_media_rights_workspace_expiry", "workspace_id", "valid_until"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("media_artifacts.id", ondelete="CASCADE"), nullable=False
    )
    rights_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    license_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rights_holder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    territories: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="imported")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
