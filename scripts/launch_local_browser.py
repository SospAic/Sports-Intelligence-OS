#!/usr/bin/env python3
"""Launch the operator's REAL local browser (Edge/Chrome) with a remote-debugging
port so the Sports Intelligence OS adapters can scrape through it via CDP.

Why: TikTok / Douyin block the bundled headless Chromium (datacenter IP +
automation fingerprint). Driving the user's own browser reuses their real
fingerprint, residential IP and login cookies, which passes those walls.

Usage:
    python scripts/launch_local_browser.py [--port 9222] [--browser edge|chrome]
    python scripts/launch_local_browser.py --stop   # kill the launched instance

Then in the app: Settings -> Platforms -> TikTok/Douyin -> set
"本地浏览器 CDP 地址" to http://127.0.0.1:9222 (or http://host.docker.internal:9222
if the worker runs inside Docker).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

PORT = 9222
PROFILE_DIR = os.path.join(os.path.dirname(__file__), "..", "tmp", "edge_cdp_profile")


def _find_browser(browser: str) -> str | None:
    if browser == "edge":
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ]
    else:
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
    candidates += [shutil.which("msedge"), shutil.which("google-chrome"), shutil.which("chrome")]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def launch(browser: str, port: int) -> int:
    exe = _find_browser(browser)
    if not exe:
        print(f"ERROR: could not find {browser} on this machine.", file=sys.stderr)
        return 2
    profile = os.path.abspath(PROFILE_DIR)
    os.makedirs(profile, exist_ok=True)
    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Persist pid so --stop can kill it.
    pid_file = os.path.join(profile, "launcher.pid")
    with open(pid_file, "w") as f:
        f.write(str(proc.pid))
    # Give it a moment, then verify the DevTools endpoint is up.
    time.sleep(3)
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as r:
            data = r.read().decode()
        print(f"OK: {browser} launched (pid={proc.pid}). DevTools up:")
        print(f"    http://127.0.0.1:{port}/json/version")
        print(f"    {data[:120]}")
        print("\nNext: in the app set the platform's CDP endpoint to "
              f"http://127.0.0.1:{port} (or http://host.docker.internal:{port} if worker is in Docker).")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Launched but DevTools endpoint not reachable yet: {exc}", file=sys.stderr)
        return 1


def stop() -> int:
    profile = os.path.abspath(PROFILE_DIR)
    pid_file = os.path.join(profile, "launcher.pid")
    if not os.path.exists(pid_file):
        print("No launched instance found.", file=sys.stderr)
        return 1
    pid = int(open(pid_file).read().strip())
    try:
        import signal

        os.kill(pid, signal.SIGTERM)
        print(f"Stopped launched browser (pid={pid}).")
    except Exception as exc:  # noqa: BLE001
        print(f"Could not stop pid={pid}: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--browser", choices=["edge", "chrome"], default="edge")
    ap.add_argument("--stop", action="store_true", help="stop the launched instance")
    args = ap.parse_args()
    if args.stop:
        return stop()
    return launch(args.browser, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
