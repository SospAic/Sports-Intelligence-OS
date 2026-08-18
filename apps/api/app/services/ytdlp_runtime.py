"""Shared yt-dlp runtime discovery and command-line options.

YouTube now needs an external JavaScript runtime for complete extraction.  Keep
the discovery logic in one small module so preview, sync, search and download
workers use the same Node.js configuration.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class YtDlpRuntimeStatus(BaseModel):
    node_configured_path: str | None = None
    node_resolved_path: str | None = None
    node_available: bool = False
    node_version: str | None = None
    yt_dlp_version: str | None = None
    ejs_package_expected: bool = True
    remote_components: list[str] = Field(default_factory=list)
    update_enabled: bool = False
    update_command: str = 'python -m pip install -U "yt-dlp[default]"'
    update_note: str = (
        "容器环境建议重新构建 API/Worker 镜像；运行中的容器内更新不会持久化到下一次部署。"
    )


def configured_node_path() -> str | None:
    value = os.environ.get("SIO_YTDLP_NODE_PATH", "").strip()
    return value or None


def resolve_node_path(configured: str | None = None) -> str | None:
    """Return a usable Node executable, preferring the explicit setting."""

    requested = (configured or configured_node_path() or "").strip()
    candidates = [requested] if requested else []
    found = shutil.which("node") or shutil.which("nodejs")
    if found:
        candidates.append(found)
    # Useful when a Windows path is persisted and the worker runs outside PATH.
    if os.name == "nt":
        candidates.extend(
            [
                r"C:\Program Files\nodejs\node.exe",
                r"C:\Program Files (x86)\nodejs\node.exe",
            ]
        )
    for item in candidates:
        if not item:
            continue
        path = Path(item)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def configured_remote_components() -> list[str]:
    raw = os.environ.get("SIO_YTDLP_REMOTE_COMPONENTS", "").strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


def runtime_args(
    *,
    node_path: str | None = None,
    remote_components: list[str] | None = None,
) -> list[str]:
    """Build safe yt-dlp runtime flags.

    If Node is not installed, no flag is emitted: this preserves the existing
    non-YouTube behavior and lets yt-dlp provide its own actionable diagnostic.
    """

    resolved = resolve_node_path(node_path)
    args: list[str] = []
    if resolved:
        args += ["--js-runtimes", f"node:{resolved}"]
    for component in remote_components or configured_remote_components():
        if component in {"ejs:github", "ejs:npm"}:
            args += ["--remote-components", component]
    return args


async def _version(executable: str, *args: str, max_wait_seconds: float = 8.0) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=max_wait_seconds)
    except (OSError, TimeoutError):
        return None
    if proc.returncode != 0:
        return None
    value = out.decode("utf-8", "replace").strip()
    return value or None


async def runtime_status(*, update_enabled: bool = False) -> YtDlpRuntimeStatus:
    configured = configured_node_path()
    resolved = resolve_node_path(configured)
    node_version = await _version(resolved, "--version") if resolved else None
    yt_version = await _version(sys.executable, "-m", "yt_dlp", "--version")
    return YtDlpRuntimeStatus(
        node_configured_path=configured,
        node_resolved_path=resolved,
        node_available=bool(resolved and node_version),
        node_version=node_version,
        yt_dlp_version=yt_version,
        remote_components=configured_remote_components(),
        update_enabled=update_enabled,
    )


def runtime_config_from_settings(settings: Any) -> dict[str, Any]:
    """Expose only non-secret runtime values to command builders/tests."""

    return {
        "node_path": getattr(settings, "ytdlp_node_path", None),
        "remote_components": getattr(settings, "ytdlp_remote_components", ""),
    }
