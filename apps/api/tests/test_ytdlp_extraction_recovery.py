"""Extraction-recovery behaviour for the yt-dlp adapter.

Anti-bot platforms (TikTok in particular) intermittently serve a stripped page
that the webpage extractor cannot parse. yt-dlp's ``--retries`` never helps
there because the HTTP request itself succeeded, so the adapter escalates to a
different extraction path. These tests pin that contract *without* touching the
network.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.adapters.platforms.base import LoginRequiredError, TransientAdapterError
from app.adapters.platforms.yt_dlp import (
    TIKTOK_RECOVERY_APP_INFO,
    YTDLP_EXTRACTION_ATTEMPTS,
    YtDlpAdapter,
    _is_permanent_extractor_error,
    _recovery_args_for,
)

REHYDRATION_ERROR = (
    "ERROR: [TikTok] 7666080726214774029: Unable to extract universal data "
    "for rehydration; please report this issue on https://github.com/yt-dlp/yt-dlp"
)

TIKTOK_URL = "https://www.tiktok.com/@olympicsbringsustogether/video/7666080726214774029"
YOUTUBE_URL = "https://www.youtube.com/watch?v=abcdefghijk"


class _FakeProc:
    """Minimal asyncio subprocess stand-in (no stdout/stderr pipes)."""

    def __init__(self, stdout: bytes, stderr: bytes, returncode: int) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def _install_fake_exec(monkeypatch, outcomes: list[tuple[bytes, bytes, int]], calls: list):
    """Patch subprocess creation to replay ``outcomes`` in order."""

    async def _fake_exec(*cmd, **_kwargs):
        calls.append(list(cmd))
        index = min(len(calls) - 1, len(outcomes) - 1)
        stdout, stderr, code = outcomes[index]
        return _FakeProc(stdout, stderr, code)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    # Keep the suite fast: recovery backoff is real wall-clock time otherwise.
    # Bind the original first — patching with a lambda that calls
    # ``asyncio.sleep`` would recurse into the patched attribute.
    real_sleep = asyncio.sleep

    async def _no_wait(*_args, **_kwargs):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _no_wait)


# --------------------------------------------------------------------------
# pure helpers
# --------------------------------------------------------------------------


def test_recovery_args_are_platform_aware() -> None:
    assert _recovery_args_for(TIKTOK_URL, 0) == []
    first = _recovery_args_for(TIKTOK_URL, 1)
    assert first == ["--extractor-args", f"tiktok:app_info={TIKTOK_RECOVERY_APP_INFO[0]}"]
    second = _recovery_args_for(TIKTOK_URL, 2)
    assert second != first
    # Non-TikTok platforms simply retry the same command.
    assert _recovery_args_for(YOUTUBE_URL, 1) == []


@pytest.mark.parametrize(
    "text",
    [
        "ERROR: Private video. Sign in if you've been granted access",
        "ERROR: Video unavailable",
        "ERROR: This video is not available in your country",
        "ERROR: Your IP address is blocked from accessing this post",
    ],
)
def test_permanent_errors_are_detected(text: str) -> None:
    assert _is_permanent_extractor_error(text) is True


def test_transient_extractor_error_is_not_permanent() -> None:
    assert _is_permanent_extractor_error(REHYDRATION_ERROR) is False


# --------------------------------------------------------------------------
# _run_yt_dlp behaviour
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tiktok_rehydration_failure_recovers_on_second_attempt(monkeypatch) -> None:
    payload = json.dumps({"id": "7666080726214774029", "title": "ok"}).encode()
    calls: list[list[str]] = []
    _install_fake_exec(
        monkeypatch,
        [
            (b"", REHYDRATION_ERROR.encode(), 1),
            (payload, b"", 0),
        ],
        calls,
    )

    entries, _ = await YtDlpAdapter()._run_yt_dlp(TIKTOK_URL, download={}, playlist_end=1)

    assert [entry["id"] for entry in entries] == ["7666080726214774029"]
    assert len(calls) == 2, "the adapter must retry after a rehydration failure"
    # The retry must use a *different* extraction path, not the same command.
    assert "--extractor-args" in calls[1]
    assert any(arg.startswith("tiktok:app_info=") for arg in calls[1])
    # The URL always stays last so yt-dlp parses recovery flags as options.
    assert calls[1][-1] == TIKTOK_URL


@pytest.mark.asyncio
async def test_permanent_error_fails_fast_without_retry(monkeypatch) -> None:
    calls: list[list[str]] = []
    _install_fake_exec(
        monkeypatch,
        [(b"", b"ERROR: [TikTok] Private video. Log into an account", 1)],
        calls,
    )

    # A login wall is permanent: it must surface as a *non-retryable* error so
    # neither the in-adapter loop nor the Celery retry ladder burns wall clock
    # on an attempt that can never succeed without credentials.
    with pytest.raises(LoginRequiredError) as excinfo:
        await YtDlpAdapter()._run_yt_dlp(TIKTOK_URL, download={}, playlist_end=1)

    assert excinfo.value.retryable is False
    assert excinfo.value.code == "login_required"
    assert len(calls) == 1, "permanent failures must not burn extra platform requests"


@pytest.mark.asyncio
async def test_rehydration_failure_is_non_retryable_after_recovery(monkeypatch) -> None:
    """#65: a TikTok anti-bot "universal data for rehydration" error must first
    burn its escalating recovery attempts, then surface as a *non-retryable*
    login wall so the Celery retry ladder does not multiply wall clock."""

    calls: list[list[str]] = []
    # Every attempt fails with the rehydration error -> recovery is exhausted.
    _install_fake_exec(
        monkeypatch,
        [(b"", REHYDRATION_ERROR.encode(), 1)] * YTDLP_EXTRACTION_ATTEMPTS,
        calls,
    )

    with pytest.raises(LoginRequiredError) as excinfo:
        await YtDlpAdapter()._run_yt_dlp(TIKTOK_URL, download={}, playlist_end=1)

    assert excinfo.value.retryable is False
    assert excinfo.value.code == "login_required"
    # The adapter must have actually tried the recovery paths before giving up.
    assert len(calls) == YTDLP_EXTRACTION_ATTEMPTS
    assert any(
        "--extractor-args" in call and any(a.startswith("tiktok:app_info=") for a in call)
        for call in calls
    )


@pytest.mark.asyncio
async def test_successful_first_attempt_does_not_retry(monkeypatch) -> None:
    payload = json.dumps({"id": "abc", "title": "ok"}).encode()
    calls: list[list[str]] = []
    _install_fake_exec(monkeypatch, [(payload, b"", 0)], calls)

    entries, _ = await YtDlpAdapter()._run_yt_dlp(YOUTUBE_URL, download={}, playlist_end=1)

    assert entries and len(calls) == 1


@pytest.mark.asyncio
async def test_timeout_is_never_retried(monkeypatch) -> None:
    """A hung subprocess must fail fast — retrying would double the wall clock."""

    calls: list[list[str]] = []

    async def _fake_exec(*cmd, **_kwargs):
        calls.append(list(cmd))
        return _FakeProc(b"", b"", 0)

    async def _timeout(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(YtDlpAdapter, "_communicate_with_timeout", staticmethod(_timeout))

    with pytest.raises(TransientAdapterError, match="timed out"):
        await YtDlpAdapter()._run_yt_dlp(TIKTOK_URL, download={}, playlist_end=1)

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_all_attempts_exhausted_raises_with_original_error(monkeypatch) -> None:
    """#65: rehydration exhaustion is a non-retryable wall, not a transient error."""

    calls: list[list[str]] = []
    _install_fake_exec(monkeypatch, [(b"", REHYDRATION_ERROR.encode(), 1)], calls)

    with pytest.raises(LoginRequiredError) as excinfo:
        await YtDlpAdapter()._run_yt_dlp(TIKTOK_URL, download={}, playlist_end=1)

    assert excinfo.value.retryable is False
    assert excinfo.value.code == "login_required"
    assert len(calls) >= 2, "exhausting attempts still means more than one try"


@pytest.mark.asyncio
async def test_single_json_account_path_also_recovers(monkeypatch) -> None:
    """Account metadata drives the monitoring product; it gets the same guard."""

    payload = json.dumps({"id": "chan", "channel": "x"}).encode()
    calls: list[list[str]] = []
    _install_fake_exec(
        monkeypatch,
        [
            (b"", REHYDRATION_ERROR.encode(), 1),
            (payload, b"", 0),
        ],
        calls,
    )

    obj, _ = await YtDlpAdapter()._run_yt_dlp_single(TIKTOK_URL)

    assert obj["id"] == "chan"
    assert len(calls) == 2
    assert any(arg.startswith("tiktok:app_info=") for arg in calls[1])
