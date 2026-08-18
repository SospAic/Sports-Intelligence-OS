from app.adapters.platforms.base import PlatformAdapter
from app.adapters.platforms.bilibili_browser import BilibiliBrowserAdapter
from app.adapters.platforms.douyin import DouyinAdapter
from app.adapters.platforms.douyin_browser import DouyinBrowserAdapter
from app.adapters.platforms.tiktok import TikTokAdapter
from app.adapters.platforms.tiktok_browser import TikTokBrowserAdapter
from app.adapters.platforms.youtube import YouTubeAdapter
from app.adapters.platforms.youtube_browser import YouTubeBrowserAdapter
from app.adapters.platforms.yt_dlp import (
    DouyinYtDlpAdapter,
    TikTokYtDlpAdapter,
    YouTubeYtDlpAdapter,
)
from app.core.config import Settings
from app.providers.registry import ProviderRegistry


def build_platform_adapter_registry(
    settings: Settings | None = None,
) -> ProviderRegistry[PlatformAdapter]:
    registry: ProviderRegistry[PlatformAdapter] = ProviderRegistry()
    registry.register(
        YouTubeAdapter(
            timeout_seconds=(settings.platform_request_timeout_seconds if settings else 10.0),
            max_attempts=(settings.platform_request_max_attempts if settings else 3),
            settings=settings,
        )
    )
    registry.register(TikTokAdapter())
    registry.register(DouyinAdapter())
    # Browser adapters require an approved public-page or authorized-account mode.
    registry.register(BilibiliBrowserAdapter())
    registry.register(YouTubeBrowserAdapter())
    registry.register(TikTokBrowserAdapter())
    registry.register(DouyinBrowserAdapter())
    # yt-dlp universal adapters: command-line extraction (no browser) with an
    # automatic browser-simulation fallback. These are the default for
    # YouTube / TikTok / Douyin so monitoring no longer needs Chromium for the
    # common case while staying robust where yt-dlp is weak (e.g. Douyin).
    registry.register(YouTubeYtDlpAdapter())
    registry.register(TikTokYtDlpAdapter())
    registry.register(DouyinYtDlpAdapter())
    return registry
