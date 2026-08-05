from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import Source

DEFAULT_SOURCE_EXAMPLES = (
    # --- ESPN ---
    # CONFIRMED DEAD (2026-07): ESPN Top Headlines returns connection errors / unreachable.
    # Kept in seed for audit trail; will not be re-enabled without verified restoration.
    (
        "ESPN Top Headlines（示例，默认停用）",
        "https://www.espn.com/espn/rss/news",
        "general_sports",
    ),
    (
        "ESPN NFL Headlines（示例，默认停用）",
        "https://www.espn.com/espn/rss/nfl/news",
        "nfl",
    ),
    (
        "ESPN NBA Headlines（示例，默认停用）",
        "https://www.espn.com/espn/rss/nba/news",
        "basketball",
    ),
    # --- CBS Sports ---
    (
        "CBS Sports Headlines（示例，默认停用）",
        "https://www.cbssports.com/rss/headlines/",
        "general_sports",
    ),
    (
        "CBS Sports NFL（示例，默认停用）",
        "https://www.cbssports.com/nfl/rss/headlines/",
        "nfl",
    ),
    (
        "CBS Sports NBA（示例，默认停用）",
        "https://www.cbssports.com/nba/rss/headlines/",
        "basketball",
    ),
    # CONFIRMED DEAD (2026-07): CBS Sports MLB RSS returns HTTP 404.
    # Kept in seed for audit trail; will not be re-enabled without verified restoration.
    (
        "CBS Sports MLB（示例，默认停用）",
        "https://www.cbssports.com/mlb/rss/headlines/",
        "baseball",
    ),
    (
        "CBS Sports NHL（示例，默认停用）",
        "https://www.cbssports.com/nhl/rss/headlines/",
        "hockey",
    ),
    # --- Yahoo Sports ---
    (
        "Yahoo Sports Top News（示例，默认停用）",
        "https://sports.yahoo.com/rss/",
        "general_sports",
    ),
    (
        "Yahoo Sports NFL（示例，默认停用）",
        "https://sports.yahoo.com/nfl/rss/",
        "nfl",
    ),
    (
        "Yahoo Sports NBA（示例，默认停用）",
        "https://sports.yahoo.com/nba/rss/",
        "basketball",
    ),
    # --- NBC Sports / Pro Football Talk ---
    (
        "ProFootballTalk - NBC Sports（示例，默认停用）",
        "https://profootballtalk.nbcsports.com/feed/",
        "nfl",
    ),
    # --- The Ringer ---
    (
        "The Ringer（示例，默认停用）",
        "https://www.theringer.com/rss/index.xml",
        "general_sports",
    ),
    # --- Deadspin ---
    (
        "Deadspin（示例，默认停用）",
        "https://deadspin.com/rss",
        "general_sports",
    ),
    # --- Official League Feeds ---
    (
        "NFL.com News（示例，默认停用）",
        "https://www.nfl.com/rss/rsslanding?searchString=home",
        "nfl",
    ),
    (
        "NBA.com News（示例，默认停用）",
        "https://www.nba.com/feeds/nba-news.rss",
        "basketball",
    ),
    (
        "MLB.com News（示例，默认停用）",
        "https://www.mlb.com/feeds/news/rss.xml",
        "baseball",
    ),
    # --- Replacement sources (added 2026-07 to cover dead ESPN Top / CBS MLB) ---
    # BBC Sport RSS: publicly documented feed at https://www.bbc.co.uk/news/10628494.
    # Terms: BBC content is © BBC; RSS available for personal/non-commercial aggregation.
    # robots.txt: allows /sport/rss.xml crawling. Rate limit: conservative ≤1 req/30 min.
    (
        "BBC Sport（示例，默认停用）",
        "http://feeds.bbci.co.uk/sport/rss.xml",
        "general_sports",
    ),
    # The Guardian Sport RSS: official open platform feed.
    # Terms: Guardian content is © Guardian News & Media; RSS provided for personal use.
    # robots.txt: allows /sport/rss crawling. Rate limit: conservative ≤1 req/30 min.
    # Field coverage: title, summary, published date, link — sufficient for article model.
    (
        "The Guardian Sport（示例，默认停用）",
        "https://www.theguardian.com/sport/rss",
        "general_sports",
    ),
    # Sports Illustrated top stories RSS.
    # Terms: SI content is © The Arena Group; RSS for personal/non-commercial use.
    # robots.txt: allows /rss crawling. Rate limit: conservative ≤1 req/30 min.
    (
        "Sports Illustrated Top Stories（示例，默认停用）",
        "https://www.si.com/rss/si_topstories.rss",
        "general_sports",
    ),
)

