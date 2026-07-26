from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class OperationTaskRead(BaseModel):
    id: UUID
    category: str
    task_type: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    metadata: dict[str, Any]


class OperationTaskPage(BaseModel):
    items: list[OperationTaskRead]
    page: int
    page_size: int
    total: int


class SystemEventRead(BaseModel):
    id: UUID
    severity: str
    category: str
    event_type: str
    message: str
    resource_type: str | None
    resource_id: UUID | None
    status: str
    metadata: dict[str, Any]
    trace_id: UUID
    created_at: datetime


class SystemEventPage(BaseModel):
    items: list[SystemEventRead]
    page: int
    page_size: int
    total: int


class AuditEntryRead(BaseModel):
    id: UUID
    actor_type: str
    actor_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    change_summary: dict[str, Any]
    reason: str | None
    trace_id: UUID
    created_at: datetime


class AuditEntryPage(BaseModel):
    items: list[AuditEntryRead]
    page: int
    page_size: int
    total: int
