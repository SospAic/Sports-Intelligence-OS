from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

RightsStatus = Literal["unknown", "pending_review", "approved", "restricted", "expired"]
RightsSourceKind = Literal["live", "imported"]


class MediaRightsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rights_status: RightsStatus = "pending_review"
    license_type: str | None = Field(default=None, max_length=120)
    rights_holder: str | None = Field(default=None, max_length=255)
    territories: list[str] = Field(default_factory=list, max_length=100)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    evidence_url: HttpUrl | None = None
    evidence_note: str | None = Field(default=None, max_length=10_000)
    source_kind: RightsSourceKind = "imported"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_window(self) -> MediaRightsUpdate:
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("权利有效期结束时间不能早于开始时间")
        if self.rights_status == "approved" and not (self.license_type or self.evidence_url):
            raise ValueError("批准使用前至少需要填写许可类型或证据链接")
        return self


class MediaRightsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None
    workspace_id: UUID
    artifact_id: UUID
    artifact_kind: str
    file_name: str
    artifact_status: str
    rights_status: RightsStatus
    license_type: str | None
    rights_holder: str | None
    territories: list[str]
    valid_from: datetime | None
    valid_until: datetime | None
    evidence_url: str | None
    evidence_note: str | None
    source_kind: RightsSourceKind
    verified_at: datetime | None
    verified_by: UUID | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class MediaRightsPage(BaseModel):
    items: list[MediaRightsRead]
    page: int
    page_size: int
    total: int
