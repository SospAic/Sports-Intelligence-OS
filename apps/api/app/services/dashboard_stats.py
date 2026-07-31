from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import (
    AutomationEvaluation,
    AutomationRule,
    NotificationChannel,
    NotificationDelivery,
)
from app.models.generation import GenerationRun
from app.models.monitoring import Account, ContentItem, Platform
from app.models.news import Article, TopicEvent
from app.models.operations import DashboardStat
from app.models.sync import SyncRun

ALL_STAT_KEYS: tuple[str, ...] = (
    "account_counts",
    "content_counts",
    "sync_stats",
    "news_stats",
    "generation_stats",
    "automation_stats",
    "notification_stats",
)


class DashboardStatsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def calculate_stats(self, workspace_id: UUID) -> dict[str, Any]:
        """Compute and upsert all dashboard stats for *workspace_id*."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=24)

        results: dict[str, Any] = {
            "account_counts": await self._account_counts(workspace_id, cutoff),
            "content_counts": await self._content_counts(workspace_id, cutoff),
            "sync_stats": await self._sync_stats(workspace_id, now, cutoff),
            "news_stats": await self._news_stats(workspace_id, cutoff),
            "generation_stats": await self._generation_stats(workspace_id, cutoff),
            "automation_stats": await self._automation_stats(workspace_id, cutoff),
            "notification_stats": await self._notification_stats(workspace_id, cutoff),
        }

        for stat_key, stat_value in results.items():
            await self._upsert_stat(workspace_id, stat_key, stat_value, now)

        await self._session.commit()
        return results

    async def get_stats(self, workspace_id: UUID) -> dict[str, Any]:
        """Return a complete cache, recalculating when missing or older than 5 minutes."""
        rows = (
            await self._session.scalars(
                select(DashboardStat).where(
                    DashboardStat.workspace_id == workspace_id,
                    DashboardStat.period == "current",
                )
            )
        ).all()
        now = datetime.now(UTC)
        stale_before = now - timedelta(minutes=5)
        if len(rows) != len(ALL_STAT_KEYS) or any(
            (
                row.calculated_at.replace(tzinfo=UTC)
                if row.calculated_at.tzinfo is None
                else row.calculated_at.astimezone(UTC)
            )
            < stale_before
            for row in rows
        ):
            return await self.calculate_stats(workspace_id)
        return {row.stat_key: row.stat_value for row in rows}

    async def get_stat(
        self, workspace_id: UUID, stat_key: str, period: str = "current"
    ) -> dict[str, Any] | None:
        """Return a specific stat row, or *None* when it does not exist."""
        row = await self._session.scalar(
            select(DashboardStat).where(
                DashboardStat.workspace_id == workspace_id,
                DashboardStat.stat_key == stat_key,
                DashboardStat.period == period,
            )
        )
        return row.stat_value if row is not None else None

    # ------------------------------------------------------------------
    # Stat calculators (private)
    # ------------------------------------------------------------------

    async def _account_counts(self, workspace_id: UUID, cutoff: datetime) -> dict[str, Any]:
        ws_filter = Account.workspace_id == workspace_id

        total = int(
            await self._session.scalar(
                select(func.count()).select_from(Account).where(ws_filter)
            )
            or 0
        )

        active = int(
            await self._session.scalar(
                select(func.count())
                .select_from(Account)
                .where(
                    ws_filter,
                    Account.is_active.is_(True),
                )
            )
            or 0
        )
        synced_24h = int(
            await self._session.scalar(
                select(func.count())
                .select_from(Account)
                .where(
                    ws_filter,
                    Account.is_active.is_(True),
                    Account.last_synced_at >= cutoff,
                )
            )
            or 0
        )

        platform_rows = (
            await self._session.execute(
                select(Platform.key, func.count(Account.id))
                .join(Account, Account.platform_id == Platform.id)
                .where(ws_filter, Account.is_active.is_(True))
                .group_by(Platform.key)
            )
        ).all()

        return {
            "total": total,
            "active": active,
            "synced_24h": synced_24h,
            "by_platform": {key: count for key, count in platform_rows},
        }

    async def _content_counts(self, workspace_id: UUID, cutoff: datetime) -> dict[str, Any]:
        ws_filter = ContentItem.workspace_id == workspace_id

        total = int(
            await self._session.scalar(
                select(func.count()).select_from(ContentItem).where(ws_filter)
            )
            or 0
        )

        new_24h = int(
            await self._session.scalar(
                select(func.count())
                .select_from(ContentItem)
                .where(ws_filter, ContentItem.first_seen_at >= cutoff)
            )
            or 0
        )

        platform_rows = (
            await self._session.execute(
                select(Platform.key, func.count(ContentItem.id))
                .join(ContentItem, ContentItem.platform_id == Platform.id)
                .where(ws_filter)
                .group_by(Platform.key)
            )
        ).all()

        return {
            "total": total,
            "new_24h": new_24h,
            "by_platform": {key: count for key, count in platform_rows},
        }

    async def _sync_stats(
        self, workspace_id: UUID, now: datetime, cutoff: datetime
    ) -> dict[str, Any]:
        ws_filter = SyncRun.workspace_id == workspace_id
        recent = [ws_filter, SyncRun.started_at >= cutoff]

        successful = int(
            await self._session.scalar(
                select(func.count())
                .select_from(SyncRun)
                .where(*recent, SyncRun.status.in_(["success", "degraded"]))
            )
            or 0
        )

        failed = int(
            await self._session.scalar(
                select(func.count())
                .select_from(SyncRun)
                .where(*recent, SyncRun.status == "error")
            )
            or 0
        )

        next_scheduled = await self._session.scalar(
            select(func.min(Account.next_sync_at)).where(
                Account.workspace_id == workspace_id,
                Account.is_active.is_(True),
                Account.next_sync_at > now,
            )
        )

        return {
            "successful_24h": successful,
            "failed_24h": failed,
            "next_scheduled_at": next_scheduled.isoformat() if next_scheduled else None,
        }

    async def _news_stats(self, workspace_id: UUID, cutoff: datetime) -> dict[str, Any]:
        article_filter = Article.workspace_id == workspace_id

        total_articles = int(
            await self._session.scalar(
                select(func.count()).select_from(Article).where(article_filter)
            )
            or 0
        )

        new_articles_24h = int(
            await self._session.scalar(
                select(func.count())
                .select_from(Article)
                .where(article_filter, Article.published_at >= cutoff)
            )
            or 0
        )

        event_filter = TopicEvent.workspace_id == workspace_id

        total_events = int(
            await self._session.scalar(
                select(func.count()).select_from(TopicEvent).where(event_filter)
            )
            or 0
        )

        hot_events = int(
            await self._session.scalar(
                select(func.count())
                .select_from(TopicEvent)
                .where(
                    event_filter,
                    TopicEvent.heat_score > 70,
                    TopicEvent.last_update_time >= cutoff,
                )
            )
            or 0
        )

        return {
            "total_articles": total_articles,
            "new_articles_24h": new_articles_24h,
            "total_events": total_events,
            "hot_events": hot_events,
        }

    async def _generation_stats(self, workspace_id: UUID, cutoff: datetime) -> dict[str, Any]:
        ws_filter = GenerationRun.workspace_id == workspace_id
        recent = [ws_filter, GenerationRun.created_at >= cutoff]

        total = int(
            await self._session.scalar(
                select(func.count()).select_from(GenerationRun).where(ws_filter)
            )
            or 0
        )

        completed_24h = int(
            await self._session.scalar(
                select(func.count())
                .select_from(GenerationRun)
                .where(*recent, GenerationRun.status == "completed")
            )
            or 0
        )

        failed_24h = int(
            await self._session.scalar(
                select(func.count())
                .select_from(GenerationRun)
                .where(*recent, GenerationRun.status == "failed")
            )
            or 0
        )

        duration_rows = (
            await self._session.execute(
                select(GenerationRun.started_at, GenerationRun.completed_at).where(
                *recent,
                GenerationRun.status == "completed",
                GenerationRun.started_at.isnot(None),
                GenerationRun.completed_at.isnot(None),
            )
            )
        ).all()
        durations = [
            (completed - started).total_seconds()
            for started, completed in duration_rows
            if started is not None and completed is not None
        ]
        avg_duration = sum(durations) / len(durations) if durations else None

        return {
            "total": total,
            "completed_24h": completed_24h,
            "failed_24h": failed_24h,
            "avg_duration_seconds": (
                round(float(avg_duration), 2) if avg_duration is not None else None
            ),
        }

    async def _automation_stats(self, workspace_id: UUID, cutoff: datetime) -> dict[str, Any]:
        rule_filter = AutomationRule.workspace_id == workspace_id

        enabled_rules = int(
            await self._session.scalar(
                select(func.count())
                .select_from(AutomationRule)
                .where(rule_filter, AutomationRule.enabled.is_(True))
            )
            or 0
        )

        eval_filter = AutomationEvaluation.workspace_id == workspace_id
        eval_recent = [eval_filter, AutomationEvaluation.evaluated_at >= cutoff]

        evaluations_24h = int(
            await self._session.scalar(
                select(func.count()).select_from(AutomationEvaluation).where(*eval_recent)
            )
            or 0
        )

        matched_24h = int(
            await self._session.scalar(
                select(func.count())
                .select_from(AutomationEvaluation)
                .where(*eval_recent, AutomationEvaluation.matched.is_(True))
            )
            or 0
        )

        return {
            "enabled_rules": enabled_rules,
            "evaluations_24h": evaluations_24h,
            "matched_24h": matched_24h,
        }

    async def _notification_stats(self, workspace_id: UUID, cutoff: datetime) -> dict[str, Any]:
        ws_filter = NotificationDelivery.workspace_id == workspace_id
        recent = [ws_filter, NotificationDelivery.created_at >= cutoff]

        total_24h = int(
            await self._session.scalar(
                select(func.count()).select_from(NotificationDelivery).where(*recent)
            )
            or 0
        )

        delivered_24h = int(
            await self._session.scalar(
                select(func.count())
                .select_from(NotificationDelivery)
                .where(*recent, NotificationDelivery.status == "delivered")
            )
            or 0
        )

        failed_24h = int(
            await self._session.scalar(
                select(func.count())
                .select_from(NotificationDelivery)
                .where(*recent, NotificationDelivery.status == "failed")
            )
            or 0
        )

        channel_rows = (
            await self._session.execute(
                select(
                    NotificationChannel.health_status,
                    func.count(NotificationChannel.id),
                )
                .where(
                    NotificationChannel.workspace_id == workspace_id,
                    NotificationChannel.enabled.is_(True),
                )
                .group_by(NotificationChannel.health_status)
            )
        ).all()

        return {
            "total_24h": total_24h,
            "delivered_24h": delivered_24h,
            "failed_24h": failed_24h,
            "channel_health": {status: count for status, count in channel_rows},
        }

    # ------------------------------------------------------------------
    # Persistence helper
    # ------------------------------------------------------------------

    async def _upsert_stat(
        self,
        workspace_id: UUID,
        stat_key: str,
        stat_value: dict[str, Any],
        now: datetime,
    ) -> None:
        existing = await self._session.scalar(
            select(DashboardStat).where(
                DashboardStat.workspace_id == workspace_id,
                DashboardStat.stat_key == stat_key,
                DashboardStat.period == "current",
            )
        )
        if existing is not None:
            existing.stat_value = stat_value
            existing.calculated_at = now
        else:
            self._session.add(
                DashboardStat(
                    workspace_id=workspace_id,
                    stat_key=stat_key,
                    stat_value=stat_value,
                    period="current",
                    calculated_at=now,
                )
            )
