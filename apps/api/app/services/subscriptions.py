"""Subscription alert evaluation and durable notification queueing."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import NotificationChannel, NotificationDelivery
from app.models.monitoring import Account
from app.models.subscription import SubscriptionEvent, SubscriptionRule
from app.schemas.subscription import (
    SubscriptionEvaluateRequest,
    SubscriptionEventPage,
    SubscriptionEventRead,
    SubscriptionRuleCreate,
    SubscriptionRulePage,
    SubscriptionRuleRead,
    SubscriptionRuleUpdate,
)
from app.services.audit import build_audit_entry


class SubscriptionError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class SubscriptionNotFound(SubscriptionError):
    def __init__(self, message: str = "订阅不存在") -> None:
        super().__init__(message, code="subscription_not_found", status_code=404)


class SubscriptionConflict(SubscriptionError):
    def __init__(self, message: str, code: str = "subscription_conflict") -> None:
        super().__init__(message, code=code, status_code=409)


class SubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_rules(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        enabled: bool | None,
    ) -> SubscriptionRulePage:
        conditions = [SubscriptionRule.workspace_id == workspace_id]
        if enabled is not None:
            conditions.append(SubscriptionRule.enabled == enabled)
        items = list(
            (
                await self.session.scalars(
                    select(SubscriptionRule)
                    .where(*conditions)
                    .order_by(SubscriptionRule.priority, SubscriptionRule.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(SubscriptionRule).where(*conditions)
            )
            or 0
        )
        return SubscriptionRulePage(
            items=[SubscriptionRuleRead.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_rule(self, workspace_id: UUID, rule_id: UUID) -> SubscriptionRuleRead:
        rule = await self._rule(workspace_id, rule_id)
        return SubscriptionRuleRead.model_validate(rule)

    async def create_rule(
        self, workspace_id: UUID, actor_id: UUID, payload: SubscriptionRuleCreate
    ) -> SubscriptionRuleRead:
        await self._validate_references(
            workspace_id,
            payload.platform_id,
            payload.account_id,
            payload.channel_ids,
        )
        duplicate = await self.session.scalar(
            select(SubscriptionRule.id).where(
                SubscriptionRule.workspace_id == workspace_id,
                SubscriptionRule.name == payload.name,
            )
        )
        if duplicate is not None:
            raise SubscriptionConflict("同一工作区内订阅名称不能重复", "subscription_name_exists")
        rule = SubscriptionRule(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=actor_id,
            name=payload.name,
            description=payload.description,
            trigger_type=payload.trigger_type,
            platform_id=payload.platform_id,
            account_id=payload.account_id,
            keywords=payload.keywords,
            thresholds=payload.thresholds,
            channel_ids=[str(item) for item in payload.channel_ids],
            cooldown_seconds=payload.cooldown_seconds,
            priority=payload.priority,
            enabled=payload.enabled,
        )
        self.session.add(rule)
        self._audit(workspace_id, actor_id, "subscription.created", rule.id)
        await self.session.commit()
        await self.session.refresh(rule)
        return SubscriptionRuleRead.model_validate(rule)

    async def update_rule(
        self,
        workspace_id: UUID,
        rule_id: UUID,
        actor_id: UUID,
        payload: SubscriptionRuleUpdate,
    ) -> SubscriptionRuleRead:
        rule = await self._rule(workspace_id, rule_id)
        changes = payload.model_dump(exclude_unset=True)
        candidate_trigger = changes.get("trigger_type", rule.trigger_type)
        candidate_keywords = changes.get("keywords", rule.keywords)
        candidate_thresholds = changes.get("thresholds", rule.thresholds)
        if candidate_trigger == "keyword_match" and not candidate_keywords:
            raise SubscriptionConflict(
                "关键词订阅至少需要一个关键词", "subscription_keywords_required"
            )
        if candidate_trigger == "metric_spike" and not candidate_thresholds:
            raise SubscriptionConflict(
                "指标突变订阅至少需要一个阈值", "subscription_thresholds_required"
            )
        platform_id = changes.get("platform_id", rule.platform_id)
        account_id = changes.get("account_id", rule.account_id)
        channel_ids = changes.get("channel_ids", [UUID(value) for value in rule.channel_ids])
        await self._validate_references(workspace_id, platform_id, account_id, channel_ids)
        if "channel_ids" in changes:
            changes["channel_ids"] = [str(item) for item in channel_ids]
        for field, value in changes.items():
            setattr(rule, field, value)
        self._audit(workspace_id, actor_id, "subscription.updated", rule.id, changes)
        await self.session.commit()
        await self.session.refresh(rule)
        return SubscriptionRuleRead.model_validate(rule)

    async def delete_rule(self, workspace_id: UUID, rule_id: UUID, actor_id: UUID) -> None:
        rule = await self._rule(workspace_id, rule_id)
        self._audit(workspace_id, actor_id, "subscription.deleted", rule.id)
        await self.session.delete(rule)
        await self.session.commit()

    async def list_events(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        subscription_id: UUID | None,
    ) -> SubscriptionEventPage:
        conditions = [SubscriptionEvent.workspace_id == workspace_id]
        if subscription_id is not None:
            conditions.append(SubscriptionEvent.subscription_id == subscription_id)
        items = list(
            (
                await self.session.scalars(
                    select(SubscriptionEvent)
                    .where(*conditions)
                    .order_by(SubscriptionEvent.evaluated_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(SubscriptionEvent).where(*conditions)
            )
            or 0
        )
        return SubscriptionEventPage(
            items=[SubscriptionEventRead.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def evaluate(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: SubscriptionEvaluateRequest,
    ) -> list[SubscriptionEventRead]:
        rules = list(
            (
                await self.session.scalars(
                    select(SubscriptionRule)
                    .where(
                        SubscriptionRule.workspace_id == workspace_id,
                        SubscriptionRule.enabled.is_(True),
                    )
                    .order_by(SubscriptionRule.priority, SubscriptionRule.created_at)
                )
            ).all()
        )
        results: list[SubscriptionEventRead] = []
        for rule in rules:
            if not self._target_matches(rule, payload):
                continue
            existing = await self.session.scalar(
                select(SubscriptionEvent).where(
                    SubscriptionEvent.workspace_id == workspace_id,
                    SubscriptionEvent.subscription_id == rule.id,
                    SubscriptionEvent.event_key == payload.event_key,
                )
            )
            if existing is not None:
                results.append(SubscriptionEventRead.model_validate(existing))
                continue
            matched, details = self._match_rule(rule, payload)
            now = datetime.now(UTC)
            status = "not_matched"
            delivery_ids: list[str] = []
            if matched and self._in_cooldown(rule, now):
                status = "suppressed"
                details["suppression"] = "cooldown_active"
            elif matched:
                delivery_ids, missing_channels = await self._queue_deliveries(
                    workspace_id, rule, payload, details
                )
                if delivery_ids and not missing_channels:
                    status = "queued"
                elif delivery_ids:
                    status = "partial"
                    details["missing_channel_ids"] = missing_channels
                else:
                    status = "failed"
                    details["failure"] = "no enabled notification channels available"
                if delivery_ids:
                    rule.last_triggered_at = now
            event = SubscriptionEvent(
                id=uuid4(),
                workspace_id=workspace_id,
                subscription_id=rule.id,
                event_key=payload.event_key,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                event_type=rule.trigger_type,
                evaluated_at=now,
                matched=matched,
                status=status,
                details={**details, "source_kind": payload.source_kind},
                delivery_ids=delivery_ids,
            )
            self.session.add(event)
            await self.session.flush()
            results.append(SubscriptionEventRead.model_validate(event))
        if rules:
            await self.session.commit()
        return results

    async def _queue_deliveries(
        self,
        workspace_id: UUID,
        rule: SubscriptionRule,
        payload: SubscriptionEvaluateRequest,
        details: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        channel_ids = self._uuid_list(rule.channel_ids)
        if not channel_ids:
            return [], []
        channels = list(
            (
                await self.session.scalars(
                    select(NotificationChannel).where(
                        NotificationChannel.workspace_id == workspace_id,
                        NotificationChannel.id.in_(channel_ids),
                        NotificationChannel.enabled.is_(True),
                    )
                )
            ).all()
        )
        channel_map = {channel.id: channel for channel in channels}
        missing = [str(channel_id) for channel_id in channel_ids if channel_id not in channel_map]
        safe_facts = _safe_facts(payload.facts)
        title = str(safe_facts.get("title") or safe_facts.get("headline") or payload.entity_type)
        body = (
            f"订阅「{rule.name}」命中：{_trigger_label(rule.trigger_type)}。"
            f"\n{title}\n{json.dumps(details, ensure_ascii=False, default=str)[:1500]}"
        )
        delivery_ids: list[str] = []
        for channel_id in channel_ids:
            if channel_id not in channel_map:
                continue
            delivery = NotificationDelivery(
                id=uuid4(),
                workspace_id=workspace_id,
                channel_id=channel_id,
                rule_id=None,
                subscription_id=rule.id,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                payload={
                    "title": f"订阅提醒：{rule.name}",
                    "body": body,
                    "subscription_id": str(rule.id),
                    "trigger_type": rule.trigger_type,
                    "source_kind": payload.source_kind,
                    "facts": safe_facts,
                },
                status="queued",
                attempts=0,
                error=None,
                idempotency_key=_idempotency_key(rule.id, payload.event_key, channel_id),
            )
            self.session.add(delivery)
            delivery_ids.append(str(delivery.id))
        return delivery_ids, missing

    async def _validate_references(
        self,
        workspace_id: UUID,
        platform_id: UUID | None,
        account_id: UUID | None,
        channel_ids: list[UUID],
    ) -> None:
        if account_id is not None:
            account = await self.session.scalar(
                select(Account).where(
                    Account.id == account_id,
                    Account.workspace_id == workspace_id,
                )
            )
            if account is None:
                raise SubscriptionConflict(
                    "订阅目标账号不存在或不属于当前工作区", "subscription_account_invalid"
                )
            if platform_id is not None and account.platform_id != platform_id:
                raise SubscriptionConflict(
                    "订阅平台与账号的平台不一致", "subscription_platform_mismatch"
                )
        if channel_ids:
            found = set(
                (
                    await self.session.scalars(
                        select(NotificationChannel.id).where(
                            NotificationChannel.workspace_id == workspace_id,
                            NotificationChannel.id.in_(channel_ids),
                        )
                    )
                ).all()
            )
            missing = [str(item) for item in channel_ids if item not in found]
            if missing:
                raise SubscriptionConflict(
                    "订阅包含不存在的通知渠道", "subscription_channel_invalid"
                )

    async def _rule(self, workspace_id: UUID, rule_id: UUID) -> SubscriptionRule:
        rule = await self.session.scalar(
            select(SubscriptionRule).where(
                SubscriptionRule.workspace_id == workspace_id,
                SubscriptionRule.id == rule_id,
            )
        )
        if rule is None:
            raise SubscriptionNotFound()
        return rule

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_id: UUID,
        changes: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            build_audit_entry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type="subscription_rule",
                resource_id=resource_id,
                change_summary_json=changes or {},
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )

    @staticmethod
    def _target_matches(rule: SubscriptionRule, payload: SubscriptionEvaluateRequest) -> bool:
        account_id = payload.facts.get("account_id")
        platform_id = payload.facts.get("platform_id")
        if rule.account_id is not None and str(rule.account_id) != str(
            account_id or payload.entity_id
        ):
            return False
        if rule.platform_id is not None and str(rule.platform_id) != str(platform_id):
            return False
        return True

    @staticmethod
    def _match_rule(
        rule: SubscriptionRule, payload: SubscriptionEvaluateRequest
    ) -> tuple[bool, dict[str, Any]]:
        if rule.trigger_type == "new_content":
            return bool(payload.facts.get("is_new")), {
                "reason": "new_content" if payload.facts.get("is_new") else "not_new"
            }
        if rule.trigger_type == "keyword_match":
            haystack = " ".join(
                str(payload.facts.get(key) or "")
                for key in ("title", "description", "text", "body", "headline")
            ).casefold()
            matched_keywords = [
                keyword for keyword in rule.keywords if keyword.casefold() in haystack
            ]
            return bool(matched_keywords), {"matched_keywords": matched_keywords}
        matched_metrics: dict[str, Any] = {}
        for metric, threshold in rule.thresholds.items():
            current = _number(payload.facts.get(metric))
            previous = _number(payload.previous.get(metric))
            if current is None:
                continue
            if _threshold_matches(current, previous, threshold):
                matched_metrics[metric] = {
                    "current": current,
                    "previous": previous,
                    "threshold": threshold,
                }
        return bool(matched_metrics), {"matched_metrics": matched_metrics}

    @staticmethod
    def _in_cooldown(rule: SubscriptionRule, now: datetime) -> bool:
        if not rule.last_triggered_at or not rule.cooldown_seconds:
            return False
        last = rule.last_triggered_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return last + timedelta(seconds=rule.cooldown_seconds) > now

    @staticmethod
    def _uuid_list(values: list[str]) -> list[UUID]:
        result: list[UUID] = []
        for value in values:
            try:
                result.append(UUID(str(value)))
            except (TypeError, ValueError):
                continue
        return result


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _threshold_matches(current: float, previous: float | None, threshold: Any) -> bool:
    if isinstance(threshold, dict):
        absolute = _number(threshold.get("absolute", threshold.get("min")))
        increase = _number(threshold.get("increase"))
        rate = _number(threshold.get("rate"))
        if absolute is not None and current < absolute:
            return False
        if increase is not None and (previous is None or current - previous < increase):
            return False
        if rate is not None:
            if previous is None or previous <= 0 or current / previous < rate:
                return False
        return any(item is not None for item in (absolute, increase, rate))
    simple = _number(threshold)
    return simple is not None and current >= simple


def _safe_facts(facts: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "title",
        "headline",
        "platform_key",
        "account_id",
        "content_id",
        "view_count",
        "like_count",
        "comment_count",
        "share_count",
        "favorite_count",
        "heat_score",
        "sport",
        "league",
    }
    return {key: value for key, value in facts.items() if key in allowed}


def _idempotency_key(subscription_id: UUID, event_key: str, channel_id: UUID) -> str:
    digest = hashlib.sha256(event_key.encode()).hexdigest()[:32]
    return f"subscription:{subscription_id}:{channel_id}:{digest}"


def _trigger_label(trigger_type: str) -> str:
    return {
        "new_content": "新作品",
        "keyword_match": "关键词命中",
        "metric_spike": "指标突变",
    }.get(trigger_type, trigger_type)
