"""Background embedding backfill for locally indexed content.

为什么要独立任务
----------------
嵌入 9000+ 条内容是分钟级甚至小时级的工作，绝不能挂在请求路径上。这里提供两个
入口：

``index_content_item``
    单条内容的增量索引，同步流程写入新内容后可以直接派发。
``backfill_content_embeddings``
    分批扫描尚未索引（或指定重建）的内容，跑完一批就提交一次。任务本身带
    ``limit``，跑不完会返回 ``remaining``，调用方按需再投递，避免单个 Celery
    任务超过 ``task_time_limit``。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.models.embedding import ContentEmbedding
from app.models.monitoring import ContentItem
from app.services.content_indexing import ContentIndexingService
from app.services.embedding import EmbeddingError
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

#: 单个任务默认处理多少条内容。按每条 1~3 个块、batch_size=16 估算，500 条大约
#: 是几十次 HTTP 往返，稳稳落在 task_time_limit（1860s）之内。
DEFAULT_BATCH_LIMIT = 500

#: 一次从库里取多少条进内存。取太多会让事务过长，取太少会让往返变多。
_FETCH_CHUNK = 50


def _has_text_clause() -> Any:
    """Only items with actual text are worth a round trip to the model."""

    return or_(
        func.coalesce(func.trim(ContentItem.title), "") != "",
        func.coalesce(func.trim(ContentItem.description), "") != "",
    )


def build_pending_query(
    *,
    model: str,
    workspace_id: UUID | None,
    reindex: bool,
) -> Any:
    """Select content items that still need embedding for ``model``.

    未索引判定用 ``NOT EXISTS``（而不是 LEFT JOIN + IS NULL）：内容与块是
    一对多，JOIN 会放大行数，NOT EXISTS 能让 Postgres 直接走
    ``ix_content_embeddings_item`` 的半连接。
    """

    statement = select(ContentItem).where(_has_text_clause())
    if workspace_id is not None:
        statement = statement.where(ContentItem.workspace_id == workspace_id)
    if not reindex:
        already = exists().where(
            and_(
                ContentEmbedding.content_item_id == ContentItem.id,
                ContentEmbedding.model == model,
            )
        )
        statement = statement.where(~already)
    # 新内容优先：用户最可能搜刚同步进来的东西。
    return statement.order_by(ContentItem.last_seen_at.desc(), ContentItem.id)


async def _count_pending(
    session: AsyncSession, *, model: str, workspace_id: UUID | None, reindex: bool
) -> int:
    base = build_pending_query(model=model, workspace_id=workspace_id, reindex=reindex).order_by(
        None
    )
    return int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)


async def _backfill(*, workspace_id: UUID | None, limit: int, reindex: bool) -> dict[str, Any]:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    summary: dict[str, Any] = {
        "status": "ok",
        "model": None,
        "processed": 0,
        "indexed": 0,
        "unchanged": 0,
        "empty": 0,
        "failed": 0,
        "chunks_written": 0,
        "chunks_deleted": 0,
        "remaining": 0,
    }
    try:
        async with session_factory() as session:
            service = ContentIndexingService(session, settings)
            if not service.embedder.enabled:
                summary["status"] = "disabled"
                summary["detail"] = "SIO_EMBEDDING_BACKEND is 'none'; nothing was indexed"
                return summary
            model = service.embedder.model
            summary["model"] = model

            processed = 0
            while processed < limit:
                take = min(_FETCH_CHUNK, limit - processed)
                statement = build_pending_query(
                    model=model, workspace_id=workspace_id, reindex=reindex
                ).limit(take)
                # reindex 模式下已索引的内容不会离开结果集，必须用 offset 前进，
                # 否则每轮都会取到同一批。
                if reindex:
                    statement = statement.offset(processed)
                items = list((await session.scalars(statement)).all())
                if not items:
                    break
                for item in items:
                    processed += 1
                    try:
                        outcome = await service.index_item(item)
                    except EmbeddingError as exc:
                        await session.rollback()
                        summary["failed"] = int(summary["failed"]) + 1
                        logger.warning(
                            "content_embedding_failed",
                            extra={"content_item_id": str(item.id), "error": str(exc)},
                        )
                        # 后端不可用时继续跑只会把错误刷满日志，直接收工。
                        summary["status"] = "degraded"
                        summary["detail"] = str(exc)[:500]
                        summary["processed"] = processed
                        summary["remaining"] = await _count_pending(
                            session,
                            model=model,
                            workspace_id=workspace_id,
                            reindex=reindex,
                        )
                        return summary
                    summary["chunks_written"] = int(summary["chunks_written"]) + outcome.written
                    summary["chunks_deleted"] = int(summary["chunks_deleted"]) + outcome.deleted
                    if outcome.status == "indexed":
                        summary["indexed"] = int(summary["indexed"]) + 1
                    elif outcome.status == "unchanged":
                        summary["unchanged"] = int(summary["unchanged"]) + 1
                    elif outcome.status == "empty":
                        summary["empty"] = int(summary["empty"]) + 1
                await session.commit()

            summary["processed"] = processed
            summary["remaining"] = await _count_pending(
                session, model=model, workspace_id=workspace_id, reindex=reindex
            )
    finally:
        await engine.dispose()
    return summary


async def _index_one(content_item_id: UUID) -> dict[str, Any]:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            item = await session.scalar(
                select(ContentItem).where(ContentItem.id == content_item_id)
            )
            if item is None:
                return {"status": "missing", "content_item_id": str(content_item_id)}
            outcome = await ContentIndexingService(session, settings).index_item(item)
            await session.commit()
            return {
                "status": outcome.status,
                "content_item_id": str(outcome.content_item_id),
                "written": outcome.written,
                "skipped": outcome.skipped,
                "deleted": outcome.deleted,
            }
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.embedding.backfill_content_embeddings")
def backfill_content_embeddings(
    workspace_id: str | None = None,
    limit: int = DEFAULT_BATCH_LIMIT,
    reindex: bool = False,
) -> dict[str, Any]:
    parsed = UUID(workspace_id) if workspace_id else None
    bounded = max(1, min(int(limit), 5000))
    return asyncio.run(_backfill(workspace_id=parsed, limit=bounded, reindex=bool(reindex)))


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.tasks.embedding.index_content_item",
    bind=True,
    max_retries=2,
)
def index_content_item(self: Any, content_item_id: str) -> dict[str, Any]:
    try:
        return asyncio.run(_index_one(UUID(content_item_id)))
    except EmbeddingError as exc:
        logger.warning(
            "content_embedding_backend_unavailable",
            extra={"content_item_id": content_item_id},
        )
        if int(getattr(self.request, "retries", 0)) >= int(self.max_retries or 0):
            return {
                "status": "failed",
                "content_item_id": content_item_id,
                "error": str(exc)[:500],
            }
        raise self.retry(exc=exc, countdown=60) from exc
