from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ExperimentDimension = Literal["title", "hook", "story_order", "thumbnail"]
ExperimentStatus = Literal["draft", "running", "completed", "archived"]
ExperimentSourceKind = Literal["live", "imported", "mock"]
ExperimentWindowKey = Literal["1h", "3h", "6h", "24h", "72h", "7d", "30d"]


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    hypothesis: str | None = Field(default=None, max_length=5000)
    dimension: ExperimentDimension
    source_kind: ExperimentSourceKind = "imported"


class ExperimentUpdate(BaseModel):
    hypothesis: str | None = Field(default=None, max_length=5000)
    status: ExperimentStatus | None = None


class ExperimentVariantCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    content_item_id: UUID | None = None
    publication_id: UUID | None = None
    exposure_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_evidence_link(self) -> ExperimentVariantCreate:
        if self.content_item_id is None and self.publication_id is None:
            raise ValueError("实验变体必须关联已监控作品或发布记录")
        return self


class ExperimentVariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    experiment_id: UUID
    label: str
    description: str | None
    content_item_id: UUID | None
    publication_id: UUID | None
    exposure_at: datetime | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json", default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ExperimentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    workspace_id: UUID
    created_by: UUID
    name: str
    hypothesis: str | None
    dimension: ExperimentDimension
    status: ExperimentStatus
    source_kind: ExperimentSourceKind
    metadata: dict[str, Any] = Field(validation_alias="metadata_json", default_factory=dict)
    variant_count: int = 0
    created_at: datetime
    updated_at: datetime


class ExperimentDetail(ExperimentRead):
    variants: list[ExperimentVariantRead] = Field(default_factory=list)


class ExperimentPage(BaseModel):
    items: list[ExperimentRead]
    page: int
    page_size: int
    total: int


class ExperimentReportVariant(BaseModel):
    variant_id: UUID
    label: str
    sample_count: int
    measured_count: int
    average_views: float | None
    average_interaction_rate: float | None
    average_completion_rate: float | None
    source_kinds: list[ExperimentSourceKind]
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class ExperimentReport(BaseModel):
    experiment: ExperimentDetail
    window_key: ExperimentWindowKey
    comparison_type: Literal["observational"] = "observational"
    variants: list[ExperimentReportVariant]
    caveats: list[str]
