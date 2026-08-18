"""Contract tests for the hotspot topic evidence chain."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.news import Article, Source
from app.models.trends import TrendTopic, TrendVideo
from app.models.workspace import Workspace

from .conftest import PG_SYNC_URL, TEST_PASSWORD


def test_topic_evidence_returns_news_links_and_related_video_samples(client) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert login.status_code == 200, login.text

    now = datetime.now(UTC)
    engine = create_engine(PG_SYNC_URL)
    with Session(engine) as session:
        workspace = session.scalar(select(Workspace).limit(1))
        assert workspace is not None
        source = Source(
            id=uuid4(),
            workspace_id=workspace.id,
            name="Sports Desk",
            source_type="rss",
            url="https://example.test/feed.xml",
            category="sports",
            reliability_score=Decimal("92"),
            priority=80,
            enabled=True,
            provider_key="rss",
            config_json={},
        )
        article = Article(
            id=uuid4(),
            workspace_id=workspace.id,
            source_id=source.id,
            external_id="article-nba-1",
            canonical_url="https://example.test/nba-final",
            title="NBA final produces a late comeback",
            summary="The NBA final turned in the fourth quarter.",
            fetched_at=now,
            published_at=now,
            content_hash="a" * 64,
            source_kind="live",
            source_provider="rss",
            source_url="https://example.test/feed.xml",
        )
        topic = TrendTopic(
            id=uuid4(),
            workspace_id=workspace.id,
            platform="web",
            title="NBA",
            category="basketball",
            heat_score=82,
            rank=1,
            sample_size=3,
            metadata_json={
                "source_kind": "live",
                "provider": "public_rss_aggregate",
                "source_article_refs": [{"external_id": "article-nba-1"}],
            },
            observed_at=now,
        )
        video = TrendVideo(
            id=uuid4(),
            workspace_id=workspace.id,
            platform="youtube",
            external_id="video-nba-1",
            title="NBA final comeback highlights",
            video_url="https://youtube.example/watch/video-nba-1",
            view_count=100_000,
            like_count=4_000,
            breakout_score=78,
            metadata_json={
                "source_kind": "live",
                "provider": "youtube_data_api_v3",
            },
            observed_at=now,
        )
        session.add_all([source, article, topic, video])
        session.commit()
        topic_id = topic.id

    engine.dispose()

    response = client.get(f"/api/v1/trends/topics/{topic_id}/evidence")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["topic"]["title"] == "NBA"
    assert payload["news"][0]["url"] == "https://example.test/nba-final"
    assert payload["news"][0]["matched_by"] == "采集引用"
    assert payload["videos"][0]["external_id"] == "video-nba-1"
    assert payload["videos"][0]["view_count"] == 100_000
    assert payload["coverage"]["exact_reference_news"] == 1

