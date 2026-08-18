"""A download that produced no files must say *why*.

"未生成任何媒体文件（请检查清晰度 / 开关设置）" sent users hunting for a
settings bug when the real answer was "TikTok has no subtitle track for this
video". These tests pin the diagnostic wording contract.
"""

from __future__ import annotations

from app.services.download import explain_empty_download


def test_no_entries_reports_unresolvable_url() -> None:
    reason = explain_empty_download({"download_video": True}, [])
    assert "未从该地址解析到任何视频条目" in reason


def test_subtitle_only_run_without_any_track_blames_the_platform() -> None:
    reason = explain_empty_download(
        {"download_video": False, "write_subtitles": True, "subtitle_langs": "zh.*,en.*"},
        [{"extractor": "TikTok", "subtitles": {}, "automatic_captions": {}}],
    )
    assert "TikTok" in reason
    assert "不是设置问题" in reason


def test_subtitle_language_mismatch_is_called_out() -> None:
    reason = explain_empty_download(
        {"download_video": False, "write_subtitles": True, "subtitle_langs": "ja.*"},
        [{"extractor": "Youtube", "subtitles": {"en": [{}]}, "automatic_captions": {"de": [{}]}}],
    )
    assert "en" in reason and "de" in reason
    assert "ja.*" in reason


def test_tiktok_browser_empty_reason_does_not_surface_yt_dlp_parser_error() -> None:
    reason = explain_empty_download(
        {"download_video": False, "write_subtitles": True},
        [
            {
                "extractor": "tiktok_browser",
                "_sio_empty_reason": "TikTok 公开页未提供所选字幕轨道。",
            }
        ],
    )
    assert reason == "TikTok 公开页未提供所选字幕轨道。"
    assert "Unexpected response from webpage request" not in reason


def test_video_run_points_at_quality_settings() -> None:
    reason = explain_empty_download(
        {"download_video": True, "video_quality": "2160p"},
        [{"extractor": "TikTok"}],
    )
    assert "清晰度" in reason


def test_thumbnail_only_run_has_its_own_message() -> None:
    reason = explain_empty_download(
        {"download_video": False, "write_thumbnail": True},
        [{"extractor": "TikTok"}],
    )
    assert "封面" in reason


def test_no_producing_option_enabled() -> None:
    reason = explain_empty_download({"download_video": False}, [{"extractor": "TikTok"}])
    assert "未开启任何会产生文件的选项" in reason
