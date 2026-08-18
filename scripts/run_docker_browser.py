#!/usr/bin/env python3
"""Run the Docker-contained headed Chromium used for manual platform login.

The browser is visible through the local noVNC endpoint exposed by Compose.
It is intentionally isolated in a dedicated persistent profile and is not
exposed on the host's CDP port; the API reaches it through the private Compose
network at ``http://browser:9222``.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright


DISPLAY = os.environ.get("DISPLAY", ":99")
PROFILE_DIR = Path(os.environ.get("SIO_BROWSER_PROFILE_DIR", "/workspace/browser-profile"))
CDP_PORT = int(os.environ.get("SIO_BROWSER_CDP_PORT", "9222"))
CHROME_CDP_PORT = int(os.environ.get("SIO_BROWSER_CHROME_CDP_PORT", "9223"))
VNC_PORT = int(os.environ.get("SIO_BROWSER_VNC_PORT", "6080"))


def _start_process(args: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - all commands are fixed image-local binaries
        args,
        stdout=sys.stdout,
        stderr=sys.stderr,
        start_new_session=True,
    )


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return


def _clear_stale_display(display: str) -> None:
    """Remove Xvfb markers left by a crashed run in this dedicated container."""
    if not display.startswith(":"):
        return
    display_number = display[1:].split(".", 1)[0]
    lock_path = Path(f"/tmp/.X{display_number}-lock")
    socket_path = Path(f"/tmp/.X11-unix/X{display_number}")
    if lock_path.exists():
        try:
            stale_pid = int(lock_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            stale_pid = 0
        if stale_pid and stale_pid != os.getpid() and Path(f"/proc/{stale_pid}").exists():
            try:
                os.kill(stale_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            time.sleep(0.25)
        lock_path.unlink(missing_ok=True)
    socket_path.unlink(missing_ok=True)


def _wait_for_display(display: str, process: subprocess.Popen[bytes]) -> None:
    socket_path = Path(f"/tmp/.X11-unix/X{display.lstrip(':').split('.', 1)[0]}")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Xvfb exited before the display became ready")
        if socket_path.exists():
            return
        time.sleep(0.1)
    raise RuntimeError(f"Xvfb display did not become ready: {display}")
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _wait_for_url(url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except Exception as exc:  # noqa: BLE001 - retry until the child is ready
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"browser endpoint did not become ready: {url}: {last_error}")


def main() -> int:
    _clear_stale_display(DISPLAY)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    # A crash/restart can leave Chromium's process-singleton markers in the
    # named volume. This container owns the profile and starts exactly one
    # Chromium process, so stale markers are safe to remove before launch.
    for marker in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        (PROFILE_DIR / marker).unlink(missing_ok=True)
    processes: list[subprocess.Popen[bytes]] = []
    browser_process: subprocess.Popen[bytes] | None = None

    def shutdown(*_args: object) -> None:
        if browser_process is not None:
            _terminate_process(browser_process)
        for process in reversed(processes):
            _terminate_process(process)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        xvfb_process = _start_process(
            [
                "Xvfb",
                DISPLAY,
                "-screen",
                "0",
                "1440x900x24",
                "-ac",
                "+extension",
                "GLX",
                "+render",
                "-noreset",
            ]
        )
        processes.append(xvfb_process)
        _wait_for_display(DISPLAY, xvfb_process)
        processes.append(_start_process([sys.executable, "/workspace/scripts/cdp_proxy.py"]))
        processes.append(
            _start_process(
                [
                    "x11vnc",
                    "-display",
                    DISPLAY,
                    "-forever",
                    "-shared",
                    "-nopw",
                    "-rfbport",
                    "5900",
                    "-listen",
                    "0.0.0.0",
                ]
            )
        )
        processes.append(
            _start_process(
                [
                    "websockify",
                    "--web=/usr/share/novnc",
                    f"0.0.0.0:{VNC_PORT}",
                    "127.0.0.1:5900",
                ]
            )
        )
        with sync_playwright() as playwright:
            executable = playwright.chromium.executable_path
        browser_args = [
            "--remote-debugging-address=0.0.0.0",
            f"--remote-debugging-port={CHROME_CDP_PORT}",
            "--remote-allow-origins=*",
            f"--user-data-dir={PROFILE_DIR}",
            "--window-size=1440,900",
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-sandbox",
            "about:blank",
        ]
        browser_process = _start_process([executable, *browser_args])
        _wait_for_url(f"http://127.0.0.1:{CDP_PORT}/json/version")
        _wait_for_url(f"http://127.0.0.1:{VNC_PORT}/vnc.html")
        print(
            f"Docker browser ready: CDP http://0.0.0.0:{CDP_PORT}, "
            f"noVNC http://0.0.0.0:{VNC_PORT}/vnc.html",
            flush=True,
        )
        while browser_process.poll() is None:
            time.sleep(1)
    finally:
        shutdown()
    return browser_process.returncode if browser_process is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
