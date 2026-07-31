import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.models.automation import AutomationRule, NotificationDelivery
from app.models.monitoring import (
    Account,
    AccountSnapshot,
    ContentItem,
    ContentSnapshot,
    DerivedMetric,
    Platform,
)
from app.models.news import Article, EventArticle, TopicEvent
from app.models.workspace import WorkspaceMembership
from app.providers.llm.registry import build_llm_provider_registry
from app.providers.notifications.base import NotificationProviderError
from app.providers.notifications.registry import build_notification_provider_registry
from app.schemas.automation import AutomationEvaluateRequest
from app.services.automation import AutomationService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _send(delivery_id: UUID) -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    notification_providers = build_notification_provider_registry(settings)
    llm_providers = build_llm_provider_registry(settings)
    try:
        async with session_factory() as session:
            await AutomationService(
                session, settings, notification_providers, llm_providers
            ).send_delivery(delivery_id)
    finally:
        for provider in (*notification_providers.values(), *llm_providers.values()):
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="app.tasks.automation.send_notification",
    max_retries=3,
)
def send_notification(self: object, delivery_id: str) -> None:
    try:
        asyncio.run(_send(UUID(delivery_id)))
    except NotificationProviderError as exc:
        if exc.retryable and hasattr(self, "retry"):
            raise self.retry(exc=exc, countdown=30) from exc
        raise


async def _queued_delivery_ids() -> list[UUID]:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            stale_before = datetime.now(UTC) - timedelta(seconds=settings.task_stale_after_seconds)
            await session.execute(
                update(NotificationDelivery)
                .where(
                    NotificationDelivery.status == "sending",
                    NotificationDelivery.updated_at < stale_before,
                )
                .values(
                    status="failed",
                    error={
                        "code": "stale_delivery_recovered",
                        "detail": "Delivery exceeded its execution lease and was released",
                        "retryable": True,
                    },
                )
            )
            await session.commit()
            deliveries = list(
                (
                    await session.scalars(
                        select(NotificationDelivery)
                        .where(
                            or_(
                                NotificationDelivery.status == "queued",
                                (
                                    (NotificationDelivery.status == "failed")
                                    & (
                                        NotificationDelivery.attempts
                                        < settings.notification_request_max_attempts
                                    )
                                ),
                            )
                        )
                        .order_by(NotificationDelivery.created_at)
                        .limit(100)
                    )
                ).all()
            )
            return [
                delivery.id
                for delivery in deliveries
                if delivery.status == "queued"
                or bool((delivery.error or {}).get("retryable", False))
            ]
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.automation.dispatch_queued_notifications")  # type: ignore[untyped-decorator]
def dispatch_queued_notifications() -> int:
    delivery_ids = asyncio.run(_queued_delivery_ids())
    for delivery_id in delivery_ids:
        send_notification.delay(str(delivery_id))
    return len(delivery_ids)


def _json_number(value: int | Decimal | None) -> int | float | None:
    if isinstance(value, Decimal):
        return float(value)
    return value


async def _metric_facts(
    session: AsyncSession, workspace_id: UUID, entity_type: str, entity_id: UUID
) -> dict[str, float]:
    rows = list(
        (
            await session.scalars(
                select(DerivedMetric)
                .where(
                    DerivedMetric.workspace_id == workspace_id,
                    DerivedMetric.entity_type == entity_type,
                    DerivedMetric.entity_id == entity_id,
                )
                .order_by(DerivedMetric.calculated_at.desc())
            )
        ).all()
    )
    facts: dict[str, float] = {}
    for metric in rows:
        facts.setdefault(metric.metric_key, float(metric.value))
    return facts


