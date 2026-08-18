from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.news import NewsService


def test_news_event_lifecycle_uses_observation_age() -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    event = SimpleNamespace(
        status="active",
        last_update_time=now - timedelta(hours=25),
        metadata_json={},
    )

    NewsService._apply_event_lifecycle(event, now)

    assert event.status == "developing"
    assert event.metadata_json["lifecycle"]["algorithm"] == "observation-age-v1"

    event.last_update_time = now - timedelta(hours=73)
    NewsService._apply_event_lifecycle(event, now)
    assert event.status == "closed"


def test_closed_news_event_is_not_reopened_by_lifecycle_refresh() -> None:
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    event = SimpleNamespace(
        status="closed",
        last_update_time=now - timedelta(hours=1),
        metadata_json={},
    )

    NewsService._apply_event_lifecycle(event, now)

    assert event.status == "closed"
    assert event.metadata_json == {}
