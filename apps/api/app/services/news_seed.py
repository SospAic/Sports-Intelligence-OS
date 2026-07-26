from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import Source

DEFAULT_SOURCE_EXAMPLES = (
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
)


def source_uuid(workspace_id: UUID, name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sports-intelligence-os:news-source:{workspace_id}:{name}")


async def seed_news_source_examples(session: AsyncSession, workspace_id: UUID) -> int:
    """Create disabled, metadata-only examples; this never downloads or stores articles."""

    created = 0
    for name, url, sport in DEFAULT_SOURCE_EXAMPLES:
        source = await session.scalar(
            select(Source).where(Source.workspace_id == workspace_id, Source.name == name)
        )
        if source is not None:
            continue
        session.add(
            Source(
                id=source_uuid(workspace_id, name),
                workspace_id=workspace_id,
                name=name,
                source_type="rss",
                url=url,
                category="sports_media",
                language="en",
                country="US",
                reliability_score=Decimal("75"),
                priority=50,
                enabled=False,
                provider_key="rss",
                config_json={
                    "sport": sport,
                    "sync_interval_seconds": 1800,
                    "attribution_required": "ESPN",
                    "store_only_feed_provided_content": True,
                    "terms_url": "https://www.espn.com/espn/news/story?page=rssinfo",
                    "example_config": True,
                },
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
