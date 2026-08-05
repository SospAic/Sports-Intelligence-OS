from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.conditions import (
    ConditionValidationError,
    evaluate_condition_tree,
    validate_condition_tree,
)
from app.core.config import Settings
from app.models.automation import (
    AutomationAction,
    AutomationEvaluation,
    AutomationRule,
    AutomationRuntimeState,
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryAttempt,
)
from app.models.monitoring import Account, ContentItem
from app.models.news import Article, TopicEvent
from app.models.notification_template import NotificationTemplateVersion
from app.models.topics import SavedTopic
from app.providers.llm.base import LLMProvider
from app.providers.notifications.base import (
    NotificationMessage,
    NotificationProvider,
    NotificationProviderError,
)
from app.providers.notifications.crypto import NotificationConfigCipher, mask_notification_config
from app.providers.registry import ProviderRegistry
from app.repositories.automation import AutomationRepository
from app.schemas.automation import (
    AutomationActionCreate,
    AutomationActionRead,
    AutomationEvaluateRequest,
    AutomationEvaluationPage,
    AutomationEvaluationRead,
    AutomationRuleCreate,
    AutomationRuleDetail,
    AutomationRulePage,
    AutomationRuleRead,
    AutomationRuleUpdate,
    ConditionValidateRequest,
    ConditionValidateResult,
    NotificationChannelCreate,
    NotificationChannelRead,
    NotificationChannelUpdate,
    NotificationDeliveryPage,
    NotificationDeliveryRead,
    NotificationTestRequest,
)
from app.schemas.generation import GenerationCreate
from app.services.audit import build_audit_entry, build_external_call_attempt
from app.services.generation import GenerationError, GenerationService
from app.services.notification_template import NotificationTemplateService


class AutomationError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class AutomationNotFound(AutomationError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="automation_not_found", status_code=404)


class AutomationConflict(AutomationError):
    def __init__(self, message: str, code: str = "automation_conflict") -> None:
        super().__init__(message, code=code, status_code=409)


