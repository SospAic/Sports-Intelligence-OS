"""Platform protocol adapters are added in Prompt 04."""

from app.adapters.platforms import (
    BilibiliBrowserAdapter,
    DouyinAdapter,
    PlatformAdapter,
    TikTokAdapter,
    YouTubeAdapter,
)

__all__ = [
    "BilibiliBrowserAdapter",
    "DouyinAdapter",
    "PlatformAdapter",
    "TikTokAdapter",
    "YouTubeAdapter",
]
