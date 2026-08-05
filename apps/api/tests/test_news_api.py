from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.news import Article
from app.models.workspace import Workspace
from app.providers.news.base import NewsProvider
from app.providers.news.feed import RSSProvider
from app.providers.registry import ProviderRegistry
from app.services.news import NewsService
from app.services.news_seed import (
    DEFAULT_SOURCE_EXAMPLES,
    EXPANDED_SOURCE_EXAMPLES,
    seed_news_source_examples,
)

from .conftest import PG_ASYNC_URL, TEST_PASSWORD


def test_article_body_scraping_requires_explicit_public_page_approvals() -> None:
    enabled = {
        "article_body_scrape_enabled": True,
        "public_access_confirmed": True,
        "terms_or_license_confirmed": True,
        "robots_or_permission_confirmed": True,
        "field_necessity_confirmed": True,
        "rate_limit_confirmed": True,
    }
    assert NewsService._article_body_scrape_allowed(enabled)
    assert not NewsService._article_body_scrape_allowed(
        {**enabled, "terms_or_license_confirmed": False}
    )
    assert not NewsService._article_body_scrape_allowed({})


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def create_manual_source(client: TestClient, csrf: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/news/sources",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Editorial Desk",
            "source_type": "manual",
            "category": "user_input",
            "reliability_score": 70,
            "priority": 80,
            "config": {},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_manual_article(
    client: TestClient,
    csrf: str,
    source_id: object,
    *,
    title: str,
    url: str,
    summary: str,
    published_at: str | None,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/news/articles/manual",
        headers={"X-CSRF-Token": csrf},
        json={
            "source_id": source_id,
            "canonical_url": url,
            "title": title,
            "summary": summary,
            "published_at": published_at,
            "language": "en",
            "sport": "basketball",
            "league": "NBA",
            "country": "US",
            "visual_score": 65,
            "story_score": 80,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_manual_news_dedup_clustering_merge_split_bookmark_and_scoring(
    client: TestClient,
) -> None:
    csrf = authenticate(client)
    source = create_manual_source(client, csrf)
    secret_config = client.post(
        "/api/v1/news/sources",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Unsafe JSON",
            "source_type": "json",
            "url": "https://api.example/news",
            "category": "test",
            "config": {
                "authorization_token": "must-not-be-stored",
                "field_mappings": {"title": "title", "url": "url"},
            },
        },
    )
    assert secret_config.status_code == 422
    private_source = client.post(
        "/api/v1/news/sources",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Private Network",
            "source_type": "rss",
            "url": "http://127.0.0.1/feed",
            "category": "test",
        },
    )
    assert private_source.status_code == 422
    first = create_manual_article(
        client,
        csrf,
        source["id"],
        title="Star wins final in overtime",
        url="https://publisher.example/final?utm_source=desk",
        summary="The final ended after overtime.",
        published_at="2026-07-25T10:00:00Z",
    )
    second = create_manual_article(
        client,
        csrf,
        source["id"],
        title="Star wins final in overtime!",
        url="https://wire.example/final-copy",
        summary="The final ended after overtime.",
        published_at="2026-07-25T10:05:00Z",
    )
    third = create_manual_article(
        client,
        csrf,
        source["id"],
        title="Coach announces retirement after season",
        url="https://publisher.example/retirement",
        summary="The coach announced a retirement.",
        published_at=None,
    )

    assert first["source_kind"] == "imported"
    assert second["is_duplicate"] is True
    assert third["published_at"] is None
    duplicate_listing = client.get(
        "/api/v1/news/articles",
        params={"is_duplicate": True, "sort": "reliability_score"},
    )
    assert duplicate_listing.status_code == 200, duplicate_listing.text
    assert duplicate_listing.json()["total"] == 2

    events = client.get("/api/v1/news/events", params={"sort": "heat_score"})
    assert events.status_code == 200
    assert events.json()["total"] == 2
    event_ids = [item["id"] for item in events.json()["items"]]
    merged = client.post(
        "/api/v1/news/events/merge",
        headers={"X-CSRF-Token": csrf},
        json={"event_ids": event_ids, "title": "Combined editorial event"},
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["article_count"] == 3

    split = client.post(
        f"/api/v1/news/events/{merged.json()['id']}/split",
        headers={"X-CSRF-Token": csrf},
        json={"article_ids": [third["id"]], "title": "Retirement event"},
    )
    assert split.status_code == 200, split.text
    assert split.json()["article_count"] == 1
    bookmarked = client.patch(
        f"/api/v1/news/events/{split.json()['id']}/bookmark",
        headers={"X-CSRF-Token": csrf},
        json={"bookmarked": True},
    )
    assert bookmarked.status_code == 200
    assert bookmarked.json()["is_bookmarked"] is True
    ideas = client.get("/api/v1/news/articles", params={"is_bookmarked": True})
    assert ideas.status_code == 200
    assert ideas.json()["items"][0]["id"] == third["id"]

    scoring = client.get("/api/v1/news/scoring-config")
    assert scoring.status_code == 200
    updated = client.put(
        "/api/v1/news/scoring-config",
        headers={"X-CSRF-Token": csrf},
        json={
            "source_weight": 20,
            "freshness_weight": 30,
            "source_count_weight": 20,
            "article_count_weight": 20,
            "user_interest_weight": 10,
            "freshness_half_life_hours": 8,
            "title_similarity_threshold": 0.9,
            "event_similarity_threshold": 0.7,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == scoring.json()["version"] + 1

    source_updated = client.patch(
        f"/api/v1/news/sources/{source['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"category": "editorial_verified"},
    )
    assert source_updated.status_code == 200
    assert source_updated.json()["category"] == "editorial_verified"
    disabled = client.delete(
        f"/api/v1/news/sources/{source['id']}",
        headers={"X-CSRF-Token": csrf},
    )
    assert disabled.status_code == 204
    assert client.get(f"/api/v1/news/sources/{source['id']}").json()["enabled"] is False
    assert client.get("/api/v1/news/articles").json()["total"] == 0
    assert client.get("/api/v1/news/events").json()["total"] == 0


@pytest.mark.asyncio
async def test_rss_sync_is_auditable_and_default_examples_store_no_articles(
    client: TestClient,
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.news.enqueue_news_sync", lambda _run_id: None)

    async def allow_test_endpoint(url: str) -> str:
        return url

    monkeypatch.setattr("app.providers.news.feed.ensure_public_endpoint", allow_test_endpoint)
    csrf = authenticate(client)
    source_response = client.post(
        "/api/v1/news/sources",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "Test RSS",
            "source_type": "rss",
            "url": "https://feed.example/sports.xml",
            "category": "sports_media",
            "language": "en",
            "country": "US",
            "reliability_score": 80,
            "config": {"sport": "football", "max_pages": 1},
        },
    )
    assert source_response.status_code == 201
    source_id = source_response.json()["id"]
    queued = client.post(
        f"/api/v1/news/sources/{source_id}/sync",
        headers={"X-CSRF-Token": csrf},
        json={},
    )
    assert queued.status_code == 202, queued.text

    xml = b"""<rss version="2.0"><channel><title>Test</title>
      <item><guid>one</guid><title>Football final result</title>
      <link>https://sports.example/one</link><pubDate>Fri, 25 Jul 2026 10:00:00 GMT</pubDate>
      <description>Result report.</description></item>
    </channel></rss>"""
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=xml))
    )
    registry: ProviderRegistry[NewsProvider] = ProviderRegistry()
    registry.register(RSSProvider(client=http_client, max_attempts=1))
    engine = create_async_engine(PG_ASYNC_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await NewsService(session, registry).execute_sync(UUID(queued.json()["id"]))
        async with session_factory() as session:
            workspace_id = await session.scalar(
                select(Workspace.id).where(Workspace.slug == "test-workspace")
            )
            assert workspace_id is not None
            before = int((await session.scalar(select(func.count()).select_from(Article))) or 0)
            first_seed = await seed_news_source_examples(session, workspace_id)
            second_seed = await seed_news_source_examples(session, workspace_id)
            after = int((await session.scalar(select(func.count()).select_from(Article))) or 0)
            assert first_seed == len(DEFAULT_SOURCE_EXAMPLES) + 1 + len(EXPANDED_SOURCE_EXAMPLES)
            assert second_seed == 0
            assert before == after == 1
    finally:
        await http_client.aclose()
        await engine.dispose()

    article_listing = client.get("/api/v1/news/articles", params={"sport": "football"})
    runs = client.get(f"/api/v1/news/sources/{source_id}/sync-runs")
    sources = client.get("/api/v1/news/sources", params={"enabled": False})
    assert article_listing.status_code == 200
    assert article_listing.json()["items"][0]["source_kind"] == "live"
    assert article_listing.json()["items"][0]["published_at"].startswith("2026-07-25T10:00:00")
    assert runs.json()["items"][0]["status"] == "success"
    assert runs.json()["items"][0]["records_created"] == 1
    disabled_expanded = sum(
        not bool(spec.get("enabled", True)) for spec in EXPANDED_SOURCE_EXAMPLES
    )
    assert sources.json()["total"] == len(DEFAULT_SOURCE_EXAMPLES) + disabled_expanded
    assert all(
        item["config"].get("example_config") is True
        for item in sources.json()["items"]
        if "example_config" in item["config"]
    )
