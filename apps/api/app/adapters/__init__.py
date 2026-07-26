"""Platform protocol adapters are added in Prompt 04."""

from app.adapters.platforms import (
    BilibiliAdapter,
    DouyinAdapter,
    MockPlatformAdapter,
    PlatformAdapter,
    TikTokAdapter,
    YouTubeAdapter,
)

__all__ = [
    "BilibiliAdapter",
    "DouyinAdapter",
    "MockPlatformAdapter",
    "PlatformAdapter",
    "TikTokAdapter",
    "YouTubeAdapter",
]
