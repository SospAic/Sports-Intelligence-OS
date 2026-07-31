"""Platform protocol adapters are added in Prompt 04."""

from app.adapters.platforms import (
    BilibiliBrowserAdapter,
    DouyinAdapter,
    MockPlatformAdapter,
    PlatformAdapter,
    TikTokAdapter,
    YouTubeAdapter,
)

__all__ = [
    "BilibiliBrowserAdapter",
    "DouyinAdapter",
    "MockPlatformAdapter",
    "PlatformAdapter",
    "TikTokAdapter",
    "YouTubeAdapter",
]
