"""Cross-platform display-name guard tests.

Every case here is an account-layer rule that must hold identically for
YouTube, TikTok, Douyin and Bilibili. The three corruption shapes asserted
below were all found as real rows in the live database before the guard
existed (see profile_helpers module docstring).
"""

from __future__ import annotations

import pytest

from app.adapters.platforms.profile_helpers import (
    is_error_page_title,
    is_invalid_display_name,
    should_update_display_name,
)


class TestIsErrorPageTitle:
    @pytest.mark.parametrize(
        "value",
        ["404", "404 Not Found", "not found", "Page Not Found", "页面不存在", "视频不存在"],
    )
    def test_recognises_error_pages(self, value: str) -> None:
        assert is_error_page_title(value) is True

    @pytest.mark.parametrize("value", ["NBA", "Olympic Games", "404 Studios", None, ""])
    def test_leaves_real_names_alone(self, value: str | None) -> None:
        assert is_error_page_title(value) is False


class TestIsInvalidDisplayName:
    @pytest.mark.parametrize("value", [None, "", "   ", "\t\n"])
    def test_rejects_empty(self, value: str | None) -> None:
        assert is_invalid_display_name(value) is True

    @pytest.mark.parametrize("value", ["404 Not Found", "该账号不存在", "用户不存在"])
    def test_rejects_error_page_titles(self, value: str) -> None:
        """Real row: YouTube UCiio0ydw439X13KyZgMIcHw stored as '404 Not Found'."""
        assert is_invalid_display_name(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "@https://www.tiktok.com/@olympicsbringsustogether",
            "https://www.tiktok.com/@nba",
            "http://space.bilibili.com/1744580599",
            "www.douyin.com/user/abc",
        ],
    )
    def test_rejects_urls_leaked_into_the_name(self, value: str) -> None:
        """Real row: a pasted TikTok URL became the account's display name."""
        assert is_invalid_display_name(value) is True

    @pytest.mark.parametrize("value", ["的抖音", "的抖音号", "哔哩哔哩", "的快手", "主页"])
    def test_rejects_bare_platform_suffixes(self, value: str) -> None:
        """Real rows: two Douyin accounts stored as the bare suffix '的抖音'."""
        assert is_invalid_display_name(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "NBA",
            "Olympic Games",
            "咪咕体育",
            "老王的抖音",  # nickname present — must NOT be rejected
            "抖音小助手",  # contains the platform word but is a real name
            "@boltmotivation",  # handle-style names stay valid
            "🏀 Hoops Daily",
            "404 Studios",  # error-page words as part of a longer real name
        ],
    )
    def test_accepts_real_names(self, value: str) -> None:
        assert is_invalid_display_name(value) is False


class TestShouldUpdateDisplayName:
    def test_first_capture_is_written(self) -> None:
        assert should_update_display_name(None, "NBA") is True
        assert should_update_display_name("", "NBA") is True

    def test_invalid_scrape_never_overwrites_a_good_name(self) -> None:
        assert should_update_display_name("NBA", "404 Not Found") is False
        assert should_update_display_name("Olympic Motion", "的抖音") is False
        assert should_update_display_name("NBA", "https://www.tiktok.com/@nba") is False
        assert should_update_display_name("NBA", None) is False

    def test_invalid_scrape_never_overwrites_even_an_empty_name(self) -> None:
        assert should_update_display_name(None, "404 Not Found") is False

    def test_identical_name_is_skipped(self) -> None:
        assert should_update_display_name("NBA", "NBA") is False
        assert should_update_display_name("NBA", "  NBA  ") is False

    def test_genuine_rename_is_applied(self) -> None:
        assert should_update_display_name("NBA", "NBA Official") is True
