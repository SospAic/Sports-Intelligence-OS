import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, or_

from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.models.session import AuthSession, LoginAttempt
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
