from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

InboxItemKind = Literal[
    "task",
    "notification",
    "editorial_comment",
    "subscription_event",
    "dead_letter",
]


class InboxReadStateRead(BaseModel):
    item_key: str
    item_kind: InboxItemKind
    item_id: UUID
    read_at: datetime


class InboxReadStateUpsert(BaseModel):
    item_key: str = Field(min_length=38, max_length=80)


class InboxReadStateBulkUpsert(BaseModel):
    item_keys: list[str] = Field(min_length=1, max_length=500)
