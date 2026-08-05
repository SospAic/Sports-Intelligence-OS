from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
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
            "workspace_id",
            "keyword",
            "platform",
            "observed_at",
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
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="cross_platform_link_confidence_range",
        ),
        CheckConstraint(
            "status IN ('suggested', 'confirmed', 'rejected')",
            name="cross_platform_link_status",
        ),
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
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="suggested", index=True)
    match_details_json: Mapped[dict[str, Any]] = mapped_column(
        "match_details", JSON, nullable=False, default=dict
    )


class DerivativeTopic(TimestampMixin, Base):
    """衍生话题：围绕某个趋势热点的「平台上已存在」或「AI 预测的潜在」衍生角度。

    - ``existing_on_platform``：通过对热点关键词做平台搜索、按角度聚类得到的
      已在平台上有人制作的衍生内容（带样本热度证据）。
    - ``ai_predicted``：由 LLM 基于热点与现有衍生缺口生成的潜在热门衍生话题
      （带预测热度与理由），可被「采纳」后进入创作流程。
    """

    __tablename__ = "derivative_topics"
    __table_args__ = (
        Index("ix_derivative_topic_workspace", "workspace_id"),
        Index("ix_derivative_topic_source", "source_topic_id"),
        Index("ix_derivative_topic_kind", "workspace_id", "kind"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    source_topic_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trend_topics.id", ondelete="CASCADE"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="existing_on_platform")
    angle: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    predicted_heat_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(
        "evidence", JSON, nullable=False, default=dict
    )
    ai_rationale: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="suggested", index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    adopted_generation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class SearchQuery(TimestampMixin, Base):
    """智能搜索请求：一段自然语言描述 + 平台范围，触发一次全网/指定平台检索分析。"""

    __tablename__ = "search_queries"
    __table_args__ = (Index("ix_search_query_workspace", "workspace_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_text: Mapped[str] = mapped_column(String(2000), nullable=False)
    platform_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="all")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    requested_by: Mapped[UUID | None] = mapped_column(nullable=True)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SearchAnalysis(TimestampMixin, Base):
    """智能搜索分析结果：检索条件相关热度、声量、情绪、时间线、平台分布、相关衍生与摘要。"""

    __tablename__ = "search_analyses"
    __table_args__ = (
        Index("ix_search_analysis_workspace", "workspace_id"),
        Index("ix_search_analysis_query", "search_query_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    search_query_id: Mapped[UUID] = mapped_column(
        ForeignKey("search_queries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    related_hotness: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_estimate: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timeline_phases: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    platform_distribution: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    related_derivative_topics: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    sources: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_llm: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    results_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
