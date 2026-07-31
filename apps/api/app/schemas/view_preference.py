from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ViewPreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferences: dict[str, Any] = Field(default_factory=dict)


class ViewPreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    user_id: UUID
    view_key: str
    preferences: dict[str, Any]
    updated_at: datetime
