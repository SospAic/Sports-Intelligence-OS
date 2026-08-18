"""Tests for URL-based platform auto-detection."""

from app.services.platform_detect import detect_platform_key_from_url


def test_youtube_variants():
    assert detect_platform_key_from_url("https://www.youtube.com/@foo") == "youtube"
    assert detect_platform_key_from_url("https://youtube.com/c/abc") == "youtube"
    assert detect_platform_key_from_url("https://youtu.be/xyz") == "youtube"
    assert detect_platform_key_from_url("youtube.com/@foo") == "youtube"


def test_tiktok_variants():
    assert detect_platform_key_from_url("https://www.tiktok.com/@foo") == "tiktok"
    assert detect_platform_key_from_url("tiktok.com/@foo") == "tiktok"


def test_douyin_variants():
    assert detect_platform_key_from_url("https://www.douyin.com/user/abc") == "douyin"
    assert detect_platform_key_from_url("https://v.douyin.com/xyz/") == "douyin"
    assert detect_platform_key_from_url("https://iesdouyin.com/abc") == "douyin"


def test_bilibili_variants():
    assert detect_platform_key_from_url("https://www.bilibili.com/video/av1") == "bilibili"
    assert detect_platform_key_from_url("https://b23.tv/abc") == "bilibili"


def test_handle_syntax():
    assert detect_platform_key_from_url("@youtube/foo") == "youtube"
    assert detect_platform_key_from_url("@tiktok/foo") == "tiktok"


def test_unknown_returns_none():
    assert detect_platform_key_from_url("https://example.com/foo") is None
    assert detect_platform_key_from_url("") is None
    assert detect_platform_key_from_url("   ") is None
    assert detect_platform_key_from_url("not a url") is None
