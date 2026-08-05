from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation import GenerationRun
from app.models.news import NewsSyncRun
from app.models.operations import AuditEntry, SystemEvent, TaskRun
from app.models.sync import SyncRun
from app.schemas.monitoring import SyncRunRead
from app.schemas.operations import (
    AuditEntryPage,
    AuditEntryRead,
    OperationTaskPage,
    OperationTaskRead,
    SystemEventPage,
    SystemEventRead,
)
from app.services.error_detail import business_hint_for
from app.services.sync import cancel_sync_run

_TERMINAL_ERROR_STATUSES = frozenset({"error", "degraded", "skipped", "cancelled"})


def _operation_error_hint(
    status: str,
    *,
    code: str | None,
    message: str | None,
    detail: str | None,
    category: str | None = None,
    adapter_key: str | None = None,
    existing: str | None = None,
) -> str | None:
    """Return an operator hint only when a task actually has an error signal.

    ``business_hint_for(None)`` intentionally has a useful generic fallback for
    failures, but using it for every successful row makes the operations page
    look broken.  Keep the fallback for terminal error states with incomplete
    metadata while leaving queued/running/success rows clean.
    """

    has_error_fields = any((code, message, detail))
    if not has_error_fields and status not in _TERMINAL_ERROR_STATUSES:
        return None
    return existing or business_hint_for(code, adapter_key=adapter_key, category=category)


class UnsupportedTaskCancelError(Exception):
    """Raised when a task category does not support in-UI cancellation yet."""


class OperationsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def cancel_task(self, workspace_id: UUID, task_id: UUID, category: str) -> SyncRunRead:
        """Terminate a background task listed on the operations dashboard.

        Only ``platform_sync`` runs support in-UI cancellation today. Other
        categories (news_sync, generation, worker) raise
        :class:`UnsupportedTaskCancelError` rather than faking a success, per the
        project's no-fake-success rule.
        """
        if category == "platform_sync":
            return await cancel_sync_run(self.session, workspace_id, task_id)
        raise UnsupportedTaskCancelError(
            "该任务类型暂不支持在界面终止；当前仅平台同步（platform_sync）支持"
        )

    async def tasks(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        category: str | None,
        status: str | None,
    ) -> OperationTaskPage:
        records: list[OperationTaskRead] = []
        total = 0
        limit = min(page * page_size, 500)
        if category in (None, "worker"):
            filters: list[Any] = [TaskRun.workspace_id == workspace_id]
            if status:
                filters.append(TaskRun.status == status)
            total += int(
                await self.session.scalar(select(func.count()).select_from(TaskRun).where(*filters))
                or 0
            )
            for task_run in (
                await self.session.scalars(
                    select(TaskRun)
                    .where(*filters)
                    .order_by(TaskRun.scheduled_at.desc())
                    .limit(limit)
                )
            ).all():
                records.append(
                    OperationTaskRead(
                        id=task_run.id,
                        category="worker",
                        task_type=task_run.task_type,
                        status=task_run.status,
                        started_at=task_run.started_at or task_run.scheduled_at,
                        finished_at=task_run.finished_at,
                        error_code=task_run.error_code,
                        error_message=task_run.error_detail_safe,
                        error_detail=task_run.error_detail_safe,
                        error_hint=_operation_error_hint(
                            task_run.status,
                            code=task_run.error_code,
                            message=task_run.error_detail_safe,
                            detail=task_run.error_detail_safe,
                            category="worker",
                        ),
                        metadata=task_run.progress_json,
                    )
                )
        if category in (None, "platform_sync"):
            filters = [SyncRun.workspace_id == workspace_id]
            if status:
                filters.append(SyncRun.status == status)
            total += int(
                await self.session.scalar(select(func.count()).select_from(SyncRun).where(*filters))
                or 0
            )
            for sync_run in (
                await self.session.scalars(
                    select(SyncRun).where(*filters).order_by(SyncRun.queued_at.desc()).limit(limit)
                )
            ).all():
                records.append(
                    OperationTaskRead(
                        id=sync_run.id,
                        category="platform_sync",
                        task_type=f"{sync_run.adapter_key}:{sync_run.target_type}",
                        status=sync_run.status,
                        started_at=sync_run.started_at or sync_run.queued_at,
                        finished_at=sync_run.finished_at,
                        error_code=sync_run.error_code,
                        error_message=sync_run.error_message,
                        error_detail=sync_run.error_detail,
                        error_hint=_operation_error_hint(
                            sync_run.status,
                            code=sync_run.error_code,
                            message=sync_run.error_message,
                            detail=sync_run.error_detail,
                            adapter_key=sync_run.adapter_key,
                        ),
                        metadata=sync_run.metadata_json,
                    )
                )
        if category in (None, "news_sync"):
            filters = [NewsSyncRun.workspace_id == workspace_id]
            if status:
                filters.append(NewsSyncRun.status == status)
            total += int(
                await self.session.scalar(
                    select(func.count()).select_from(NewsSyncRun).where(*filters)
                )
                or 0
            )
            for news_run in (
                await self.session.scalars(
                    select(NewsSyncRun)
                    .where(*filters)
                    .order_by(NewsSyncRun.queued_at.desc())
                    .limit(limit)
                )
            ).all():
                records.append(
                    OperationTaskRead(
                        id=news_run.id,
                        category="news_sync",
                        task_type=news_run.provider_key,
                        status=news_run.status,
                        started_at=news_run.started_at or news_run.queued_at,
                        finished_at=news_run.finished_at,
                        error_code=news_run.error_code,
                        error_message=news_run.error_message,
                        error_detail=news_run.error_detail,
                        error_hint=_operation_error_hint(
                            news_run.status,
                            code=news_run.error_code,
                            message=news_run.error_message,
                            detail=news_run.error_detail,
                            category="news_sync",
                            existing=news_run.error_hint,
                        ),
                        metadata=news_run.metadata_json,
                    )
                )
        if category in (None, "generation"):
            filters = [GenerationRun.workspace_id == workspace_id]
            if status:
                filters.append(GenerationRun.status == status)
            total += int(
                await self.session.scalar(
                    select(func.count()).select_from(GenerationRun).where(*filters)
                )
                or 0
            )
            for generation_run in (
                await self.session.scalars(
                    select(GenerationRun)
                    .where(*filters)
                    .order_by(GenerationRun.created_at.desc())
                    .limit(limit)
                )
            ).all():
                error = generation_run.error or {}
                error_code = generation_run.error_code or (
                    str(error.get("code")) if error.get("code") else None
                )
                error_detail = generation_run.error_detail_safe or (
                    str(error.get("detail") or error.get("message")) if error else None
                )
                records.append(
                    OperationTaskRead(
                        id=generation_run.id,
                        category="generation",
                        task_type=generation_run.model,
                        status=generation_run.status,
                        started_at=generation_run.started_at or generation_run.created_at,
                        finished_at=generation_run.completed_at,
                        error_code=error_code,
                        error_message=error_detail,
                        error_detail=error_detail,
                        error_hint=_operation_error_hint(
                            generation_run.status,
                            code=error_code,
                            message=error_detail,
                            detail=error_detail,
                            existing=generation_run.error_hint,
                        ),
                        metadata={
                            "provider": generation_run.provider,
                            "input_type": generation_run.input_type,
                        },
                    )
                )
        records.sort(key=lambda item: _utc(item.started_at), reverse=True)
        start = (page - 1) * page_size
        return OperationTaskPage(
            items=records[start : start + page_size], page=page, page_size=page_size, total=total
        )

    async def events(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        severity: str | None,
        category: str | None,
    ) -> SystemEventPage:
        filters: list[Any] = [SystemEvent.workspace_id == workspace_id]
        if severity:
            filters.append(SystemEvent.severity == severity)
        if category:
            filters.append(SystemEvent.category == category)
        total = int(
            await self.session.scalar(select(func.count()).select_from(SystemEvent).where(*filters))
            or 0
        )
        items = (
            await self.session.scalars(
                select(SystemEvent)
                .where(*filters)
                .order_by(SystemEvent.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return SystemEventPage(
            items=[
                SystemEventRead(
                    id=item.id,
                    severity=item.severity,
                    category=item.category,
                    event_type=item.event_type,
                    message=item.message,
                    resource_type=item.resource_type,
                    resource_id=item.resource_id,
                    status=item.status,
                    error_code=item.error_code,
                    error_detail=item.error_detail,
                    error_hint=item.error_hint,
                    metadata=item.metadata_safe_json,
                    trace_id=item.trace_id,
                    created_at=item.created_at,
                )
                for item in items
            ],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def audits(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        action: str | None,
        resource_type: str | None,
    ) -> AuditEntryPage:
        filters: list[Any] = [AuditEntry.workspace_id == workspace_id]
        if action:
            filters.append(AuditEntry.action.ilike(f"%{action.strip()}%"))
        if resource_type:
            filters.append(AuditEntry.resource_type == resource_type)
        total = int(
            await self.session.scalar(select(func.count()).select_from(AuditEntry).where(*filters))
            or 0
        )
        items = (
            await self.session.scalars(
                select(AuditEntry)
                .where(*filters)
                .order_by(AuditEntry.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return AuditEntryPage(
            items=[
                AuditEntryRead(
                    id=item.id,
                    actor_type=item.actor_type,
                    actor_id=item.actor_id,
                    action=item.action,
                    resource_type=item.resource_type,
                    resource_id=item.resource_id,
                    change_summary=item.change_summary_json,
                    reason=item.reason,
                    status=item.status,
                    error_code=item.error_code,
                    error_detail=item.error_detail,
                    error_hint=item.error_hint,
                    trace_id=item.trace_id,
                    created_at=item.created_at,
                )
                for item in items
            ],
            page=page,
            page_size=page_size,
            total=total,
        )


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
