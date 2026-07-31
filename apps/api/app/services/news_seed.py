from decimal import Decimal
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
            "confirmed_unreachable: connection errors since 2026-07, "
            "no ETA for restoration"
        ),
    },
    "CBS Sports MLB（示例，默认停用）": {
        "disabled_reason": "confirmed_404: HTTP 404 since 2026-07, feed endpoint removed by CBS",
    },
    "BBC Sport（示例，默认停用）": {
        "terms": "© BBC; RSS for personal/non-commercial aggregation",
        "robots": "allows /sport/rss.xml",
        "rate_limit_basis": (
            "conservative ≤1 req/30 min; no published limit, "
            "aligned with BBC fair-use guidance"
        ),
    },
    "The Guardian Sport（示例，默认停用）": {
        "terms": "© Guardian News & Media; RSS for personal use via open platform",
        "robots": "allows /sport/rss",
        "rate_limit_basis": (
            "conservative ≤1 req/30 min; Guardian open platform TOS "
            "recommends reasonable polling"
        ),
    },
    "Sports Illustrated Top Stories（示例，默认停用）": {
        "terms": "© The Arena Group; RSS for personal/non-commercial use",
        "robots": "allows /rss",
        "rate_limit_basis": "conservative ≤1 req/30 min; no published limit",
    },
}


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
        source = await session.scalar(
            select(Source).where(Source.workspace_id == workspace_id, Source.name == name)
        )
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
    manual = await session.scalar(
        select(Source).where(Source.workspace_id == workspace_id, Source.name == manual_name)
    )
    if manual is None:
        session.add(
            Source(
                id=source_uuid(workspace_id, manual_name),
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
    await session.commit()
    return created
