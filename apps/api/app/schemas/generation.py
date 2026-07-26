from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PromptStatus = Literal["draft", "published", "archived"]
InputType = Literal["news", "event", "content", "user_text"]
RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
ProviderKey = Literal["mock_llm", "openai_compatible"]


class PromptCollectionCreate(BaseModel):
    key: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    category: str = Field(default="generation", min_length=1, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=50)


class PromptVersionCreate(BaseModel):
    version: str = Field(min_length=1, max_length=64)
    system_prompt: str = Field(min_length=1, max_length=100_000)
    user_prompt_template: str = Field(min_length=1, max_length=200_000)
    variables_schema: dict[str, Any] = Field(default_factory=dict)
    model_config_data: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    changelog: str | None = Field(default=None, max_length=5000)

    model_config = ConfigDict(populate_by_name=True)


class PromptVersionUpdate(BaseModel):
    system_prompt: str | None = Field(default=None, min_length=1, max_length=100_000)
    user_prompt_template: str | None = Field(default=None, min_length=1, max_length=200_000)
    variables_schema: dict[str, Any] | None = None
    model_config_data: dict[str, Any] | None = Field(default=None, alias="model_config")
    changelog: str | None = Field(default=None, max_length=5000)

    model_config = ConfigDict(populate_by_name=True)


class PromptVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    collection_id: UUID
    version: str
    system_prompt: str
    user_prompt_template: str
    variables_schema: dict[str, Any]
    model_config_data: dict[str, Any] = Field(
        validation_alias="model_config", serialization_alias="model_config"
    )
    changelog: str | None
    status: PromptStatus
    created_by: UUID
    created_at: datetime
    published_at: datetime | None


class PromptVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    collection_id: UUID
    version: str
    changelog: str | None
    status: PromptStatus
    created_at: datetime
    published_at: datetime | None


class PromptCollectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    description: str | None
    category: str
    current_version_id: UUID | None
    status: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    version_count: int = 0


class PromptCollectionDetail(PromptCollectionRead):
    versions: list[PromptVersionSummary]


class PromptCollectionPage(BaseModel):
    items: list[PromptCollectionRead]
    page: int
    page_size: int
    total: int


class WorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    description: str | None
    input_types: list[str]
    steps: list[dict[str, Any]]
    default_rule_set_version_id: UUID | None
    default_prompt_version_id: UUID | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ProviderDescriptor(BaseModel):
    key: str
    name: str
    configured: bool
    is_mock: bool
    supports_streaming: bool
    detail: str
    source: Literal["database", "environment", "builtin", "unconfigured"] = "builtin"
    default_model: str | None = None
    default_parameters: dict[str, Any] = Field(default_factory=dict)


class GenerationCreate(BaseModel):
    workflow_id: UUID
    input_type: InputType
    input_id: UUID | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    rule_set_version_id: UUID | None = None
    prompt_version_id: UUID | None = None
    provider: ProviderKey = "mock_llm"
    model: str = Field(default="mock-sports-writer-v1", min_length=1, max_length=160)
    model_config_data: dict[str, Any] = Field(default_factory=dict, alias="model_config")

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def validate_input_reference(self) -> GenerationCreate:
        if self.input_type == "user_text":
            text = self.input_payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("user_text 输入必须提供非空 input_payload.text")
        elif self.input_id is None:
            raise ValueError("news、event 和 content 输入必须提供 input_id")
        return self

    @field_validator("model_config_data")
    @classmethod
    def validate_model_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "temperature",
            "top_p",
            "max_tokens",
            "target_min_chars",
            "target_max_chars",
            "max_rewrites",
            "input_cost_per_million",
            "output_cost_per_million",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"不支持的模型参数: {', '.join(sorted(unknown))}")
        minimum = int(value.get("target_min_chars", 1200))
        maximum = int(value.get("target_max_chars", 1250))
        if minimum < 200 or maximum > 5000 or minimum > maximum:
            raise ValueError("字符范围必须位于 200–5000 且最小值不能大于最大值")
        rewrites = int(value.get("max_rewrites", 2))
        if rewrites < 0 or rewrites > 5:
            raise ValueError("max_rewrites 必须位于 0–5")
        return value


class GenerationStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    step_key: str
    name: str
    sort_order: int
    status: str
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None
    prompt_snapshot: dict[str, Any] | None
    started_at: datetime | None
    completed_at: datetime | None
    error: dict[str, Any] | None


class GenerationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID
    input_type: str
    input_id: UUID | None
    input_payload: dict[str, Any]
    rule_set_version_id: UUID
    prompt_version_id: UUID
    provider: str
    model: str
    model_config_data: dict[str, Any] = Field(
        validation_alias="model_config", serialization_alias="model_config"
    )
    status: RunStatus
    current_step: str | None
    verification_status: str
    started_at: datetime | None
    completed_at: datetime | None
    raw_output: dict[str, Any] | None
    final_output: dict[str, Any] | None
    validation_result: dict[str, Any]
    rewrite_count: int
    token_usage: dict[str, Any]
    estimated_cost: Decimal | None
    error: dict[str, Any] | None
    metadata: dict[str, Any] = Field(
        validation_alias="run_metadata", serialization_alias="metadata"
    )
    is_saved: bool
    user_rating: int | None
    created_at: datetime
    updated_at: datetime
    steps: list[GenerationStepRead] = Field(default_factory=list)


class GenerationRunPage(BaseModel):
    items: list[GenerationRunRead]
    page: int
    page_size: int
    total: int


class PromptPreviewRequest(GenerationCreate):
    pass


class PromptPreviewRead(BaseModel):
    system_prompt: str
    user_prompt: str
    variables: dict[str, Any]
    provider: dict[str, Any]
    warnings: list[str]


class GenerationRewriteRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=5000)


class GenerationDecisionUpdate(BaseModel):
    is_saved: bool | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
