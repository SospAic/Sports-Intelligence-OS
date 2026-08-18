from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.operations import DeadLetterEvent, OutboxEvent, OutboxEventAttempt
from app.models.trends import TrendKeywordSnapshot, TrendTopic, TrendVideo
from app.models.workspace import Workspace
from app.services.outbox import OutboxService
from app.services.trend_categories import classify_trend_label, extract_trend_labels
from app.services.trend_collector import _infer_sports_category, _trend_terms
from app.services.trends import TrendService

from .conftest import PG_ASYNC_URL, TEST_PASSWORD


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
    engine = create_async_engine(PG_ASYNC_URL)
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
                select(OutboxEventAttempt).where(OutboxEventAttempt.outbox_event_id == event.id)
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
    engine = create_async_engine(PG_ASYNC_URL)
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


@pytest.mark.asyncio
async def test_trend_aggregate_deduplicates_snapshots_and_excludes_unverified_rows(
    client: TestClient,
    database_path: Path,
) -> None:
    """Analytics must rank entities, not every append-only observation."""
    authenticate(client)
    engine = create_async_engine(PG_ASYNC_URL)
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
                        title="Same topic",
                        category="basketball",
                        heat_score=10,
                        rank=2,
                        sample_size=1,
                        metadata_json={"source_kind": "live"},
                        observed_at=now - timedelta(days=2),
                    ),
                    TrendTopic(
                        workspace_id=workspace_id,
                        platform="youtube",
                        title="Same topic",
                        category="basketball",
                        heat_score=30,
                        rank=1,
                        sample_size=2,
                        metadata_json={"source_kind": "live"},
                        observed_at=now,
                    ),
                    TrendTopic(
                        workspace_id=workspace_id,
                        platform="youtube",
                        title="Unverified topic",
                        category="basketball",
                        heat_score=100,
                        rank=1,
                        sample_size=1,
                        metadata_json={"source_kind": "imported"},
                        observed_at=now,
                    ),
                    TrendVideo(
                        workspace_id=workspace_id,
                        platform="youtube",
                        external_id="video-1",
                        title="Old video",
                        category="basketball",
                        breakout_score=1,
                        metadata_json={"source_kind": "live"},
                        observed_at=now - timedelta(days=1),
                    ),
                    TrendVideo(
                        workspace_id=workspace_id,
                        platform="youtube",
                        external_id="video-1",
                        title="Current video",
                        category="basketball",
                        breakout_score=3,
                        metadata_json={"source_kind": "live"},
                        observed_at=now,
                    ),
                    TrendVideo(
                        workspace_id=workspace_id,
                        platform="youtube",
                        external_id="unverified-video",
                        title="Unverified video",
                        category="basketball",
                        breakout_score=100,
                        metadata_json={"source_kind": "imported"},
                        observed_at=now,
                    ),
                    TrendVideo(
                        workspace_id=workspace_id,
                        platform="web",
                        external_id="feed-a:https://publisher.example/story",
                        title="Same syndicated article",
                        category="basketball",
                        breakout_score=20,
                        metadata_json={
                            "source_kind": "live",
                            "source_article_id": "https://publisher.example/story",
                        },
                        observed_at=now - timedelta(hours=1),
                    ),
                    TrendVideo(
                        workspace_id=workspace_id,
                        platform="web",
                        external_id="feed-b:https://publisher.example/story",
                        title="Same syndicated article",
                        category="basketball",
                        breakout_score=25,
                        metadata_json={
                            "source_kind": "live",
                            "source_article_id": "https://publisher.example/story",
                        },
                        observed_at=now,
                    ),
                ]
            )
            await session.commit()

            result = await TrendService(session).aggregate(workspace_id, days=30)

            ranking = result["ranking"]
            assert [item.title for item in ranking].count("Same topic") == 1
            assert [item.title for item in ranking].count("Same syndicated article") == 1
            assert "Old video" not in [item.title for item in ranking]
            assert "Unverified topic" not in [item.title for item in ranking]
            assert "Unverified video" not in [item.title for item in ranking]
            assert result["window_days"] == 30
            assert result["raw_video_observations"] == 4
            assert result["unique_videos"] == 2
            basketball = next(
                item for item in result["matrix"]
                if item["platform"] == "youtube" and item["category"] == "basketball"
            )
            assert basketball["heat"] == pytest.approx(33.0)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_trend_aggregate_groups_same_opportunity_across_representations(
    client: TestClient,
    database_path: Path,
) -> None:
    """A cross-platform topic/video should occupy one ranking opportunity."""
    authenticate(client)
    engine = create_async_engine(PG_ASYNC_URL)
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
                        title="NBA Finals 2026",
                        category="basketball",
                        heat_score=88,
                        growth_rate=0.4,
                        rank=1,
                        sample_size=20,
                        metadata_json={"source_kind": "live"},
                        observed_at=now,
                    ),
                    TrendVideo(
                        workspace_id=workspace_id,
                        platform="youtube",
                        external_id="nba-youtube-video",
                        title="NBA Finals 2026",
                        category="basketball",
                        breakout_score=55,
                        metadata_json={"source_kind": "live"},
                        observed_at=now,
                    ),
                    TrendVideo(
                        workspace_id=workspace_id,
                        platform="tiktok",
                        external_id="nba-tiktok-video",
                        title="NBA Finals 2026",
                        category="basketball",
                        breakout_score=70,
                        metadata_json={"source_kind": "live"},
                        observed_at=now,
                    ),
                ]
            )
            await session.commit()

            result = await TrendService(session).aggregate(workspace_id, days=30)

            assert result["unique_opportunities"] == 1
            assert len(result["ranking"]) == 1
            item = result["ranking"][0]
            assert item.kind == "opportunity"
            assert item.platform == "cross_platform"
            assert item.platforms == ["tiktok", "youtube"]
            assert item.representation_count == 3
            assert item.metric == pytest.approx(88)
            assert item.stage == "accelerating"
            youtube_cell = next(
                cell
                for cell in result["matrix"]
                if cell["platform"] == "youtube" and cell["category"] == "basketball"
            )
            assert youtube_cell["heat"] == pytest.approx(88)
    finally:
        await engine.dispose()


