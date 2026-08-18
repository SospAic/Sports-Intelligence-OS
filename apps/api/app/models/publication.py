"""Publication records and fixed-window performance attribution."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import conv

from app.db.base import Base, TimestampMixin


class Publication(TimestampMixin, Base):
    """A planned, manually recorded, or externally verified publication.

    A record is deliberately separate from ``ContentItem``: creating a plan or
    importing an external URL must not make the platform monitoring tables look
    as if a publish adapter succeeded.
    """

    __tablename__ = "publications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planned', 'scheduled', 'published', 'unverified', 'failed', 'cancelled')",
            name="publication_status",
        ),
        CheckConstraint(
            "source_kind IN ('live', 'imported', 'mock')",
            name="publication_source_kind",
        ),
        Index("ix_publications_workspace_status_time", "workspace_id", "status", "published_at"),
        Index("ix_publications_workspace_content", "workspace_id", "content_item_id"),
        Index("ix_publications_workspace_generation", "workspace_id", "generation_run_id"),
        UniqueConstraint(
            "workspace_id",
            "platform_id",
            "external_id",
            name="uq_publications_workspace_platform_external",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    generation_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    editorial_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("editorial_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    platform_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platforms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="imported")
    source_provider: Mapped[str] = mapped_column(String(120), nullable=False, default="manual")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )

    attributions: Mapped[list[PerformanceAttribution]] = relationship(
        back_populates="publication",
        cascade="all, delete-orphan",
        order_by="PerformanceAttribution.window_seconds",
    )


class PerformanceAttribution(TimestampMixin, Base):
    """An observed metric snapshot at a fixed interval after publication."""

    __tablename__ = "performance_attributions"
    __table_args__ = (
        CheckConstraint(
            "window_key IN ('1h', '3h', '6h', '24h', '72h', '7d', '30d')",
            name=conv("pat_window_key"),
        ),
        CheckConstraint(
            "measurement_status IN ('measured', 'not_due', 'unavailable')",
            name=conv("pat_measurement_status"),
        ),
        CheckConstraint(
            "source_kind IS NULL OR source_kind IN ('live', 'imported', 'mock')",
            name=conv("pat_source_kind"),
        ),
        CheckConstraint(
            "view_count IS NULL OR view_count >= 0", name=conv("pat_views_nonnegative")
        ),
        CheckConstraint(
            "like_count IS NULL OR like_count >= 0", name=conv("pat_likes_nonnegative")
        ),
        CheckConstraint(
            "comment_count IS NULL OR comment_count >= 0", name=conv("pat_comments_nonnegative")
        ),
        CheckConstraint(
            "share_count IS NULL OR share_count >= 0", name=conv("pat_shares_nonnegative")
        ),
        CheckConstraint(
            "favorite_count IS NULL OR favorite_count >= 0", name=conv("pat_favorites_nonnegative")
        ),
        UniqueConstraint(
            "publication_id", "window_key", name="uq_performance_attribution_publication_window"
        ),
        Index("ix_performance_attribution_publication_window", "publication_id", "window_seconds"),
        Index("ix_performance_attribution_workspace_captured", "workspace_id", "captured_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    publication_id: Mapped[UUID] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    window_key: Mapped[str] = mapped_column(String(8), nullable=False)
    window_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    measurement_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_due")
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    view_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    like_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    share_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    favorite_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    follower_gain: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    average_watch_time: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    completion_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    source_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(
        "evidence", JSON, nullable=False, default=dict
    )

    publication: Mapped[Publication] = relationship(back_populates="attributions")
