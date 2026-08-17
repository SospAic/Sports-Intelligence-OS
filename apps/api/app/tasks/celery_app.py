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
        "app.tasks.reliability",
        "app.tasks.trends",
        "app.tasks.video_search",
        "app.tasks.embedding",
        "app.tasks.subtitles",
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
        "app.tasks.system.cleanup_auth_records": {"queue": "maintenance"},
        "app.tasks.system.cleanup_media_lifecycle": {"queue": "maintenance"},
        "app.tasks.monitoring.*": {"queue": "monitoring"},
        "app.tasks.monitoring.recover_stale_sync_runs": {"queue": "maintenance"},
        "app.tasks.monitoring.recover_stale_downloads": {"queue": "maintenance"},
        "app.tasks.news.*": {"queue": "news"},
        "app.tasks.generation.recover_stale_generations": {"queue": "maintenance"},
        "app.tasks.generation.*": {"queue": "generation"},
        "app.tasks.automation.send_notification": {"queue": "notification"},
        "app.tasks.automation.dispatch_queued_notifications": {"queue": "automation"},
        "app.tasks.automation.scan_recent_entities": {"queue": "automation"},
        "app.tasks.reliability.*": {"queue": "maintenance"},
        "app.tasks.trends.*": {"queue": "monitoring"},
        "app.tasks.video_search.*": {"queue": "video-search"},
        # 复用既有队列，避免为一个新特性改 compose 的 worker -Q 列表。
        "app.tasks.embedding.*": {"queue": "video-search"},
        "app.tasks.subtitles.*": {"queue": "subtitle"},
    },
    beat_schedule={
        "system-heartbeat": {
            "task": "app.tasks.system.heartbeat",
            "schedule": 60.0,
        },
        "cleanup-auth-records": {
            "task": "app.tasks.system.cleanup_auth_records",
            "schedule": 3600.0,
        },
        "cleanup-media-lifecycle": {
            "task": "app.tasks.system.cleanup_media_lifecycle",
            "schedule": 3600.0,
        },
        "sweep-inbox-sla": {
            "task": "app.tasks.system.sweep_inbox_sla",
            "schedule": 60.0,
        },
        "sync-all-due-accounts": {
            "task": "app.tasks.monitoring.sync_all_due_accounts",
            "schedule": 60.0,
        },
        "recover-stale-sync-runs": {
            "task": "app.tasks.monitoring.recover_stale_sync_runs",
            "schedule": 60.0,
        },
        "recover-stale-downloads": {
            "task": "app.tasks.monitoring.recover_stale_downloads",
            "schedule": 60.0,
        },
        "sync-all-news-sources": {
            "task": "app.tasks.news.sync_all_news_sources",
            "schedule": 60.0,
        },
        "refresh-news-event-lifecycles": {
            "task": "app.tasks.news.refresh_event_lifecycles",
            "schedule": 300.0,
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
        "consume-outbox-events": {
            "task": "app.tasks.reliability.consume_outbox_events",
            "schedule": 15.0,
        },
        "process-dead-letters": {
            "task": "app.tasks.reliability.process_dead_letters",
            "schedule": 3600.0,
        },
        "calculate-dashboard-stats": {
            "task": "app.tasks.reliability.calculate_dashboard_stats",
            "schedule": 300.0,
        },
        "collect-platform-trends": {
            "task": "app.tasks.trends.collect_platform_trends",
            "schedule": 3600.0,  # 每小时采集一次各平台趋势数据
        },
        "schedule-due-video-search-plans": {
            "task": "app.tasks.video_search.schedule_due_video_search_plans",
            "schedule": 60.0,
        },
    },
)
