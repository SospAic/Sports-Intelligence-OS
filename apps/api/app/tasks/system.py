import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, or_, select

from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.models.session import AuthSession, LoginAttempt
from app.models.workspace import Workspace
from app.services.inbox import InboxService
from app.services.storage import media_lifecycle
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.system.heartbeat")  # type: ignore[untyped-decorator]
def heartbeat() -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat()
    logger.info(
        "worker_heartbeat",
        extra={"event": "worker.heartbeat", "timestamp_utc": timestamp},
    )
    return {"status": "ok", "timestamp": timestamp}


@celery_app.task(name="app.tasks.system.cleanup_auth_records")  # type: ignore[untyped-decorator]
def cleanup_auth_records() -> dict[str, int]:
    return asyncio.run(_cleanup_auth_records())


async def _cleanup_auth_records() -> dict[str, int]:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    now = datetime.now(UTC)
    session_cutoff = now - timedelta(seconds=settings.session_cleanup_retention_seconds)
    attempt_cutoff = now - timedelta(seconds=settings.auth_attempt_retention_seconds)
    try:
        async with session_factory() as session:
            sessions = await session.execute(
                delete(AuthSession).where(
                    or_(
                        AuthSession.expires_at < session_cutoff,
                        and_(
                            AuthSession.revoked_at.is_not(None),
                            AuthSession.revoked_at < session_cutoff,
                        ),
                    )
                )
            )
            attempts = await session.execute(
                delete(LoginAttempt).where(LoginAttempt.attempted_at < attempt_cutoff)
            )
            await session.commit()
            return {
                "sessions_deleted": int(sessions.rowcount or 0),  # type: ignore[attr-defined]
                "attempts_deleted": int(attempts.rowcount or 0),  # type: ignore[attr-defined]
            }
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.system.cleanup_media_lifecycle")  # type: ignore[untyped-decorator]
def cleanup_media_lifecycle() -> dict[str, int]:
    return asyncio.run(_cleanup_media_lifecycle())


async def _cleanup_media_lifecycle() -> dict[str, int]:
    """Run the configured bounded policy; disabled deployments perform no scan."""

    settings = get_settings()
    if not settings.media_lifecycle_enabled:
        return {"workspaces": 0, "planned": 0, "deleted": 0, "skipped_disabled": 1}
    engine, session_factory = create_engine_and_session(settings)
    result = {"workspaces": 0, "planned": 0, "deleted": 0, "failed": 0}
    try:
        async with session_factory() as session:
            workspace_ids = list(
                (
                    await session.scalars(
                        select(Workspace.id).where(Workspace.status == "active")
                    )
                ).all()
            )
            for workspace_id in workspace_ids:
                try:
                    report = await media_lifecycle(
                        session,
                        settings,
                        workspace_id,
                        dry_run=settings.media_lifecycle_dry_run,
                        confirm=True,
                        actor_type="system",
                    )
                    result["workspaces"] += 1
                    result["planned"] += len(report.candidates)
                    result["deleted"] += report.deleted_file_count
                    result["failed"] += len(report.failed)
                except Exception:  # noqa: BLE001 - one workspace must not block others
                    await session.rollback()
                    result["failed"] += 1
                    logger.exception(
                        "media_lifecycle_workspace_failed",
                        extra={"workspace_id": str(workspace_id)},
                    )
        return result
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.system.sweep_inbox_sla")  # type: ignore[untyped-decorator]
def sweep_inbox_sla() -> dict[str, int]:
    return asyncio.run(_sweep_inbox_sla())


async def _sweep_inbox_sla() -> dict[str, int]:
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings)
    result = {"workspaces": 0, "scanned": 0, "escalated": 0, "cleared": 0}
    try:
        async with session_factory() as session:
            workspace_ids = list(
                (
                    await session.scalars(
                        select(Workspace.id).where(Workspace.status == "active")
                    )
                ).all()
            )
            for workspace_id in workspace_ids:
                report = await InboxService(session).sweep_sla(workspace_id)
                result["workspaces"] += 1
                for key in ("scanned", "escalated", "cleared"):
                    result[key] += report[key]
    finally:
        await engine.dispose()
    return result
