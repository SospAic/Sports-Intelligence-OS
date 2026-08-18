"""Tests for the Celery-backed download preview (POST /downloads/preview).

The real parse runs in a worker; these tests exercise the wiring and the
result/error mapping without touching yt-dlp, the network, or the DB.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.download import _tiktok_video_id, _youtube_video_id, build_download_preview
from app.tasks.monitoring import _run_preview


def test_youtube_video_id_variants() -> None:
    assert _youtube_video_id("https://www.youtube.com/watch?v=abc123") == "abc123"
    assert _youtube_video_id("https://youtu.be/xyz789") == "xyz789"
    assert _youtube_video_id("https://www.youtube.com/shorts/abc123") == "abc123"
    assert _youtube_video_id("https://www.tiktok.com/@u/video/1") is None
    assert (
        _tiktok_video_id("https://www.tiktok.com/@u/video/7666080726214774029")
        == "7666080726214774029"
    )
    assert _tiktok_video_id("https://www.tiktok.com/@u") is None


def test_run_preview_passthrough() -> None:
    fake = {"status": "ok", "preview": {"url": "u", "title": "t"}}
    with patch("app.services.download.build_download_preview", new=AsyncMock(return_value=fake)):
        result = asyncio.run(_run_preview("https://x", uuid.uuid4()))
    assert result == fake


def test_run_preview_catches_exception() -> None:
    with patch(
        "app.services.download.build_download_preview",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = asyncio.run(_run_preview("https://x", uuid.uuid4()))
    assert result["status"] == "error"
    assert result["error_code"] == 422


class _FakeCM:
    def __init__(self, obj: object) -> None:
        self.obj = obj

    async def __aenter__(self) -> object:
        return self.obj

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _fake_engine_session(session: object) -> tuple[MagicMock, object]:
    engine = MagicMock()
    engine.dispose = AsyncMock()
    return engine, lambda: _FakeCM(session)


async def test_build_preview_ok() -> None:
    ws = uuid.uuid4()
    settings = MagicMock()
    entries = [
        {
            "id": "v1",
            "title": "T",
            "extractor": "youtube",
            "uploader": "U",
            "thumbnail": "http://t",
            "duration": 10,
            "description": "d",
            "subtitles": {"en": {}},
            "automatic_captions": {},
        }
    ]
    session = AsyncMock()
    sr = MagicMock()
    sr.return_value.get_sync_settings_config = AsyncMock(return_value={})
    ydl = MagicMock()
    ydl.return_value._run_yt_dlp = AsyncMock(return_value=(entries, {}))
    with (
        patch(
            "app.db.session.create_engine_and_session",
            return_value=_fake_engine_session(session),
        ),
        patch("app.repositories.sync.SyncRepository", sr),
        patch("app.services.platform_detect.detect_platform_key_from_url", return_value=None),
        patch(
            "app.providers.news.utils.ensure_public_media_endpoint",
            new=AsyncMock(return_value="https://x"),
        ),
        patch("app.adapters.platforms.yt_dlp.YtDlpAdapter", ydl),
    ):
        result = await build_download_preview("https://x", ws, settings)
    assert result["status"] == "ok"
    assert result["preview"]["title"] == "T"
    assert result["preview"]["subtitle_languages"] == ["en"]


async def test_build_preview_429_fallback() -> None:
    ws = uuid.uuid4()
    settings = MagicMock()
    oembed = MagicMock()
    oembed.model_dump = MagicMock(return_value={"url": "u", "title": "oembed"})
    session = AsyncMock()
    ydl = MagicMock()
    ydl.return_value._run_yt_dlp = AsyncMock(
        side_effect=Exception("HTTP Error 429: Too Many Requests")
    )
    with (
        patch(
            "app.db.session.create_engine_and_session",
            return_value=_fake_engine_session(session),
        ),
        patch(
            "app.repositories.sync.SyncRepository",
            MagicMock(**{"return_value.get_sync_settings_config": AsyncMock(return_value={})}),
        ),
        patch("app.services.platform_detect.detect_platform_key_from_url", return_value=None),
        patch(
            "app.providers.news.utils.ensure_public_media_endpoint",
            new=AsyncMock(return_value="https://www.youtube.com/watch?v=v1"),
        ),
        patch("app.adapters.platforms.yt_dlp.YtDlpAdapter", ydl),
        patch("app.services.download._youtube_oembed_preview", new=AsyncMock(return_value=oembed)),
    ):
        result = await build_download_preview("https://www.youtube.com/watch?v=v1", ws, settings)
    assert result["status"] == "ok"
    assert result["preview"]["title"] == "oembed"


async def test_build_preview_generic_error() -> None:
    ws = uuid.uuid4()
    settings = MagicMock()
    session = AsyncMock()
    ydl = MagicMock()
    ydl.return_value._run_yt_dlp = AsyncMock(side_effect=Exception("boom"))
    with (
        patch(
            "app.db.session.create_engine_and_session",
            return_value=_fake_engine_session(session),
        ),
        patch(
            "app.repositories.sync.SyncRepository",
            MagicMock(**{"return_value.get_sync_settings_config": AsyncMock(return_value={})}),
        ),
        patch("app.services.platform_detect.detect_platform_key_from_url", return_value=None),
        patch(
            "app.providers.news.utils.ensure_public_media_endpoint",
            new=AsyncMock(return_value="https://www.tiktok.com/@u/video/1"),
        ),
        patch("app.adapters.platforms.yt_dlp.YtDlpAdapter", ydl),
        patch("app.services.download._youtube_oembed_preview", new=AsyncMock(return_value=None)),
    ):
        result = await build_download_preview("https://www.tiktok.com/@u/video/1", ws, settings)
    assert result["status"] == "error"
    assert result["error_code"] == 422


async def test_build_preview_tiktok_uses_public_browser_media() -> None:
    ws = uuid.uuid4()
    settings = MagicMock()
    settings.notification_encryption_key.get_secret_value.return_value = "test-secret-key-1234"
    session = AsyncMock()
    browser = MagicMock()
    browser.return_value.download_public_media = AsyncMock(
        return_value={
            "id": "7666080726214774029",
            "title": "Public TikTok work",
            "extractor": "tiktok_browser_direct",
            "thumbnail": "https://v16.tiktokcdn.com/cover.jpg",
            "automatic_captions": {"en": [{}]},
        }
    )
    browser.return_value.aclose = AsyncMock()
    with (
        patch(
            "app.db.session.create_engine_and_session",
            return_value=_fake_engine_session(session),
        ),
        patch(
            "app.repositories.sync.SyncRepository",
            MagicMock(**{"return_value.get_sync_settings_config": AsyncMock(return_value={})}),
        ),
        patch(
            "app.services.platform_detect.detect_platform_key_from_url",
            return_value="tiktok",
        ),
        patch(
            "app.services.platform_credentials.PlatformCredentialService.resolve",
            new=AsyncMock(return_value=(None, {})),
        ),
        patch("app.adapters.platforms.tiktok_browser.TikTokBrowserAdapter", browser),
    ):
        result = await build_download_preview(
            "https://www.tiktok.com/@u/video/7666080726214774029", ws, settings
        )
    assert result["status"] == "ok"
    assert result["preview"]["platform"] == "tiktok"
    assert result["preview"]["subtitle_languages"] == ["en"]
    assert result["preview"]["subtitle_tracks"] == [{"language": "en", "kind": "automatic"}]
