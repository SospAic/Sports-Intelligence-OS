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


class Source(TimestampMixin, Base):
    __tablename__ = "news_sources"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('rss', 'atom', 'json', 'manual')",
            name="news_source_type",
        ),
        CheckConstraint(
            "reliability_score >= 0 AND reliability_score <= 100",
            name="news_source_reliability_range",
        ),
        CheckConstraint("priority >= 0 AND priority <= 100", name="news_source_priority_range"),
        CheckConstraint("consecutive_failures >= 0", name="news_source_failures_nonnegative"),
        UniqueConstraint("workspace_id", "name"),
        Index("ix_news_sources_workspace_enabled", "workspace_id", "enabled"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    reliability_score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=50)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    provider_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(
        "config", JSON, nullable=False, default=dict
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    articles: Mapped[list[Article]] = relationship(back_populates="source")


class Article(TimestampMixin, Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id"),
        CheckConstraint(
            "source_kind IN ('live', 'imported')",
            name="news_article_source_kind",
        ),
        Index("ix_articles_workspace_published", "workspace_id", "published_at"),
        Index("ix_articles_workspace_fetched", "workspace_id", "fetched_at"),
        Index("ix_articles_source_published", "source_id", "published_at"),
        Index("ix_articles_workspace_sport", "workspace_id", "sport"),
        Index("ix_articles_workspace_duplicate", "workspace_id", "duplicate_group_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("news_sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    sport: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    league: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    duplicate_group_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    is_bookmarked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_provider: Mapped[str] = mapped_column(String(120), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)

    source: Mapped[Source] = relationship(back_populates="articles")
    event_links: Mapped[list[EventArticle]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )


class TopicEvent(TimestampMixin, Base):
    __tablename__ = "topic_events"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'developing', 'closed')", name="topic_event_status"),
        CheckConstraint("heat_score >= 0 AND heat_score <= 100", name="event_heat_range"),
        CheckConstraint(
            "reliability_score >= 0 AND reliability_score <= 100",
            name="event_reliability_range",
        ),
        CheckConstraint(
            "controversy_score >= 0 AND controversy_score <= 100",
            name="event_controversy_range",
        ),
        CheckConstraint("visual_score >= 0 AND visual_score <= 100", name="event_visual_range"),
        CheckConstraint("story_score >= 0 AND story_score <= 100", name="event_story_range"),
        Index("ix_topic_events_workspace_updated", "workspace_id", "last_update_time"),
        Index("ix_topic_events_workspace_heat", "workspace_id", "heat_score"),
        Index("ix_topic_events_workspace_sport", "workspace_id", "sport"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sport: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    league: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_update_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heat_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    reliability_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    controversy_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    visual_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    story_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    is_bookmarked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    bookmarked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    article_links: Mapped[list[EventArticle]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class EventArticle(Base):
    __tablename__ = "event_articles"
    __table_args__ = (
        UniqueConstraint("event_id", "article_id"),
        Index("ix_event_articles_article_event", "article_id", "event_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("topic_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=1)
    linked_by: Mapped[str] = mapped_column(String(32), nullable=False, default="automatic")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    event: Mapped[TopicEvent] = relationship(back_populates="article_links")
    article: Mapped[Article] = relationship(back_populates="event_links")


class NewsSyncRun(Base):
    __tablename__ = "news_sync_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'success', 'error', 'skipped')",
            name="news_sync_run_status",
        ),
        Index("ix_news_sync_runs_source_started", "source_id", "started_at"),
        Index("ix_news_sync_runs_workspace_started", "workspace_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("news_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    records_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    lock_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)


class NewsScoringConfig(TimestampMixin, Base):
    __tablename__ = "news_scoring_configs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "version"),
        CheckConstraint("freshness_half_life_hours > 0", name="news_freshness_half_life"),
        CheckConstraint(
            "title_similarity_threshold >= 0 AND title_similarity_threshold <= 1",
            name="news_title_similarity_range",
        ),
        CheckConstraint(
            "event_similarity_threshold >= 0 AND event_similarity_threshold <= 1",
            name="news_event_similarity_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    source_weight: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    freshness_weight: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    source_count_weight: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    article_count_weight: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    user_interest_weight: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    freshness_half_life_hours: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    title_similarity_threshold: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    event_similarity_threshold: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
