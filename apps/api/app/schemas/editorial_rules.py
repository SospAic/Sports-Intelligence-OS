from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.editorial_rules import RULE_TYPES

RuleType = Literal[
    "principle",
    "qualification",
    "research",
    "narrative",
    "language",
    "structure",
    "fact_check",
    "length",
    "output",
    "qa",
    "rewrite",
    "tts",
    "ssml",
    "title",
    "search_keyword",
    "material_search",
]
VersionStatus = Literal["draft", "published", "archived"]
SourceStatus = Literal["full", "partial", "unresolved"]
Severity = Literal["info", "warning", "error", "critical"]


class RuleSetCreate(BaseModel):
    key: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=50)


class RuleSetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    description: str | None
    current_version_id: UUID | None
    status: str
    tags: list[str]
    version_count: int = 0
    draft_count: int = 0
    created_at: datetime
    updated_at: datetime


class RuleSetPage(BaseModel):
    items: list[RuleSetRead]
    page: int
    page_size: int
    total: int


class RuleSetVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: str
    source_hash: str
    changelog: str | None
    status: VersionStatus
    created_by: UUID
    created_at: datetime
    published_at: datetime | None


class RuleSetDetail(RuleSetRead):
    versions: list[RuleSetVersionSummary]


class RuleSetVersionRead(RuleSetVersionSummary):
    rule_set_id: UUID
    source_text: str
    section_count: int
    rule_count: int


class RuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_id: UUID
    section_id: UUID
    key: str
    title: str
    rule_type: RuleType
    instruction: str
    why: str | None
    how: str | None
    good_example: str | None
    bad_example: str | None
    qa_check: str | None
    rewrite_instruction: str | None
    priority: int
    severity: Severity
    is_mandatory: bool
    enabled: bool
    sports: list[str]
    story_types: list[str]
    output_types: list[str]
    dependencies: list[str]
    conflicts: list[str]
    tags: list[str]
    source_reference: str | None
    source_status: SourceStatus
    sort_order: int
    created_at: datetime
    updated_at: datetime


class RuleSectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_id: UUID
    parent_id: UUID | None
    title: str
    slug: str
    description: str | None
    sort_order: int


class RuleSectionNode(RuleSectionRead):
    rules: list[RuleRead] = Field(default_factory=list)
    children: list[RuleSectionNode] = Field(default_factory=list)


class RuleTreeRead(BaseModel):
    version: RuleSetVersionSummary
    sections: list[RuleSectionNode]
    total_rules: int


class RuleFilters(BaseModel):
    query: str | None = None
    tags: list[str] = Field(default_factory=list)
    rule_type: RuleType | None = None
    is_mandatory: bool | None = None
    enabled: bool | None = None


class RulePage(BaseModel):
    items: list[RuleRead]
    page: int
    page_size: int
    total: int


class RuleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    rule_type: RuleType | None = None
    instruction: str | None = Field(default=None, min_length=1, max_length=100_000)
    why: str | None = Field(default=None, max_length=50_000)
    how: str | None = Field(default=None, max_length=50_000)
    good_example: str | None = Field(default=None, max_length=50_000)
    bad_example: str | None = Field(default=None, max_length=50_000)
    qa_check: str | None = Field(default=None, max_length=50_000)
    rewrite_instruction: str | None = Field(default=None, max_length=50_000)
    priority: int | None = Field(default=None, ge=0, le=100)
    severity: Severity | None = None
    is_mandatory: bool | None = None
    enabled: bool | None = None
    sports: list[str] | None = Field(default=None, max_length=100)
    story_types: list[str] | None = Field(default=None, max_length=100)
    output_types: list[str] | None = Field(default=None, max_length=100)
    dependencies: list[str] | None = Field(default=None, max_length=250)
    conflicts: list[str] | None = Field(default=None, max_length=250)
    tags: list[str] | None = Field(default=None, max_length=100)
    source_status: SourceStatus | None = None

    @field_validator("sports", "story_types", "output_types", "dependencies", "conflicts", "tags")
    @classmethod
    def unique_strings(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [item.strip() for item in value if item.strip()]
        if any(len(item) > 255 for item in normalized):
            raise ValueError("列表值不能超过 255 个字符")
        return list(dict.fromkeys(normalized))


class RuleEditResult(BaseModel):
    version_id: UUID
    created_draft: bool
    rule: RuleRead


class RuleBatchUpdate(BaseModel):
    rule_ids: list[UUID] = Field(min_length=1, max_length=500)
    changes: RuleUpdate


class VersionCreate(BaseModel):
    from_version_id: UUID | None = None
    version: str | None = Field(default=None, max_length=64)
    changelog: str | None = Field(default=None, max_length=5000)


class ValidationIssueRead(BaseModel):
    level: Literal["warning", "error"]
    code: str
    message: str
    rule_key: str | None


class ValidationResultRead(BaseModel):
    valid: bool
    errors: int
    warnings: int
    issues: list[ValidationIssueRead]


class RuleSimulationContext(BaseModel):
    """Only explicit editorial context is used; no hidden model inference."""

    text: str | None = Field(default=None, max_length=100_000)
    sport: str | None = Field(default=None, max_length=120)
    story_type: str | None = Field(default=None, max_length=120)
    output_type: str | None = Field(default=None, max_length=120)
    facts: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=100)


