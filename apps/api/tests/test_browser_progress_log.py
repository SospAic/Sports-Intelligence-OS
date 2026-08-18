"""Cross-platform coverage for browser sync progress and scrolling."""

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
    adapter = adapter_cls.__new__(adapter_cls)
    adapter._progress(None, "no ctx")
    adapter._progress(SimpleNamespace(progress_sink=None), "no sink")


def test_progress_swallows_a_broken_sink() -> None:
    adapter = TikTokBrowserAdapter.__new__(TikTokBrowserAdapter)
    adapter._progress(SimpleNamespace(progress_sink=object()), "boom")

    def _raises(_text: str) -> None:
        raise RuntimeError("sink exploded")

    adapter._progress(SimpleNamespace(progress_sink=_raises), "boom")


def test_scroll_page_reports_each_step() -> None:
    adapter = TikTokBrowserAdapter.__new__(TikTokBrowserAdapter)
    adapter._min_delay = 0.0
    adapter._max_delay = 0.0
    sink = _CollectingSink()

    asyncio.run(
        adapter._scroll_page(
            _FakePage(), times=3, ctx=SimpleNamespace(progress_sink=sink)
        )
    )

    assert len(sink.lines) == 3
    assert all(line.startswith("[tiktok_browser] ") for line in sink.lines)


class _ScrollingPage:
    def __init__(self) -> None:
        self.mouse = _FakeMouse()
        self.scroll_y = 0

    async def evaluate(self, expression: str, distance: int | None = None) -> int:
        if expression == "window.scrollY":
            return self.scroll_y
        self.scroll_y += int(distance or 0)
        return self.scroll_y


def test_scroll_page_uses_document_scroll_when_available() -> None:
    adapter = TikTokBrowserAdapter.__new__(TikTokBrowserAdapter)
    adapter._min_delay = 0.0
    adapter._max_delay = 0.0
    page = _ScrollingPage()

    asyncio.run(adapter._scroll_page(page, times=2))

    assert page.scroll_y == 1300