# Per-source config overrides: disabled_reason for dead feeds, terms notes for new feeds.
SOURCE_CONFIG_NOTES: dict[str, dict[str, str]] = {
    "ESPN Top Headlines（示例，默认停用）": {
        "disabled_reason": (
            "confirmed_unreachable: connection errors since 2026-07, no ETA for restoration"
        ),
    },
    "CBS Sports MLB（示例，默认停用）": {
        "disabled_reason": "confirmed_404: HTTP 404 since 2026-07, feed endpoint removed by CBS",
    },
    "BBC Sport（示例，默认停用）": {
        "terms": "© BBC; RSS for personal/non-commercial aggregation",
        "robots": "allows /sport/rss.xml",
        "rate_limit_basis": (
            "conservative ≤1 req/30 min; no published limit, aligned with BBC fair-use guidance"
        ),
    },
    "The Guardian Sport（示例，默认停用）": {
        "terms": "© Guardian News & Media; RSS for personal use via open platform",
        "robots": "allows /sport/rss",
        "rate_limit_basis": (
            "conservative ≤1 req/30 min; Guardian open platform TOS recommends reasonable polling"
        ),
    },
    "Sports Illustrated Top Stories（示例，默认停用）": {
        "terms": "© The Arena Group; RSS for personal/non-commercial use",
        "robots": "allows /rss",
        "rate_limit_basis": "conservative ≤1 req/30 min; no published limit",
    },
}

# ---------------------------------------------------------------------------
# Expanded sources (added 2026-08): popular open-source projects, free
# sports/community sites, expanded media RSS, and browser-scrapable sites.
# Sports-specific sources are enabled by default so the hot-intelligence
# pipeline starts ingesting immediately.  Broad technology feeds remain
# visible as opt-in sources, but must not pollute a sports workspace on first
# boot.
# ---------------------------------------------------------------------------

