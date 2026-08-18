from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class PromptCollection(TimestampMixin, Base):
    __tablename__ = "prompt_collections"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'disabled', 'archived')", name="prompt_collection_status"
        ),
        UniqueConstraint("workspace_id", "key"),
        Index("ix_prompt_collections_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="generation")
    # Kept service-validated to avoid a circular FK with prompt_versions.
    current_version_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    versions: Mapped[list[PromptVersion]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')", name="prompt_version_status"
        ),
        UniqueConstraint("collection_id", "version"),
        Index("ix_prompt_versions_collection_status", "collection_id", "status"),
        Index("ix_prompt_versions_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    collection_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    variables_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    model_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    collection: Mapped[PromptCollection] = relationship(back_populates="versions")


class GenerationWorkflow(TimestampMixin, Base):
    __tablename__ = "generation_workflows"
    __table_args__ = (
        UniqueConstraint("workspace_id", "key"),
        Index("ix_generation_workflows_workspace_enabled", "workspace_id", "enabled"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    default_rule_set_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rule_set_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    default_prompt_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    runs: Mapped[list[GenerationRun]] = relationship(back_populates="workflow")


class GenerationRun(TimestampMixin, Base):
    __tablename__ = "generation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="generation_run_status",
        ),
        CheckConstraint("rewrite_count >= 0", name="generation_run_rewrite_count"),
        Index("ix_generation_runs_workspace_created", "workspace_id", "created_at"),
        Index("ix_generation_runs_workspace_status", "workspace_id", "status"),
        UniqueConstraint("workspace_id", "idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    workflow_id: Mapped[UUID] = mapped_column(
        ForeignKey("generation_workflows.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    input_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    input_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_set_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rule_set_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    prompt_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    model_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    current_step: Mapped[str | None] = mapped_column(String(80), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="verification_incomplete"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    final_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation_result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    rewrite_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Keep the structured error contract available without forcing operators
    # and reporting queries to unpack the legacy JSON blob.
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_detail_safe: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    is_saved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    workflow: Mapped[GenerationWorkflow] = relationship(back_populates="runs")
    steps: Mapped[list[GenerationStep]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="GenerationStep.sort_order"
    )


class GenerationStep(Base):
    __tablename__ = "generation_steps"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'skipped')",
            name="generation_step_status",
        ),
        UniqueConstraint("run_id", "step_key"),
        Index("ix_generation_steps_run_order", "run_id", "sort_order"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    prompt_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    run: Mapped[GenerationRun] = relationship(back_populates="steps")
