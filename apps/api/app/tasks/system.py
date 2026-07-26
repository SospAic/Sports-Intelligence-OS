import logging
from datetime import UTC, datetime

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
