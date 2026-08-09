from __future__ import annotations

import json

import pytest

from app.services.platform_session_capture import (
    PLATFORM_LOGIN_URLS,
    BrowserSessionCaptureError,
    _looks_authenticated,
    _storage_state_for_platform,
    _to_netscape,
    validate_cdp_endpoint,
)

pytestmark = pytest.mark.net


def test_platform_login_urls_are_platform_specific() -> None:
    assert set(PLATFORM_LOGIN_URLS) == {"youtube", "tiktok", "douyin", "bilibili"}
    assert "youtube" in PLATFORM_LOGIN_URLS["youtube"]
    assert "tiktok.com/login" in PLATFORM_LOGIN_URLS["tiktok"]
    assert "sso.douyin.com" in PLATFORM_LOGIN_URLS["douyin"]
    assert "passport.bilibili.com/login" in PLATFORM_LOGIN_URLS["bilibili"]


def test_cdp_endpoint_is_limited_to_local_browser_hosts() -> None:
    assert validate_cdp_endpoint("http://browser:9222") == "http://browser:9222"
    assert validate_cdp_endpoint("http://host.docker.internal:9222/") == (
        "http://host.docker.internal:9222"
    )
    with pytest.raises(BrowserSessionCaptureError, match="仅允许本机"):
        validate_cdp_endpoint("http://169.254.169.254:9222")
    with pytest.raises(BrowserSessionCaptureError, match="不能包含账号密码"):
        validate_cdp_endpoint("http://user:pass@127.0.0.1:9222")


def test_cookie_capture_serializes_netscape_without_returning_json_state() -> None:
    cookies = [
        {
            "domain": ".youtube.com",
            "path": "/",
            "secure": True,
            "expires": -1,
            "name": "LOGIN_INFO",
            "value": "private-session",
        }
    ]
    rendered = _to_netscape(cookies)
    assert rendered.startswith("# Netscape HTTP Cookie File\n")
    assert ".youtube.com\tTRUE\t/\tTRUE\t0\tLOGIN_INFO\tprivate-session" in rendered
    state = _storage_state_for_platform(
        {"cookies": cookies, "origins": [{"origin": "https://www.youtube.com"}]},
        cookies,
        ("youtube.com", "google.com"),
    )
    assert json.loads(json.dumps(state))["cookies"][0]["name"] == "LOGIN_INFO"


@pytest.mark.parametrize(
    ("platform", "name"),
    [("youtube", "LOGIN_INFO"), ("tiktok", "sessionid"), ("douyin", "sid_guard")],
)
def test_cookie_capture_requires_a_login_cookie(platform: str, name: str) -> None:
    assert _looks_authenticated(platform, [{"name": name, "value": "session"}]) is True
    assert _looks_authenticated(platform, [{"name": "PREF", "value": "anonymous"}]) is False
