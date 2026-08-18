from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

PLATFORMS = ("youtube", "tiktok", "douyin", "bilibili")


def normalize_platforms(value: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(item.strip().lower() for item in value if item.strip()))
    invalid = [item for item in normalized if item not in PLATFORMS]
    if invalid:
        raise ValueError(f"不支持的平台: {', '.join(invalid)}")
    if not normalized:
        raise ValueError("至少选择一个平台")
    return normalized


class VideoSearchPlanCreate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    query_text: str = Field(min_length=2, max_length=2000)
    platforms: list[str] = Field(default_factory=lambda: list(PLATFORMS))
    interval_seconds: int = Field(default=3600, ge=60, le=2_592_000)
    max_candidates: int = Field(default=20, ge=1, le=200)
    min_match_score: float = Field(default=0.65, ge=0, le=1)
    content_mode: Literal["visual_audio", "visual_only", "audio_visual_text"] = "visual_audio"
    analyzer_key: str = Field(default="gemini_video", min_length=2, max_length=80)
    run_now: bool = True

    @field_validator("query_text")
    @classmethod
    def validate_query(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("搜索描述至少需要 2 个字符")
        return cleaned

    @field_validator("platforms")
    @classmethod
    def validate_platforms(cls, value: list[str]) -> list[str]:
        return normalize_platforms(value)


class VideoSearchPlanUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    query_text: str | None = Field(default=None, min_length=2, max_length=2000)
    platforms: list[str] | None = None
    status: Literal["active", "paused", "error"] | None = None
    interval_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    max_candidates: int | None = Field(default=None, ge=1, le=200)
    min_match_score: float | None = Field(default=None, ge=0, le=1)
    content_mode: Literal["visual_audio", "visual_only", "audio_visual_text"] | None = None
    analyzer_key: str | None = Field(default=None, min_length=2, max_length=80)

    @field_validator("query_text")
    @classmethod
    def validate_optional_query(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value is not None else None

    @field_validator("platforms")
    @classmethod
    def validate_optional_platforms(cls, value: list[str] | None) -> list[str] | None:
        return normalize_platforms(value) if value is not None else None


class VideoSearchPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    name: str
    query_text: str
    platforms: list[str] = Field(validation_alias="platforms_json", default_factory=list)
    status: str
    interval_seconds: int
    next_run_at: datetime
    last_run_at: datetime | None = None
    max_candidates: int
    min_match_score: float
    content_mode: str
    analyzer_key: str
    last_error: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class VideoSearchRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    plan_id: UUID
    workspace_id: UUID
    task_id: str | None = None
    status: str
    candidate_count: int
    analyzed_count: int
    matched_count: int
    rejected_count: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stop_requested: bool
    error_detail: str | None = None
    created_at: datetime
    updated_at: datetime


class VideoSearchCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    plan_id: UUID
    last_run_id: UUID | None = None
    workspace_id: UUID
    platform: str
    external_id: str | None = None
    canonical_url: str
    title: str | None = None
    author_name: str | None = None
    cover_url: str | None = None
    published_at: datetime | None = None
    content_match_status: str
    match_score: float | None = None
    evidence: dict[str, Any] = Field(validation_alias="evidence_json", default_factory=dict)
    content_text: str | None = None
    analysis_provider: str | None = None
    analysis_model: str | None = None
    source_kind: str
    source_provider: str
    source_url: str | None = None
    fetched_at: datetime
    analyzed_at: datetime | None = None
    error_detail: str | None = None
    created_at: datetime
    updated_at: datetime


class VideoSearchPlanPage(BaseModel):
    items: list[VideoSearchPlanRead]
    page: int
    page_size: int
    total: int


class VideoSearchRunPage(BaseModel):
    items: list[VideoSearchRunRead]
    page: int
    page_size: int
    total: int


class VideoSearchCandidatePage(BaseModel):
    items: list[VideoSearchCandidateRead]
    page: int
    page_size: int
    total: int


class VideoSearchTopicCreate(BaseModel):
    """Optional overrides when promoting a matched search candidate to a topic."""

    title: str | None = Field(default=None, min_length=1, max_length=1000)
    summary: str | None = Field(default=None, max_length=20_000)
    priority: int = Field(default=60, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=20_000)


class VideoSearchCapabilities(BaseModel):
    analyzer_key: str
    configured: bool
    model: str | None = None
    platforms: dict[str, dict[str, Any]]
    notice: str | None = None


class VideoSearchRunResponse(BaseModel):
    run: VideoSearchRunRead
    message: str


class VideoSearchSummaryInputItem(BaseModel):
    id: str
    title: str = ""
    snippet: str = ""
    platform: str = ""
    engine: str = ""
    score: float = 0.0


class VideoSearchSummaryRequest(BaseModel):
    query: str = Field(default="", max_length=2000)
    items: list[VideoSearchSummaryInputItem]


class VideoSearchSummaryItem(BaseModel):
    id: str
    sentiment: Literal["positive", "neutral", "negative"]
    heat: float = Field(ge=0, le=1)


class VideoSearchSummaryRead(BaseModel):
    total: int
    platform_distribution: dict[str, int]
    engine_distribution: dict[str, int]
    top_items: list[dict[str, Any]]
    items: list[VideoSearchSummaryItem]
    llm_summary: str | None = None
    llm_available: bool = False