EXPANDED_SOURCE_EXAMPLES: list[dict[str, Any]] = [
    # --- 开源社区源 (open-source community) ---
    {
        "name": "dev.to · Sports Analytics（开源社区，默认启用）",
        "url": "https://dev.to/feed/tag/sportsanalytics",
        "sport": "general_sports",
        "category": "open_source",
        "provider_key": "rss",
        "source_type": "rss",
        "language": "en",
        "country": "US",
        "reliability_score": 70,
        "priority": 55,
        "config": {"sync_interval_seconds": 21600},
    },
    {
        "name": "dev.to · Data Science（开源社区，默认停用）",
        "url": "https://dev.to/feed/tag/datascience",
        "sport": "general_sports",
        "category": "open_source",
        "provider_key": "rss",
        "source_type": "rss",
        "language": "en",
        "country": "US",
        "reliability_score": 70,
        "priority": 55,
        "enabled": False,
        "config": {"sync_interval_seconds": 21600},
    },
    {
        "name": "Hacker News · Front Page（开源社区，默认停用）",
        "url": "https://hnrss.org/frontpage",
        "sport": "general_sports",
        "category": "open_source",
        "provider_key": "rss",
        "source_type": "rss",
        "language": "en",
        "country": "US",
        "reliability_score": 72,
        "priority": 60,
        "enabled": False,
        "config": {"sync_interval_seconds": 21600},
    },
    {
        "name": "Hacker News · Sports（开源社区，默认停用）",
        "url": "https://hnrss.org/search?q=sports",
        "sport": "general_sports",
        "category": "open_source",
        "provider_key": "rss",
        "source_type": "rss",
        "language": "en",
        "country": "US",
        "reliability_score": 72,
        "priority": 60,
        "enabled": False,
        "config": {"sync_interval_seconds": 21600},
    },
    {
        "name": "GitHub · cfbfastR releases（开源社区，默认启用）",
        "url": "https://github.com/sportsdataverse/cfbfastR/releases.atom",
        "sport": "american_football",
        "category": "open_source",
        "provider_key": "atom",
        "source_type": "atom",
        "language": "en",
        "country": "US",
        "reliability_score": 75,
        "priority": 58,
        "config": {"sync_interval_seconds": 86400},
    },
    {
        "name": "GitHub · hoopR releases（开源社区，默认启用）",
        "url": "https://github.com/sportsdataverse/hoopR/releases.atom",
        "sport": "basketball",
        "category": "open_source",
        "provider_key": "atom",
        "source_type": "atom",
        "language": "en",
        "country": "US",
        "reliability_score": 75,
        "priority": 58,
        "config": {"sync_interval_seconds": 86400},
    },
    # --- 免费体育/社区站点 (free sports & community) ---
    {
        "name": "Reddit · r/soccer（免费社区，默认停用）",
        "url": "https://www.reddit.com/r/soccer/.rss",
        "sport": "football",
        "category": "community_web",
        "provider_key": "rss",
        "source_type": "rss",
        "language": "en",
        "country": "US",
        "reliability_score": 65,
        "priority": 50,
        "enabled": False,
        "config": {"sync_interval_seconds": 21600},
    },
    {
        "name": "Reddit · r/nba（免费社区，默认停用）",
        "url": "https://www.reddit.com/r/nba/.rss",
        "sport": "basketball",
        "category": "community_web",
        "provider_key": "rss",
        "source_type": "rss",
        "language": "en",
        "country": "US",
        "reliability_score": 65,
        "priority": 50,
        "enabled": False,
        "config": {"sync_interval_seconds": 21600},
    },
    {
        "name": "Reddit · r/sports（免费社区，默认停用）",
        "url": "https://www.reddit.com/r/sports/.rss",
        "sport": "general_sports",
        "category": "community_web",
        "provider_key": "rss",
        "source_type": "rss",
        "language": "en",
        "country": "US",
        "reliability_score": 65,
        "priority": 50,
        "enabled": False,
        "config": {"sync_interval_seconds": 21600},
    },
    {
        "name": "FBref · Big 5 Leagues（免费数据站，默认启用）",
        "url": "https://fbref.com/en/comps/Big-5/Big-5-European-Leagues",
        "sport": "football",
        "category": "community_web",
        "provider_key": "browser_news",
        "source_type": "rss",
        "language": "en",
        "country": "GB",
        "reliability_score": 60,
        "priority": 35,
        "config": {"sync_interval_seconds": 86400, "preset": "fbref"},
    },
    {
        "name": "Transfermarkt · News（免费数据站，默认启用）",
        "url": "https://www.transfermarkt.com/neues/aktuell/stat",
        "sport": "football",
        "category": "community_web",
        "provider_key": "browser_news",
        "source_type": "rss",
        "language": "en",
        "country": "DE",
        "reliability_score": 60,
        "priority": 35,
        "config": {"sync_interval_seconds": 86400, "preset": "transfermarkt"},
    },
    # --- 扩充媒体 RSS (expanded media) ---
    {
        "name": "AP News · Sports（媒体，默认停用）",
        "url": "https://apnews.com/index.rss",
        "sport": "general_sports",
        "category": "sports_media",
        "provider_key": "rss",
        "source_type": "rss",
        "language": "en",
        "country": "US",
        "reliability_score": 88,
        "priority": 80,
        "enabled": False,
        "config": {"sync_interval_seconds": 18000},
    },
    {
        "name": "The Guardian · Football（媒体，默认启用）",
        "url": "https://www.theguardian.com/football/rss",
        "sport": "football",
        "category": "sports_media",
        "provider_key": "rss",
        "source_type": "rss",
        "language": "en",
        "country": "GB",
        "reliability_score": 85,
        "priority": 78,
        "config": {"sync_interval_seconds": 18000},
    },
    {
        "name": "The Guardian · NBA（媒体，默认启用）",
        "url": "https://www.theguardian.com/sport/nba/rss",
        "sport": "basketball",
        "category": "sports_media",
        "provider_key": "rss",
        "source_type": "rss",
        "language": "en",
        "country": "GB",
        "reliability_score": 85,
        "priority": 78,
        "config": {"sync_interval_seconds": 18000},
    },
    {
        "name": "NPR · Sports（媒体，默认停用）",
        "url": "https://feeds.npr.org/104092227/feed.json",
        "sport": "general_sports",
        "category": "sports_media",
        "provider_key": "json",
        "source_type": "json",
        "language": "en",
        "country": "US",
        "reliability_score": 84,
        "priority": 76,
        "enabled": False,
        "config": {
            "sync_interval_seconds": 18000,
            "field_mappings": {
                "title": "title",
                "link": "url",
                "summary": "summary",
                "published": "date_published",
            },
        },
    },
    {
        "name": "Goal · Football（媒体，默认停用）",
        "url": "https://www.goal.com/en/feeds/news",
        "sport": "football",
        "category": "sports_media",
        "provider_key": "rss",
        "source_type": "rss",
        "language": "en",
        "country": "GB",
        "reliability_score": 78,
        "priority": 72,
        "enabled": False,
        "config": {"sync_interval_seconds": 18000},
    },
]


