from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TopicSourceType = Literal["content", "article", "event", "manual"]
TopicStatus = Literal["inbox", "planned", "in_progress", "completed", "archived"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TopicCreate(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    summary: str | None = Field(default=None, max_length=20_000)
    source_type: TopicSourceType
    source_id: UUID | None = None
    priority: int = Field(default=50, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=20_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source(self) -> "TopicCreate":
        if self.source_type == "manual" and not self.title:
            raise ValueError("manual topics require a title")
        if self.source_type != "manual" and self.source_id is None:
            raise ValueError("source_id is required")
        return self


class TopicBatchCreate(StrictModel):
    source_type: Literal["content", "article", "event"]
    source_ids: list[UUID] = Field(min_length=1, max_length=100)


class TopicUpdate(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    summary: str | None = Field(default=None, max_length=20_000)
    status: TopicStatus | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=20_000)


class TopicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: UUID
    created_by: UUID
    title: str
    summary: str | None
    source_type: TopicSourceType
    source_id: UUID | None
    status: TopicStatus
    priority: int
    notes: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    created_at: datetime
    updated_at: datetime


class TopicPage(BaseModel):
    items: list[TopicRead]
    page: int
    page_size: int
    total: int
