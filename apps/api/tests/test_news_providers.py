from datetime import UTC, datetime

import httpx
import pytest

from app.providers.news.base import NewsCallContext
from app.providers.news.browser_news import BrowserNewsProvider
from app.providers.news.feed import AtomProvider, RSSProvider
from app.providers.news.json_feed import GenericJSONFeedProvider
from app.providers.news.utils import (
    ensure_public_endpoint,
    ensure_public_media_endpoint,
    validate_source_url,
)

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def context(url: str, **config: object) -> NewsCallContext:
    return NewsCallContext(
        config={"url": url, **config},
        fetched_at=NOW,
        request_id="news-provider-test",
    )


@pytest.mark.asyncio
async def test_rss_and_atom_are_normalized_without_confusing_fetch_and_publish_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_test_endpoint(url: str) -> str:
        return url

    monkeypatch.setattr("app.providers.news.feed.ensure_public_endpoint", allow_test_endpoint)
    rss_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>Sports</title>
      <item><guid>rss-1</guid><title>Final &amp; result</title>
      <link>https://sports.example/story/?utm_source=test&amp;id=7#fragment</link>
      <description><![CDATA[<p>Team <b>wins</b>.</p>]]></description>
      <pubDate>Fri, 25 Jul 2026 10:00:00 GMT</pubDate></item>
      <item><guid>rss-2</guid><title>Publication time missing</title>
      <link>https://sports.example/missing-time</link></item>
    </channel></rss>"""
    atom_xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Atom Sports</title>
      <entry><id>atom-1</id><title>Race update</title>
      <link href="https://sports.example/race"/>
      <updated>2026-07-25T11:00:00Z</updated><summary>Lap 20 update</summary></entry>
    </feed>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=atom_xml if "atom" in request.url.path else rss_xml)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    rss = RSSProvider(client=client, max_attempts=1)
    atom = AtomProvider(client=client, max_attempts=1)
    try:
        rss_page = await rss.fetch_latest(
            context("https://feed.example/rss", language="en", sport="football"),
            cursor=None,
            limit=10,
        )
        atom_page = await atom.fetch_range(
            context("https://feed.example/atom", language="en", sport="f1"),
            start=datetime(2026, 7, 25, 10, 30, tzinfo=UTC),
            end=NOW,
            cursor=None,
            limit=10,
        )
    finally:
        await client.aclose()

    assert rss_page.items[0].canonical_url == "https://sports.example/story?id=7"
    assert rss_page.items[0].summary == "Team wins ."
    assert rss_page.items[0].published_at == datetime(2026, 7, 25, 10, 0, tzinfo=UTC)
    assert rss_page.items[1].published_at is None
    assert rss_page.items[1].fetched_at == NOW
    assert atom_page.items[0].external_id == "atom-1"
    assert atom_page.items[0].sport == "f1"


@pytest.mark.asyncio
async def test_generic_json_feed_uses_configured_mapping_and_time_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_test_endpoint(url: str) -> str:
        return url

    monkeypatch.setattr("app.providers.news.json_feed.ensure_public_endpoint", allow_test_endpoint)
    payload = {
        "data": {
            "stories": [
                {
                    "uuid": "json-1",
                    "headline": "Basketball trade",
                    "link": "https://sports.example/trade?fbclid=ignored",
                    "teaser": "A reported trade.",
                    "published": "2026-07-25T11:30:00Z",
                    "sport": "basketball",
                },
                {
                    "uuid": "json-old",
                    "headline": "Old report",
                    "link": "https://sports.example/old",
                    "published": "2026-07-20T11:30:00Z",
                },
            ]
        }
    }
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    )
    provider = GenericJSONFeedProvider(client=client, max_attempts=1)
    ctx = context(
        "https://api.example/news",
        items_path="data.stories",
        field_mappings={
            "id": "uuid",
            "title": "headline",
            "url": "link",
            "summary": "teaser",
            "published_at": "published",
            "sport": "sport",
        },
    )
    try:
        page = await provider.fetch_range(
            ctx,
            start=datetime(2026, 7, 25, 0, 0, tzinfo=UTC),
            end=NOW,
            cursor=None,
            limit=10,
        )
    finally:
        await client.aclose()
    assert len(page.items) == 1
    assert page.items[0].external_id == "json-1"
    assert page.items[0].canonical_url == "https://sports.example/trade"
    assert page.items[0].sport == "basketball"


@pytest.mark.asyncio
async def test_endpoint_resolution_rejects_hostnames_that_resolve_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PrivateResolver:
        async def getaddrinfo(self, *_args: object, **_kwargs: object) -> list[tuple]:
            return [(2, 1, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(
        "app.providers.news.utils.asyncio.get_running_loop", lambda: PrivateResolver()
    )
    with pytest.raises(ValueError, match="non-public"):
        await ensure_public_endpoint("https://public-looking.example/feed")


@pytest.mark.asyncio
async def test_known_media_url_allows_docker_synthetic_dns() -> None:
    assert (
        await ensure_public_media_endpoint("https://www.youtube.com/shorts/zOtEeA_tJFA")
        == "https://www.youtube.com/shorts/zOtEeA_tJFA"
    )


def test_media_url_allowlist_does_not_match_lookalike_hosts() -> None:
    from app.providers.news.utils import is_known_media_source

    assert is_known_media_source("https://www.youtube.com/watch?v=abc")
    assert not is_known_media_source("https://youtube.com.attacker.example/video")


@pytest.mark.asyncio
async def test_feed_dns_check_can_be_skipped_only_by_explicit_provider_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def capture_endpoint(_url: str, **kwargs: object) -> str:
        calls.append(kwargs)
        return _url

    monkeypatch.setattr("app.providers.news.feed.ensure_public_endpoint", capture_endpoint)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                content=b'<rss version="2.0"><channel><title>Sports</title></channel></rss>',
            )
        )
    )
    provider = RSSProvider(client=client, max_attempts=1, skip_dns_check=True)
    try:
        await provider.fetch_latest(context("https://feed.example/rss"), cursor=None, limit=10)
    finally:
        await client.aclose()

    assert calls == [{"skip_dns_check": True}]


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@feed.example/rss",
        "https://feed.example/rss?access_token=plain-text-secret",
    ],
)
def test_news_source_url_rejects_plaintext_credentials(url: str) -> None:
    with pytest.raises(ValueError, match="credentials|secrets"):
        validate_source_url(url)


@pytest.mark.asyncio
async def test_browser_news_normalization_caps_ui_sized_fields() -> None:
    provider = BrowserNewsProvider()
    article = await provider.normalize_article(
        {
            "title": "T" * 2_000,
            "link": "https://sports.example/story",
            "summary": "S" * 25_000,
        },
        context("https://sports.example", language="en"),
    )

    assert len(article.title) == 1_000
    assert article.summary is not None
    assert len(article.summary) == 20_000