async def seed_expanded_news_sources(session: AsyncSession, workspace_id: UUID) -> int:
    """Create the expanded default sources (enabled) if not already present."""

    created = 0
    for spec in EXPANDED_SOURCE_EXAMPLES:
        name = spec["name"]
        source_id = source_uuid(workspace_id, name)
        existing = await session.scalar(select(Source).where(Source.id == source_id))
        if existing is not None:
            continue

        config: dict[str, Any] = dict(spec.get("config", {}))
        config.setdefault("sport", spec.get("sport", "general_sports"))
        config.setdefault("sync_interval_seconds", 21600)
        config.setdefault(
            "attribution_required",
            name.split("（")[0].split(" · ")[0].strip(),
        )
        config.setdefault("store_only_feed_provided_content", True)
        if spec.get("provider_key") == "browser_news":
            config.setdefault("url", spec["url"])

        session.add(
            Source(
                id=source_uuid(workspace_id, name),
                workspace_id=workspace_id,
                name=name,
                source_type=spec["source_type"],
                url=spec["url"],
                category=spec["category"],
                language=spec.get("language"),
                country=spec.get("country"),
                reliability_score=Decimal(str(spec.get("reliability_score", 70))),
                priority=spec.get("priority", 50),
                enabled=spec.get("enabled", True),
                provider_key=spec["provider_key"],
                config_json=config,
                last_synced_at=None,
                next_sync_at=None,
                last_error_code=None,
                last_error_message=None,
            )
        )
        created += 1
    await session.commit()
    return created


def source_uuid(workspace_id: UUID, name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sports-intelligence-os:news-source:{workspace_id}:{name}")


async def seed_news_source_examples(session: AsyncSession, workspace_id: UUID) -> int:
    """Create disabled, metadata-only examples; this never downloads or stores articles."""

    # Per-source country overrides (default is "US")
    country_overrides: dict[str, str] = {
        "BBC Sport（示例，默认停用）": "GB",
        "The Guardian Sport（示例，默认停用）": "GB",
    }

    created = 0
    for name, url, sport in DEFAULT_SOURCE_EXAMPLES:
        source_id = source_uuid(workspace_id, name)
        source = await session.scalar(select(Source).where(Source.id == source_id))
        if source is not None:
            continue

        # Derive attribution from source name (text before the first "（")
        attribution = name.split("（")[0].split(" - ")[0].strip()

        config: dict[str, str | int | bool] = {
            "sport": sport,
            "sync_interval_seconds": 1800,
            "attribution_required": attribution,
            "store_only_feed_provided_content": True,
            "example_config": True,
        }
        # Merge per-source notes (disabled_reason, terms, robots, rate_limit_basis)
        if name in SOURCE_CONFIG_NOTES:
            config.update(SOURCE_CONFIG_NOTES[name])

        session.add(
            Source(
                id=source_uuid(workspace_id, name),
                workspace_id=workspace_id,
                name=name,
                source_type="rss",
                url=url,
                category="sports_media",
                language="en",
                country=country_overrides.get(name, "US"),
                reliability_score=Decimal("75"),
                priority=50,
                enabled=False,
                provider_key="rss",
                config_json=config,
                last_synced_at=None,
                next_sync_at=None,
                last_error_code=None,
                last_error_message=None,
            )
        )
        created += 1

    manual_name = "手动新闻录入"
    manual_id = source_uuid(workspace_id, manual_name)
    manual = await session.scalar(select(Source).where(Source.id == manual_id))
    if manual is None:
        session.add(
            Source(
                id=manual_id,
                workspace_id=workspace_id,
                name=manual_name,
                source_type="manual",
                url=None,
                category="user_input",
                language=None,
                country=None,
                reliability_score=Decimal("50"),
                priority=50,
                enabled=True,
                provider_key="manual_news",
                config_json={"input_mode": "manual", "example_config": False},
                last_synced_at=None,
                next_sync_at=None,
                last_error_code=None,
                last_error_message=None,
            )
        )
        created += 1
    created += await seed_expanded_news_sources(session, workspace_id)
    await session.commit()
    return created
