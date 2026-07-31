from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TrendTopic(TimestampMixin, Base):
    """趋势话题：按平台/日期聚合的热门话题"""

    __tablename__ = "trend_topics"
    __table_args__ = (
        # 同一工作区 + 平台 + 话题标题 + 观测日期 唯一
        Index("ix_trend_topics_workspace_title", "workspace_id", "title"),
        Index("ix_trend_topics_workspace_platform", "workspace_id", "platform"),
        Index("ix_trend_topics_observed_at", "observed_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="general")
    heat_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    growth_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TrendVideo(TimestampMixin, Base):
    """趋势视频：平台上的热门/爆发视频"""

    __tablename__ = "trend_videos"
    __table_args__ = (
        Index("ix_trend_videos_workspace_platform", "workspace_id", "platform"),
        Index("ix_trend_videos_observed_at", "observed_at"),
        Index("ix_trend_videos_breakout", "breakout_score"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    view_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    like_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    share_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    breakout_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TrendKeywordSnapshot(TimestampMixin, Base):
    """关键词趋势快照：某关键词在某平台的观测数据"""

    __tablename__ = "trend_keyword_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "keyword", "platform", "observed_at",
            name="uq_trend_kw_ws_kw_plat_time",
        ),
        Index("ix_trend_kw_workspace_platform", "workspace_id", "platform"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    keyword: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    video_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    avg_views: Mapped[float | None] = mapped_column(Float, nullable=True)
    heat_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class CrossPlatformLink(TimestampMixin, Base):
    """跨平台同题关联：记录不同平台实体之间的同题建议链接。

    在没有可靠实体链接和人工确认前，不把跨语言相似标题自动合并为同一事实事件。
    此表仅存储建议链接，需人工确认后才生效。
    """

    __tablename__ = "cross_platform_links"
    __table_args__ = (
        Index("ix_cpl_workspace_status", "workspace_id", "status"),
        Index("ix_cpl_source", "source_entity_type", "source_entity_id"),
        Index("ix_cpl_target", "target_entity_type", "target_entity_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_entity_id: Mapped[UUID] = mapped_column(nullable=False)
    target_entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_entity_id: Mapped[UUID] = mapped_column(nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="suggested", index=True
    )
    match_details_json: Mapped[dict[str, Any]] = mapped_column(
        "match_details", JSON, nullable=False, default=dict
    )
