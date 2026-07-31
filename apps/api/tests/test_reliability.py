from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.operations import DeadLetterEvent, OutboxEvent, OutboxEventAttempt
from app.models.trends import TrendTopic, TrendVideo
from app.models.workspace import Workspace
from app.services.outbox import OutboxService
from app.services.trend_collector import _infer_sports_category, _trend_terms
from app.services.trends import TrendService

from .conftest import TEST_PASSWORD


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


@pytest.mark.asyncio
async def test_outbox_failure_is_recorded_and_dead_lettered_without_false_success(
    client: TestClient,
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticate(client)
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def fail_dispatch(_service: OutboxService, _event: OutboxEvent) -> None:
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(OutboxService, "_dispatch_event", fail_dispatch)
    try:
        async with sessions() as session:
            workspace_id = await session.scalar(
                select(Workspace.id).where(Workspace.slug == "test-workspace")
            )
            assert workspace_id is not None
            service = OutboxService(session)
            event = await service.publish(
                workspace_id,
                "content.updated",
                "content",
                uuid4(),
                {"truth": "preserved"},
                uuid4(),
                uuid4(),
            )
            event.attempts = 4
            await session.commit()

            processed = await service.consume_pending()
            assert [item.id for item in processed] == [event.id]
            stored = await session.get(OutboxEvent, event.id)
            assert stored is not None
            assert stored.publish_status == "dead_letter"
            assert stored.published_at is None
            assert stored.payload_json == {"truth": "preserved"}
            attempt = await session.scalar(
                select(OutboxEventAttempt).where(
                    OutboxEventAttempt.outbox_event_id == event.id
                )
            )
            assert attempt is not None
            assert attempt.status == "failed"
            dead_letter = await session.scalar(
                select(DeadLetterEvent).where(DeadLetterEvent.outbox_event_id == event.id)
            )
            assert dead_letter is not None
            assert dead_letter.total_attempts == 5
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_trend_dashboard_uses_latest_unique_observations(
    client: TestClient,
    database_path: Path,
) -> None:
    authenticate(client)
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    try:
        async with sessions() as session:
            workspace_id = await session.scalar(
                select(Workspace.id).where(Workspace.slug == "test-workspace")
            )
            assert workspace_id is not None
            session.add_all(
                [
                    TrendTopic(
                        workspace_id=workspace_id,
                        platform="youtube",
                        title="Final highlights",
                        category="football",
                        heat_score=10,
                        rank=2,
                        sample_size=1,
                        metadata_json={"source_kind": "live"},
                        observed_at=now - timedelta(hours=1),
                    ),
                    TrendTopic(
                        workspace_id=workspace_id,
                        platform="youtube",
                        title="FINAL HIGHLIGHTS",
                        category="football",
                        heat_score=30,
                        rank=1,
                        sample_size=1,
                        metadata_json={"source_kind": "live"},
                        observed_at=now,
                    ),
                    TrendVideo(
                        workspace_id=workspace_id,
                        platform="youtube",
                        external_id="video-1",
                        title="Old snapshot",
                        view_count=100,
                        breakout_score=1,
                        metadata_json={"source_kind": "live"},
                        observed_at=now - timedelta(hours=1),
                    ),
                    TrendVideo(
                        workspace_id=workspace_id,
                        platform="youtube",
                        external_id="video-1",
                        title="Current snapshot",
                        view_count=250,
                        breakout_score=3,
                        metadata_json={"source_kind": "live"},
                        observed_at=now,
                    ),
                    TrendTopic(
                        workspace_id=workspace_id,
                        platform="youtube",
                        title="Unverified legacy topic",
                        category="football",
                        heat_score=100,
                        rank=1,
                        sample_size=1,
                        metadata_json={"source_kind": "imported"},
                        observed_at=now,
                    ),
                    TrendVideo(
                        workspace_id=workspace_id,
                        platform="youtube",
                        external_id="legacy-video",
                        title="Unverified legacy video",
                        view_count=999_999,
                        breakout_score=100,
                        metadata_json={"source_kind": "imported"},
                        observed_at=now,
                    ),
                ]
            )
            await session.commit()
            dashboard = await TrendService(session).get_dashboard(workspace_id)
            youtube = next(
                item for item in dashboard.platform_summary if item.platform == "youtube"
            )
            assert youtube.topic_count == 1
            assert youtube.video_count == 1
            assert youtube.total_views == 250
            assert dashboard.top_topics[0].heat_score == 30
            assert dashboard.breakout_videos[0].title == "Current snapshot"
    finally:
        await engine.dispose()


def test_trend_terms_use_controlled_sports_vocabulary_and_explicit_hashtags() -> None:
    assert _trend_terms("NBA 总决赛集锦 #绝杀时刻") >= {"NBA", "绝杀时刻"}
    assert _trend_terms("普通生活记录") == set()


def test_trend_category_is_derived_from_sports_vocabulary() -> None:
    assert _infer_sports_category("NBA 总决赛") == "basketball"
    assert _infer_sports_category("世界杯决赛") == "football"
    assert _infer_sports_category("NFL draft") == "american_football"
    assert _infer_sports_category("综合体育观察") == "sports"


def test_dashboard_stats_endpoint_returns_fresh_complete_shape(client: TestClient) -> None:
    authenticate(client)
    response = client.get("/api/v1/dashboard/stats")
    assert response.status_code == 200, response.text
    stats = response.json()["stats"]
    assert {
        "account_counts",
        "content_counts",
        "sync_stats",
        "news_stats",
        "generation_stats",
        "automation_stats",
        "notification_stats",
    } == set(stats)
    assert stats["account_counts"] == {
        "total": 0,
        "active": 0,
        "synced_24h": 0,
        "by_platform": {},
    }
