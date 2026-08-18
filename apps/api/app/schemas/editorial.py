"""Contracts for the editorial review queue."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EditorialStatus = Literal["draft", "in_review", "approved", "rejected", "archived"]


class EditorialItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation_run_id: UUID
    title: str | None = Field(default=None, max_length=255)
    assignee_id: UUID | None = None
    priority: int = Field(default=50, ge=0, le=100)
    due_at: datetime | None = None


class EditorialItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: EditorialStatus | None = None
    assignee_id: UUID | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    due_at: datetime | None = None
    review_note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def require_change(self) -> EditorialItemUpdate:
        if not self.model_fields_set:
            raise ValueError("至少提供一项审核队列变更")
        return self


class EditorialItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    generation_run_id: UUID
    created_by: UUID
    assignee_id: UUID | None
    title: str
    status: EditorialStatus
    priority: int
    due_at: datetime | None
    content_snapshot: dict[str, Any]
    source_snapshot: dict[str, Any]
    requested_at: datetime | None
    reviewed_at: datetime | None
    reviewed_by: UUID | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime


class EditorialItemPage(BaseModel):
    items: list[EditorialItemRead]
    page: int
    page_size: int
    total: int


class EditorialCommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("评论内容不能为空")
        return normalized


class EditorialCommentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolved: bool


class EditorialCommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    editorial_item_id: UUID
    author_id: UUID
    body: str
    resolved_at: datetime | None
    resolved_by: UUID | None
    created_at: datetime
    updated_at: datetime


class EditorialBulkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_ids: list[UUID] = Field(min_length=1, max_length=100)
    status: EditorialStatus | None = None
    assignee_id: UUID | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    due_at: datetime | None = None
    review_note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def require_change(self) -> EditorialBulkUpdate:
        if not self.model_fields_set.difference({"item_ids"}):
            raise ValueError("批量更新至少提供一项变更")
        return self


class EditorialBulkResult(BaseModel):
    updated_count: int
    items: list[EditorialItemRead]


class EditorialSavedViewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    status: EditorialStatus | None = None
    assignee_id: UUID | None = None
    overdue: bool = False
    unassigned: bool = False
    priority_min: int | None = Field(default=None, ge=0, le=100)
    priority_max: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_priority_range(self) -> EditorialSavedViewCreate:
        if (
            self.priority_min is not None
            and self.priority_max is not None
            and self.priority_min > self.priority_max
        ):
            raise ValueError("最低优先级不能高于最高优先级")
        return self


class EditorialSavedViewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    status: EditorialStatus | None = None
    assignee_id: UUID | None = None
    overdue: bool | None = None
    unassigned: bool | None = None
    priority_min: int | None = Field(default=None, ge=0, le=100)
    priority_max: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_priority_range(self) -> EditorialSavedViewUpdate:
        if not self.model_fields_set:
            raise ValueError("至少提供一项保存视图变更")
        if (
            self.priority_min is not None
            and self.priority_max is not None
            and self.priority_min > self.priority_max
        ):
            raise ValueError("最低优先级不能高于最高优先级")
        return self


class EditorialSavedViewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    created_by: UUID
    name: str
    status: EditorialStatus | None
    assignee_id: UUID | None
    overdue: bool
    unassigned: bool
    priority_min: int | None
    priority_max: int | None
    created_at: datetime
    updated_at: datetime
