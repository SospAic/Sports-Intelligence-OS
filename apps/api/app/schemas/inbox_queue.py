from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

InboxQueueItemKind = Literal["task", "notification"]
InboxQueueStateValue = Literal["open", "in_progress", "completed"]


class InboxQueueStatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: InboxQueueStateValue | None = None
    labels: list[str] | None = Field(default=None, max_length=10)
    assignee_id: UUID | None = None
    due_at: datetime | None = None

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        labels = list(dict.fromkeys(label.strip().lower() for label in value if label.strip()))
        if any(len(label) > 32 for label in labels):
            raise ValueError("单个标签不能超过 32 个字符")
        return labels

    @model_validator(mode="after")
    def require_change(self) -> "InboxQueueStatePatch":
        if not self.model_fields_set:
            raise ValueError("至少提供一项队列状态变更")
        return self


class InboxQueueStateBulkPatch(InboxQueueStatePatch):
    item_keys: list[str] = Field(min_length=1, max_length=100)


class InboxQueueStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_key: str
    item_kind: InboxQueueItemKind
    item_id: UUID
    state: InboxQueueStateValue
    labels: list[str]
    assignee_id: UUID | None
    due_at: datetime | None
    updated_by: UUID | None
    updated_at: datetime


class InboxSavedViewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    filters: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False


class InboxSavedViewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    filters: dict[str, Any] | None = None
    is_default: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "InboxSavedViewUpdate":
        if not self.model_fields_set:
            raise ValueError("至少提供一项保存视图变更")
        return self


class InboxSavedViewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    created_by: UUID
    name: str
    filters: dict[str, Any]
    is_default: bool
    created_at: datetime
    updated_at: datetime