async def _scan_recent_entities() -> int:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    notification_providers = build_notification_provider_registry(settings)
    llm_providers = build_llm_provider_registry(settings)
    processed = 0
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    try:
        async with session_factory() as session:
            active_workspaces = list(
                (
                    await session.scalars(
                        select(AutomationRule.workspace_id)
                        .where(AutomationRule.enabled.is_(True))
                        .distinct()
                    )
                ).all()
            )
            service = AutomationService(session, settings, notification_providers, llm_providers)
            for workspace_id in active_workspaces:
                actor_id = await session.scalar(
                    select(WorkspaceMembership.user_id)
                    .where(
                        WorkspaceMembership.workspace_id == workspace_id,
                        WorkspaceMembership.status == "active",
                        WorkspaceMembership.role.in_(("owner", "admin", "editor")),
                    )
                    .order_by(WorkspaceMembership.joined_at)
                    .limit(1)
                )
                if actor_id is None:
                    continue
                content_rows = (
                    await session.execute(
                        select(ContentSnapshot, ContentItem, Platform)
                        .join(ContentItem, ContentItem.id == ContentSnapshot.content_item_id)
                        .join(Platform, Platform.id == ContentItem.platform_id)
                        .where(
                            ContentItem.workspace_id == workspace_id,
                            ContentSnapshot.captured_at >= cutoff,
                        )
                        .order_by(ContentSnapshot.captured_at.desc())
                        .limit(200)
                    )
                ).all()
                for snapshot, item, platform in content_rows:
                    facts: dict[str, Any] = {
                        "entity_id": str(item.id),
                        "view_count": snapshot.view_count,
                        "like_count": snapshot.like_count,
                        "comment_count": snapshot.comment_count,
                        "share_count": snapshot.share_count,
                        "favorite_count": snapshot.favorite_count,
                        "source_kind": snapshot.source_kind,
                        "platform_key": platform.key,
                        "title": item.title,
                    }
                    facts.update(
                        await _metric_facts(session, workspace_id, "content_item", item.id)
                    )
                    previous = await session.scalar(
                        select(ContentSnapshot)
                        .where(
                            ContentSnapshot.content_item_id == item.id,
                            ContentSnapshot.captured_at < snapshot.captured_at,
                        )
                        .order_by(ContentSnapshot.captured_at.desc())
                        .limit(1)
                    )
                    previous_facts = (
                        {
                            "view_count": previous.view_count,
                            "like_count": previous.like_count,
                            "comment_count": previous.comment_count,
                            "share_count": previous.share_count,
                            "favorite_count": previous.favorite_count,
                        }
                        if previous
                        else {}
                    )
                    await service.evaluate(
                        workspace_id,
                        actor_id,
                        AutomationEvaluateRequest(
                            entity_type="content",
                            entity_id=item.id,
                            facts=facts,
                            previous=previous_facts,
                            event_key=f"content_snapshot:{snapshot.id}",
                            source_kind=snapshot.source_kind,
                        ),
                    )
                    processed += 1

                account_rows = (
                    await session.execute(
                        select(AccountSnapshot, Account, Platform)
                        .join(Account, Account.id == AccountSnapshot.account_id)
                        .join(Platform, Platform.id == Account.platform_id)
                        .where(
                            Account.workspace_id == workspace_id,
                            AccountSnapshot.captured_at >= cutoff,
                        )
                        .order_by(AccountSnapshot.captured_at.desc())
                        .limit(100)
                    )
                ).all()
                for snapshot, account, platform in account_rows:
                    facts = {
                        "entity_id": str(account.id),
                        "follower_count": snapshot.follower_count,
                        "following_count": snapshot.following_count,
                        "total_like_count": snapshot.total_like_count,
                        "total_view_count": snapshot.total_view_count,
                        "video_count": snapshot.video_count,
                        "engagement_rate": _json_number(snapshot.engagement_rate),
                        "source_kind": snapshot.source_kind,
                        "platform_key": platform.key,
                    }
                    facts.update(await _metric_facts(session, workspace_id, "account", account.id))
                    await service.evaluate(
                        workspace_id,
                        actor_id,
                        AutomationEvaluateRequest(
                            entity_type="account",
                            entity_id=account.id,
                            facts=facts,
                            event_key=f"account_snapshot:{snapshot.id}",
                            source_kind=snapshot.source_kind,
                        ),
                    )
                    processed += 1

                events = list(
                    (
                        await session.scalars(
                            select(TopicEvent)
                            .where(
                                TopicEvent.workspace_id == workspace_id,
                                TopicEvent.last_update_time >= cutoff,
                            )
                            .order_by(TopicEvent.last_update_time.desc())
                            .limit(100)
                        )
                    ).all()
                )
                for event in events:
                    article_source_kinds = set(
                        (
                            await session.scalars(
                                select(Article.source_kind)
                                .join(EventArticle, EventArticle.article_id == Article.id)
                                .where(EventArticle.event_id == event.id)
                            )
                        ).all()
                    )
                    inferred_source_kind = "live" if "live" in article_source_kinds else "imported"
                    source_kind = str(event.metadata_json.get("source_kind", inferred_source_kind))
                    if source_kind not in {"live", "imported", "mock"}:
                        source_kind = "imported"
                    validated_source_kind = cast(Literal["live", "imported", "mock"], source_kind)
                    await service.evaluate(
                        workspace_id,
                        actor_id,
                        AutomationEvaluateRequest(
                            entity_type="news",
                            entity_id=event.id,
                            facts={
                                "entity_id": str(event.id),
                                "heat_score": float(event.heat_score),
                                "source_count": event.source_count,
                                "article_count": event.article_count,
                                "reliability_score": float(event.reliability_score),
                                "controversy_score": float(event.controversy_score),
                                "visual_score": float(event.visual_score),
                                "story_score": float(event.story_score),
                                "sport": event.sport,
                                "league": event.league,
                                "status": event.status,
                                "source_kind": source_kind,
                            },
                            event_key=(
                                f"topic_event:{event.id}:{event.last_update_time.isoformat()}"
                            ),
                            source_kind=validated_source_kind,
                        ),
                    )
                    processed += 1
    except Exception:
        logger.exception("automation_entity_scan_failed")
        raise
    finally:
        for provider in (*notification_providers.values(), *llm_providers.values()):
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()
    return processed


@celery_app.task(name="app.tasks.automation.scan_recent_entities")  # type: ignore[untyped-decorator]
def scan_recent_entities() -> int:
    return asyncio.run(_scan_recent_entities())
