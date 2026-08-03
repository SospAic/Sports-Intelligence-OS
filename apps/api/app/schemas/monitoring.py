from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.schemas.settings import YtDlpDownloadSettings

SourceKind = Literal["live", "imported"]
AccountSyncStatus = Literal[
    "never", "queued", "syncing", "success", "degraded", "error", "disabled", "cancelled"
]
SortOrder = Literal["asc", "desc"]
AccountSort = Literal[
    "created_at",
    "updated_at",
    "display_name",
    "last_synced_at",
    "follower_count",
    "total_view_count",
    "follower_growth_24h",
]
ContentSort = Literal[
    "published_at",
    "first_seen_at",
    "last_seen_at",
    "title",
    "view_count",
    "view_growth_24h",
    "like_count",
    "comment_count",
    "share_count",
    "completion_rate",
    "engagement_rate",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    category: str
    enabled: bool
    adapter_key: str
    capabilities: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AccountCreate(StrictModel):
    # Platform is optional on first registration: when omitted, the system
    # infers it from the profile URL (see platform_detect). This lets the
    # operator paste a single URL without choosing a platform manually.
    platform_id: UUID | None = None
    external_id: str = Field(min_length=1, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    # display_name is optional on first registration: when omitted it is
    # defaulted to ``external_id`` and refined after the first sync.
    display_name: str | None = Field(default=None, max_length=255)
    profile_url: HttpUrl | None = None
    avatar_url: HttpUrl | None = None
    description: str | None = Field(default=None, max_length=10_000)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    language: str | None = Field(default=None, max_length=16)
    is_verified: bool | None = None
    sync_interval_seconds: int = Field(default=28800, ge=3600, le=604_800)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("external_id", "username", "display_name")
    @classmethod
    def strip_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class AccountUpdate(StrictModel):
    username: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    profile_url: HttpUrl | None = None
    avatar_url: HttpUrl | None = None
    description: str | None = Field(default=None, max_length=10_000)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    language: str | None = Field(default=None, max_length=16)
    is_active: bool | None = None
    sync_interval_seconds: int | None = Field(default=None, ge=3600, le=604_800)
    metadata: dict[str, Any] | None = None

    @field_validator("username", "display_name")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class AccountSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    account_id: UUID
    captured_at: datetime
    follower_count: int | None
    following_count: int | None
    total_like_count: int | None
    total_view_count: int | None
    video_count: int | None
    engagement_rate: float | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    source_kind: SourceKind
    source_provider: str
    fetched_at: datetime
    raw_payload_ref: str | None


class AccountMetricsHistoryPoint(BaseModel):
    """Compact time-series point for account metric charts (ascending by captured_at)."""

    model_config = ConfigDict(from_attributes=True)

    captured_at: datetime
    follower_count: int | None
    following_count: int | None
    total_like_count: int | None
    total_view_count: int | None
    video_count: int | None


class AccountMetricsHistory(BaseModel):
    """Account metric time series suitable for a front-end area/line chart."""

    account_id: UUID
    days: int
    points: list[AccountMetricsHistoryPoint]


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    platform_id: UUID
    platform: PlatformRead
    external_id: str
    username: str | None
    display_name: str
    profile_url: str | None
    avatar_url: str | None
    description: str | None
    country: str | None
    language: str | None
    is_verified: bool | None
    is_active: bool
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    last_synced_at: datetime | None
    next_sync_at: datetime | None
    sync_interval_seconds: int
    sync_status: AccountSyncStatus
    last_sync_error_code: str | None
    last_sync_error_message: str | None
    source_kind: SourceKind
    source_provider: str
    fetched_at: datetime
    source_url: str | None
    raw_payload_ref: str | None
    created_at: datetime
    updated_at: datetime
    latest_snapshot: AccountSnapshotRead | None = None
    follower_growth_24h: float | None = None


class AccountPage(BaseModel):
    items: list[AccountRead]
    page: int
    page_size: int
    total: int


class AccountSyncFetchSettings(StrictModel):
    """Per-account catalogue fetch window, deep-merged over the workspace
    ``sync_settings.yt_dlp`` window and works cap by the sync executor.

    Every field is optional; ``None`` means "inherit the workspace default".
    These are the controls surfaced in the per-sync "抓取数据设置" popup.
    """

    # 单次抓取数量: hard cap on how many works a single sync ingests.
    max_contents: int | None = Field(default=None, ge=1, le=5000)
    # 抓取范围 (YYYYMMDD). dateafter = 起始日期, datebefore = 截止日期.
    dateafter: str | None = None
    datebefore: str | None = None
    # 起始位置: 1-based offset into the catalogue (skip the first N works).
    playlist_start: int | None = Field(default=None, ge=1, le=100_000)


class AccountSyncSettingsOverride(StrictModel):
    """Per-account override layered on top of the workspace sync settings.

    Two independent sub-objects are overridable, both deep-merged over the
    workspace policy by the sync executor:

    * ``download`` — the yt-dlp artifact download policy;
    * ``fetch`` — the catalogue fetch window (count / date range / start).
    """

    download: YtDlpDownloadSettings
    fetch: AccountSyncFetchSettings | None = None


# -- Batch operations -------------------------------------------------------


class AccountBatchSyncRequest(StrictModel):
    account_ids: list[UUID] = Field(min_length=1, max_length=100)


class AccountBatchUpdateRequest(StrictModel):
    account_ids: list[UUID] = Field(min_length=1, max_length=100)
    is_active: bool


class AccountBatchDeleteRequest(StrictModel):
    account_ids: list[UUID] = Field(min_length=1, max_length=100)


class AccountBatchSyncItem(BaseModel):
    account_id: UUID
    status: Literal["accepted", "skipped", "failed"]
    sync_run_id: UUID | None = None
    detail: str | None = None


class AccountBatchSyncResult(BaseModel):
    accepted: int
    skipped: int
    failed: int
    items: list[AccountBatchSyncItem]


class AccountBatchResult(BaseModel):
    updated: int
    account_ids: list[UUID]


# -- Cross-platform comparison ---------------------------------------------


class AccountComparisonSnapshot(BaseModel):
    captured_at: datetime
    follower_count: int | None
    total_view_count: int | None
    video_count: int | None
    engagement_rate: float | None
    source_kind: SourceKind


class AccountComparisonRow(BaseModel):
    account_id: UUID
    platform_key: str
    display_name: str
    username: str | None
    is_active: bool
    sync_status: AccountSyncStatus
    latest: AccountComparisonSnapshot | None = None
    previous: AccountComparisonSnapshot | None = None
    follower_delta: int | None = None
    view_delta: int | None = None
    window_hours: float | None = None


class AccountComparisonSummary(BaseModel):
    account_count: int
    total_followers: int | None = None
    total_views: int | None = None
    total_videos: int | None = None
    best_followers_account_id: UUID | None = None
    best_views_account_id: UUID | None = None
    best_engagement_account_id: UUID | None = None


class AccountComparisonResponse(BaseModel):
    rows: list[AccountComparisonRow]
    summary: AccountComparisonSummary


# -- Adaptive sync interval ------------------------------------------------


class SyncIntervalResponse(BaseModel):
    account_id: UUID
    sync_interval_seconds: int
    basis: Literal["adaptive", "default"]
    posting_median_gap_seconds: int | None = None


class AccountSnapshotPage(BaseModel):
    items: list[AccountSnapshotRead]
    page: int
    page_size: int
    total: int


class ContentSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    content_item_id: UUID
    captured_at: datetime
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    share_count: int | None
    favorite_count: int | None
    follower_gain: int | None
    average_watch_time: float | None
    completion_rate: float | None
    search_traffic_rate: float | None
    recommendation_traffic_rate: float | None
    profile_traffic_rate: float | None
    revenue: float | None
    rpm: float | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    source_kind: SourceKind
    source_provider: str
    fetched_at: datetime
    raw_payload_ref: str | None


class ContentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    platform_id: UUID
    platform: PlatformRead
    account_id: UUID
    external_id: str
    content_type: str
    title: str
    description: str | None
    published_at: datetime | None
    duration_seconds: float | None
    canonical_url: str
    cover_url: str | None
    language: str | None
    status: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    first_seen_at: datetime
    last_seen_at: datetime
    source_kind: SourceKind
    source_provider: str
    fetched_at: datetime
    source_url: str | None
    raw_payload_ref: str | None
    media: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    latest_snapshot: ContentSnapshotRead | None = None
    view_growth_24h: float | None = None


class ContentPage(BaseModel):
    items: list[ContentRead]
    page: int
    page_size: int
    total: int


class ContentCalendarBucket(BaseModel):
    """One calendar day with aggregated content metrics."""

    date: str  # YYYY-MM-DD
    count: int
    total_views: int
    total_likes: int


class ContentCalendarResponse(BaseModel):
    """Per-day aggregation of published works for a single month."""

    year: int
    month: int  # 1-12
    platform: str | None = None
    account: UUID | None = None
    buckets: list[ContentCalendarBucket]
    total_count: int
    total_views: int


def _default_traffic_source_split() -> dict[str, float | None]:
    return {"recommendation": None, "search": None, "profile": None}


class AccountContentSummary(BaseModel):
    """Aggregated content-level metrics for an account overview.

    Mirrors the acquisition baseline: every field here is derived from real
    observations that the account's adapter actually returned. Traffic source
    proportions are view-weighted; fields the adapter could not obtain (e.g.
    completion rate when only a public browse path is available) simply come
    back as ``None`` and the UI renders the required condition instead.
    """

    account_id: UUID
    content_count: int
    avg_completion_rate: float | None = None
    avg_watch_time_seconds: float | None = None
    avg_engagement_rate: float | None = None
    total_interactions: int | None = None
    traffic_source_split: dict[str, float | None] = Field(
        default_factory=_default_traffic_source_split
    )
    recent_24h_view_growth: int | None = None
    top_content_id: UUID | None = None
    top_content_title: str | None = None
    top_content_views: int | None = None


class ContentCreate(BaseModel):
    """Manual content creation — fields mirror the ContentItem model."""

    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    external_id: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="video", min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=50_000)
    published_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    canonical_url: str = Field(max_length=2048)
    cover_url: str | None = Field(default=None, max_length=2048)
    language: str | None = Field(default=None, max_length=16)
    status: str = Field(default="public", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContentUpdate(BaseModel):
    """Partial update for an existing content item."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    canonical_url: str | None = Field(default=None, max_length=2048)
    cover_url: str | None = Field(default=None, max_length=2048)
    language: str | None = Field(default=None, max_length=16)
    status: str | None = Field(default=None, max_length=64)
    duration_seconds: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] | None = None


class ContentSnapshotPage(BaseModel):
    items: list[ContentSnapshotRead]
    page: int
    page_size: int
    total: int


class DerivedMetricRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    entity_type: Literal["account", "content_item"]
    entity_id: UUID
    metric_key: str
    window: str
    value: float
    calculated_at: datetime
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")


class DerivedMetricPage(BaseModel):
    items: list[DerivedMetricRead]
    page: int
    page_size: int
    total: int


class SyncUnavailableResponse(BaseModel):
    code: Literal["platform_sync_not_available"] = "platform_sync_not_available"
    detail: str


class SyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    target_type: str
    target_id: UUID
    adapter_key: str
    request_id: str
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    status: Literal["queued", "running", "success", "degraded", "error", "skipped", "cancelled"]
    records_created: int
    records_updated: int
    progress_percent: int
    progress_stage: str
    progress_message: str | None
    items_processed: int
    items_total: int | None
    error_code: str | None
    error_message: str | None
    error_detail: str | None
    error_hint: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")


class SyncRunPage(BaseModel):
    items: list[SyncRunRead]
    page: int
    page_size: int
    total: int
