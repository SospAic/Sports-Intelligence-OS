"""Cross-platform coverage for the live sync log emitted by browser adapters.

Per the project's cross-platform consistency rule, an account-level behaviour
must land on all four platforms at once. The scrolling sync log originally only
existed on the yt-dlp path, so TikTok/Douyin/Bilibili accounts showed an empty
panel. The log line emitter now lives on the shared BrowserPlatformAdapter base,
and these tests pin that all four browser adapters inherit it.

No browser is launched: the emitter is pure, and _scroll_page is driven with a
fake page object.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.adapters.platforms.bilibili_browser import BilibiliBrowserAdapter
from app.adapters.platforms.browser_base import BrowserPlatformAdapter
from app.adapters.platforms.douyin_browser import DouyinBrowserAdapter
from app.adapters.platforms.tiktok_browser import TikTokBrowserAdapter
from app.adapters.platforms.youtube_browser import YouTubeBrowserAdapter

ALL_BROWSER_ADAPTERS = [
    TikTokBrowserAdapter,
    DouyinBrowserAdapter,
    BilibiliBrowserAdapter,
    YouTubeBrowserAdapter,
]


class _CollectingSink:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, text: str) -> None:
        self.lines.append(text)


class _FakeMouse:
    async def wheel(self, dx: int, dy: int) -> None:
        return None


class _FakePage:
    def __init__(self) -> None:
        self.mouse = _FakeMouse()


@pytest.mark.parametrize("adapter_cls", ALL_BROWSER_ADAPTERS)
def test_every_browser_adapter_inherits_the_shared_emitter(adapter_cls) -> None:
    """All four platforms must share one emitter, not re-implement it."""
    assert issubclass(adapter_cls, BrowserPlatformAdapter)
    assert adapter_cls._progress is BrowserPlatformAdapter._progress


@pytest.mark.parametrize("adapter_cls", ALL_BROWSER_ADAPTERS)
def test_progress_emits_platform_tagged_line(adapter_cls) -> None:
    adapter = adapter_cls.__new__(adapter_cls)
    sink = _CollectingSink()

    adapter._progress(SimpleNamespace(progress_sink=sink), "打开页面")

    assert sink.lines == ["打开页面"]


@pytest.mark.parametrize("adapter_cls", ALL_BROWSER_ADAPTERS)
def test_progress_is_a_noop_without_a_sink(adapter_cls) -> None:
    """A run with no sink (or no ctx at all) must not raise."""
    adapter = adapter_cls.__new__(adapter_cls)

    adapter._progress(None, "no ctx")
    adapter._progress(SimpleNamespace(progress_sink=None), "no sink")


def test_progress_swallows_a_broken_sink() -> None:
    """Observability must never abort a sync.

    This is the direct regression guard for the production incident: a
    non-callable sink was wired in, and the resulting TypeError propagated out
    of the adapter and killed every sync run on all four platforms.
    """
    adapter = TikTokBrowserAdapter.__new__(TikTokBrowserAdapter)

    not_callable = object()
    adapter._progress(SimpleNamespace(progress_sink=not_callable), "boom")

    def _raises(_text: str) -> None:
        raise RuntimeError("sink exploded")

    adapter._progress(SimpleNamespace(progress_sink=_raises), "boom")


def test_scroll_page_reports_each_step() -> None:
    adapter = TikTokBrowserAdapter.__new__(TikTokBrowserAdapter)
    adapter._min_delay = 0.0
    adapter._max_delay = 0.0
    sink = _CollectingSink()

    asyncio.run(adapter._scroll_page(_FakePage(), times=3, ctx=SimpleNamespace(progress_sink=sink)))

    assert sink.lines == [
        "[tiktok_browser] 滚动加载 1/3",
        "[tiktok_browser] 滚动加载 2/3",
        "[tiktok_browser] 滚动加载 3/3",
    ]
