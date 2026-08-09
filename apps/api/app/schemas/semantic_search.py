"""Request/response contracts for local (non-LLM) content retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

SearchMode = Literal["hybrid", "vector", "keyword"]
ChunkKind = Literal["meta", "subtitle", "transcript"]


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    mode: SearchMode = "hybrid"
    limit: int = Field(default=20, ge=1, le=100)
    #: 每路召回的候选深度。调大能提高召回率，代价是排序耗时。
    candidates: int = Field(default=120, ge=10, le=1000)
    chunk_kinds: list[ChunkKind] | None = None
    platform_ids: list[UUID] | None = None
    account_ids: list[UUID] | None = None
    published_after: datetime | None = None
    published_before: datetime | None = None
    #: True 时为每个片段附带 ``score_breakdown``（排查"为什么这条排第一"用）。
    debug: bool = False

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("搜索词不能为空")
        return cleaned


class ScoreBreakdown(BaseModel):
    """Why a chunk scored what it scored. Only present when ``debug`` is set."""

    #: 归一化余弦相似度（1 最像）。纯关键词命中的块没有向量分。
    vector_score: float | None = None
    keyword_score: float
    rrf_score: float
    #: 未开启重排（或该候选没进重排窗口）时为 null。
    rerank_score: float | None = None
    explanation: str


class SemanticSearchChunk(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_kind: str
    chunk_index: int
    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    source_ref: str | None = None
    #: 余弦距离（0 最近）。纯关键词命中的块没有距离。
    distance: float | None = None
    score: float
    matched_by: list[str]
    score_breakdown: ScoreBreakdown | None = None


class SemanticSearchHit(BaseModel):
    content_item_id: UUID
    title: str
    canonical_url: str
    cover_url: str | None = None
    platform_id: UUID
    account_id: UUID
    published_at: datetime | None = None
    duration_seconds: float | None = None
    score: float
    best_chunk: SemanticSearchChunk
    chunks: list[SemanticSearchChunk]
    #: 与 ``best_chunk.score_breakdown`` 同源，方便消费方不用下钻。
    score_breakdown: ScoreBreakdown | None = None


class SemanticSearchResponse(BaseModel):
    query: str
    mode_requested: SearchMode
    mode_used: SearchMode
    #: 请求了向量检索但后端不可用时为 True，此时结果仅来自关键词召回。
    degraded: bool = False
    model: str | None = None
    total: int
    items: list[SemanticSearchHit]
    took_ms: int


class SemanticSearchStatus(BaseModel):
    enabled: bool
    backend: str
    model: str
    dimension: int
    #: 当前模型已索引的块数 / 内容数。
    embedded_chunks: int
    embedded_items: int
    #: 有可嵌文本但尚未索引的内容数。
    pending_items: int
    chunk_kinds: dict[str, int]


class ReindexRequest(BaseModel):
    limit: int = Field(default=500, ge=1, le=5000)
    #: True 时重算已索引内容（换模型或改分块参数后使用）。
    reindex: bool = False


class ReindexResponse(BaseModel):
    task_id: str
    limit: int
    reindex: bool
