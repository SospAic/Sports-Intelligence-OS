"""Derived SLO snapshots for operator-facing reliability evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import NotificationDeliveryAttempt
from app.models.inbox_queue import InboxQueueState
from app.models.operations import ExternalCallAttempt, TaskRun
from app.models.sync import SyncRun
from app.schemas.reliability import SloMetricRead, SloSummaryRead


class ReliabilitySloService:
    """Build bounded, auditable metrics from persisted operational records.

    These metrics intentionally describe this workspace's recorded activity. A
    healthy snapshot does not claim that a third-party platform or notification
    target is reachable when no corresponding live attempt was recorded.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def snapshot(self, workspace_id: UUID, *, window_minutes: int) -> SloSummaryRead:
        bounded_window = max(1, min(window_minutes, 10_080))
        generated_at = datetime.now(UTC)
        cutoff = generated_at - timedelta(minutes=bounded_window)

        sync_runs = list(
            (
                await self.session.scalars(
                    select(SyncRun)
                    .where(
                        SyncRun.workspace_id == workspace_id,
                        SyncRun.queued_at >= cutoff,
                    )
                    .order_by(SyncRun.queued_at.desc())
                    .limit(2_000)
                )
            ).all()
        )
        external_calls = list(
            (
                await self.session.scalars(
                    select(ExternalCallAttempt)
                    .where(
                        ExternalCallAttempt.workspace_id == workspace_id,
                        ExternalCallAttempt.started_at >= cutoff,
                    )
                    .order_by(ExternalCallAttempt.started_at.desc())
                    .limit(2_000)
                )
            ).all()
        )
        notification_attempts = list(
            (
                await self.session.scalars(
                    select(NotificationDeliveryAttempt)
                    .where(
                        NotificationDeliveryAttempt.workspace_id == workspace_id,
                        NotificationDeliveryAttempt.started_at >= cutoff,
                    )
                    .order_by(NotificationDeliveryAttempt.started_at.desc())
                    .limit(2_000)
                )
            ).all()
        )
        task_runs = list(
            (
                await self.session.scalars(
                    select(TaskRun)
                    .where(
                        TaskRun.scheduled_at >= cutoff,
                        or_(TaskRun.workspace_id == workspace_id, TaskRun.workspace_id.is_(None)),
                    )
                    .order_by(TaskRun.scheduled_at.desc())
                    .limit(2_000)
                )
            ).all()
        )
        queue_states = list(
            (
                await self.session.scalars(
                    select(InboxQueueState)
                    .where(
                        InboxQueueState.workspace_id == workspace_id,
                        InboxQueueState.updated_at >= cutoff,
                    )
                    .order_by(InboxQueueState.updated_at.desc())
                    .limit(2_000)
                )
            ).all()
        )

        metrics = [
            self._metric(
                "sync_runs",
                sync_runs,
                success_statuses={"success"},
                failure_statuses={"error", "degraded", "cancelled"},
                active_statuses={"queued", "running"},
                timestamp=lambda item: item.queued_at,
                duration=lambda item: _duration_ms(item.started_at, item.finished_at),
                note="只统计已持久化的同步运行，不代表未配置凭证的平台可用性。",
            ),
            self._metric(
                "external_calls",
                external_calls,
                success_statuses={"success"},
                failure_statuses={"failed", "timeout"},
                active_statuses=set(),
                timestamp=lambda item: item.started_at,
                duration=lambda item: item.duration_ms,
                note="仅包含已经记录的外部调用；没有调用记录不会被推断为成功。",
            ),
            self._metric(
                "notification_attempts",
                notification_attempts,
                success_statuses={"success"},
                failure_statuses={"failed", "timeout"},
                active_statuses=set(),
                timestamp=lambda item: item.started_at,
                duration=lambda item: item.duration_ms,
                note="通知成功率只代表投递尝试，不等同于第三方阅读或业务处理成功。",
            ),
            self._metric(
                "task_runs",
                task_runs,
                success_statuses={"success", "completed"},
                failure_statuses={"failed", "error"},
                active_statuses={"queued", "running"},
                timestamp=lambda item: item.scheduled_at,
                duration=lambda item: _duration_ms(item.started_at, item.finished_at),
                note="包含工作区任务及系统级任务；指标来自 TaskRun 持久化记录。",
            ),
            self._metric(
                "inbox_queue",
                queue_states,
                success_statuses={"completed"},
                failure_statuses=set(),
                active_statuses={"open", "in_progress"},
                timestamp=lambda item: item.updated_at,
                duration=lambda _item: None,
                note="队列项不是外部调用；该指标用于观察内部处理积压。",
            ),
        ]
        return SloSummaryRead(
            window_minutes=bounded_window,
            generated_at=generated_at,
            metrics=metrics,
        )

    @staticmethod
    def _metric(
        key: str,
        rows: list[Any],
        *,
        success_statuses: set[str],
        failure_statuses: set[str],
        active_statuses: set[str],
        timestamp: Any,
        duration: Any,
        note: str,
    ) -> SloMetricRead:
        successes = sum(1 for row in rows if str(row.status) in success_statuses)
        failures = sum(1 for row in rows if str(row.status) in failure_statuses)
        in_progress = sum(1 for row in rows if str(row.status) in active_statuses)
        durations = [value for value in (duration(row) for row in rows) if value is not None]
        outcomes = successes + failures
        timestamps = [value for value in (timestamp(row) for row in rows) if value is not None]
        notes = [note]
        if not rows:
            notes.append("窗口内没有可用记录；未使用模拟数据补齐。")
        return SloMetricRead(
            key=key,
            observations=len(rows),
            successes=successes,
            failures=failures,
            in_progress=in_progress,
            success_rate=round(successes / outcomes, 4) if outcomes else None,
            average_latency_ms=(round(sum(durations) / len(durations), 2) if durations else None),
            latest_at=max(timestamps) if timestamps else None,
            notes=notes,
        )


def _duration_ms(started_at: datetime | None, finished_at: datetime | None) -> float | None:
    if started_at is None or finished_at is None:
        return None
    return max(0.0, (finished_at - started_at).total_seconds() * 1000)
