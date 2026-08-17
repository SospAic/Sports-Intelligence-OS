from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

PublicationStatus = Literal[
    "planned", "scheduled", "published", "unverified", "failed", "cancelled"
]
PublicationSourceKind = Literal["live", "imported", "mock"]
PublicationWindowKey = Literal["1h", "3h", "6h", "24h", "72h", "7d", "30d"]
MeasurementStatus = Literal["measured", "not_due", "unavailable"]


class PublicationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    generation_run_id: UUID | None = None
    editorial_item_id: UUID | None = None
    content_item_id: UUID | None = None
    account_id: UUID | None = None
    platform_id: UUID | None = None
    canonical_url: AnyHttpUrl | None = None
    external_id: str | None = Field(default=None, min_length=1, max_length=255)
    status: PublicationStatus = "planned"
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    source_kind: PublicationSourceKind = "imported"
    source_provider: str = Field(default="manual", min_length=1, max_length=120)
    source_url: AnyHttpUrl | None = None
    verification_note: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("发布标题不能为空")
        return value

    @model_validator(mode="after")
    def validate_status(self) -> PublicationCreate:
        if self.status in {"published", "unverified"} and self.published_at is None:
            raise ValueError("已发布或待核实记录必须提供 published_at")
        if self.status == "published" and not (self.external_id or self.canonical_url):
            raise ValueError("只有提供平台作品 ID 或链接后才能标记为已发布")
        return self


class PublicationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    account_id: UUID | None = None
    platform_id: UUID | None = None
    canonical_url: AnyHttpUrl | None = None
    external_id: str | None = Field(default=None, min_length=1, max_length=255)
    status: PublicationStatus | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    verification_note: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] | None = None


class PerformanceAttributionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    publication_id: UUID
    window_key: PublicationWindowKey
    window_seconds: int
    target_at: datetime
    measurement_status: MeasurementStatus
    captured_at: datetime | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    share_count: int | None
    favorite_count: int | None
    follower_gain: int | None
    average_watch_time: float | None
    completion_rate: float | None
    source_kind: PublicationSourceKind | None
    source_provider: str | None
    source_url: str | None
    note: str | None
    evidence: dict[str, Any] = Field(validation_alias="evidence_json", default_factory=dict)
    captured_offset_seconds: int | None = None


class PublicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    created_by: UUID
    generation_run_id: UUID | None
    editorial_item_id: UUID | None
    content_item_id: UUID | None
    account_id: UUID | None
    platform_id: UUID | None
    title: str
    canonical_url: str | None
    external_id: str | None
    status: PublicationStatus
    scheduled_at: datetime | None
    published_at: datetime | None
    source_kind: PublicationSourceKind
    source_provider: str
    source_url: str | None
    verification_note: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json", default_factory=dict)
    created_at: datetime
    updated_at: datetime


class PublicationDetail(PublicationRead):
    attributions: list[PerformanceAttributionRead] = Field(default_factory=list)


class PublicationPage(BaseModel):
    items: list[PublicationRead]
    page: int
    page_size: int
    total: int


class AttributionRefreshResponse(BaseModel):
    publication: PublicationRead
    attributions: list[PerformanceAttributionRead]
    measured_count: int
    unavailable_count: int
    not_due_count: int