def test_trend_terms_use_controlled_sports_vocabulary_and_explicit_hashtags() -> None:
    assert _trend_terms("NBA 总决赛集锦 #绝杀时刻") >= {"NBA", "绝杀时刻"}
    assert _trend_terms("普通生活记录") == set()


def test_trend_labels_prioritize_specific_topics_and_drop_generic_noise() -> None:
    assert classify_trend_label("ESPN") is None
    assert classify_trend_label("FOOTBALL") is None
    assert classify_trend_label("basketball") is None
    assert classify_trend_label("#NBAFinals").label_type.value == "topic"
    assert classify_trend_label("World Cup").label_type.value == "event"
    assert classify_trend_label("LeBron").label_type.value == "person"
    labels = extract_trend_labels("#NBAFinals LeBron World Cup football ESPN")
    assert labels[0].text == "NBAFinals"
    assert labels[0].label_type.value == "topic"
    assert {label.text.casefold() for label in labels} >= {"nbafinals", "lebron"}
    assert "football" not in {label.text.casefold() for label in labels}
    assert "espn" not in {label.text.casefold() for label in labels}


def test_trend_category_is_derived_from_sports_vocabulary() -> None:
    assert _infer_sports_category("NBA 总决赛") == "basketball"
    assert _infer_sports_category("世界杯决赛") == "football"
    assert _infer_sports_category("NFL draft") == "american_football"
    assert _infer_sports_category("Olympic badminton final") == "badminton"
    assert _infer_sports_category("NHL hockey playoffs") == "ice_hockey"
    assert _infer_sports_category("综合体育观察") == "sports"


