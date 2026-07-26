from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "sports_intelligence",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.system",
        "app.tasks.monitoring",
        "app.tasks.news",
        "app.tasks.generation",
        "app.tasks.automation",
    ],
)
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=1800,
    task_time_limit=1860,
    worker_prefetch_multiplier=1,
    task_default_queue="maintenance",
    task_routes={
        "app.tasks.system.heartbeat": {"queue": "maintenance"},
        "app.tasks.monitoring.*": {"queue": "monitoring"},
        "app.tasks.news.*": {"queue": "news"},
        "app.tasks.generation.recover_stale_generations": {"queue": "maintenance"},
        "app.tasks.generation.*": {"queue": "generation"},
        "app.tasks.automation.send_notification": {"queue": "notification"},
        "app.tasks.automation.dispatch_queued_notifications": {"queue": "automation"},
        "app.tasks.automation.scan_recent_entities": {"queue": "automation"},
    },
    beat_schedule={
        "system-heartbeat": {
            "task": "app.tasks.system.heartbeat",
            "schedule": 60.0,
        },
        "sync-all-due-accounts": {
            "task": "app.tasks.monitoring.sync_all_due_accounts",
            "schedule": 60.0,
        },
        "sync-all-news-sources": {
            "task": "app.tasks.news.sync_all_news_sources",
            "schedule": 60.0,
        },
        "dispatch-queued-notifications": {
            "task": "app.tasks.automation.dispatch_queued_notifications",
            "schedule": 5.0,
        },
        "scan-recent-automation-entities": {
            "task": "app.tasks.automation.scan_recent_entities",
            "schedule": 30.0,
        },
        "recover-stale-generations": {
            "task": "app.tasks.generation.recover_stale_generations",
            "schedule": 60.0,
        },
    },
)
