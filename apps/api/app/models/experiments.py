"""Observation-only content experiments backed by real publication evidence."""

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
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import conv

from app.db.base import Base, TimestampMixin


class ContentExperiment(TimestampMixin, Base):
    """A descriptive comparison, never an automatic causal A/B claim."""

    __tablename__ = "content_experiments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'running', 'completed', 'archived')",
            name=conv("ck_content_experiments_content_experiment_status"),
        ),
        CheckConstraint(
            "dimension IN ('title', 'hook', 'story_order', 'thumbnail')",
            name=conv("ck_content_experiments_content_experiment_dimension"),
        ),
        CheckConstraint(
            "source_kind IN ('live', 'imported', 'mock')",
            name=conv("ck_content_experiments_content_experiment_source_kind"),
        ),
        Index("ix_content_experiments_workspace_id", "workspace_id"),
        Index("ix_content_experiments_created_by", "created_by"),
        Index("ix_content_experiments_status", "status"),
        Index("ix_content_experiments_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="imported")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )

    variants: Mapped[list[ContentExperimentVariant]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="ContentExperimentVariant.created_at",
    )


class ContentExperimentVariant(TimestampMixin, Base):
    """One labeled variant linked to a monitored content/publication record."""

    __tablename__ = "content_experiment_variants"
    __table_args__ = (
        Index("ix_content_experiment_variants_workspace_id", "workspace_id"),
        Index("ix_content_experiment_variants_publication", "publication_id"),
        UniqueConstraint(
            "experiment_id", "label", name="uq_content_experiment_variant_label"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    experiment_id: Mapped[UUID] = mapped_column(
        ForeignKey("content_experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True
    )
    publication_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("publications.id", ondelete="SET NULL"), nullable=True
    )
    exposure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )

    experiment: Mapped[ContentExperiment] = relationship(back_populates="variants")
