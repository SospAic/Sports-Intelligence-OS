import asyncio
import logging

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.models.operations import DeadLetterEvent
from app.models.workspace import Workspace
from app.services.dashboard_stats import DashboardStatsService
from app.services.outbox import OutboxService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _consume_outbox_events() -> int:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            service = OutboxService(session)
            processed = await service.consume_pending()
            return len(processed)
    except Exception:
        logger.exception("consume_outbox_events_failed")
        raise
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.reliability.consume_outbox_events")  # type: ignore[untyped-decorator]
def consume_outbox_events() -> int:
    return asyncio.run(_consume_outbox_events())


async def _process_dead_letters() -> int:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            # Count pending dead letters
            count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(DeadLetterEvent)
                    .where(DeadLetterEvent.replay_status == "pending")
                )
                or 0
            )
            logger.info("dead_letter_pending_count", extra={"count": count})

            # Replays are deliberately operator-controlled. Automatically
            # replaying poison events after 24 hours creates an endless loop
            # and can repeat external side effects without authorization.
            return count
    except Exception:
        logger.exception("process_dead_letters_failed")
        raise
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.reliability.process_dead_letters")  # type: ignore[untyped-decorator]
def process_dead_letters() -> int:
    return asyncio.run(_process_dead_letters())


async def _calculate_dashboard_stats() -> int:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    processed = 0
    try:
        async with session_factory() as session:
            workspace_ids = list(
                (
                    await session.scalars(select(Workspace.id).where(Workspace.status == "active"))
                ).all()
            )
            service = DashboardStatsService(session)
            for workspace_id in workspace_ids:
                try:
                    await service.calculate_stats(workspace_id)
                    processed += 1
                except Exception:
                    logger.exception(
                        "dashboard_stats_calculation_failed",
                        extra={"workspace_id": str(workspace_id)},
                    )
            return processed
    except Exception:
        logger.exception("calculate_dashboard_stats_failed")
        raise
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.reliability.calculate_dashboard_stats")  # type: ignore[untyped-decorator]
def calculate_dashboard_stats() -> int:
    return asyncio.run(_calculate_dashboard_stats())
