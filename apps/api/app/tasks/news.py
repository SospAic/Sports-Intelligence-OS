import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from celery import Task

from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.providers.news.registry import build_news_provider_registry
from app.schemas.news import NewsSyncRequest
from app.services.news import NewsService, RetryableNewsSyncError
from app.tasks.celery_app import celery_app


async def _execute(run_id: UUID) -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    providers = build_news_provider_registry(settings)
    try:
        async with session_factory() as session:
            await NewsService(session, providers).execute_sync(run_id)
    finally:
        for provider in providers.values():
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()


async def _mark_exhausted(run_id: UUID, message: str) -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    providers = build_news_provider_registry(settings)
    try:
        async with session_factory() as session:
            await NewsService(session, providers).mark_retry_exhausted(run_id, message)
    finally:
        for provider in providers.values():
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()


@celery_app.task(bind=True, name="app.tasks.news.sync_news_source")  # type: ignore[untyped-decorator]
def sync_news_source(self: Task, run_id: str) -> None:
    settings = get_settings()
    parsed_id = UUID(run_id)
    try:
        asyncio.run(_execute(parsed_id))
    except RetryableNewsSyncError as exc:
        retries = int(self.request.retries)
        if retries >= settings.sync_task_max_retries:
            asyncio.run(_mark_exhausted(parsed_id, str(exc)))
            raise
        raise self.retry(
            exc=exc,
            countdown=min(2**retries, 60),
            max_retries=settings.sync_task_max_retries,
        ) from exc


async def _schedule_due() -> int:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    providers = build_news_provider_registry(settings)
    run_ids: list[UUID] = []
    try:
        async with session_factory() as session:
            service = NewsService(session, providers)
            await service.recover_stale_syncs(
                datetime.now(UTC) - timedelta(seconds=settings.task_stale_after_seconds)
            )
            for source in await service.repository.due_sources(datetime.now(UTC)):
                run, created = await service.request_sync(
                    source.workspace_id,
                    source.id,
                    request_id=f"scheduled-{uuid4()}",
                    payload=NewsSyncRequest(),
                )
                if created:
                    run_ids.append(run.id)
    finally:
        for provider in providers.values():
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()
    for run_id in run_ids:
        sync_news_source.delay(str(run_id))
    return len(run_ids)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.tasks.news.sync_all_news_sources"
)
def sync_all_news_sources() -> int:
    return asyncio.run(_schedule_due())


async def _refresh_all_event_lifecycles() -> dict[str, dict[str, int]]:
    from sqlalchemy import select

    from app.models.workspace import Workspace

    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    providers = build_news_provider_registry(settings)
    results: dict[str, dict[str, int]] = {}
    try:
        async with session_factory() as session:
            workspace_ids = list(
                (
                    await session.scalars(select(Workspace.id).where(Workspace.status == "active"))
                ).all()
            )
            for workspace_id in workspace_ids:
                results[str(workspace_id)] = await NewsService(
                    session, providers
                ).refresh_event_lifecycle(workspace_id)
    finally:
        for provider in providers.values():
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()
    return results


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.tasks.news.refresh_event_lifecycles"
)
def refresh_event_lifecycles() -> dict[str, dict[str, int]]:
    """Keep active news events aligned with the current observation age."""
    return asyncio.run(_refresh_all_event_lifecycles())
