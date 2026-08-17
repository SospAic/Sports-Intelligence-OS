"""Auditable, no-side-effect rule applicability simulations."""

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

from app.db.base import Base, TimestampMixin


class RuleSimulationRun(TimestampMixin, Base):
    """A frozen preview of which versioned rules apply to an input context.

    This table intentionally stores the result rather than re-evaluating it on
    read. A rule version is immutable once published, but retaining the exact
    input and projection still matters for historical review and feedback.
    """

    __tablename__ = "rule_simulation_runs"
    __table_args__ = (
        Index("ix_rule_simulation_runs_workspace_created", "workspace_id", "created_at"),
        Index("ix_rule_simulation_runs_version_created", "version_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_set_id: Mapped[UUID] = mapped_column(
        ForeignKey("rule_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rule_set_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    historical_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    applicable_count: Mapped[int] = mapped_column(nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    feedback: Mapped[list[RuleSimulationFeedback]] = relationship(
        back_populates="simulation", cascade="all, delete-orphan"
    )


class RuleSimulationFeedback(TimestampMixin, Base):
    """Human judgement attached to one simulated rule result."""

    __tablename__ = "rule_simulation_feedback"
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('pass', 'fail', 'not_applicable', 'uncertain')",
            name="rule_simulation_feedback_verdict",
        ),
        UniqueConstraint(
            "simulation_id",
            "rule_id",
            "created_by",
            name="uq_rule_simulation_feedback_actor_rule",
        ),
        Index("ix_rule_simulation_feedback_simulation", "simulation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    simulation_id: Mapped[UUID] = mapped_column(
        ForeignKey("rule_simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[UUID] = mapped_column(
        ForeignKey("rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    verdict: Mapped[str] = mapped_column(String(24), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    simulation: Mapped[RuleSimulationRun] = relationship(back_populates="feedback")
