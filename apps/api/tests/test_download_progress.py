"""Regression coverage for on-demand download progress reporting."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.adapters.platforms.tiktok_browser import TikTokBrowserAdapter
from app.models.download import Download
from app.schemas.download import DownloadRead
from app.services.download import (
    DownloadService,
    _apply_progress_lines,
    _progress_line,
    _requested_files,
)
from app.tasks.monitoring import (
    _has_matching_subtitle_track,
    _subtitle_language_filter,
    _yt_dlp_session_configured,
)


def test_progress_line_extracts_stage_and_percentage() -> None:
    result = _progress_line("[download]  42.5% of 10.00MiB at 2.00MiB/s ETA 00:03")

    assert result == {
        "message": "[download] 42.5% of 10.00MiB at 2.00MiB/s ETA 00:03",
        "stage": "downloading",
        "percent": 42,
    }


def test_subtitle_language_filter_expands_selected_language_families() -> None:
    assert (
        _subtitle_language_filter(
            {"subtitle_primary_lang": "en", "subtitle_secondary_lang": "zh"}
        )
        == "en.*,zh.*"
    )
    assert (
        _subtitle_language_filter(
            {"subtitle_primary_lang": "en", "subtitle_secondary_lang": "none"}
        )
        == "en.*"
    )
    assert _subtitle_language_filter({"subtitle_langs": "ja.*,ko.*"}) == "ja.*,ko.*"
    assert _subtitle_language_filter(
        {
            "subtitle_primary_lang": "",
            "subtitle_secondary_lang": "",
            "subtitle_langs": "zh.*,en.*",
        }
    ) == "zh.*,en.*"


def test_youtube_subtitle_preflight_matches_regional_automatic_tracks() -> None:
    entry = {
        "subtitles": {},
        "automatic_captions": {"en-US": [{}], "ja": [{}]},
    }

    assert _has_matching_subtitle_track(entry, "automatic_captions", "en.*")
    assert not _has_matching_subtitle_track(entry, "subtitles", "en.*")


def test_video_strategy_is_not_treated_as_a_container() -> None:
    from app.adapters.platforms.yt_dlp import YtDlpAdapter

    assert YtDlpAdapter._video_format_selector(
        {"video_quality": "best", "video_format": "bestvideo+bestaudio"}
    ) == "bestvideo+bestaudio/best"


def test_tiktok_subtitle_fallback_requires_a_real_yt_dlp_cookie_source() -> None:
    assert _yt_dlp_session_configured({"cookies_netscape": "# Netscape HTTP Cookie File"})
    assert _yt_dlp_session_configured({"cookies_from_browser": "chrome"})
    assert not _yt_dlp_session_configured({"storage_state_json": "{}"})
    assert not _yt_dlp_session_configured({})


def test_progress_log_is_bounded_and_deduplicates_adjacent_lines() -> None:
    progress = _apply_progress_lines(None, ["[info] Extracting URL", "[info] Extracting URL"])
    progress = _apply_progress_lines(
        progress,
        [f"[download] {index}%" for index in range(121)],
    )

    assert len(progress["log"]) == 120
    assert progress["log"][-1]["message"] == "[download] 120%"
    assert progress["percent"] == 100


def test_requested_files_and_failure_method_are_explicit() -> None:
    assert _requested_files(
        {
            "download_video": False,
            "write_subtitles": True,
            "write_thumbnail": True,
            "write_info_json": True,
        }
    ) == {
        "subtitles": "pending",
        "thumbnail": "pending",
        "info_json": "pending",
    }
    assert hasattr(DownloadService, "mark_failed")
    assert hasattr(DownloadService, "recover_stale_downloads")


def test_download_read_accepts_progress_payload() -> None:
    now = datetime.now(UTC)
    row = Download(
        id=uuid4(),
        workspace_id=uuid4(),
        url="https://example.com/video",
        status="running",
        progress={
            "stage": "downloading",
            "percent": 12,
            "log": [{"at": now.isoformat(), "level": "info", "message": "12%"}],
            "files": {"video": "pending"},
        },
        created_at=now,
        updated_at=now,
    )

    result = DownloadRead.model_validate(row)

    assert result.progress["stage"] == "downloading"
    assert result.progress["files"]["video"] == "pending"


def test_tiktok_browser_media_helpers_accept_public_cdn_and_find_item() -> None:
    item = {
        "id": "7666080726214774029",
        "desc": "公开作品",
        "video": {
            "playAddr": "https://v16.tiktokcdn.com/example.mp4",
            "subtitleInfos": [
                {
                    "LanguageCode": "en",
                    "Url": "https://v16.tiktokcdn.com/example.vtt",
                    "Source": "ASR",
                }
            ],
        },
    }
    payload = {"itemList": [item]}

    assert TikTokBrowserAdapter._find_post_payload(payload, item["id"]) == item
    assert (
        TikTokBrowserAdapter._public_media_url(item["video"]["playAddr"])
        == item["video"]["playAddr"]
    )
    assert TikTokBrowserAdapter._public_media_url("https://example.com/not-tiktok.mp4") is None
    assert TikTokBrowserAdapter._select_public_video_url(
        {
            "downloadAddr": "https://v16.tiktokcdn.com/download.mp4",
            "playAddr": "https://v16.tiktokcdn.com/playback.mp4",
        }
    ) == ("https://v16.tiktokcdn.com/playback.mp4", "public_playback")
    assert TikTokBrowserAdapter._select_public_video_url(
        {"downloadAddr": "https://v16.tiktokcdn.com/download.mp4"}
    ) == ("https://v16.tiktokcdn.com/download.mp4", "public_download")
    assert TikTokBrowserAdapter._subtitle_candidates(item) == [
        {
            "url": "https://v16.tiktokcdn.com/example.vtt",
            "language": "en",
            "auto": True,
        }
    ]


def test_tiktok_subtitle_only_media_starts_from_profile_page() -> None:
    adapter = TikTokBrowserAdapter()
    calls: list[str] = []
    item = {
        "id": "7666080726214774029",
        "desc": "公开作品",
        "video": {
            "subtitleInfos": [
                {
                    "LanguageCode": "und",
                    "Url": "https://v16.tiktokcdn.com/example.vtt",
                }
            ]
        },
    }

    async def fake_navigate(_ctx, target, **kwargs):
        calls.append(target)
        response_handler = kwargs["response_handler"]

        class Response:
            url = "https://www.tiktok.com/api/item/detail/"
            headers = {"content-type": "application/json"}

            async def json(self):
                return {"itemInfo": {"itemStruct": item}}

        await response_handler(Response())
        return SimpleNamespace(request=AsyncMock()), SimpleNamespace()

    adapter._navigate = fake_navigate
    adapter._check_login_required = AsyncMock()
    adapter._polite_delay = AsyncMock()
    adapter._dispose_context = AsyncMock()

    result = asyncio.run(
        adapter.download_public_media(
            SimpleNamespace(config={}),
            "https://www.tiktok.com/@olympicsbringsustogether/video/7666080726214774029",
            "7666080726214774029",
            "C:/tmp/media",
            {
                "download_video": False,
                "write_subtitles": True,
                "subtitle_langs": "und",
                "preview_only": True,
            },
        )
    )

    assert calls == ["https://www.tiktok.com/@olympicsbringsustogether"]
    assert result["id"] == "7666080726214774029"


def test_tiktok_subtitle_only_falls_back_to_the_only_public_auto_track(tmp_path) -> None:
    adapter = TikTokBrowserAdapter()
    item = {
        "id": "7666080726214774029",
        "desc": "公开作品",
        "video": {
            "subtitleInfos": [
                {
                    "LanguageCode": "und",
                    "Url": "https://v16.tiktokcdn.com/example.vtt",
                    "Source": "ASR",
                }
            ]
        },
    }
    media_response = SimpleNamespace(ok=True, body=AsyncMock(return_value=b"WEBVTT\n"))
    request = SimpleNamespace(get=AsyncMock(return_value=media_response))
    context = SimpleNamespace(request=request)

    async def fake_navigate(_ctx, target, **kwargs):
        response_handler = kwargs["response_handler"]

        class Response:
            url = "https://www.tiktok.com/api/item/detail/"
            headers = {"content-type": "application/json"}

            async def json(self):
                return {"itemInfo": {"itemStruct": item}}

        await response_handler(Response())
        return context, SimpleNamespace()

    adapter._navigate = fake_navigate
    adapter._check_login_required = AsyncMock()
    adapter._polite_delay = AsyncMock()
    adapter._dispose_context = AsyncMock()

    result = asyncio.run(
        adapter.download_public_media(
            SimpleNamespace(config={}),
            "https://www.tiktok.com/@olympicsbringsustogether/video/7666080726214774029",
            "7666080726214774029",
            str(tmp_path),
            {
                "download_video": False,
                "write_subtitles": True,
                "write_auto_subtitles": False,
                "subtitle_langs": "zh.*,en.*",
            },
        )
    )

    assert "_sio_empty_reason" not in result
    assert request.get.await_count == 1
    assert (tmp_path / "7666080726214774029" / "7666080726214774029.und.auto.vtt").is_file()