@pytest.mark.asyncio
async def test_trend_category_filter_uses_full_category_read_model(
    client: TestClient,
    database_path: Path,
) -> None:
    """A category filter must not be limited to the global first page."""

    authenticate(client)
    engine = create_async_engine(PG_ASYNC_URL)
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
                        title="Category filter basketball sample",
                        category="basketball",
                        heat_score=99,
                        rank=1,
                        sample_size=5,
                        metadata_json={"source_kind": "live"},
                        observed_at=now,
                    ),
                    TrendVideo(
                        workspace_id=workspace_id,
                        platform="youtube",
                        external_id="category-filter-general-sports",
                        title="Category filter general sports sample",
                        category="general_sports",
                        breakout_score=99,
                        metadata_json={"source_kind": "live"},
                        observed_at=now,
                    ),
                ]
            )
            await session.commit()

        topic_response = client.get(
            "/api/v1/trends/topics?category=basketball&window_hours=24&page_size=100"
        )
        assert topic_response.status_code == 200, topic_response.text
        topic_body = topic_response.json()
        assert topic_body["total"] >= 1
        assert all(item["category"] == "basketball" for item in topic_body["items"])

        video_response = client.get(
            "/api/v1/trends/videos?category=sports&window_hours=24&page_size=100"
        )
        assert video_response.status_code == 200, video_response.text
        video_body = video_response.json()
        assert any(
            item["external_id"] == "category-filter-general-sports"
            for item in video_body["items"]
        )

        category_response = client.get("/api/v1/trends/categories?window_hours=24")
        assert category_response.status_code == 200, category_response.text
        category_body = {item["category"]: item for item in category_response.json()}
        assert category_body["sports"]["video_count"] >= 1
        assert category_body["basketball"]["topic_count"] >= 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_trend_keywords_hide_generic_labels_and_expose_label_type(
    client: TestClient,
) -> None:
    authenticate(client)
    engine = create_async_engine(PG_ASYNC_URL)
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
                    TrendKeywordSnapshot(
                        workspace_id=workspace_id,
                        keyword="ESPN",
                        platform="web",
                        observed_at=now,
                        video_count=20,
                        heat_index=100,
                        metadata_json={"source_kind": "live"},
                    ),
                    TrendKeywordSnapshot(
                        workspace_id=workspace_id,
                        keyword="FOOTBALL",
                        platform="web",
                        observed_at=now,
                        video_count=20,
                        heat_index=99,
                        metadata_json={"source_kind": "live"},
                    ),
                    TrendKeywordSnapshot(
                        workspace_id=workspace_id,
                        keyword="LeBron",
                        platform="tiktok",
                        observed_at=now,
                        video_count=4,
                        heat_index=79,
                        metadata_json={"source_kind": "live"},
                    ),
                ]
            )
            await session.commit()

        response = client.get("/api/v1/trends/keywords?window_hours=24")
        assert response.status_code == 200, response.text
        body = response.json()
        keywords = {item["keyword"].casefold(): item for item in body}
        assert "espn" not in keywords
        assert "football" not in keywords
        assert keywords["lebron"]["metadata"]["label_type"] == "person"
    finally:
        await engine.dispose()


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


def test_reliability_slo_is_explicitly_derived_and_does_not_fill_missing_activity(
    client: TestClient,
) -> None:
    authenticate(client)
    response = client.get("/api/v1/reliability/slo?window_minutes=60")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["window_minutes"] == 60
    assert {item["key"] for item in body["metrics"]} == {
        "sync_runs",
        "external_calls",
        "notification_attempts",
        "task_runs",
        "inbox_queue",
    }
    for metric in body["metrics"]:
        assert metric["metric_kind"] == "derived"
        assert metric["observations"] == 0
        assert metric["success_rate"] is None
        assert "未使用模拟数据补齐" in " ".join(metric["notes"])
