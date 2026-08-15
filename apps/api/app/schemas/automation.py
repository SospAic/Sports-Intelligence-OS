from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.settings import ConfigFieldDescriptor

EntityType = Literal["content", "account", "news", "topic_event"]
ActionType = Literal[
    "notification",
    "webhook",
    "create_topic",
    "create_generation",
    "save_content",
    "external_api",
]
ProviderKey = Literal[
    "email",
    "generic_webhook",
    "telegram",
    "discord",
    "feishu",
    "dingtalk",
    "wecom",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AutomationActionCreate(StrictModel):
    action_type: ActionType
    config: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = Field(default=0, ge=0, le=1000)
    enabled: bool = True


class AutomationActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rule_id: UUID
    action_type: ActionType
    config: dict[str, Any]
    sort_order: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AutomationRuleCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    entity_type: EntityType
    trigger_type: str = Field(default="entity_updated", min_length=1, max_length=64)
    condition_tree: dict[str, Any]
    schedule: dict[str, Any] = Field(default_factory=dict)
    cooldown_seconds: int = Field(default=0, ge=0, le=31_536_000)
    deduplication_window: int = Field(default=3600, ge=0, le=31_536_000)
    enabled: bool = False
    priority: int = Field(default=100, ge=0, le=1000)
    actions: list[AutomationActionCreate] = Field(default_factory=list, max_length=20)

    @field_validator("actions")
    @classmethod
    def unique_action_order(
        cls, actions: list[AutomationActionCreate]
    ) -> list[AutomationActionCreate]:
        orders = [action.sort_order for action in actions]
        if len(orders) != len(set(orders)):
            raise ValueError("action sort_order values must be unique")
        return actions


class AutomationRuleUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    trigger_type: str | None = Field(default=None, min_length=1, max_length=64)
    condition_tree: dict[str, Any] | None = None
    schedule: dict[str, Any] | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0, le=31_536_000)
    deduplication_window: int | None = Field(default=None, ge=0, le=31_536_000)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)


class AutomationRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_by: UUID
    name: str
    description: str | None
    entity_type: EntityType
    trigger_type: str
    condition_tree: dict[str, Any]
    schedule: dict[str, Any]
    cooldown_seconds: int
    deduplication_window: int
    enabled: bool
    priority: int
    created_at: datetime
    updated_at: datetime


class AutomationRuleDetail(AutomationRuleRead):
    actions: list[AutomationActionRead]


class AutomationRulePage(BaseModel):
    items: list[AutomationRuleRead]
    page: int
    page_size: int
    total: int


class ConditionValidateRequest(StrictModel):
    entity_type: EntityType
    condition_tree: dict[str, Any]
    facts: dict[str, Any] | None = None
    previous: dict[str, Any] | None = None
    consecutive_count: int = Field(default=0, ge=0)


class ConditionValidateResult(BaseModel):
    valid: bool
    matched: bool | None = None
    explanation: dict[str, Any] | None = None


class AutomationEvaluateRequest(StrictModel):
    entity_type: EntityType
    entity_id: UUID
    facts: dict[str, Any]
    previous: dict[str, Any] = Field(default_factory=dict)
    trigger_type: str = Field(default="entity_updated", min_length=1, max_length=64)
    event_key: str = Field(min_length=1, max_length=200)
    source_kind: Literal["live", "imported"]
    test_mode: bool = False


class AutomationEvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    rule_id: UUID
    entity_type: str
    entity_id: UUID
    evaluated_at: datetime
    matched: bool
    condition_result: dict[str, Any]
    deduplication_key: str
    event_key: str
    execution_status: str
    metadata: dict[str, Any] = Field(validation_alias="evaluation_metadata")


class AutomationEvaluationPage(BaseModel):
    items: list[AutomationEvaluationRead]
    page: int
    page_size: int
    total: int


class NotificationChannelCreate(StrictModel):
    provider_key: ProviderKey
    name: str = Field(min_length=1, max_length=255)
    config: dict[str, Any]
    enabled: bool = True

    @model_validator(mode="after")
    def reject_empty_config(self) -> NotificationChannelCreate:
        if not self.config:
            raise ValueError("notification channel config cannot be empty")
        return self


class NotificationChannelUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class NotificationChannelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_key: ProviderKey
    name: str
    config_masked: dict[str, Any]
    enabled: bool
    last_tested_at: datetime | None
    health_status: str
    created_at: datetime
    updated_at: datetime


class NotificationChannelValidationRead(BaseModel):
    """Result of a local notification configuration check.

    This endpoint deliberately performs no external I/O.  A valid result means
    the provider accepted the decrypted configuration; it is not a delivery
    receipt.
    """

    channel_id: UUID
    provider_key: str
    status: Literal["configured", "invalid", "disabled"]
    is_mock: bool
    external_io_performed: bool = False
    checked_at: datetime
    detail: str


class NotificationProviderRead(BaseModel):
    key: str
    name: str
    is_mock: bool
    config_fields: list[ConfigFieldDescriptor]


class NotificationTestRequest(StrictModel):
    title: str = Field(default="Sports Intelligence OS 测试通知", min_length=1, max_length=255)
    body: str = Field(default="通知渠道配置测试成功。", min_length=1, max_length=10_000)


class NotificationDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    rule_id: UUID | None
    subscription_id: UUID | None = None
    entity_type: str
    entity_id: UUID
    payload: dict[str, Any]
    status: str
    attempts: int
    sent_at: datetime | None
    error: dict[str, Any] | None
    provider_message_id: str | None
    created_at: datetime
    updated_at: datetime


class NotificationDeliveryPage(BaseModel):
    items: list[NotificationDeliveryRead]
    page: int
    page_size: int
    total: int


class NotificationChannelHealthRead(BaseModel):
    channel_id: UUID
    name: str
    provider_key: str
    enabled: bool
    health_status: str
    deliveries: int = 0
    delivered: int = 0
    failed: int = 0
    queued: int = 0
    sending: int = 0
    attempts: int = 0
    successful_attempts: int = 0
    failed_attempts: int = 0
    success_rate: float | None = None
    average_latency_ms: float | None = None
    last_delivery_at: datetime | None = None
    last_error_code: str | None = None


class NotificationHealthSummaryRead(BaseModel):
    window_minutes: int
    generated_at: datetime
    channels: list[NotificationChannelHealthRead] = Field(default_factory=list)
    deliveries: int = 0
    delivered: int = 0
    failed: int = 0
    queued: int = 0
    sending: int = 0
    successful_attempts: int = 0
    failed_attempts: int = 0
    success_rate: float | None = None
    average_latency_ms: float | None = None
