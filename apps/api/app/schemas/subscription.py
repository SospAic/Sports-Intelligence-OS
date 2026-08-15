"""Request and response contracts for subscription alerts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SubscriptionTriggerType = Literal["new_content", "keyword_match", "metric_spike"]
SubscriptionEntityType = Literal["content", "account", "news"]


class SubscriptionRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    trigger_type: SubscriptionTriggerType = "new_content"
    platform_id: UUID | None = None
    account_id: UUID | None = None
    keywords: list[str] = Field(default_factory=list, max_length=20)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    channel_ids: list[UUID] = Field(min_length=1, max_length=10)
    cooldown_seconds: int = Field(default=3600, ge=0, le=31_536_000)
    priority: int = Field(default=100, ge=0, le=1000)
    enabled: bool = True

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            item = " ".join(value.split()).casefold()
            if item and item not in normalized:
                normalized.append(item)
        return normalized

    @model_validator(mode="after")
    def validate_trigger_config(self) -> SubscriptionRuleCreate:
        if self.trigger_type == "keyword_match" and not self.keywords:
            raise ValueError("keyword_match subscriptions require at least one keyword")
        if self.trigger_type == "metric_spike" and not self.thresholds:
            raise ValueError("metric_spike subscriptions require thresholds")
        return self


class SubscriptionRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    trigger_type: SubscriptionTriggerType | None = None
    platform_id: UUID | None = None
    account_id: UUID | None = None
    keywords: list[str] | None = Field(default=None, max_length=20)
    thresholds: dict[str, Any] | None = None
    channel_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=10)
    cooldown_seconds: int | None = Field(default=None, ge=0, le=31_536_000)
    priority: int | None = Field(default=None, ge=0, le=1000)
    enabled: bool | None = None

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = []
        for value in values:
            item = " ".join(value.split()).casefold()
            if item and item not in normalized:
                normalized.append(item)
        return normalized


class SubscriptionRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_by: UUID
    name: str
    description: str | None
    trigger_type: SubscriptionTriggerType
    platform_id: UUID | None
    account_id: UUID | None
    keywords: list[str]
    thresholds: dict[str, Any]
    channel_ids: list[UUID]
    cooldown_seconds: int
    priority: int
    enabled: bool
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SubscriptionRulePage(BaseModel):
    items: list[SubscriptionRuleRead]
    page: int
    page_size: int
    total: int


class SubscriptionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subscription_id: UUID
    event_key: str
    entity_type: str
    entity_id: UUID
    event_type: str
    evaluated_at: datetime
    matched: bool
    status: str
    details: dict[str, Any]
    delivery_ids: list[UUID]


class SubscriptionEventPage(BaseModel):
    items: list[SubscriptionEventRead]
    page: int
    page_size: int
    total: int


class SubscriptionEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: SubscriptionEntityType
    entity_id: UUID
    event_key: str = Field(min_length=1, max_length=255)
    facts: dict[str, Any]
    previous: dict[str, Any] = Field(default_factory=dict)
    source_kind: Literal["live", "imported"]
