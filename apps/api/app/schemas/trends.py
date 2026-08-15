from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# 话题
# ---------------------------------------------------------------------------


class TrendTopicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    platform: str
    title: str
    category: str
    heat_score: float
    growth_rate: float | None = None
    rank: int
    sample_size: int
    metadata: dict[str, Any] = Field(validation_alias="metadata_json", default_factory=dict)
    observed_at: datetime
    created_at: datetime
    updated_at: datetime


class TrendTopicPage(BaseModel):
    items: list[TrendTopicRead]
    page: int
    page_size: int
    total: int


# ---------------------------------------------------------------------------
# 视频
# ---------------------------------------------------------------------------


class TrendVideoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    platform: str
    external_id: str
    title: str
    author_name: str | None = None
    author_url: str | None = None
    cover_url: str | None = None
    video_url: str | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    breakout_score: float | None = None
    category: str | None = None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json", default_factory=dict)
    observed_at: datetime
    created_at: datetime
    updated_at: datetime


class TrendVideoPage(BaseModel):
    items: list[TrendVideoRead]
    page: int
    page_size: int
    total: int


# ---------------------------------------------------------------------------
# 聚合统计（单/多平台 + 分类）
# ---------------------------------------------------------------------------


class TrendAggregateItem(BaseModel):
    platform: str
    category: str
    title: str
    kind: str  # "topic" | "video"
    metric: float
    metric_label: str
    observed_at: datetime


class TrendAggregate(BaseModel):
    """Single/multi-platform + category aggregation for the analytics view."""

    generated_at: datetime
    window_days: int
    platforms: list[str]
    categories: list[str]
    # 趋势时间线: 每天每平台的累计热度
    timeline: list[dict[str, Any]]
    # 排行榜单: 热点/视频按热度排序
    ranking: list[TrendAggregateItem]
    # 指数对比: 各平台归一化热度（0-100）
    index: list[dict[str, Any]]
    # 热度矩阵: 平台 × 分类 热度合计
    matrix: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# 关键词快照
# ---------------------------------------------------------------------------


class TrendKeywordSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    keyword: str
    platform: str
    observed_at: datetime
    video_count: int | None = None
    total_views: int | None = None
    avg_views: float | None = None
    heat_index: float | None = None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json", default_factory=dict)
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Dashboard 聚合
# ---------------------------------------------------------------------------


class PlatformSummary(BaseModel):
    """单平台趋势概要"""

    platform: str
    topic_count: int = 0
    video_count: int = 0
    avg_heat_score: float = 0.0
    max_breakout_score: float | None = None
    total_views: int | None = None


class TrendDashboard(BaseModel):
    """趋势分析看板聚合数据"""

    top_topics: list[TrendTopicRead] = Field(default_factory=list)
    breakout_videos: list[TrendVideoRead] = Field(default_factory=list)
    platform_summary: list[PlatformSummary] = Field(default_factory=list)
    window_hours: int = 24
    generated_at: datetime | None = None


# ---------------------------------------------------------------------------
# 评分解释 (Explainability)
# ---------------------------------------------------------------------------


class ScoreComponent(BaseModel):
    """单个评分分量的详细解释"""

    name: str
    raw_value: float | None = None
    percentile: float | None = None
    weight: float
    weighted_contribution: float | None = None
    missing: bool = False
    note: str | None = None


class ScoreExplanation(BaseModel):
    """评分可解释性详情"""

    entity_id: UUID
    entity_type: str
    score_field: str
    score_value: float | None = None
    algorithm_version: str
    components: list[ScoreComponent] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    sample_window: dict[str, str | None] = Field(default_factory=dict)
    confidence: float | None = None
    confidence_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 跨平台关联 (Cross-Platform Links)
# ---------------------------------------------------------------------------


class CrossPlatformLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    source_entity_type: str
    source_entity_id: UUID
    target_entity_type: str
    target_entity_id: UUID
    confidence: float
    status: str
    match_details: dict[str, Any] = Field(
        validation_alias="match_details_json", default_factory=dict
    )
    created_at: datetime
    updated_at: datetime


class CrossPlatformLinkPage(BaseModel):
    items: list[CrossPlatformLinkRead]
    page: int
    page_size: int
    total: int


# ---------------------------------------------------------------------------
# 衍生话题 (Derivative Topics)
# ---------------------------------------------------------------------------


class DerivativeTopicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    source_topic_id: UUID | None = None
    platform: str
    kind: str
    angle: str | None = None
    title: str
    description: str | None = None
    predicted_heat_score: float | None = None
    evidence: dict[str, Any] = Field(validation_alias="evidence_json", default_factory=dict)
    ai_rationale: str | None = None
    status: str
    confidence: float
    adopted_generation_id: UUID | None = None
    observed_at: datetime
    created_at: datetime
    updated_at: datetime


class DerivativeTopicPage(BaseModel):
    items: list[DerivativeTopicRead]
    page: int
    page_size: int
    total: int


class DerivativeGenerateRequest(BaseModel):
    topic_id: UUID


class DerivativeGenerateResponse(BaseModel):
    status: str
    notice: str | None = None
    items: list[DerivativeTopicRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 智能搜索 (Smart Search Analysis)
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query_text: str
    platform: str = "all"
    limit: int = 10


class SearchQueryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    query_text: str
    platform_scope: str
    status: str
    requested_by: UUID | None = None
    result_count: int
    created_at: datetime
    updated_at: datetime


class SearchAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    search_query_id: UUID
    related_hotness: float | None = None
    volume_estimate: dict[str, Any] | None = None
    sentiment: str | None = None
    timeline_phases: list[Any] | None = None
    platform_distribution: dict[str, Any] | None = None
    related_derivative_topics: list[Any] | None = None
    summary: str | None = None
    sources: list[Any] | None = None
    model_used: str | None = None
    raw_llm: dict[str, Any] | None = None
    results_json: list[Any] | None = None
    created_at: datetime
    updated_at: datetime


class SearchQueryPage(BaseModel):
    items: list[SearchQueryRead]
    page: int
    page_size: int
    total: int


class SearchAnalysisResponse(BaseModel):
    query: SearchQueryRead
    analysis: SearchAnalysisRead
    results: list[dict[str, Any]] = Field(default_factory=list)
    notice: str | None = None
