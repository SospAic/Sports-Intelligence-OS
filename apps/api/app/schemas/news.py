from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

NewsSourceType = Literal["rss", "atom", "json", "web", "manual"]
NewsSort = Literal[
    "published_at",
    "fetched_at",
    "heat_score",
    "reliability_score",
    "source_count",
    "controversy_score",
    "visual_score",
    "story_score",
]
EventSort = Literal[
    "last_update_time",
    "heat_score",
    "reliability_score",
    "source_count",
    "article_count",
    "controversy_score",
    "visual_score",
    "story_score",
]
SortOrder = Literal["asc", "desc"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    source_type: NewsSourceType
    url: HttpUrl | None = None
    category: str = Field(min_length=1, max_length=120)
    language: str | None = Field(default=None, max_length=16)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    reliability_score: float = Field(default=50, ge=0, le=100)
    priority: int = Field(default=50, ge=0, le=100)
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_url_mode(self) -> "SourceCreate":
        if self.source_type == "manual" and self.url is not None:
            raise ValueError("manual source must not have a URL")
        if self.source_type != "manual" and self.url is None:
            raise ValueError("network source requires a URL")
        return self


class SourceUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: HttpUrl | None = None
    category: str | None = Field(default=None, min_length=1, max_length=120)
    language: str | None = Field(default=None, max_length=16)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    reliability_score: float | None = Field(default=None, ge=0, le=100)
    priority: int | None = Field(default=None, ge=0, le=100)
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    name: str
    source_type: NewsSourceType
    url: str | None
    category: str
    language: str | None
    country: str | None
    reliability_score: float
    priority: int
    enabled: bool
    provider_key: str
    config: dict[str, Any] = Field(validation_alias="config_json")
    last_attempt_at: datetime | None
    last_synced_at: datetime | None
    next_sync_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    consecutive_failures: int
    active_sync_run_id: UUID | None = None
    active_sync_status: Literal["queued", "running"] | None = None
    created_at: datetime
    updated_at: datetime


class SourcePage(BaseModel):
    items: list[SourceRead]
    page: int
    page_size: int
    total: int


class ManualArticleCreate(StrictModel):
    source_id: UUID
    external_id: str | None = Field(default=None, max_length=512)
    canonical_url: HttpUrl
    title: str = Field(min_length=1, max_length=1000)
    summary: str | None = Field(default=None, max_length=20_000)
    content: str | None = Field(default=None, max_length=100_000)
    author: str | None = Field(default=None, max_length=255)
    published_at: datetime | None = None
    event_time: datetime | None = None
    language: str | None = Field(default=None, max_length=16)
    sport: str | None = Field(default=None, max_length=120)
    league: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    controversy_score: float = Field(default=0, ge=0, le=100)
    visual_score: float = Field(default=0, ge=0, le=100)
    story_score: float = Field(default=0, ge=0, le=100)


class ArticleUpdate(BaseModel):
    """Partial update for an existing article."""

    title: str | None = Field(default=None, min_length=1, max_length=1000)
    summary: str | None = None
    content: str | None = None
    author: str | None = Field(default=None, max_length=255)
    canonical_url: str | None = Field(default=None, max_length=2048)
    published_at: datetime | None = None
    event_time: datetime | None = None
    language: str | None = Field(default=None, max_length=16)
    sport: str | None = Field(default=None, max_length=120)
    league: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    controversy_score: float | None = Field(default=None, ge=0, le=100)
    visual_score: float | None = Field(default=None, ge=0, le=100)
    story_score: float | None = Field(default=None, ge=0, le=100)


class ArticleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    source_id: UUID
    source: SourceRead
    external_id: str
    canonical_url: str
    title: str
    summary: str | None
    content: str | None
    author: str | None
    published_at: datetime | None
    event_time: datetime | None
    fetched_at: datetime
    language: str | None
    sport: str | None
    league: str | None
    country: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    content_hash: str
    duplicate_group_id: UUID | None
    is_duplicate: bool = False
    is_bookmarked: bool
    source_kind: Literal["live", "imported"]
    source_provider: str
    source_url: str
    raw_payload_ref: str | None
    event_id: UUID | None = None
    heat_score: float | None = None
    created_at: datetime
    updated_at: datetime


class ArticlePage(BaseModel):
    items: list[ArticleRead]
    page: int
    page_size: int
    total: int


class TopicEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    title: str
    normalized_title: str
    summary: str | None
    sport: str | None
    league: str | None
    start_time: datetime | None
    last_update_time: datetime
    article_count: int
    source_count: int
    heat_score: float
    reliability_score: float
    controversy_score: float
    visual_score: float
    story_score: float
    status: Literal["active", "developing", "closed"]
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    is_bookmarked: bool
    bookmarked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TopicEventDetail(TopicEventRead):
    articles: list[ArticleRead]


class TopicEventPage(BaseModel):
    items: list[TopicEventRead]
    page: int
    page_size: int
    total: int


class EventMergeRequest(StrictModel):
    event_ids: list[UUID] = Field(min_length=2, max_length=50)
    title: str | None = Field(default=None, min_length=1, max_length=1000)


class EventSplitRequest(StrictModel):
    article_ids: list[UUID] = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=1000)


class BookmarkRequest(StrictModel):
    bookmarked: bool = True


class NewsSyncRequest(StrictModel):
    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "NewsSyncRequest":
        if (self.start is None) != (self.end is None):
            raise ValueError("start and end must be provided together")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("start cannot be after end")
        return self


class NewsSyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    source_id: UUID
    provider_key: str
    request_id: str
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    status: Literal["queued", "running", "success", "error", "skipped", "cancelled"]
    records_created: int
    records_updated: int
    duplicate_count: int
    error_code: str | None
    error_message: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")


class NewsSyncRunPage(BaseModel):
    items: list[NewsSyncRunRead]
    page: int
    page_size: int
    total: int


class NewsScoringConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    version: int
    is_active: bool
    source_weight: float
    freshness_weight: float
    source_count_weight: float
    article_count_weight: float
    user_interest_weight: float
    freshness_half_life_hours: float
    title_similarity_threshold: float
    event_similarity_threshold: float
    created_at: datetime
    updated_at: datetime


class NewsScoringConfigUpdate(StrictModel):
    source_weight: float = Field(ge=0, le=100)
    freshness_weight: float = Field(ge=0, le=100)
    source_count_weight: float = Field(ge=0, le=100)
    article_count_weight: float = Field(ge=0, le=100)
    user_interest_weight: float = Field(ge=0, le=100)
    freshness_half_life_hours: float = Field(gt=0, le=720)
    title_similarity_threshold: float = Field(ge=0, le=1)
    event_similarity_threshold: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_weight_total(self) -> "NewsScoringConfigUpdate":
        total = (
            self.source_weight
            + self.freshness_weight
            + self.source_count_weight
            + self.article_count_weight
            + self.user_interest_weight
        )
        if abs(total - 100) > 0.001:
            raise ValueError("heat score weights must total 100")
        return self
