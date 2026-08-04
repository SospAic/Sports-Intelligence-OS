from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base


class SyncRun(Base):
    """Auditable execution record and cross-worker lock for platform synchronization."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('account', 'account_contents', 'content_item')",
            name="sync_run_target_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'success', 'degraded', "
            "'error', 'skipped', 'cancelled')",
            name="sync_run_status",
        ),
        CheckConstraint("records_created >= 0", name="sync_run_created_nonnegative"),
        CheckConstraint("records_updated >= 0", name="sync_run_updated_nonnegative"),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="sync_run_progress_range",
        ),
        CheckConstraint(
            "items_processed >= 0", name="sync_run_items_processed_nonnegative"
        ),
        Index("ix_sync_runs_workspace_started", "workspace_id", "started_at"),
        Index("ix_sync_runs_target_started", "target_type", "target_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    adapter_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    records_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    items_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Code-level detail: the underlying exception class, where it originated,
    # the adapter that raised it and the trace id. Surfaced verbatim to
    # operators/developers so failures are debuggable rather than opaque.
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Business-level explanation: a human-readable description of what the
    # error means for this account and the concrete remediation steps, mapped
    # from ``error_code``. Shown to operators alongside the raw detail.
    error_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    # Non-null only while queued/running. The unique value is released on terminal status.
    lock_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)


class SyncRunEvent(Base):
    """Append-only, per-step execution log for a :class:`SyncRun`.

    Captures stage transitions, per-page listings, per-content upserts,
    analytics fetches and every caught exception so operators can replay
    exactly what a sync did (and where it degraded) instead of only seeing a
    terminal ``success``/``error`` summary.
    """

    __tablename__ = "sync_run_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["sync_run_id"],
            ["sync_runs.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "event_type IN ('stage', 'page', 'item', 'analytics', "
            "'external_call', 'warning', 'error', 'info', 'summary')",
            name="sync_run_event_type",
        ),
        CheckConstraint(
            "level IN ('info', 'warn', 'error')",
            name="sync_run_event_level",
        ),
        Index("ix_sync_run_events_run_sequence", "sync_run_id", "sequence"),
        Index("ix_sync_run_events_run_created", "sync_run_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    sync_run_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