class RuleSimulationRequest(BaseModel):
    context: RuleSimulationContext
    historical_at: datetime | None = None
    include_disabled: bool = False


class RuleSimulationRuleRead(BaseModel):
    rule_id: UUID
    key: str
    title: str
    priority: int
    enabled: bool
    applies: bool
    execution_state: Literal["not_executed"] = "not_executed"
    reason: str
    source_status: SourceStatus


class RuleSimulationFeedbackCreate(BaseModel):
    verdict: Literal["pass", "fail", "not_applicable", "uncertain"]
    comment: str | None = Field(default=None, max_length=5000)


class RuleSimulationFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    simulation_id: UUID
    rule_id: UUID
    created_by: UUID
    verdict: Literal["pass", "fail", "not_applicable", "uncertain"]
    comment: str | None
    created_at: datetime
    updated_at: datetime


class RuleSimulationRead(BaseModel):
    id: UUID
    workspace_id: UUID
    rule_set_id: UUID
    version_id: UUID
    version: str
    source_hash: str
    created_by: UUID
    historical_at: datetime | None
    context: RuleSimulationContext
    rules: list[RuleSimulationRuleRead]
    applicable_count: int
    skipped_count: int
    feedback: list[RuleSimulationFeedbackRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class RuleSimulationPage(BaseModel):
    items: list[RuleSimulationRead]
    page: int
    page_size: int
    total: int


class VersionActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class RuleDiffItem(BaseModel):
    key: str
    change: Literal["added", "removed", "modified"]
    fields: list[str] = Field(default_factory=list)


class RuleDiffRead(BaseModel):
    left_version: RuleSetVersionSummary
    right_version: RuleSetVersionSummary
    added: int
    removed: int
    modified: int
    unchanged: int
    items: list[RuleDiffItem]


class RuleImportRequest(BaseModel):
    format: Literal["txt", "json"]
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=2_000_000)
    key: str = Field(default="elite-sports-narration-v7-9", pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(default="Elite Sports Faceless Narration Engine V7.9", max_length=255)
    changelog: str | None = Field(default="导入完整 V7.9 原文并生成结构化规则", max_length=5000)
    publish: bool = True


class RuleImportResult(BaseModel):
    rule_set: RuleSetRead
    version: RuleSetVersionRead
    created: bool
    validation: ValidationResultRead


class RuleExportSection(BaseModel):
    slug: str
    parent_slug: str | None
    title: str
    description: str | None
    sort_order: int


class RuleExportRule(BaseModel):
    section_slug: str
    key: str
    title: str
    rule_type: RuleType
    instruction: str
    why: str | None
    how: str | None
    good_example: str | None
    bad_example: str | None
    qa_check: str | None
    rewrite_instruction: str | None
    priority: int
    severity: Severity
    is_mandatory: bool
    enabled: bool
    sports: list[str]
    story_types: list[str]
    output_types: list[str]
    dependencies: list[str]
    conflicts: list[str]
    tags: list[str]
    source_reference: str | None
    source_status: SourceStatus
    sort_order: int


class RuleExportBundle(BaseModel):
    schema_version: Literal[1] = 1
    rule_set_key: str
    rule_set_name: str
    description: str | None
    tags: list[str]
    version: str
    source_text: str
    source_hash: str
    changelog: str | None
    sections: list[RuleExportSection]
    rules: list[RuleExportRule]


assert len(RULE_TYPES) == 16
