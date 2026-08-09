"""Regression tests for the live sync log sink + yt-dlp progress streaming.

These exercise the helpers that power the "scrolling sync detail" panel without
touching the network: a fake subprocess for the streaming reader and a fake run
object for the metadata tail sink.

The most important case here is ``test_sink_is_callable_like_production``:
adapters receive the sink typed as ``Callable[[str], None]`` and invoke it as
``progress_callback(line)``. An earlier revision only ever tested ``sink.push``
while production wired the bare object, so every sync run died with
``TypeError: '_YtDlpLogSink' object is not callable`` and the suite stayed green.
"""

from __future__ import annotations

import asyncio

from app.adapters.platforms.yt_dlp import YtDlpAdapter
from app.services.sync import (
    SYNC_LOG_TAIL_KEY,
    PlatformSyncExecutor,
    _SyncLogSink,
)


class _FakeRun:
    """Minimal stand-in exposing the only attribute the sink touches."""

    def __init__(self) -> None:
        self.metadata_json: dict = {}


class _Reader:
    """In-memory async byte stream supporting read() and readline()."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    async def read(self, n: int = -1) -> bytes:
        if self._pos >= len(self._data):
            return b""
        end = self._pos + n if n and n > 0 else len(self._data)
        chunk = self._data[self._pos : end]
        self._pos = end
        return chunk

    async def readline(self) -> bytes:
        if self._pos >= len(self._data):
            return b""
        nl = self._data.find(b"\n", self._pos)
        if nl == -1:
            chunk = self._data[self._pos :]
            self._pos = len(self._data)
        else:
            chunk = self._data[self._pos : nl + 1]
            self._pos = nl + 1
        return chunk


class _FakeProc:
    def __init__(self, stdout: bytes, stderr: bytes) -> None:
        self.stdout = _Reader(stdout)
        self.stderr = _Reader(stderr)
        self.returncode = 0

    async def wait(self) -> int:
        return 0


def test_sink_is_callable_like_production() -> None:
    """The sink must work when invoked directly, not only via ``.push``.

    ``AdapterCallContext.progress_sink`` is handed to adapters as
    ``progress_callback`` and called as a plain function. This test drives the
    exact production shape.
    """
    run = _FakeRun()
    sink = _SyncLogSink(run)

    assert callable(sink)
    sink("[download]  42%")

    assert run.metadata_json[SYNC_LOG_TAIL_KEY] == ["[download]  42%"]


def test_sink_dedups_consecutive_and_bounds_tail() -> None:
    run = _FakeRun()
    sink = _SyncLogSink(run, max_lines=3)
    for _ in range(5):
        sink.push("[download]  10%")
    # consecutive identical lines collapse to a single entry
    assert run.metadata_json[SYNC_LOG_TAIL_KEY] == ["[download]  10%"]
    sink.push("[download]  20%")
    sink.push("[download]  30%")
    sink.push("[download]  40%")
    # tail is bounded to the last max_lines entries
    assert run.metadata_json[SYNC_LOG_TAIL_KEY] == [
        "[download]  20%",
        "[download]  30%",
        "[download]  40%",
    ]


def test_sink_strips_crlf_and_preserves_existing_metadata() -> None:
    run = _FakeRun()
    run.metadata_json = {"heartbeat_at": "2026-08-07T00:00:00+00:00"}
    sink = _SyncLogSink(run)
    sink.push("a\r\nb\n")
    # \r and \n both become spaces, leaving a double space between a and b
    assert sink._lines == ["a  b"]
    assert run.metadata_json[SYNC_LOG_TAIL_KEY] == ["a  b"]
    # pre-existing metadata keys are preserved
    assert run.metadata_json["heartbeat_at"] == "2026-08-07T00:00:00+00:00"


def test_communicate_streams_stderr_to_callback() -> None:
    # Pass the sink object itself, exactly as execute_account_run does.
    run = _FakeRun()
    sink = _SyncLogSink(run)

    async def _run() -> tuple[bytes, bytes]:
        proc = _FakeProc(
            b'{"id": "abc"}\n',
            b"[download]  10%\n[download]  20%\n",
        )
        return await YtDlpAdapter._communicate_with_timeout(
            proc, 5, stderr_callback=sink
        )

    out, err = asyncio.run(_run())
    assert out == b'{"id": "abc"}\n'
    assert err == b"[download]  10%\n[download]  20%\n"
    # the reader forwards each stderr line (with trailing newline) which the sink
    # normalises and stores in the rolling tail
    assert run.metadata_json[SYNC_LOG_TAIL_KEY] == [
        "[download]  10%",
        "[download]  20%",
    ]


def test_communicate_without_callback_returns_buffers() -> None:
    async def _run() -> tuple[bytes, bytes]:
        proc = _FakeProc(b"stdout-data", b"stderr-data")
        return await YtDlpAdapter._communicate_with_timeout(proc, 5)

    out, err = asyncio.run(_run())
    assert out == b"stdout-data"
    assert err == b"stderr-data"


def test_stage_transitions_are_mirrored_into_the_tail() -> None:
    """Stage lines make the panel useful on every platform.

    Browser adapters emit far less chatter than yt-dlp, so without this the
    TikTok/Douyin/Bilibili panel would stay empty. Driving _set_progress is also
    what guarantees stage lines and adapter lines share one writer (the sink),
    instead of racing each other over the same metadata key.
    """
    executor = PlatformSyncExecutor.__new__(PlatformSyncExecutor)
    run = _FakeRun()
    run.progress_percent = 0
    sink = _SyncLogSink(run)
    executor._log_sink = sink

    executor._set_progress(run, 12, "account_profile", "正在同步账号资料与公开指标")
    executor._set_progress(run, 25, "content_list", "正在获取作品列表")

    assert run.metadata_json[SYNC_LOG_TAIL_KEY] == [
        "▸ 正在同步账号资料与公开指标",
        "▸ 正在获取作品列表",
    ]
    # heartbeat metadata still written alongside the tail
    assert "heartbeat_at" in run.metadata_json


def test_set_progress_without_a_sink_does_not_raise() -> None:
    executor = PlatformSyncExecutor.__new__(PlatformSyncExecutor)
    executor._log_sink = None
    run = _FakeRun()
    run.progress_percent = 0

    executor._set_progress(run, 5, "validating", "正在验证采集方式与凭证")

    assert run.progress_percent == 5
