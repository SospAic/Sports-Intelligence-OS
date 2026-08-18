from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


def _now() -> datetime:
    return datetime.now(UTC)


class VideoSearchPlan(TimestampMixin, Base):
    """A scheduled video-content query. Discovery metadata is never a match by itself."""

    __tablename__ = "video_search_plans"
    __table_args__ = (
        Index("ix_video_search_plans_workspace_status", "workspace_id", "status"),
        Index("ix_video_search_plans_due", "status", "next_run_at"),
        CheckConstraint(
            "status IN ('active', 'paused', 'error')",
            name="video_search_plan_status",
        ),
        CheckConstraint(
            "interval_seconds >= 60 AND interval_seconds <= 2592000",
            name="video_search_plan_interval",
        ),
        CheckConstraint(
            "max_candidates >= 1 AND max_candidates <= 200",
            name="video_search_plan_max_candidates",
        ),
        CheckConstraint(
            "min_match_score >= 0 AND min_match_score <= 1",
            name="video_search_plan_score_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    query_text: Mapped[str] = mapped_column(String(2000), nullable=False)
    platforms_json: Mapped[list[str]] = mapped_column(
        "platforms",
        JSON,
        nullable=False,
        default=lambda: ["youtube", "tiktok", "douyin", "bilibili"],
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    min_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.65)
    content_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="visual_audio")
    analyzer_key: Mapped[str] = mapped_column(String(80), nullable=False, default="gemini_video")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(nullable=True)


class VideoSearchRun(TimestampMixin, Base):
    """One observable execution of a plan, including partial and stopped work."""

    __tablename__ = "video_search_runs"
    __table_args__ = (
        Index("ix_video_search_runs_workspace_created", "workspace_id", "created_at"),
        Index("ix_video_search_runs_plan_status", "plan_id", "status"),
        CheckConstraint(
            "status IN ('queued', 'running', 'stopping', 'completed', 'partial', "
            "'failed', 'stopped')",
            name="video_search_run_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("video_search_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analyzed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stop_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class VideoSearchCandidate(TimestampMixin, Base):
    """A deduplicated candidate with evidence from a real content analyzer."""

    __tablename__ = "video_search_candidates"
    __table_args__ = (
        UniqueConstraint("plan_id", "canonical_url", name="uq_video_search_candidate_plan_url"),
        Index(
            "ix_video_search_candidates_workspace_status", "workspace_id", "content_match_status"
        ),
        Index(
            "ix_video_search_candidates_plan_score",
            "plan_id",
            "content_match_status",
            "match_score",
        ),
        CheckConstraint(
            "content_match_status IN ('discovered', 'analyzing', 'matched', 'rejected', "
            "'unavailable', 'failed')",
            name="video_search_candidate_status",
        ),
        CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)",
            name="video_search_candidate_score_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("video_search_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    last_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("video_search_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    canonical_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_match_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="discovered", index=True
    )
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(
        "evidence", JSON, nullable=False, default=dict
    )
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    analysis_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="live")
    source_provider: Mapped[str] = mapped_column(
        String(80), nullable=False, default="platform_search"
    )
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
