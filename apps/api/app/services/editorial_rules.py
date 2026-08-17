from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.editorial_rules import Rule, RuleSection, RuleSet, RuleSetVersion
from app.models.operations import AuditEntry
from app.models.rule_simulation import RuleSimulationFeedback, RuleSimulationRun
from app.repositories.editorial_rules import EditorialRuleRepository
from app.rules.parser import (
    ParsedRule,
    ParsedRuleDocument,
    ParsedSection,
    RuleParseError,
    parse_v79_bytes,
)
from app.rules.validation import ValidationIssue, validate_rules
from app.schemas.editorial_rules import (
    RuleBatchUpdate,
    RuleDiffItem,
    RuleDiffRead,
    RuleEditResult,
    RuleExportBundle,
    RuleExportRule,
    RuleExportSection,
    RuleImportRequest,
    RuleImportResult,
    RulePage,
    RuleRead,
    RuleSectionNode,
    RuleSectionRead,
    RuleSetCreate,
    RuleSetDetail,
    RuleSetPage,
    RuleSetRead,
    RuleSetVersionRead,
    RuleSetVersionSummary,
    RuleSimulationContext,
    RuleSimulationFeedbackCreate,
    RuleSimulationFeedbackRead,
    RuleSimulationPage,
    RuleSimulationRead,
    RuleSimulationRequest,
    RuleSimulationRuleRead,
    RuleTreeRead,
    RuleUpdate,
    ValidationIssueRead,
    ValidationResultRead,
    VersionCreate,
)


def _sort_sections_parents_first[T](
    sections: list[T],
    *,
    key_of: Callable[[T], object],
    parent_of: Callable[[T], object | None],
) -> list[T]:
    """Order sections so every parent row precedes its children.

    ``RuleSection`` carries a self-referential ``parent_id`` foreign key.
    PostgreSQL enforces that constraint at insert time, so a child section must
    be persisted after its parent. SQLite did not enforce foreign keys, which
    masked this ordering requirement. Sorting by ancestor depth guarantees
    parents are inserted first regardless of how deeply sections are nested.
    """
    by_key: dict[object, T] = {key_of(item): item for item in sections}
    depth_cache: dict[object, int] = {}

    def depth(item: T) -> int:
        key = key_of(item)
        cached = depth_cache.get(key)
        if cached is not None:
            return cached
        parent_key = parent_of(item)
        if parent_key is None or parent_key not in by_key:
            value = 0
        else:
            value = 1 + depth(by_key[parent_key])
        depth_cache[key] = value
        return value

    return sorted(
        sections,
        key=lambda item: (depth(item), getattr(item, "sort_order", 0)),
    )


class EditorialRuleError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class EditorialRuleNotFound(EditorialRuleError):
    def __init__(self, message: str = "规则资源不存在") -> None:
        super().__init__(message, code="editorial_rule_not_found", status_code=404)


class EditorialRuleConflict(EditorialRuleError):
    def __init__(self, message: str, code: str = "editorial_rule_conflict") -> None:
        super().__init__(message, code=code, status_code=409)


EDITABLE_RULE_FIELDS = {
    "title",
    "rule_type",
    "instruction",
    "why",
    "how",
    "good_example",
    "bad_example",
    "qa_check",
    "rewrite_instruction",
    "priority",
    "severity",
    "is_mandatory",
    "enabled",
    "sports",
    "story_types",
    "output_types",
    "dependencies",
    "conflicts",
    "tags",
    "source_status",
}


def _source_status(value: str) -> Literal["full", "partial", "unresolved"]:
    return cast(Literal["full", "partial", "unresolved"], value)


class EditorialRuleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EditorialRuleRepository(session)

    async def list_rule_sets(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        query: str | None,
        status: str | None,
    ) -> RuleSetPage:
        rows, total = await self.repo.list_rule_sets(
            workspace_id, page=page, page_size=page_size, query=query, status=status
        )
        return RuleSetPage(
            items=[
                RuleSetRead.model_validate(row.rule_set).model_copy(
                    update={"version_count": row.version_count, "draft_count": row.draft_count}
                )
                for row in rows
            ],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def create_rule_set(
        self, workspace_id: UUID, actor_id: UUID, payload: RuleSetCreate
    ) -> RuleSetRead:
        if await self.repo.rule_set_by_key(workspace_id, payload.key):
            raise EditorialRuleConflict("规则集合 key 已存在", "duplicate_rule_set_key")
        rule_set = RuleSet(
            id=uuid4(),
            workspace_id=workspace_id,
            key=payload.key,
            name=payload.name,
            description=payload.description,
            current_version_id=None,
            status="active",
            tags=payload.tags,
        )
        self.session.add(rule_set)
        self._audit(workspace_id, actor_id, "editorial_rule_set.created", "rule_set", rule_set.id)
        await self.session.commit()
        await self.session.refresh(rule_set)
        return RuleSetRead.model_validate(rule_set)

    async def rule_set_detail(self, workspace_id: UUID, rule_set_id: UUID) -> RuleSetDetail:
        rule_set = await self._rule_set(workspace_id, rule_set_id)
        versions = await self.repo.versions(workspace_id, rule_set_id)
        base = RuleSetRead.model_validate(rule_set).model_copy(
            update={
                "version_count": len(versions),
                "draft_count": sum(item.status == "draft" for item in versions),
            }
        )
        return RuleSetDetail(
            **base.model_dump(),
            versions=[RuleSetVersionSummary.model_validate(item) for item in versions],
        )

    async def get_version(
        self, workspace_id: UUID, rule_set_id: UUID, version_id: UUID
    ) -> RuleSetVersionRead:
        version = await self._version(workspace_id, rule_set_id, version_id)
        return self._version_read(version)

    async def get_tree(
        self, workspace_id: UUID, rule_set_id: UUID, version_id: UUID
    ) -> RuleTreeRead:
        version = await self._version(workspace_id, rule_set_id, version_id)
        nodes = {
            section.id: RuleSectionNode(
                **RuleSectionRead.model_validate(section).model_dump(), children=[], rules=[]
            )
            for section in version.sections
        }
        for rule in sorted(version.rules, key=lambda item: (item.sort_order, item.key)):
            if rule.section_id in nodes:
                nodes[rule.section_id].rules.append(RuleRead.model_validate(rule))
        roots: list[RuleSectionNode] = []
        for section in sorted(version.sections, key=lambda item: (item.sort_order, item.slug)):
            node = nodes[section.id]
            if section.parent_id is not None and section.parent_id in nodes:
                nodes[section.parent_id].children.append(node)
            else:
                roots.append(node)
        return RuleTreeRead(
            version=RuleSetVersionSummary.model_validate(version),
            sections=roots,
            total_rules=len(version.rules),
        )

    async def list_rules(
        self,
        workspace_id: UUID,
        rule_set_id: UUID,
        version_id: UUID,
        *,
        page: int,
        page_size: int,
        query: str | None,
        tags: list[str],
        rule_type: str | None,
        is_mandatory: bool | None,
        enabled: bool | None,
    ) -> RulePage:
        await self._version(workspace_id, rule_set_id, version_id)
        if tags:
            items, _ = await self.repo.rules(
                workspace_id,
                version_id,
                query=query,
                rule_type=rule_type,
                is_mandatory=is_mandatory,
                enabled=enabled,
                page=1,
                page_size=5000,
            )
            required = {item.casefold() for item in tags}
            filtered = [item for item in items if required <= {tag.casefold() for tag in item.tags}]
            start = (page - 1) * page_size
            return RulePage(
                items=[
                    RuleRead.model_validate(item) for item in filtered[start : start + page_size]
                ],
                page=page,
                page_size=page_size,
                total=len(filtered),
            )
        items, total = await self.repo.rules(
            workspace_id,
            version_id,
            query=query,
            rule_type=rule_type,
            is_mandatory=is_mandatory,
            enabled=enabled,
            page=page,
            page_size=page_size,
        )
        return RulePage(
            items=[RuleRead.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def create_draft(
        self,
        workspace_id: UUID,
        rule_set_id: UUID,
        actor_id: UUID,
        payload: VersionCreate,
    ) -> RuleSetVersionRead:
        rule_set = await self._rule_set(workspace_id, rule_set_id)
        source_id = payload.from_version_id or rule_set.current_version_id
        if source_id is None:
            raise EditorialRuleConflict("规则集合还没有可复制的版本", "source_version_required")
        source = await self._version(workspace_id, rule_set_id, source_id)
        label = payload.version or await self._next_label(workspace_id, rule_set_id, source.version)
        if await self.repo.version_by_label(workspace_id, rule_set_id, label):
            raise EditorialRuleConflict("版本号已存在", "duplicate_rule_version")
        draft = self._clone_version(source, actor_id, label, payload.changelog)
        self.session.add(draft)
        self._audit(
            workspace_id,
            actor_id,
            "editorial_rule_version.created",
            "rule_set_version",
            draft.id,
            {"source_version_id": str(source.id), "version": label},
        )
        await self.session.commit()
        return self._version_read(await self._version(workspace_id, rule_set_id, draft.id))

    async def update_rule(
        self,
        workspace_id: UUID,
        rule_set_id: UUID,
        version_id: UUID,
        rule_id: UUID,
        actor_id: UUID,
        payload: RuleUpdate,
    ) -> RuleEditResult:
        version = await self._version(workspace_id, rule_set_id, version_id)
        source_rule = next((item for item in version.rules if item.id == rule_id), None)
        if source_rule is None:
            raise EditorialRuleNotFound("规则不存在")
        created_draft = False
        if version.status == "published":
            label = await self._next_label(workspace_id, rule_set_id, version.version)
            draft = self._clone_version(version, actor_id, label, "编辑已发布规则自动创建草稿")
            self.session.add(draft)
            await self.session.flush()
            version = draft
            source_rule = next(item for item in draft.rules if item.key == source_rule.key)
            created_draft = True
        elif version.status != "draft":
            raise EditorialRuleConflict("只有草稿版本允许编辑", "version_not_editable")
        self._apply_rule_update(source_rule, payload)
        source_rule.updated_at = datetime.now(UTC)
        self._audit(
            workspace_id,
            actor_id,
            "editorial_rule.updated",
            "rule",
            source_rule.id,
            {"version_id": str(version.id), "fields": sorted(payload.model_fields_set)},
        )
        await self.session.commit()
        await self.session.refresh(source_rule)
        return RuleEditResult(
            version_id=version.id,
            created_draft=created_draft,
            rule=RuleRead.model_validate(source_rule),
        )

    async def batch_update(
        self,
        workspace_id: UUID,
        rule_set_id: UUID,
        version_id: UUID,
        actor_id: UUID,
        payload: RuleBatchUpdate,
    ) -> tuple[UUID, bool, int]:
        version = await self._version(workspace_id, rule_set_id, version_id)
        created_draft = False
        requested = set(payload.rule_ids)
        if version.status == "published":
            label = await self._next_label(workspace_id, rule_set_id, version.version)
            draft = self._clone_version(version, actor_id, label, "批量编辑已发布规则自动创建草稿")
            self.session.add(draft)
            await self.session.flush()
            version = draft
            # IDs changed during clone; recover keys from the original version.
            original = await self._version(workspace_id, rule_set_id, version_id)
            source_keys = {item.key for item in original.rules if item.id in requested}
            targets = [item for item in draft.rules if item.key in source_keys]
            created_draft = True
        elif version.status == "draft":
            targets = [item for item in version.rules if item.id in requested]
        else:
            raise EditorialRuleConflict("只有草稿版本允许编辑", "version_not_editable")
        if len(targets) != len(requested):
            raise EditorialRuleNotFound("一个或多个规则不存在")
        now = datetime.now(UTC)
        for rule in targets:
            self._apply_rule_update(rule, payload.changes)
            rule.updated_at = now
        self._audit(
            workspace_id,
            actor_id,
            "editorial_rule.batch_updated",
            "rule_set_version",
            version.id,
            {"count": len(targets), "fields": sorted(payload.changes.model_fields_set)},
        )
        await self.session.commit()
        return version.id, created_draft, len(targets)

    async def validate_version(
        self, workspace_id: UUID, rule_set_id: UUID, version_id: UUID
    ) -> ValidationResultRead:
        version = await self._version(workspace_id, rule_set_id, version_id)
        return self._validation_result(validate_rules(version.rules))

    async def simulate(
        self,
        workspace_id: UUID,
        rule_set_id: UUID,
        version_id: UUID,
        actor_id: UUID,
        payload: RuleSimulationRequest,
    ) -> RuleSimulationRead:
        """Persist a deterministic applicability preview for one rule version.

        Rules are editorial instructions, not executable truth predicates. The
        simulator therefore only applies explicit sport/story/output filters
        and records ``not_executed`` for every result. It never calls an LLM,
        mutates a generation run, publishes content, or claims QA passed.
        """

        version = await self._version(workspace_id, rule_set_id, version_id)
        context = payload.context
        projections = [
            self._simulation_projection(rule, context)
            for rule in sorted(version.rules, key=lambda item: (-item.priority, item.key))
            if payload.include_disabled or rule.enabled
        ]
        now = datetime.now(UTC)
        run = RuleSimulationRun(
            id=uuid4(),
            workspace_id=workspace_id,
            rule_set_id=rule_set_id,
            version_id=version_id,
            created_by=actor_id,
            historical_at=payload.historical_at,
            input_json=context.model_dump(mode="json"),
            result_json=[item.model_dump(mode="json") for item in projections],
            applicable_count=sum(item.applies for item in projections),
            skipped_count=sum(not item.applies for item in projections),
            created_at=now,
            updated_at=now,
        )
        self.session.add(run)
        self._audit(
            workspace_id,
            actor_id,
            "editorial_rule_simulation.created",
            "rule_simulation",
            run.id,
            {
                "version_id": str(version_id),
                "applicable_count": run.applicable_count,
                "skipped_count": run.skipped_count,
                "historical_at": payload.historical_at.isoformat()
                if payload.historical_at
                else None,
                "execution_state": "not_executed",
            },
        )
        await self.session.commit()
        await self.session.refresh(run)
        return self._simulation_read(run, version, feedback=[])

    async def list_simulations(
        self,
        workspace_id: UUID,
        rule_set_id: UUID,
        version_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> RuleSimulationPage:
        version = await self._version(workspace_id, rule_set_id, version_id)
        conditions = [
            RuleSimulationRun.workspace_id == workspace_id,
            RuleSimulationRun.rule_set_id == rule_set_id,
            RuleSimulationRun.version_id == version_id,
        ]
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(RuleSimulationRun).where(*conditions)
            )
            or 0
        )
        runs = list(
            (
                await self.session.scalars(
                    select(RuleSimulationRun)
                    .options(selectinload(RuleSimulationRun.feedback))
                    .where(*conditions)
                    .order_by(RuleSimulationRun.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return RuleSimulationPage(
            items=[self._simulation_read(run, version) for run in runs],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_simulation(
        self, workspace_id: UUID, rule_set_id: UUID, version_id: UUID, simulation_id: UUID
    ) -> RuleSimulationRead:
        version = await self._version(workspace_id, rule_set_id, version_id)
        run = await self.session.scalar(
            select(RuleSimulationRun)
            .options(selectinload(RuleSimulationRun.feedback))
            .where(
                RuleSimulationRun.id == simulation_id,
                RuleSimulationRun.workspace_id == workspace_id,
                RuleSimulationRun.rule_set_id == rule_set_id,
                RuleSimulationRun.version_id == version_id,
            )
        )
        if run is None:
            raise EditorialRuleNotFound("规则模拟记录不存在")
        return self._simulation_read(run, version)

    async def feedback(
        self,
        workspace_id: UUID,
        rule_set_id: UUID,
        version_id: UUID,
        simulation_id: UUID,
        rule_id: UUID,
        actor_id: UUID,
        payload: RuleSimulationFeedbackCreate,
    ) -> RuleSimulationFeedbackRead:
        version = await self._version(workspace_id, rule_set_id, version_id)
        run = await self.session.scalar(
            select(RuleSimulationRun).where(
                RuleSimulationRun.id == simulation_id,
                RuleSimulationRun.workspace_id == workspace_id,
                RuleSimulationRun.rule_set_id == rule_set_id,
                RuleSimulationRun.version_id == version_id,
            )
        )
        if run is None:
            raise EditorialRuleNotFound("规则模拟记录不存在")
        result_rule_ids = {str(item.get("rule_id")) for item in run.result_json}
        if str(rule_id) not in result_rule_ids:
            raise EditorialRuleConflict(
                "该规则不在模拟结果中，不能提交反馈", "simulation_rule_not_found"
            )
        if not any(item.id == rule_id for item in version.rules):
            raise EditorialRuleNotFound("规则不存在")
        feedback = await self.session.scalar(
            select(RuleSimulationFeedback).where(
                RuleSimulationFeedback.simulation_id == simulation_id,
                RuleSimulationFeedback.rule_id == rule_id,
                RuleSimulationFeedback.created_by == actor_id,
            )
        )
        now = datetime.now(UTC)
        if feedback is None:
            feedback = RuleSimulationFeedback(
                id=uuid4(),
                workspace_id=workspace_id,
                simulation_id=simulation_id,
                rule_id=rule_id,
                created_by=actor_id,
                verdict=payload.verdict,
                comment=payload.comment,
                created_at=now,
                updated_at=now,
            )
            self.session.add(feedback)
        else:
            feedback.verdict = payload.verdict
            feedback.comment = payload.comment
            feedback.updated_at = now
        self._audit(
            workspace_id,
            actor_id,
            "editorial_rule_simulation.feedback_submitted",
            "rule_simulation",
            simulation_id,
            {"rule_id": str(rule_id), "verdict": payload.verdict},
        )
        await self.session.commit()
        await self.session.refresh(feedback)
        return RuleSimulationFeedbackRead.model_validate(feedback)

    @staticmethod
    def _simulation_projection(
        rule: Rule, context: RuleSimulationContext
    ) -> RuleSimulationRuleRead:
        if not rule.enabled:
            return RuleSimulationRuleRead(
                rule_id=rule.id,
                key=rule.key,
                title=rule.title,
                priority=rule.priority,
                enabled=False,
                applies=False,
                reason="规则已停用",
                source_status=_source_status(rule.source_status),
            )
        for label, value, allowed in (
            ("sport", context.sport, rule.sports),
            ("story_type", context.story_type, rule.story_types),
            ("output_type", context.output_type, rule.output_types),
        ):
            if not allowed:
                continue
            normalized = {item.casefold() for item in allowed}
            if value is None:
                return RuleSimulationRuleRead(
                    rule_id=rule.id,
                    key=rule.key,
                    title=rule.title,
                    priority=rule.priority,
                    enabled=True,
                    applies=False,
                    reason=f"规则限定 {label}，输入未提供该上下文",
                    source_status=_source_status(rule.source_status),
                )
            if value.casefold() not in normalized:
                return RuleSimulationRuleRead(
                    rule_id=rule.id,
                    key=rule.key,
                    title=rule.title,
                    priority=rule.priority,
                    enabled=True,
                    applies=False,
                    reason=f"输入 {label}={value} 不匹配规则限定值",
                    source_status=_source_status(rule.source_status),
                )
        reason = "上下文筛选匹配；未执行规则指令、模型或 QA"
        if rule.source_status != "full":
            reason += f"；来源状态为 {rule.source_status}，需人工核验"
        return RuleSimulationRuleRead(
            rule_id=rule.id,
            key=rule.key,
            title=rule.title,
            priority=rule.priority,
            enabled=True,
            applies=True,
            reason=reason,
            source_status=_source_status(rule.source_status),
        )

    def _simulation_read(
        self,
        run: RuleSimulationRun,
        version: RuleSetVersion,
        feedback: list[RuleSimulationFeedback] | None = None,
    ) -> RuleSimulationRead:
        feedback_items = run.feedback if feedback is None else feedback
        return RuleSimulationRead(
            id=run.id,
            workspace_id=run.workspace_id,
            rule_set_id=run.rule_set_id,
            version_id=run.version_id,
            version=version.version,
            source_hash=version.source_hash,
            created_by=run.created_by,
            historical_at=run.historical_at,
            context=RuleSimulationContext.model_validate(run.input_json),
            rules=[RuleSimulationRuleRead.model_validate(item) for item in run.result_json],
            applicable_count=run.applicable_count,
            skipped_count=run.skipped_count,
            feedback=[RuleSimulationFeedbackRead.model_validate(item) for item in feedback_items],
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    async def publish(
        self,
        workspace_id: UUID,
        rule_set_id: UUID,
        version_id: UUID,
        actor_id: UUID,
        reason: str | None,
    ) -> RuleSetVersionRead:
        rule_set = await self._rule_set(workspace_id, rule_set_id)
        version = await self._version(workspace_id, rule_set_id, version_id)
        if version.status == "published":
            return self._version_read(version)
        if version.status != "draft":
            raise EditorialRuleConflict("只有草稿版本可以发布", "version_not_publishable")
        result = self._validation_result(validate_rules(version.rules))
        if not result.valid:
            raise EditorialRuleConflict(
                f"规则版本存在 {result.errors} 个阻断错误", "rule_validation_failed"
            )
        version.status = "published"
        version.published_at = datetime.now(UTC)
        rule_set.current_version_id = version.id
        self._audit(
            workspace_id,
            actor_id,
            "editorial_rule_version.published",
            "rule_set_version",
            version.id,
            {"warnings": result.warnings},
            reason,
        )
        await self.session.commit()
        return self._version_read(version)

    async def rollback(
        self,
        workspace_id: UUID,
        rule_set_id: UUID,
        version_id: UUID,
        actor_id: UUID,
        reason: str | None,
    ) -> RuleSetVersionRead:
        rule_set = await self._rule_set(workspace_id, rule_set_id)
        version = await self._version(workspace_id, rule_set_id, version_id)
        if version.status != "published":
            raise EditorialRuleConflict("只能回滚到已发布版本", "rollback_target_not_published")
        previous = rule_set.current_version_id
        rule_set.current_version_id = version.id
        self._audit(
            workspace_id,
            actor_id,
            "editorial_rule_version.rolled_back",
            "rule_set",
            rule_set.id,
            {
                "from_version_id": str(previous) if previous else None,
                "to_version_id": str(version.id),
            },
            reason,
        )
        await self.session.commit()
        return self._version_read(version)

    async def compare(
        self,
        workspace_id: UUID,
        rule_set_id: UUID,
        left_id: UUID,
        right_id: UUID,
    ) -> RuleDiffRead:
        left = await self._version(workspace_id, rule_set_id, left_id)
        right = await self._version(workspace_id, rule_set_id, right_id)
        left_rules = {item.key: item for item in left.rules}
        right_rules = {item.key: item for item in right.rules}
        items: list[RuleDiffItem] = []
        unchanged = 0
        fields = sorted(EDITABLE_RULE_FIELDS)
        for key in sorted(left_rules.keys() | right_rules.keys()):
            if key not in left_rules:
                items.append(RuleDiffItem(key=key, change="added"))
            elif key not in right_rules:
                items.append(RuleDiffItem(key=key, change="removed"))
            else:
                changed = [
                    field
                    for field in fields
                    if getattr(left_rules[key], field) != getattr(right_rules[key], field)
                ]
                if changed:
                    items.append(RuleDiffItem(key=key, change="modified", fields=changed))
                else:
                    unchanged += 1
        return RuleDiffRead(
            left_version=RuleSetVersionSummary.model_validate(left),
            right_version=RuleSetVersionSummary.model_validate(right),
            added=sum(item.change == "added" for item in items),
            removed=sum(item.change == "removed" for item in items),
            modified=sum(item.change == "modified" for item in items),
            unchanged=unchanged,
            items=items,
        )

    async def import_request(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: RuleImportRequest,
    ) -> RuleImportResult:
        key: str
        name: str
        description: str | None
        tags: list[str]
        if payload.format == "txt":
            try:
                document = parse_v79_bytes(payload.content.encode("utf-8"))
            except RuleParseError as exc:
                raise EditorialRuleError(str(exc), code="rule_import_invalid") from exc
            key, name, description, tags = (
                payload.key,
                payload.name,
                "完整 V7.9 原文及可编辑结构化规则",
                ["v7.9", "sports", "narration", "full-source"],
            )
        else:
            try:
                bundle = RuleExportBundle.model_validate_json(payload.content)
            except ValidationError as exc:
                raise EditorialRuleError("JSON 规则包结构无效", code="rule_json_invalid") from exc
            document = self._document_from_bundle(bundle)
            key, name, description, tags = (
                bundle.rule_set_key,
                bundle.rule_set_name,
                bundle.description,
                bundle.tags,
            )
        return await self.import_document(
            workspace_id,
            actor_id,
            document,
            key=key,
            name=name,
            description=description,
            tags=tags,
            changelog=payload.changelog,
            publish=payload.publish,
        )

    async def import_document(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        document: ParsedRuleDocument,
        *,
        key: str,
        name: str,
        description: str | None,
        tags: list[str],
        changelog: str | None,
        publish: bool,
    ) -> RuleImportResult:
        document_validation = self._validation_result(validate_rules(document.rules))
        if not document_validation.valid:
            raise EditorialRuleConflict(
                f"导入规则存在 {document_validation.errors} 个阻断错误",
                "rule_validation_failed",
            )
        rule_set = await self.repo.rule_set_by_key(workspace_id, key)
        if rule_set is None:
            rule_set = RuleSet(
                id=uuid4(),
                workspace_id=workspace_id,
                key=key,
                name=name,
                description=description,
                current_version_id=None,
                status="active",
                tags=tags,
            )
            self.session.add(rule_set)
            await self.session.flush()
        existing = await self.repo.version_by_hash(workspace_id, rule_set.id, document.source_hash)
        if existing is not None:
            result = self._validation_result(validate_rules(existing.rules))
            return RuleImportResult(
                rule_set=await self._rule_set_read(workspace_id, rule_set),
                version=self._version_read(existing),
                created=False,
                validation=result,
            )
        label = document.version
        if await self.repo.version_by_label(workspace_id, rule_set.id, label):
            label = await self._next_label(workspace_id, rule_set.id, label)
        version = self._materialize_document(
            workspace_id, rule_set.id, actor_id, label, changelog, document
        )
        self.session.add(version)
        await self.session.flush()
        result = self._validation_result(validate_rules(version.rules))
        if publish and result.valid:
            version.status = "published"
            version.published_at = datetime.now(UTC)
            rule_set.current_version_id = version.id
        elif publish:
            raise EditorialRuleConflict(
                f"导入规则存在 {result.errors} 个阻断错误", "rule_validation_failed"
            )
        self._audit(
            workspace_id,
            actor_id,
            "editorial_rule_version.imported",
            "rule_set_version",
            version.id,
            {
                "filename_hash": document.source_hash,
                "source_status": "full",
                "sections": len(document.sections),
                "rules": len(document.rules),
                "published": publish,
            },
        )
        await self.session.commit()
        loaded = await self._version(workspace_id, rule_set.id, version.id)
        rule_set = await self._rule_set(workspace_id, rule_set.id)
        return RuleImportResult(
            rule_set=await self._rule_set_read(workspace_id, rule_set),
            version=self._version_read(loaded),
            created=True,
            validation=result,
        )

    async def export_bundle(
        self, workspace_id: UUID, rule_set_id: UUID, version_id: UUID
    ) -> RuleExportBundle:
        rule_set = await self._rule_set(workspace_id, rule_set_id)
        version = await self._version(workspace_id, rule_set_id, version_id)
        sections_by_id = {item.id: item for item in version.sections}
        return RuleExportBundle(
            rule_set_key=rule_set.key,
            rule_set_name=rule_set.name,
            description=rule_set.description,
            tags=rule_set.tags,
            version=version.version,
            source_text=version.source_text,
            source_hash=version.source_hash,
            changelog=version.changelog,
            sections=[
                RuleExportSection(
                    slug=section.slug,
                    parent_slug=(
                        sections_by_id[section.parent_id].slug
                        if section.parent_id in sections_by_id
                        else None
                    ),
                    title=section.title,
                    description=section.description,
                    sort_order=section.sort_order,
                )
                for section in sorted(version.sections, key=lambda item: item.sort_order)
            ],
            rules=[
                RuleExportRule(
                    section_slug=sections_by_id[rule.section_id].slug,
                    **{
                        field: getattr(rule, field)
                        for field in (
                            "key",
                            "title",
                            "rule_type",
                            "instruction",
                            "why",
                            "how",
                            "good_example",
                            "bad_example",
                            "qa_check",
                            "rewrite_instruction",
                            "priority",
                            "severity",
                            "is_mandatory",
                            "enabled",
                            "sports",
                            "story_types",
                            "output_types",
                            "dependencies",
                            "conflicts",
                            "tags",
                            "source_reference",
                            "source_status",
                            "sort_order",
                        )
                    },
                )
                for rule in sorted(version.rules, key=lambda item: item.sort_order)
            ],
        )

    async def export_json(self, workspace_id: UUID, rule_set_id: UUID, version_id: UUID) -> str:
        bundle = await self.export_bundle(workspace_id, rule_set_id, version_id)
        return json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2)

    async def source_text(self, workspace_id: UUID, rule_set_id: UUID, version_id: UUID) -> str:
        return (await self._version(workspace_id, rule_set_id, version_id)).source_text

    async def _rule_set(self, workspace_id: UUID, rule_set_id: UUID) -> RuleSet:
        rule_set = await self.repo.rule_set(workspace_id, rule_set_id)
        if rule_set is None:
            raise EditorialRuleNotFound("规则集合不存在")
        return rule_set

    async def _version(
        self, workspace_id: UUID, rule_set_id: UUID, version_id: UUID
    ) -> RuleSetVersion:
        version = await self.repo.version(workspace_id, rule_set_id, version_id)
        if version is None:
            raise EditorialRuleNotFound("规则版本不存在")
        return version

    async def _rule_set_read(self, workspace_id: UUID, rule_set: RuleSet) -> RuleSetRead:
        versions = await self.repo.versions(workspace_id, rule_set.id)
        return RuleSetRead.model_validate(rule_set).model_copy(
            update={
                "version_count": len(versions),
                "draft_count": sum(item.status == "draft" for item in versions),
            }
        )

    def _version_read(self, version: RuleSetVersion) -> RuleSetVersionRead:
        return RuleSetVersionRead(
            **RuleSetVersionSummary.model_validate(version).model_dump(),
            rule_set_id=version.rule_set_id,
            source_text=version.source_text,
            section_count=len(version.sections),
            rule_count=len(version.rules),
        )

    async def _next_label(self, workspace_id: UUID, rule_set_id: UUID, base: str) -> str:
        clean_base = base.split("-draft.", maxsplit=1)[0]
        index = 1
        while await self.repo.version_by_label(
            workspace_id, rule_set_id, f"{clean_base}-draft.{index}"
        ):
            index += 1
        return f"{clean_base}-draft.{index}"

    def _clone_version(
        self,
        source: RuleSetVersion,
        actor_id: UUID,
        label: str,
        changelog: str | None,
    ) -> RuleSetVersion:
        now = datetime.now(UTC)
        draft = RuleSetVersion(
            id=uuid4(),
            workspace_id=source.workspace_id,
            rule_set_id=source.rule_set_id,
            version=label,
            source_text=source.source_text,
            source_hash=source.source_hash,
            changelog=changelog,
            status="draft",
            created_by=actor_id,
            created_at=now,
            published_at=None,
        )
        section_map: dict[UUID, UUID] = {item.id: uuid4() for item in source.sections}
        draft.sections = [
            RuleSection(
                id=section_map[item.id],
                workspace_id=item.workspace_id,
                version_id=draft.id,
                parent_id=section_map.get(item.parent_id) if item.parent_id else None,
                title=item.title,
                slug=item.slug,
                description=item.description,
                sort_order=item.sort_order,
            )
            for item in _sort_sections_parents_first(
                source.sections, key_of=lambda s: s.id, parent_of=lambda s: s.parent_id
            )
        ]
        draft.rules = [
            Rule(
                id=uuid4(),
                workspace_id=item.workspace_id,
                version_id=draft.id,
                section_id=section_map[item.section_id],
                key=item.key,
                title=item.title,
                rule_type=item.rule_type,
                instruction=item.instruction,
                why=item.why,
                how=item.how,
                good_example=item.good_example,
                bad_example=item.bad_example,
                qa_check=item.qa_check,
                rewrite_instruction=item.rewrite_instruction,
                priority=item.priority,
                severity=item.severity,
                is_mandatory=item.is_mandatory,
                enabled=item.enabled,
                sports=list(item.sports),
                story_types=list(item.story_types),
                output_types=list(item.output_types),
                dependencies=list(item.dependencies),
                conflicts=list(item.conflicts),
                tags=list(item.tags),
                source_reference=item.source_reference,
                source_status=item.source_status,
                sort_order=item.sort_order,
                created_at=now,
                updated_at=now,
            )
            for item in source.rules
        ]
        return draft

    def _materialize_document(
        self,
        workspace_id: UUID,
        rule_set_id: UUID,
        actor_id: UUID,
        label: str,
        changelog: str | None,
        document: ParsedRuleDocument,
    ) -> RuleSetVersion:
        now = datetime.now(UTC)
        version = RuleSetVersion(
            id=uuid4(),
            workspace_id=workspace_id,
            rule_set_id=rule_set_id,
            version=label,
            source_text=document.source_text,
            source_hash=document.source_hash,
            changelog=changelog,
            status="draft",
            created_by=actor_id,
            created_at=now,
            published_at=None,
        )
        section_ids = {item.key: uuid4() for item in document.sections}
        version.sections = [
            RuleSection(
                id=section_ids[item.key],
                workspace_id=workspace_id,
                version_id=version.id,
                parent_id=section_ids.get(item.parent_key) if item.parent_key else None,
                title=item.title,
                slug=item.slug,
                description=item.description,
                sort_order=item.sort_order,
            )
            for item in _sort_sections_parents_first(
                document.sections, key_of=lambda s: s.key, parent_of=lambda s: s.parent_key
            )
        ]
        version.rules = [
            Rule(
                id=uuid4(),
                workspace_id=workspace_id,
                version_id=version.id,
                section_id=section_ids[item.section_key],
                key=item.key,
                title=item.title,
                rule_type=item.rule_type,
                instruction=item.instruction,
                why=item.why,
                how=item.how,
                good_example=item.good_example,
                bad_example=item.bad_example,
                qa_check=item.qa_check,
                rewrite_instruction=item.rewrite_instruction,
                priority=item.priority,
                severity=item.severity,
                is_mandatory=item.is_mandatory,
                enabled=item.enabled,
                sports=item.sports,
                story_types=item.story_types,
                output_types=item.output_types,
                dependencies=item.dependencies,
                conflicts=item.conflicts,
                tags=item.tags,
                source_reference=item.source_reference,
                source_status=item.source_status,
                sort_order=item.sort_order,
                created_at=now,
                updated_at=now,
            )
            for item in document.rules
        ]
        return version

    def _document_from_bundle(self, bundle: RuleExportBundle) -> ParsedRuleDocument:
        actual_hash = sha256(bundle.source_text.encode("utf-8")).hexdigest()
        if actual_hash != bundle.source_hash:
            raise EditorialRuleError("JSON 规则包原文哈希不匹配", code="rule_source_hash_mismatch")
        section_keys = {
            item.slug: f"json-section-{index}" for index, item in enumerate(bundle.sections)
        }
        if len(section_keys) != len(bundle.sections):
            raise EditorialRuleError("JSON 规则包章节 slug 重复", code="duplicate_section_slug")
        sections = [
            ParsedSection(
                key=section_keys[item.slug],
                parent_key=section_keys.get(item.parent_slug) if item.parent_slug else None,
                title=item.title,
                slug=item.slug,
                description=item.description,
                sort_order=item.sort_order,
            )
            for item in bundle.sections
        ]
        if any(
            item.parent_slug and item.parent_slug not in section_keys for item in bundle.sections
        ):
            raise EditorialRuleError(
                "JSON 规则包引用了不存在的父章节", code="invalid_parent_section"
            )
        rules = [
            ParsedRule(
                section_key=section_keys[item.section_slug],
                **item.model_dump(exclude={"section_slug"}),
            )
            for item in bundle.rules
            if item.section_slug in section_keys
        ]
        if len(rules) != len(bundle.rules):
            raise EditorialRuleError("JSON 规则包存在缺失章节的规则", code="missing_rule_section")
        return ParsedRuleDocument(
            version=bundle.version,
            source_text=bundle.source_text,
            source_hash=bundle.source_hash,
            sections=sections,
            rules=rules,
        )

    def _apply_rule_update(self, rule: Rule, payload: RuleUpdate) -> None:
        for field in payload.model_fields_set:
            if field in EDITABLE_RULE_FIELDS:
                setattr(rule, field, getattr(payload, field))

    def _validation_result(self, issues: list[ValidationIssue]) -> ValidationResultRead:
        errors = sum(item.level == "error" for item in issues)
        warnings = sum(item.level == "warning" for item in issues)
        return ValidationResultRead(
            valid=errors == 0,
            errors=errors,
            warnings=warnings,
            issues=[
                ValidationIssueRead(
                    level=item.level,  # type: ignore[arg-type]
                    code=item.code,
                    message=item.message,
                    rule_key=item.rule_key,
                )
                for item in issues
            ],
        )

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        changes: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> None:
        self.session.add(
            AuditEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                before_hash=None,
                after_hash=None,
                change_summary_json=changes or {},
                reason=reason,
                ip_hash=None,
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )
