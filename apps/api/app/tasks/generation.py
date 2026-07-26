import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.models.generation import GenerationRun
from app.providers.llm.registry import build_llm_provider_registry
from app.services.generation import GenerationService
from app.tasks.celery_app import celery_app


async def _execute(run_id: UUID) -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    providers = build_llm_provider_registry(settings)
    try:
        async with session_factory() as session:
            await GenerationService(session, providers, settings).execute_run(run_id)
    finally:
        for provider in providers.values():
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()


@celery_app.task(name="app.tasks.generation.execute_generation")  # type: ignore[untyped-decorator]
def execute_generation(run_id: str) -> None:
    asyncio.run(_execute(UUID(run_id)))


async def _recover_stale() -> tuple[list[UUID], int]:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.task_stale_after_seconds)
    redispatch: list[UUID] = []
    failed = 0
    try:
        async with session_factory() as session:
            runs = list(
                (
                    await session.scalars(
                        select(GenerationRun)
                        .where(
                            GenerationRun.status.in_(("queued", "running")),
                            GenerationRun.updated_at < cutoff,
                        )
                        .limit(200)
                    )
                ).all()
            )
            now = datetime.now(UTC)
            for run in runs:
                if run.status == "running":
                    run.status = "failed"
                    run.completed_at = now
                    run.error = {
                        "code": "stale_generation_recovered",
                        "message": "Generation exceeded its execution lease and was released",
                    }
                    failed += 1
                    continue
                run.run_metadata = {
                    **run.run_metadata,
                    "recovery_dispatch_count": int(
                        run.run_metadata.get("recovery_dispatch_count", 0)
                    )
                    + 1,
                    "recovery_dispatched_at": now.isoformat(),
                }
                redispatch.append(run.id)
            if runs:
                await session.commit()
    finally:
        await engine.dispose()
    return redispatch, failed


@celery_app.task(name="app.tasks.generation.recover_stale_generations")  # type: ignore[untyped-decorator]
def recover_stale_generations() -> dict[str, int]:
    redispatch, failed = asyncio.run(_recover_stale())
    for run_id in redispatch:
        execute_generation.delay(str(run_id))
    return {"redispatched": len(redispatch), "failed": failed}