class AutomationService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        notification_providers: ProviderRegistry[NotificationProvider],
        llm_providers: ProviderRegistry[LLMProvider] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.repo = AutomationRepository(session)
        self.notification_providers = notification_providers
        self.llm_providers = llm_providers
        explicit_key = (
            settings.notification_encryption_key.get_secret_value()
            if settings.notification_encryption_key
            else ""
        )
        key = explicit_key or settings.secret_key.get_secret_value()
        self.cipher = NotificationConfigCipher(key)

    async def list_rules(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        entity_type: str | None,
        enabled: bool | None,
    ) -> AutomationRulePage:
        items, total = await self.repo.list_rules(
            workspace_id,
            page=page,
            page_size=page_size,
            entity_type=entity_type,
            enabled=enabled,
        )
        return AutomationRulePage(
            items=[AutomationRuleRead.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_rule(self, workspace_id: UUID, rule_id: UUID) -> AutomationRuleDetail:
        rule = await self.repo.rule(workspace_id, rule_id)
        if rule is None:
            raise AutomationNotFound("自动化规则不存在")
        return AutomationRuleDetail.model_validate(rule)

    async def create_rule(
        self, workspace_id: UUID, actor_id: UUID, payload: AutomationRuleCreate
    ) -> AutomationRuleDetail:
        self._validate_tree(payload.condition_tree, payload.entity_type)
        if payload.enabled and not payload.actions:
            raise AutomationConflict("启用的规则必须至少包含一个动作", "automation_action_required")
        rule = AutomationRule(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=actor_id,
            name=payload.name,
            description=payload.description,
            entity_type=payload.entity_type,
            trigger_type=payload.trigger_type,
            condition_tree=payload.condition_tree,
            schedule=payload.schedule,
            cooldown_seconds=payload.cooldown_seconds,
            deduplication_window=payload.deduplication_window,
            enabled=payload.enabled,
            priority=payload.priority,
        )
        rule.actions = [
            AutomationAction(
                id=uuid4(),
                workspace_id=workspace_id,
                rule_id=rule.id,
                action_type=action.action_type,
                config=action.config,
                sort_order=action.sort_order,
                enabled=action.enabled,
            )
            for action in payload.actions
        ]
        for action in rule.actions:
            self._validate_action(action.action_type, action.config, enabled=rule.enabled)
            if rule.enabled and action.enabled:
                await self._validate_action_references(
                    workspace_id, action.action_type, action.config
                )
        self.session.add(rule)
        self._audit(workspace_id, actor_id, "automation_rule.created", "automation_rule", rule.id)
        await self.session.commit()
        return await self.get_rule(workspace_id, rule.id)

    async def update_rule(
        self,
        workspace_id: UUID,
        rule_id: UUID,
        actor_id: UUID,
        payload: AutomationRuleUpdate,
    ) -> AutomationRuleDetail:
        rule = await self._rule(workspace_id, rule_id)
        changes = payload.model_dump(exclude_unset=True)
        candidate_tree = cast(dict[str, Any], changes.get("condition_tree", rule.condition_tree))
        self._validate_tree(candidate_tree, rule.entity_type)
        for field, value in changes.items():
            setattr(rule, field, value)
        if rule.enabled:
            enabled_actions = [action for action in rule.actions if action.enabled]
            if not enabled_actions:
                raise AutomationConflict(
                    "启用的规则必须至少包含一个动作", "automation_action_required"
                )
            for action in enabled_actions:
                self._validate_action(action.action_type, action.config, enabled=True)
                await self._validate_action_references(
                    workspace_id, action.action_type, action.config
                )
        self._audit(
            workspace_id,
            actor_id,
            "automation_rule.updated",
            "automation_rule",
            rule.id,
            changes,
        )
        await self.session.commit()
        return await self.get_rule(workspace_id, rule.id)

    async def delete_rule(self, workspace_id: UUID, rule_id: UUID, actor_id: UUID) -> None:
        rule = await self._rule(workspace_id, rule_id)
        self._audit(workspace_id, actor_id, "automation_rule.deleted", "automation_rule", rule.id)
        await self.session.delete(rule)
        await self.session.commit()

    async def add_action(
        self,
        workspace_id: UUID,
        rule_id: UUID,
        actor_id: UUID,
        payload: AutomationActionCreate,
    ) -> AutomationActionRead:
        rule = await self._rule(workspace_id, rule_id)
        self._validate_action(
            payload.action_type, payload.config, enabled=payload.enabled and rule.enabled
        )
        if payload.enabled and rule.enabled:
            await self._validate_action_references(
                workspace_id, payload.action_type, payload.config
            )
        if any(action.sort_order == payload.sort_order for action in rule.actions):
            raise AutomationConflict("动作顺序已被占用", "automation_action_order_conflict")
        action = AutomationAction(
            id=uuid4(),
            workspace_id=workspace_id,
            rule_id=rule.id,
            action_type=payload.action_type,
            config=payload.config,
            sort_order=payload.sort_order,
            enabled=payload.enabled,
        )
        self.session.add(action)
        self._audit(
            workspace_id, actor_id, "automation_action.created", "automation_action", action.id
        )
        await self.session.commit()
        await self.session.refresh(action)
        return AutomationActionRead.model_validate(action)

    async def delete_action(
        self, workspace_id: UUID, rule_id: UUID, action_id: UUID, actor_id: UUID
    ) -> None:
        rule = await self._rule(workspace_id, rule_id)
        action = next((item for item in rule.actions if item.id == action_id), None)
        if action is None:
            raise AutomationNotFound("自动化动作不存在")
        if (
            rule.enabled
            and action.enabled
            and len([item for item in rule.actions if item.enabled]) == 1
        ):
            raise AutomationConflict("启用的规则必须保留至少一个动作", "automation_action_required")
        self._audit(
            workspace_id, actor_id, "automation_action.deleted", "automation_action", action.id
        )
        await self.session.delete(action)
        await self.session.commit()

    def validate_conditions(self, payload: ConditionValidateRequest) -> ConditionValidateResult:
        self._validate_tree(payload.condition_tree, payload.entity_type)
        if payload.facts is None:
            return ConditionValidateResult(valid=True)
        result = evaluate_condition_tree(
            payload.condition_tree,
            payload.facts,
            previous=payload.previous,
            consecutive_count=payload.consecutive_count,
        )
        return ConditionValidateResult(
            valid=True, matched=result.value, explanation=result.explanation
        )

    async def evaluate(
        self, workspace_id: UUID, actor_id: UUID, payload: AutomationEvaluateRequest
    ) -> list[AutomationEvaluationRead]:
        rules = await self.repo.matching_rules(
            workspace_id, payload.entity_type, payload.trigger_type
        )
        evaluations: list[AutomationEvaluationRead] = []
        for rule in rules:
            event_key = f"{payload.event_key}:{rule.id}"
            existing = await self.repo.evaluation_by_event(workspace_id, rule.id, event_key)
            if existing is not None:
                evaluations.append(AutomationEvaluationRead.model_validate(existing))
                continue
            evaluation = await self._evaluate_rule(workspace_id, actor_id, rule, payload, event_key)
            evaluations.append(AutomationEvaluationRead.model_validate(evaluation))
        return evaluations

    async def _evaluate_rule(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        rule: AutomationRule,
        payload: AutomationEvaluateRequest,
        event_key: str,
    ) -> AutomationEvaluation:
        now = datetime.now(UTC)
        state = await self.repo.runtime_state(
            workspace_id, rule.id, payload.entity_type, payload.entity_id
        )
        if state is None:
            state = AutomationRuntimeState(
                id=uuid4(),
                workspace_id=workspace_id,
                rule_id=rule.id,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                consecutive_count=0,
                last_evaluated_at=None,
                last_matched_at=None,
                cooldown_until=None,
                last_deduplication_key=None,
            )
            self.session.add(state)

        condition = evaluate_condition_tree(
            rule.condition_tree,
            payload.facts,
            previous=payload.previous,
            consecutive_count=state.consecutive_count,
        )
        matched = condition.matched
        explanation = condition.explanation

        pending_consecutive = self._has_pending_consecutive(explanation)
        state.consecutive_count = (
            state.consecutive_count + 1 if matched or pending_consecutive else 0
        )
        state.last_evaluated_at = now
        window = rule.deduplication_window
        bucket = int(now.timestamp()) // window if window else int(now.timestamp())
        deduplication_key = f"{rule.id}:{payload.entity_id}:{bucket}"
        suppression: str | None = None
        if matched and state.cooldown_until and _as_utc(state.cooldown_until) > now:
            suppression = "cooldown_active"
        if matched and not suppression and window:
            previous_dedup = await self.session.scalar(
                select(AutomationEvaluation.id).where(
                    AutomationEvaluation.workspace_id == workspace_id,
                    AutomationEvaluation.rule_id == rule.id,
                    AutomationEvaluation.deduplication_key == deduplication_key,
                    AutomationEvaluation.matched.is_(True),
                )
            )
            if previous_dedup is not None:
                suppression = "deduplicated"

        evaluation = AutomationEvaluation(
            id=uuid4(),
            workspace_id=workspace_id,
            rule_id=rule.id,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            evaluated_at=now,
            matched=matched,
            condition_result={**explanation, "suppression": suppression, "actions": []},
            deduplication_key=deduplication_key,
            event_key=event_key,
            execution_status=(
                "suppressed" if suppression else "queued" if matched else "not_matched"
            ),
            evaluation_metadata={
                "source_kind": payload.source_kind,
                "test_mode": payload.test_mode,
                "trigger_type": payload.trigger_type,
            },
        )
        self.session.add(evaluation)
        await self.session.flush()
        if matched and not suppression:
            action_results = await self._execute_actions(
                workspace_id, actor_id, rule, evaluation, payload
            )
            failed = [item for item in action_results if item["status"] == "failed"]
            succeeded = [
                item for item in action_results if item["status"] in {"completed", "queued"}
            ]
            evaluation.condition_result = {**evaluation.condition_result, "actions": action_results}
            if failed and succeeded:
                evaluation.execution_status = "partial"
            elif failed:
                evaluation.execution_status = "failed"
            else:
                evaluation.execution_status = "completed"
            state.last_matched_at = now
            state.last_deduplication_key = deduplication_key
            if rule.cooldown_seconds:
                state.cooldown_until = now + timedelta(seconds=rule.cooldown_seconds)
        await self.session.commit()
        await self.session.refresh(evaluation)
        return evaluation

    async def _execute_actions(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        rule: AutomationRule,
        evaluation: AutomationEvaluation,
        payload: AutomationEvaluateRequest,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        generation_context: dict[str, Any] = {}
        for action in sorted(rule.actions, key=lambda item: item.sort_order):
            if not action.enabled:
                continue
            try:
                if action.action_type == "create_generation":
                    generation_context = await self._create_generation(
                        workspace_id, actor_id, evaluation, payload, action.config
                    )
                    result = {
                        "action_id": str(action.id),
                        "type": action.action_type,
                        "status": "completed",
                        **generation_context,
                    }
                elif action.action_type in {"notification", "webhook", "external_api"}:
                    delivery = await self._create_delivery(
                        workspace_id,
                        rule,
                        evaluation,
                        payload,
                        action,
                        generation_context,
                    )
                    result = {
                        "action_id": str(action.id),
                        "type": action.action_type,
                        "status": "queued",
                        "delivery_id": str(delivery.id),
                    }
                elif action.action_type == "create_topic":
                    await self._create_topic(workspace_id, payload, rule)
                    result = {
                        "action_id": str(action.id),
                        "type": action.action_type,
                        "status": "completed",
                    }
                elif action.action_type == "save_content":
                    await self._save_content(workspace_id, payload, rule)
                    result = {
                        "action_id": str(action.id),
                        "type": action.action_type,
                        "status": "completed",
                    }
                else:
                    raise ValueError(f"unsupported action type: {action.action_type}")
            except Exception as exc:
                generation_context = (
                    {"generation_error": self._safe_error(exc)}
                    if action.action_type == "create_generation"
                    else generation_context
                )
                result = {
                    "action_id": str(action.id),
                    "type": action.action_type,
                    "status": "failed",
                    "error": self._safe_error(exc),
                }
            results.append(result)
        return results

    async def _create_generation(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        evaluation: AutomationEvaluation,
        payload: AutomationEvaluateRequest,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        if self.llm_providers is None:
            raise RuntimeError("LLM providers are unavailable")
        input_type = str(
            config.get("input_type") or self._generation_input_type(payload.entity_type)
        )
        generation_payload = GenerationCreate.model_validate(
            {
                "workflow_id": config["workflow_id"],
                "input_type": input_type,
                "input_id": str(payload.entity_id) if input_type != "user_text" else None,
                "input_payload": (
                    {"text": json.dumps(payload.facts, ensure_ascii=False)}
                    if input_type == "user_text"
                    else {}
                ),
                "rule_set_version_id": config.get("rule_set_version_id"),
                "prompt_version_id": config.get("prompt_version_id"),
                "provider": config.get("provider", "openai_compatible"),
                "model": config.get("model", "gpt-4o-mini"),
                "model_config": config.get("model_config", {}),
            }
        )
        generation_service = GenerationService(self.session, self.llm_providers, self.settings)
        run, _ = await generation_service.create_run(
            workspace_id,
            actor_id,
            generation_payload,
            f"automation:{evaluation.id}",
        )
        await generation_service.execute_run(run.id)
        completed = await generation_service.get_run(workspace_id, run.id)
        return {
            "generation_id": str(completed.id),
            "generation_status": completed.status,
            "generation_summary": (
                (completed.final_output or {}).get("event_fact_summary")
                if completed.status == "completed"
                else None
            ),
        }

    async def _create_delivery(
        self,
        workspace_id: UUID,
        rule: AutomationRule,
        evaluation: AutomationEvaluation,
        payload: AutomationEvaluateRequest,
        action: AutomationAction,
        generation_context: dict[str, Any],
    ) -> NotificationDelivery:
        channel_id = UUID(str(action.config["channel_id"]))
        channel = await self.repo.channel(workspace_id, channel_id)
        if channel is None or not channel.enabled:
            raise ValueError("notification channel is missing or disabled")
        key = f"automation:{evaluation.id}:{action.id}"
        existing = await self.repo.delivery_by_key(workspace_id, key)
        if existing is not None:
            return existing
        reserved_template_keys = {
            "rule_name",
            "entity_id",
            "entity_type",
            "generation_summary",
            "generation_error",
        }
        fact_values = {
            key: value
            for key, value in payload.facts.items()
            if isinstance(key, str) and key not in reserved_template_keys
        }
        values = _SafeFormat(
            rule_name=rule.name,
            entity_id=str(payload.entity_id),
            entity_type=payload.entity_type,
            generation_summary=generation_context.get("generation_summary") or "",
            generation_error=(generation_context.get("generation_error") or {}).get("detail", ""),
            **fact_values,
        )
        template_id = action.config.get("template_id")
        template_version: NotificationTemplateVersion | None = None
        if template_id:
            template_version = await self.session.scalar(
                select(NotificationTemplateVersion)
                .where(
                    NotificationTemplateVersion.template_id == UUID(str(template_id)),
                    NotificationTemplateVersion.workspace_id == workspace_id,
                    NotificationTemplateVersion.status == "published",
                )
                .order_by(NotificationTemplateVersion.version.desc())
                .limit(1)
            )
            if template_version is None:
                raise ValueError("notification template is missing or has no published version")
            rendered = NotificationTemplateService.render_template(template_version, values)
        else:
            rendered = {
                "subject": str(action.config.get("title", "{rule_name} 已触发")).format_map(values),
                "body": str(
                    action.config.get("body", "实体 {entity_id} 满足监控条件。")
                ).format_map(values),
            }
        notification_payload = {
            "title": rendered["subject"][:255],
            "body": rendered["body"][:10_000],
            "url": action.config.get("url"),
            "data": {
                "rule_id": str(rule.id),
                "evaluation_id": str(evaluation.id),
                "entity_type": payload.entity_type,
                "entity_id": str(payload.entity_id),
                "source_kind": payload.source_kind,
                "notification_template_id": (
                    str(template_version.template_id) if template_version else None
                ),
                "notification_template_version_id": (
                    str(template_version.id) if template_version else None
                ),
                "notification_template_version": (
                    template_version.version if template_version else None
                ),
                **generation_context,
            },
        }
        delivery = NotificationDelivery(
            id=uuid4(),
            workspace_id=workspace_id,
            channel_id=channel.id,
            rule_id=rule.id,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            payload=notification_payload,
            status="queued",
            attempts=0,
            sent_at=None,
            error=None,
            idempotency_key=key,
            provider_message_id=None,
        )
        self.session.add(delivery)
        await self.session.flush()
        return delivery

    async def _create_topic(
        self, workspace_id: UUID, payload: AutomationEvaluateRequest, rule: AutomationRule
    ) -> None:
        source_type = {
            "content": "content",
            "news": "article",
            "topic_event": "event",
            "account": "manual",
        }[payload.entity_type]
        existing = await self.session.scalar(
            select(SavedTopic).where(
                SavedTopic.workspace_id == workspace_id,
                SavedTopic.source_type == source_type,
                SavedTopic.source_id == payload.entity_id,
            )
        )
        if existing is not None:
            return
        entity: ContentItem | Article | TopicEvent | Account | None
        if payload.entity_type == "content":
            entity = await self.session.scalar(
                select(ContentItem).where(
                    ContentItem.workspace_id == workspace_id,
                    ContentItem.id == payload.entity_id,
                )
            )
        elif payload.entity_type == "news":
            entity = await self.session.scalar(
                select(Article).where(
                    Article.workspace_id == workspace_id,
                    Article.id == payload.entity_id,
                )
            )
        elif payload.entity_type == "topic_event":
            event = await self.session.scalar(
                select(TopicEvent).where(
                    TopicEvent.workspace_id == workspace_id, TopicEvent.id == payload.entity_id
                )
            )
            entity = event
            if event is not None:
                event.is_bookmarked = True
                event.bookmarked_at = datetime.now(UTC)
        else:
            entity = await self.session.scalar(
                select(Account).where(
                    Account.workspace_id == workspace_id,
                    Account.id == payload.entity_id,
                )
            )
        if entity is None:
            raise ValueError("topic source entity does not exist")
        title = str(
            getattr(entity, "title", None)
            or getattr(entity, "display_name", None)
            or f"{payload.entity_type} {payload.entity_id}"
        )
        self.session.add(
            SavedTopic(
                id=uuid4(),
                workspace_id=workspace_id,
                created_by=rule.created_by,
                title=title,
                summary=getattr(entity, "summary", None) or getattr(entity, "description", None),
                source_type=source_type,
                source_id=payload.entity_id,
                status="inbox",
                priority=min(100, max(0, rule.priority // 10)),
                notes=f"由自动化规则“{rule.name}”创建",
                metadata_json={
                    "source_kind": payload.source_kind,
                    "source_entity_type": payload.entity_type,
                    "rule_id": str(rule.id),
                },
            )
        )

    async def _save_content(
        self, workspace_id: UUID, payload: AutomationEvaluateRequest, rule: AutomationRule
    ) -> None:
        if payload.entity_type != "content":
            raise ValueError("save_content only supports content entities")
        content = await self.session.scalar(
            select(ContentItem).where(
                ContentItem.workspace_id == workspace_id, ContentItem.id == payload.entity_id
            )
        )
        if content is None:
            raise ValueError("content entity does not exist")
        content.metadata_json = {
            **content.metadata_json,
            "saved_by_automation": True,
            "saved_by_rule_id": str(rule.id),
        }

    async def list_evaluations(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        rule_id: UUID | None,
        matched: bool | None,
        evaluated_from: datetime | None = None,
    ) -> AutomationEvaluationPage:
        items, total = await self.repo.list_evaluations(
            workspace_id,
            page=page,
            page_size=page_size,
            rule_id=rule_id,
            matched=matched,
            evaluated_from=evaluated_from,
        )
        return AutomationEvaluationPage(
            items=[AutomationEvaluationRead.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def list_channels(self, workspace_id: UUID) -> list[NotificationChannelRead]:
        return [
            NotificationChannelRead.model_validate(item)
            for item in await self.repo.list_channels(workspace_id)
        ]

    async def create_channel(
        self, workspace_id: UUID, actor_id: UUID, payload: NotificationChannelCreate
    ) -> NotificationChannelRead:
        provider = self._notification_provider(payload.provider_key)
        try:
            await provider.validate_config(payload.config)
        except (NotificationProviderError, ValueError) as exc:
            raise AutomationError(
                str(exc), code="notification_config_invalid", status_code=422
            ) from exc
        channel = NotificationChannel(
            id=uuid4(),
            workspace_id=workspace_id,
            provider_key=provider.key,
            name=payload.name,
            config_encrypted=self.cipher.encrypt(payload.config),
            config_masked=mask_notification_config(payload.config),
            enabled=payload.enabled,
            last_tested_at=None,
            health_status="unknown",
        )
        self.session.add(channel)
        self._audit(
            workspace_id,
            actor_id,
            "notification_channel.created",
            "notification_channel",
            channel.id,
        )
        await self.session.commit()
        await self.session.refresh(channel)
        return NotificationChannelRead.model_validate(channel)

    async def update_channel(
        self,
        workspace_id: UUID,
        channel_id: UUID,
        actor_id: UUID,
        payload: NotificationChannelUpdate,
    ) -> NotificationChannelRead:
        channel = await self._channel(workspace_id, channel_id)
        if payload.config is not None:
            provider = self._notification_provider(channel.provider_key)
            current_config = self.cipher.decrypt(channel.config_encrypted)
            secret_keys = {field.key for field in provider.config_fields if field.secret}
            updates = {
                key: value
                for key, value in payload.config.items()
                if not (key in secret_keys and isinstance(value, str) and value in {"", "••••••••"})
            }
            merged_config = {**current_config, **updates}
            try:
                await provider.validate_config(merged_config)
            except (NotificationProviderError, ValueError) as exc:
                raise AutomationError(
                    str(exc), code="notification_config_invalid", status_code=422
                ) from exc
            channel.config_encrypted = self.cipher.encrypt(merged_config)
            channel.config_masked = mask_notification_config(merged_config)
            channel.health_status = "unknown"
        if payload.name is not None:
            channel.name = payload.name
        if payload.enabled is not None:
            channel.enabled = payload.enabled
        self._audit(
            workspace_id,
            actor_id,
            "notification_channel.updated",
            "notification_channel",
            channel.id,
        )
        await self.session.commit()
        await self.session.refresh(channel)
        return NotificationChannelRead.model_validate(channel)

    async def delete_channel(self, workspace_id: UUID, channel_id: UUID, actor_id: UUID) -> None:
        channel = await self._channel(workspace_id, channel_id)
        delivery_exists = await self.session.scalar(
            select(NotificationDelivery.id)
            .where(NotificationDelivery.channel_id == channel.id)
            .limit(1)
        )
        if delivery_exists is not None:
            channel.enabled = False
            await self.session.commit()
            raise AutomationConflict(
                "已有投递历史的渠道已停用但不能删除", "notification_channel_has_history"
            )
        self._audit(
            workspace_id,
            actor_id,
            "notification_channel.deleted",
            "notification_channel",
            channel.id,
        )
        await self.session.delete(channel)
        await self.session.commit()

    async def test_channel(
        self,
        workspace_id: UUID,
        channel_id: UUID,
        payload: NotificationTestRequest,
    ) -> NotificationDeliveryRead:
        channel = await self._channel(workspace_id, channel_id)
        if not channel.enabled:
            raise AutomationConflict("通知渠道已停用", "notification_channel_disabled")
        delivery = NotificationDelivery(
            id=uuid4(),
            workspace_id=workspace_id,
            channel_id=channel.id,
            rule_id=None,
            entity_type="notification_channel",
            entity_id=channel.id,
            payload={
                "title": payload.title,
                "body": payload.body,
                "url": None,
                "data": {"test": True},
            },
            status="queued",
            attempts=0,
            sent_at=None,
            error=None,
            idempotency_key=f"channel-test:{channel.id}:{uuid4()}",
            provider_message_id=None,
        )
        self.session.add(delivery)
        await self.session.commit()
        try:
            return await self.send_delivery(delivery.id)
        except NotificationProviderError:
            failed = await self.session.get(NotificationDelivery, delivery.id)
            if failed is None:
                raise AutomationNotFound("通知投递不存在") from None
            return NotificationDeliveryRead.model_validate(failed)

    async def send_delivery(self, delivery_id: UUID) -> NotificationDeliveryRead:
        delivery = await self.session.get(NotificationDelivery, delivery_id)
        if delivery is None:
            raise AutomationNotFound("通知投递不存在")
        if delivery.status == "delivered":
            return NotificationDeliveryRead.model_validate(delivery)
        claim = cast(
            CursorResult[Any],
            await self.session.execute(
                update(NotificationDelivery)
                .where(
                    NotificationDelivery.id == delivery_id,
                    NotificationDelivery.status.in_(("queued", "failed")),
                )
                .values(
                    status="sending",
                    attempts=NotificationDelivery.attempts + 1,
                )
            ),
        )
        await self.session.commit()
        if claim.rowcount != 1:
            await self.session.refresh(delivery)
            return NotificationDeliveryRead.model_validate(delivery)
        await self.session.refresh(delivery)
        channel = await self._channel(delivery.workspace_id, delivery.channel_id)
        provider = self._notification_provider(channel.provider_key)
        config = self.cipher.decrypt(channel.config_encrypted)

        # Create per-attempt record
        attempt_started = datetime.now(UTC)
        attempt_record = NotificationDeliveryAttempt(
            id=uuid4(),
            delivery_id=delivery.id,
            workspace_id=delivery.workspace_id,
            channel_id=channel.id,
            attempt_number=delivery.attempts,
            status="failed",
            provider_key=channel.provider_key,
            provider_message_id=None,
            started_at=attempt_started,
            finished_at=None,
            duration_ms=None,
            error_code=None,
            error_detail_safe=None,
            retryable=None,
            request_summary={"title": str(delivery.payload.get("title", ""))[:100]},
            response_summary=None,
        )
        self.session.add(attempt_record)
        await self.session.flush()

        try:
            receipt = await provider.send(
                config,
                NotificationMessage(
                    title=str(delivery.payload.get("title", "Sports Intelligence OS 通知")),
                    body=str(delivery.payload.get("body", "")),
                    url=cast(str | None, delivery.payload.get("url")),
                    data=cast(dict[str, Any], delivery.payload.get("data", {})),
                ),
                idempotency_key=delivery.idempotency_key,
            )
        except NotificationProviderError as exc:
            finished = datetime.now(UTC)
            attempt_record.status = "failed"
            attempt_record.finished_at = finished
            attempt_record.duration_ms = int((finished - attempt_started).total_seconds() * 1000)
            attempt_record.error_code = exc.code
            attempt_record.error_detail_safe = str(exc)[:500]
            attempt_record.retryable = exc.retryable
            # Also log to external_call_attempts
            self.session.add(
                build_external_call_attempt(
                    id=uuid4(),
                    workspace_id=delivery.workspace_id,
                    call_type="notification",
                    provider_key=channel.provider_key,
                    entity_type=delivery.entity_type,
                    entity_id=delivery.entity_id,
                    attempt_number=delivery.attempts,
                    status="failed",
                    target_url=None,
                    started_at=attempt_started,
                    finished_at=finished,
                    duration_ms=attempt_record.duration_ms,
                    http_status=None,
                    error_code=exc.code,
                    error_detail_safe=str(exc)[:500],
                    retryable=exc.retryable,
                    request_summary={"title": str(delivery.payload.get("title", ""))[:100]},
                    response_summary={"error_code": exc.code},
                )
            )
            delivery.status = "failed"
            delivery.error = {"code": exc.code, "detail": str(exc), "retryable": exc.retryable}
            channel.health_status = "degraded" if exc.retryable else "unhealthy"
            await self.session.commit()
            raise
        finished = datetime.now(UTC)
        attempt_record.status = "success"
        attempt_record.finished_at = finished
        attempt_record.duration_ms = int((finished - attempt_started).total_seconds() * 1000)
        attempt_record.provider_message_id = receipt.external_id
        attempt_record.response_summary = {"external_id": receipt.external_id}
        # Log to external_call_attempts
        self.session.add(
            build_external_call_attempt(
                id=uuid4(),
                workspace_id=delivery.workspace_id,
                call_type="notification",
                provider_key=channel.provider_key,
                entity_type=delivery.entity_type,
                entity_id=delivery.entity_id,
                attempt_number=delivery.attempts,
                status="success",
                target_url=None,
                started_at=attempt_started,
                finished_at=finished,
                duration_ms=attempt_record.duration_ms,
                http_status=None,
                error_code=None,
                error_detail_safe=None,
                retryable=None,
                request_summary={"title": str(delivery.payload.get("title", ""))[:100]},
                response_summary={"external_id": receipt.external_id},
            )
        )
        delivery.status = "delivered"
        delivery.sent_at = finished
        delivery.provider_message_id = receipt.external_id
        delivery.error = None
        channel.last_tested_at = (
            datetime.now(UTC) if delivery.rule_id is None else channel.last_tested_at
        )
        channel.health_status = "healthy"
        await self.session.commit()
        await self.session.refresh(delivery)
        return NotificationDeliveryRead.model_validate(delivery)

    async def list_deliveries(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        status: str | None,
        channel_id: UUID | None,
    ) -> NotificationDeliveryPage:
        items, total = await self.repo.list_deliveries(
            workspace_id,
            page=page,
            page_size=page_size,
            status=status,
            channel_id=channel_id,
        )
        return NotificationDeliveryPage(
            items=[NotificationDeliveryRead.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def _rule(self, workspace_id: UUID, rule_id: UUID) -> AutomationRule:
        rule = await self.repo.rule(workspace_id, rule_id)
        if rule is None:
            raise AutomationNotFound("自动化规则不存在")
        return rule

    async def _channel(self, workspace_id: UUID, channel_id: UUID) -> NotificationChannel:
        channel = await self.repo.channel(workspace_id, channel_id)
        if channel is None:
            raise AutomationNotFound("通知渠道不存在")
        return channel

    def _notification_provider(self, key: str) -> NotificationProvider:
        try:
            return self.notification_providers.get(key)
        except LookupError as exc:
            raise AutomationError(
                "通知 Provider 不存在", code="notification_provider_unknown", status_code=422
            ) from exc

    @staticmethod
    def _generation_input_type(entity_type: str) -> str:
        return {"content": "content", "news": "event", "topic_event": "event"}.get(
            entity_type, "user_text"
        )

    @staticmethod
    def _validate_tree(tree: dict[str, Any], entity_type: str) -> None:
        try:
            validate_condition_tree(tree, entity_type)
        except ConditionValidationError as exc:
            raise AutomationError(str(exc), code="condition_tree_invalid", status_code=422) from exc

    @staticmethod
    def _validate_action(action_type: str, config: dict[str, Any], *, enabled: bool) -> None:
        if _contains_secret_key(config):
            raise AutomationError(
                "动作配置不能保存密钥；请改用加密通知渠道",
                code="action_secret_not_allowed",
                status_code=422,
            )
        if not enabled:
            return
        if action_type in {"notification", "webhook", "external_api"}:
            try:
                UUID(str(config.get("channel_id")))
            except (ValueError, TypeError) as exc:
                raise AutomationError(
                    "通知动作必须选择 channel_id",
                    code="notification_channel_required",
                    status_code=422,
                ) from exc
        if action_type == "notification" and config.get("template_id"):
            try:
                UUID(str(config.get("template_id")))
            except (ValueError, TypeError) as exc:
                raise AutomationError(
                    "通知动作必须选择已发布的 template_id",
                    code="notification_template_required",
                    status_code=422,
                ) from exc
        if action_type == "create_generation":
            try:
                UUID(str(config.get("workflow_id")))
            except (ValueError, TypeError) as exc:
                raise AutomationError(
                    "生成动作必须选择 workflow_id",
                    code="generation_workflow_required",
                    status_code=422,
                ) from exc

    async def _validate_action_references(
        self, workspace_id: UUID, action_type: str, config: dict[str, Any]
    ) -> None:
        if action_type in {"notification", "webhook", "external_api"}:
            channel = await self.repo.channel(workspace_id, UUID(str(config["channel_id"])))
            if channel is None or not channel.enabled:
                raise AutomationError(
                    "通知渠道不存在或已停用",
                    code="notification_channel_unavailable",
                    status_code=422,
                )
        if action_type == "notification" and config.get("template_id"):
            published = await self.session.scalar(
                select(NotificationTemplateVersion.id).where(
                    NotificationTemplateVersion.workspace_id == workspace_id,
                    NotificationTemplateVersion.template_id == UUID(str(config["template_id"])),
                    NotificationTemplateVersion.status == "published",
                )
            )
            if published is None:
                raise AutomationError(
                    "通知模板不存在或尚未发布",
                    code="notification_template_unavailable",
                    status_code=422,
                )

    @staticmethod
    def _has_pending_consecutive(explanation: dict[str, Any]) -> bool:
        if explanation.get("operator") == "consecutive_matches":
            return explanation.get("actual") is True and explanation.get("result") is False
        children = explanation.get("conditions")
        return isinstance(children, list) and any(
            AutomationService._has_pending_consecutive(item)
            for item in children
            if isinstance(item, dict)
        )

    @staticmethod
    def _safe_error(exc: Exception) -> dict[str, Any]:
        if isinstance(exc, (AutomationError, GenerationError, NotificationProviderError)):
            return {"code": getattr(exc, "code", "action_failed"), "detail": str(exc)}
        return {"code": "action_failed", "detail": str(exc)[:500]}

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        changes: dict[str, Any] | None = None,
        *,
        status: str = "success",
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        self.session.add(
            build_audit_entry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                before_hash=None,
                after_hash=(
                    hashlib.sha256(
                        json.dumps(changes, default=str, sort_keys=True).encode()
                    ).hexdigest()
                    if changes
                    else None
                ),
                change_summary_json=changes or {},
                reason=None,
                ip_hash=None,
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
                status=status,
                error_code=error_code,
                error_detail=error_detail,
            )
        )


class _SafeFormat(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _contains_secret_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).casefold()
            if any(part in lowered for part in ("password", "secret", "token", "api_key")):
                return True
            if _contains_secret_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_key(item) for item in value)
    return False
