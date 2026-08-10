"""TikTok anti-bot wall classification.

When a real login session/cookie is configured, an anti-bot wall is treated as
*transient* (retryable) so the sync's existing backoff can self-heal it. When no
session is configured the wall stays *permanent* (the operator must add a cookie).
"""

from datetime import UTC, datetime

import pytest

from app.adapters.platforms.base import (
    AdapterCallContext,
    LoginRequiredError,
    TransientAdapterError,
)
from app.adapters.platforms.tiktok_browser import TikTokBrowserAdapter


def _ctx(config: dict) -> AdapterCallContext:
    return AdapterCallContext(
        config=config,
        observed_at=datetime.now(UTC),
        request_id="test-request",
    )


def test_wall_is_retryable_when_session_configured() -> None:
    adapter = TikTokBrowserAdapter()
    ctx = _ctx({"storage_state_json": '{"cookies": []}'})
    with pytest.raises(TransientAdapterError):
        adapter._raise_login_wall(ctx, "公开页未返回账号资料（反爬拦截）")


def test_wall_is_retryable_when_netscape_cookie_configured() -> None:
    adapter = TikTokBrowserAdapter()
    ctx = _ctx({"cookies_netscape": "# Netscape HTTP Cookie File\n"})
    with pytest.raises(TransientAdapterError):
        adapter._raise_login_wall(ctx, "公开页未返回账号指标（反爬拦截）")


def test_wall_is_permanent_when_no_session() -> None:
    adapter = TikTokBrowserAdapter()
    ctx = _ctx({})
    with pytest.raises(LoginRequiredError):
        adapter._raise_login_wall(ctx, "公开页未返回账号资料（反爬拦截）")
