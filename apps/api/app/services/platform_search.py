"""Platform search helper backed by yt-dlp.

Wraps ``python -m yt_dlp`` so the hotspot module can run real searches on the
platforms yt-dlp supports (YouTube via ``ytsearch``, Bilibili via
``bilisearch``). Platforms without a working search extractor (TikTok, Douyin
— blocked by anti-bot / login walls) are reported gracefully instead of
crashing, matching the project's existing adapter constraints.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from app.services.ytdlp_runtime import runtime_args

YTDLP_TIMEOUT_SECONDS = 45.0

# Platforms yt-dlp can actually search. Extend as extractors improve.
SEARCH_BUILDERS: dict[str, Any] = {
    "youtube": lambda q, n: f"ytsearch{n}:{q}",
    "bilibili": lambda q, n: f"bilisearch:{q}",
}

# Human-readable labels + which platforms are usable for the UI scope picker.
PLATFORM_LABELS = {
    "youtube": "YouTube",
    "bilibili": "Bilibili",
    "tiktok": "TikTok",
    "douyin": "抖音",
}
SEARCHABLE_PLATFORMS = list(SEARCH_BUILDERS.keys())


async def yt_search(
    platform: str, query: str, limit: int = 10
) -> tuple[list[dict[str, Any]], str | None]:
    """Run a platform search and return ``(results, error_note)``.

    ``results`` entries: ``title, url, author, view_count, like_count, comment_count,
    published, platform``. ``error_note`` is non-None only when the search
    could not run (unconfigured platform / timeout / no output) — callers
    surface it but should not fail the whole request.
    """
    builder = SEARCH_BUILDERS.get(platform)
    if builder is None:
        label = PLATFORM_LABELS.get(platform, platform)
        return [], f"平台「{label}」暂未接入搜索（受反爬/登录限制）"

    url = builder(query, limit)
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
            "--no-progress",
            "--ignore-errors",
            "--flat-playlist",
            "--playlist-end",
            str(limit),
            *runtime_args(),
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=YTDLP_TIMEOUT_SECONDS)
    except TimeoutError:
        return [], "yt-dlp 搜索超时"
    except FileNotFoundError:
        return [], "运行环境未安装 yt-dlp"

    if not out:
        return [], (err.decode("utf-8", "replace")[:300] or "无搜索结果")

    try:
        obj = json.loads(out.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return [], "yt-dlp 输出解析失败"

    if not isinstance(obj, dict):
        return [], None

    entries = obj.get("entries") or []
    results: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        results.append(
            {
                "external_id": entry.get("id"),
                "title": entry.get("title"),
                "url": entry.get("url") or entry.get("webpage_url"),
                "author": entry.get("uploader") or entry.get("channel"),
                "cover_url": entry.get("thumbnail"),
                "view_count": entry.get("view_count"),
                "like_count": entry.get("like_count"),
                "comment_count": entry.get("comment_count"),
                "duration": entry.get("duration"),
                "published": entry.get("upload_date") or entry.get("timestamp"),
                "platform": platform,
            }
        )
    return results, None
