"""Scheduled video-content search jobs."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.models.video_search import VideoSearchPlan, VideoSearchRun
from app.services.video_content_search import VideoContentSearchService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _execute(run_id: UUID) -> dict[str, Any]:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            return await VideoContentSearchService(session, settings).execute_run(run_id)
    finally:
        await engine.dispose()


async def _mark_failed(run_id: UUID, detail: str) -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            run = await session.scalar(select(VideoSearchRun).where(VideoSearchRun.id == run_id))
            if run is not None and run.status in {"queued", "running", "stopping"}:
                run.status = "failed"
                run.error_detail = detail[:4000]
                run.finished_at = datetime.now(UTC)
                plan = await session.scalar(
                    select(VideoSearchPlan).where(VideoSearchPlan.id == run.plan_id)
                )
                if plan is not None:
                    plan.last_error = detail[:4000]
                await session.commit()
    finally:
        await engine.dispose()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.tasks.video_search.run_video_search",
    bind=True,
    max_retries=1,
)
def run_video_search(self: Any, run_id: str) -> dict[str, Any]:
    try:
        return asyncio.run(_execute(UUID(run_id)))
    except Exception as exc:
        logger.exception("video_search_run_failed", extra={"run_id": run_id})
        if int(getattr(self.request, "retries", 0)) >= int(self.max_retries or 0):
            try:
                asyncio.run(_mark_failed(UUID(run_id), str(exc)))
            except Exception:  # noqa: BLE001 - preserve the original task failure
                logger.exception("video_search_run_mark_failed", extra={"run_id": run_id})
            return {"status": "failed", "run_id": run_id, "error": str(exc)[:4000]}
        raise self.retry(exc=exc, countdown=30) from exc


async def _schedule_due() -> dict[str, Any]:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    dispatched = 0
    failed = 0
    now = datetime.now(UTC)
    try:
        async with session_factory() as session:
            plans = list(
                (
                    await session.scalars(
                        select(VideoSearchPlan)
                        .where(
                            VideoSearchPlan.status == "active",
                            VideoSearchPlan.next_run_at <= now,
                        )
                        .with_for_update(skip_locked=True)
                        .limit(50)
                    )
                ).all()
            )
            for plan in plans:
                active = await session.scalar(
                    select(VideoSearchRun.id).where(
                        VideoSearchRun.plan_id == plan.id,
                        VideoSearchRun.status.in_(["queued", "running", "stopping"]),
                    )
                )
                if active:
                    plan.next_run_at = now + timedelta(seconds=60)
                    continue
                run = VideoSearchRun(
                    plan_id=plan.id,
                    workspace_id=plan.workspace_id,
                    status="queued",
                )
                session.add(run)
                await session.flush()
                plan.next_run_at = now + timedelta(seconds=plan.interval_seconds)
                try:
                    task = run_video_search.delay(str(run.id))
                    run.task_id = task.id
                    dispatched += 1
                except Exception as exc:  # noqa: BLE001 - persist scheduler failure
                    run.status = "failed"
                    run.error_detail = str(exc)[:4000]
                    plan.status = "error"
                    plan.last_error = str(exc)[:4000]
                    failed += 1
            await session.commit()
    finally:
        await engine.dispose()
    return {"dispatched": dispatched, "failed": failed}


@celery_app.task(name="app.tasks.video_search.schedule_due_video_search_plans")
def schedule_due_video_search_plans() -> dict[str, Any]:
    return asyncio.run(_schedule_due())
