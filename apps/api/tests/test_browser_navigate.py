"""Unit tests for ``BrowserPlatformAdapter._navigate``.

These exercise the retry / context-cleanup logic without a real browser or CDP
endpoint, so they run under the default (``not net``) test selection.
"""

from __future__ import annotations

import asyncio

import pytest

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterCapability,
    AdapterDescriptor,
    LoginRequiredError,
)
from app.adapters.platforms.browser_base import BrowserPlatformAdapter
from app.adapters.platforms.tiktok_browser import TikTokBrowserAdapter


class _FakePage:
    def __init__(self, fail: bool) -> None:
        self._fail = fail
        self.goto_calls = 0
        self.on_calls = 0

    async def goto(self, url: str, **kwargs: object) -> None:
        self.goto_calls += 1
        if self._fail:
            raise RuntimeError("net::ERR_CONNECTION_CLOSED")

    def on(self, event: str, handler: object) -> None:
        self.on_calls += 1


class _FakeContext:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _NavTestAdapter(BrowserPlatformAdapter):
    """Minimal adapter that drives ``_navigate`` with scripted failures."""

    def __init__(self, fail_pattern: list[bool]) -> None:
        super().__init__()
        self.descriptor = AdapterDescriptor(
            key="nav_test_adapter",
            name="Nav Test Adapter",
            implementation_status="implemented",
            capabilities={AdapterCapability.PUBLIC_PROFILE: True},
            config_fields=(),
            source_kinds=frozenset({"live"}),
        )
        self._fail_pattern = fail_pattern
        self._attempt = 0
        self.new_page_calls = 0
        self.pages: list[_FakePage] = []
        self.contexts: list[_FakeContext] = []

    async def _new_page(self, ctx: AdapterCallContext):  # type: ignore[override]
        self._attempt += 1
        should_fail = (
            self._fail_pattern[self._attempt - 1]
            if self._attempt - 1 < len(self._fail_pattern)
            else False
        )
        context = _FakeContext()
        page = _FakePage(fail=should_fail)
        self.new_page_calls += 1
        self.contexts.append(context)
        self.pages.append(page)
        return context, page

    # --- abstract-method stubs (never invoked by these tests) ---
    async def resolve_account(self, ctx, locator):  # noqa: D401
        raise NotImplementedError

    async def fetch_account(self, ctx, external_id):  # noqa: D401
        raise NotImplementedError

    async def list_contents(self, ctx, external_account_id, **kwargs):  # noqa: D401
        raise NotImplementedError

    async def fetch_content(self, ctx, external_id):  # noqa: D401
        raise NotImplementedError

    async def fetch_account_analytics(self, ctx, external_id):  # noqa: D401
        raise NotImplementedError

    async def fetch_content_analytics(self, ctx, external_ids):  # noqa: D401
        raise NotImplementedError


async def _instant_sleep(*_args, **_kwargs) -> None:
    return None


@pytest.fixture
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.adapters.platforms.browser_base.asyncio.sleep", _instant_sleep)


def test_navigate_retries_then_succeeds(fast_sleep: None) -> None:
    adapter = _NavTestAdapter([True, True, False])
    context, page = asyncio.run(adapter._navigate(None, "https://example.com", max_attempts=3))
    assert adapter.new_page_calls == 3
    # Failed attempts' contexts must be closed; the surviving one is live.
    assert adapter.contexts[0].closed is True
    assert adapter.contexts[1].closed is True
    assert adapter.contexts[2].closed is False
    # Only the successful attempt actually navigates.
    assert page.goto_calls == 1
    assert context is adapter.contexts[2]


def test_navigate_raises_after_exhausting_attempts(fast_sleep: None) -> None:
    adapter = _NavTestAdapter([True, True, True])
    with pytest.raises(RuntimeError):
        asyncio.run(adapter._navigate(None, "https://example.com", max_attempts=3))
    assert adapter.new_page_calls == 3
    assert all(c.closed for c in adapter.contexts)


def test_navigate_registers_response_handler_before_goto(fast_sleep: None) -> None:
    adapter = _NavTestAdapter([False])
    handler = lambda response: None  # noqa: E731 - dummy
    asyncio.run(
        adapter._navigate(None, "https://example.com", max_attempts=3, response_handler=handler)
    )
    assert adapter.pages[0].on_calls == 1


class _AnalyticsFakePage:
    """A logged-out / anti-bot limited TikTok page: no rehydration JSON and no
    count DOM elements are present, so every metric extraction path yields None.

    ``url`` is a normal profile URL, not a login redirect: this page models the
    subtler wall where TikTok serves a 200 response that is simply stripped of
    data, so ``_check_login_required``'s URL and DOM probes both find nothing
    and the failure has to be caught by the metrics-extraction branch instead.
    """

    url = "https://www.tiktok.com/@nba"

    async def goto(self, url: str, **kwargs: object) -> None:  # noqa: D401
        return None

    async def evaluate(self, _expr: str) -> None:  # noqa: D401
        return None

    def locator(self, _selector: str) -> _AnalyticsFakePage._Loc:
        return _AnalyticsFakePage._Loc()

    class _Loc:
        first = None

        async def inner_text(self) -> str:
            raise RuntimeError("element not found")


class _AnalyticsFakeContext:
    closed = False

    async def close(self) -> None:
        self.closed = True


class _AnalyticsTestAdapter(TikTokBrowserAdapter):
    def __init__(self) -> None:
        super().__init__()
        self._ctx = _AnalyticsFakeContext()
        self._page = _AnalyticsFakePage()

    async def _new_page(self, ctx: AdapterCallContext):  # type: ignore[override]
        return self._ctx, self._page

    async def _polite_delay(self, multiplier: float = 1.0) -> None:  # type: ignore[override]
        return None


def test_tiktok_analytics_raises_login_required_when_metrics_absent() -> None:
    """A logged-out / anti-bot limited page must surface the login wall itself.

    Returning an all-None metrics object would leave downstream code with only a
    vague '指标提取失败'. Raising a *retryable* error would be just as wrong: no
    number of retries can conjure data the platform refuses to serve anonymously,
    so each attempt only burns the scheduler's budget. ``LoginRequiredError`` is
    permanent and carries the one actionable instruction — configure a cookie.
    """
    adapter = _AnalyticsTestAdapter()
    with pytest.raises(LoginRequiredError) as excinfo:
        asyncio.run(adapter.fetch_account_analytics(None, "nba"))
    assert excinfo.value.retryable is False
    assert excinfo.value.code == "login_required"
