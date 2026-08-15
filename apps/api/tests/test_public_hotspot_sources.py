"""Offline contract tests for independent public hotspot collection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.news import Source
from app.models.trends import TrendVideo
from app.models.workspace import Workspace
from app.providers.news.base import NewsArticleData, NewsPage
from app.services.trend_collector import TrendCollectorService

from .conftest import PG_ASYNC_URL


class _FakePublicProvider:
    key = "rss"

    async def fetch_latest(self, _context, *, cursor, limit):
        assert cursor is None
        assert limit == 50
        now = datetime.now(UTC)
        return NewsPage(
            items=(
                NewsArticleData(
                    external_id="fresh-1",
                    canonical_url="https://example.test/fresh-1",
                    title="NBA final has a dramatic finish",
                    summary="Fresh sports story",
                    content=None,
                    author="Reporter",
                    published_at=now - timedelta(hours=2),
                    event_time=None,
                    language="en",
                    sport="basketball",
                    league="NBA",
                    country="US",
                    source_kind="live",
                    provider="rss",
                    fetched_at=now,
                ),
                NewsArticleData(
                    external_id="old-1",
                    canonical_url="https://example.test/old-1",
                    title="Old NBA story",
                    summary=None,
                    content=None,
                    author=None,
                    published_at=now - timedelta(hours=80),
                    event_time=None,
                    language="en",
                    sport="basketball",
                    league="NBA",
                    country="US",
                    source_kind="live",
                    provider="rss",
                    fetched_at=now,
                ),
            ),
            next_cursor=None,
        )

    async def aclose(self) -> None:
        return None


class _FakeRegistry:
    def __init__(self) -> None:
        self.provider = _FakePublicProvider()

    def get(self, key: str) -> _FakePublicProvider:
        assert key == "rss"
        return self.provider

    def values(self) -> tuple[_FakePublicProvider, ...]:
        return (self.provider,)


@pytest.mark.asyncio
async def test_public_hotspot_collection_is_independent_and_truthful(
    client, database_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = client
    engine = create_async_engine(PG_ASYNC_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        workspace = await session.scalar(select(Workspace).limit(1))
        assert workspace is not None
        session.add(
            Source(
                id=uuid4(),
                workspace_id=workspace.id,
                name="Public sports RSS",
                source_type="rss",
                url="https://example.test/feed.xml",
                category="sports_media",
                language="en",
                country="US",
                reliability_score=Decimal("90"),
                priority=99,
                enabled=True,
                provider_key="rss",
                config_json={},
            )
        )
        await session.commit()
        monkeypatch.setattr(
            "app.services.trend_collector.build_news_provider_registry",
            lambda _settings: _FakeRegistry(),
        )

        result = await TrendCollectorService(session).collect_public_source_trends(workspace.id)
        await session.commit()
        videos = list(
            (
                await session.scalars(
                    select(TrendVideo).where(
                        TrendVideo.workspace_id == workspace.id,
                        TrendVideo.platform == "web",
                    )
                )
            ).all()
        )

        assert result["status"] == "collected"
        assert result["sources"] == 1
        assert result["videos"] == 1
        assert len(videos) == 1
        assert videos[0].view_count is None
        assert videos[0].metadata_json["access_method"] == "public_rss"
        assert videos[0].metadata_json["metric_available"] is False

    await engine.dispose()
