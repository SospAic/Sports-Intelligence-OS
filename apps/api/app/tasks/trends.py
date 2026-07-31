"""趋势数据采集 Celery 任务。

支持两种调用方式：
- 指定 workspace_id：仅采集该工作区的趋势数据
- 不指定 workspace_id（定时任务）：遍历所有活跃工作区进行采集
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _collect_for_workspace(workspace_id: UUID) -> dict[str, Any]:
    """为单个工作区执行趋势采集"""
    from app.services.trend_collector import TrendCollectorService

    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            svc = TrendCollectorService(session)
            return await svc.collect_all(workspace_id)
    finally:
        await engine.dispose()


async def _collect_all_workspaces() -> dict[str, Any]:
    """遍历所有活跃工作区执行趋势采集"""
    from sqlalchemy import select

    from app.models.workspace import Workspace

    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    results: dict[str, Any] = {}
    try:
        async with session_factory() as session:
            stmt = select(Workspace.id).where(Workspace.status == "active")
            rows = await session.execute(stmt)
            workspace_ids = [row[0] for row in rows.fetchall()]
    finally:
        await engine.dispose()

    for ws_id in workspace_ids:
        try:
            results[str(ws_id)] = await _collect_for_workspace(ws_id)
        except Exception as exc:
            logger.error(
                "trend_collection_workspace_failed",
                extra={"workspace_id": str(ws_id), "error": str(exc)},
            )
            results[str(ws_id)] = {"error": str(exc)}

    return results


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.tasks.trends.collect_platform_trends",
    bind=True,
    max_retries=2,
)
def collect_platform_trends(
    self: Any, workspace_id: str | None = None
) -> dict[str, Any]:
    """采集平台趋势数据。

    Args:
        workspace_id: 工作区 ID（可选）。为 None 时采集所有活跃工作区。
    """
    try:
        if workspace_id:
            return asyncio.run(_collect_for_workspace(UUID(workspace_id)))
        return asyncio.run(_collect_all_workspaces())
    except Exception as exc:
        logger.exception("trend_collection_failed")
        raise self.retry(exc=exc, countdown=60) from exc
