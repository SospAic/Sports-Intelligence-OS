"""Fast content-listing path for the yt-dlp adapter.

The legacy path ran one ``--dump-json`` over the whole channel window, which
forced a *full* extraction of every work on every sync — including works
already stored and unchanged. Measured on a real YouTube channel (20 works):
63.4s legacy vs 24.0s for the fast path when everything is new, and 11.8s in
steady state.

These tests pin the contract without touching the network:
  * a cheap ``--flat-playlist`` catalogue read decides what needs full detail;
  * only unknown works pay the per-video extraction cost;
  * extraction fans out, bounded by a per-platform concurrency ceiling;
  * anything unexpected degrades to the legacy single-shot path rather than
    failing the sync.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import UTC, datetime

import pytest

from app.adapters.platforms.base import AdapterCallContext
from app.adapters.platforms.yt_dlp import (
    YTDLP_PLATFORM_FETCH_CONCURRENCY,
    TikTokYtDlpAdapter,
    YouTubeYtDlpAdapter,
)

HANDLE = "@example"


def _ctx(**overrides) -> AdapterCallContext:
    base = AdapterCallContext(
        config={"yt_dlp": {}},
        observed_at=datetime.now(UTC),
        request_id="test-request",
    )
    return dataclasses.replace(base, **overrides)


class _FakeProc:
    """Minimal asyncio subprocess stand-in (no stdout/stderr pipes)."""

    def __init__(self, stdout: bytes, returncode: int = 0) -> None:
        self._stdout = stdout
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, b""


def _flat_line(vid: str, title: str, views: int) -> bytes:
    return (
        json.dumps(
            {
                "id": vid,
                "title": title,
                "view_count": views,
                "duration": 100,
                "url": f"https://www.youtube.com/watch?v={vid}",
            }
        ).encode()
        + b"\n"
    )


def _detail_line(vid: str, title: str) -> bytes:
    return (
        json.dumps(
            {
                "id": vid,
                "title": title,
                "description": f"description of {vid}",
                "timestamp": 1_700_000_000,
                "view_count": 999,
                "like_count": 42,
                "comment_count": 7,
                "duration": 100,
                "webpage_url": f"https://www.youtube.com/watch?v={vid}",
                "tags": ["nba"],
            }
        ).encode()
        + b"\n"
    )


class _Recorder:
    """Replays flat / detail / legacy responses and records every command."""

    def __init__(
        self,
        flat: list[str],
        *,
        detail_fails: set[str] | None = None,
        flat_output: bytes | None = None,
    ) -> None:
        self.flat = flat
        self.detail_fails = detail_fails or set()
        self.flat_output = flat_output
        self.commands: list[list[str]] = []
        self.detail_ids: list[str] = []
        self.legacy_calls = 0
        self.in_flight = 0
        self.max_in_flight = 0

    async def __call__(self, *cmd, **_kwargs):
        args = list(cmd)
        self.commands.append(args)
        if "--flat-playlist" in args:
            if self.flat_output is not None:
                return _FakeProc(self.flat_output)
            body = b"".join(_flat_line(v, f"flat {v}", 100 + i) for i, v in enumerate(self.flat))
            return _FakeProc(body)
        if "--no-playlist" in args:
            vid = args[-1].rsplit("=", 1)[-1]
            self.detail_ids.append(vid)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            # Yield control so genuinely-parallel calls overlap and the
            # in-flight high-water mark is meaningful.
            await asyncio.sleep(0.01)
            self.in_flight -= 1
            if vid in self.detail_fails:
                return _FakeProc(b"", returncode=1)
            return _FakeProc(_detail_line(vid, f"detail {vid}"))
        # Legacy single-shot playlist extraction.
        self.legacy_calls += 1
        body = b"".join(_detail_line(v, f"legacy {v}") for v in self.flat)
        return _FakeProc(body)


@pytest.fixture
def recorder(monkeypatch):
    def _install(rec: _Recorder) -> _Recorder:
        monkeypatch.setattr(asyncio, "create_subprocess_exec", rec)
        return rec

    return _install


def test_fetch_concurrency_is_clamped_per_platform() -> None:
    """A generous global setting must never make a fragile platform aggressive."""
    youtube = YouTubeYtDlpAdapter()
    tiktok = TikTokYtDlpAdapter()

    assert youtube._fetch_concurrency(_ctx(fetch_concurrency=99)) == (
        YTDLP_PLATFORM_FETCH_CONCURRENCY["youtube"]
    )
    assert tiktok._fetch_concurrency(_ctx(fetch_concurrency=99)) == (
        YTDLP_PLATFORM_FETCH_CONCURRENCY["tiktok"]
    )
    # TikTok's ceiling is strictly lower than YouTube's: anti-bot posture.
    assert tiktok._fetch_concurrency(_ctx(fetch_concurrency=99)) < youtube._fetch_concurrency(
        _ctx(fetch_concurrency=99)
    )
    # Explicitly sequential stays sequential, and garbage degrades safely.
    assert youtube._fetch_concurrency(_ctx(fetch_concurrency=1)) == 1
    assert youtube._fetch_concurrency(_ctx(fetch_concurrency=0)) == 1


@pytest.mark.anyio
async def test_legacy_path_used_when_fast_listing_is_disabled(recorder) -> None:
    """Concurrency 1 + no skip policy must reproduce the old behaviour exactly."""
    rec = recorder(_Recorder(["a1", "a2"]))
    adapter = YouTubeYtDlpAdapter()

    page = await adapter.list_contents(
        _ctx(fetch_concurrency=1, skip_known=False),
        HANDLE,
        published_after=None,
        cursor=None,
        page_size=10,
    )

    assert rec.legacy_calls == 1
    assert rec.detail_ids == []
    assert not any("--flat-playlist" in c for c in rec.commands)
    assert [item.title for item in page.items] == ["legacy a1", "legacy a2"]


@pytest.mark.anyio
async def test_known_works_skip_the_expensive_extraction(recorder) -> None:
    """Only unknown works pay the per-video extraction cost."""
    rec = recorder(_Recorder(["old1", "old2", "new1"]))
    adapter = YouTubeYtDlpAdapter()

    page = await adapter.list_contents(
        _ctx(
            fetch_concurrency=4,
            skip_known=True,
            known_external_ids=frozenset({"old1", "old2"}),
        ),
        HANDLE,
        published_after=None,
        cursor=None,
        page_size=10,
    )

    assert rec.detail_ids == ["new1"], "known works must not be re-extracted"
    assert rec.legacy_calls == 0
    # Every listed work is still returned — skipping detail is not dropping.
    by_id = {item.external_id: item for item in page.items}
    assert set(by_id) == {"old1", "old2", "new1"}
    # The known works keep their (truthful) flat catalogue data...
    assert by_id["old1"].description is None
    assert by_id["old1"].metadata["yt_view_count"] == 100
    # ...while the new work carries full detail.
    assert by_id["new1"].description == "description of new1"
    assert by_id["new1"].metadata["yt_like_count"] == 42
    assert by_id["new1"].published_at is not None


@pytest.mark.anyio
async def test_all_works_extracted_when_policy_refreshes_existing(recorder) -> None:
    """skip_known=False means a refresh sync: everything gets full detail."""
    rec = recorder(_Recorder(["v1", "v2", "v3"]))
    adapter = YouTubeYtDlpAdapter()

    page = await adapter.list_contents(
        _ctx(
            fetch_concurrency=4,
            skip_known=False,
            known_external_ids=frozenset({"v1", "v2"}),
        ),
        HANDLE,
        published_after=None,
        cursor=None,
        page_size=10,
    )

    assert sorted(rec.detail_ids) == ["v1", "v2", "v3"]
    assert all(item.description is not None for item in page.items)


@pytest.mark.anyio
async def test_detail_extraction_respects_the_concurrency_ceiling(recorder) -> None:
    """Fan-out is bounded — an unbounded gather would be an anti-bot hazard."""
    rec = recorder(_Recorder([f"v{i}" for i in range(12)]))
    adapter = YouTubeYtDlpAdapter()

    await adapter.list_contents(
        _ctx(fetch_concurrency=3, skip_known=True),
        HANDLE,
        published_after=None,
        cursor=None,
        page_size=20,
    )

    assert len(rec.detail_ids) == 12
    assert rec.max_in_flight <= 3
    assert rec.max_in_flight > 1, "the whole point is that these overlap"


@pytest.mark.anyio
async def test_failed_detail_keeps_the_catalogue_entry(recorder) -> None:
    """One unreadable work must not drop it from the page, nor fail the page."""
    rec = recorder(_Recorder(["ok1", "bad1"], detail_fails={"bad1"}))
    adapter = YouTubeYtDlpAdapter()

    page = await adapter.list_contents(
        _ctx(fetch_concurrency=4, skip_known=True),
        HANDLE,
        published_after=None,
        cursor=None,
        page_size=10,
    )

    by_id = {item.external_id: item for item in page.items}
    assert set(by_id) == {"ok1", "bad1"}
    assert by_id["ok1"].description == "description of ok1"
    # Degraded but truthful: the flat catalogue title and view count survive.
    assert by_id["bad1"].title == "flat bad1"
    assert by_id["bad1"].description is None
    assert rec.legacy_calls == 0


@pytest.mark.anyio
async def test_empty_catalogue_falls_back_to_the_legacy_path(recorder) -> None:
    """A flat read that yields nothing is ambiguous — defer to the old path.

    Empty can mean "end of catalogue" or "flat mode unsupported here". Only the
    legacy path knows how to escalate to the browser adapter, so it must run.
    """
    rec = recorder(_Recorder(["z1"], flat_output=b""))
    adapter = YouTubeYtDlpAdapter()

    page = await adapter.list_contents(
        _ctx(fetch_concurrency=4, skip_known=True),
        HANDLE,
        published_after=None,
        cursor=None,
        page_size=10,
    )

    assert rec.legacy_calls == 1
    assert [item.title for item in page.items] == ["legacy z1"]


@pytest.mark.anyio
async def test_metrics_cache_is_populated_for_every_listed_work(recorder) -> None:
    """fetch_content_analytics reads this cache and must never re-run yt-dlp."""
    recorder(_Recorder(["known1", "new1"]))
    adapter = YouTubeYtDlpAdapter()
    ctx = _ctx(
        fetch_concurrency=4,
        skip_known=True,
        known_external_ids=frozenset({"known1"}),
    )

    await adapter.list_contents(
        ctx, HANDLE, published_after=None, cursor=None, page_size=10
    )
    analytics = await adapter.fetch_content_analytics(ctx, ["known1", "new1"])

    by_id = {row.external_id: row for row in analytics}
    # The skipped work still refreshes its view count from the flat catalogue.
    assert by_id["known1"].metrics["view_count"] == 100
    assert by_id["new1"].metrics["like_count"] == 42
