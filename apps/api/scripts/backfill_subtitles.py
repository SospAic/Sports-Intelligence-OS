#!/usr/bin/env python3
"""Backfill YouTube subtitles for existing ContentItems that lack them.

YouTube is the only adapter that produces subtitle artifacts (via yt-dlp).
TikTok / Douyin / Bilibili use browser adapters that only capture metadata,
so this script is intentionally scoped to the ``youtube`` platform.

It downloads subtitles ONLY (no video) via yt-dlp into the workspace media
root, reuses ``YtDlpAdapter._collect_media`` to parse the produced files, and
writes the ``subtitles`` map back onto ``ContentItem.media``. The local
semantic-search pipeline then re-indexes the richer transcript text.

Requires network access to YouTube and the ``yt-dlp`` binary on PATH (present
in the api container). Run from the api service container:

    docker compose exec -T api python scripts/backfill_subtitles.py --limit 200
    docker compose exec -T api python scripts/backfill_subtitles.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text

from app.adapters.platforms.yt_dlp import YtDlpAdapter
from app.core.config import Settings
from app.db.session import create_engine_and_session
from app.models.monitoring import Account, ContentItem, Platform

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_subtitles")

SUB_LANGS = "zh.*,en.*"


async def main(limit: int, workspace_id: str | None, dry_run: bool) -> int:
    settings = Settings()
    _engine, session_factory = create_engine_and_session(settings)
    media_root_base = os.environ.get("SIO_MEDIA_ROOT", "/workspace/media")

    processed = 0
    updated = 0

    async with session_factory() as session:
        stmt = (
            select(ContentItem, Account)
            .join(Account, ContentItem.account_id == Account.id)
            .join(Platform, Account.platform_id == Platform.id)
            .where(Platform.key == "youtube")
            .where(ContentItem.content_type == "video")
            .where(text("(content_items.media->>'subtitles') IS NULL"))
        )
        if workspace_id:
            stmt = stmt.where(ContentItem.workspace_id == workspace_id)
        stmt = stmt.order_by(ContentItem.id).limit(limit)

        rows = (await session.execute(stmt)).all()
        logger.info("found %d youtube videos without subtitles", len(rows))

        for content, account in rows:
            processed += 1
            video_id = content.external_id
            url = f"https://www.youtube.com/watch?v={video_id}"
            workspace_root = os.path.join(media_root_base, str(content.workspace_id))
            media_dir = os.path.join(workspace_root, "_backfill", account.external_id)
            os.makedirs(media_dir, exist_ok=True)
            out_tmpl = os.path.join(media_dir, video_id, "%(id)s.%(ext)s")

            if dry_run:
                logger.info("[dry-run] would fetch subtitles for %s (%s)", video_id, url)
                continue

            cmd = [
                "yt-dlp",
                "--skip-download",
                "--write-sub",
                "--sub-langs",
                SUB_LANGS,
                "-o",
                out_tmpl,
                url,
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
            except subprocess.CalledProcessError as exc:
                logger.warning("yt-dlp failed for %s: %s", video_id, (exc.stderr or "")[-200:])
                continue

            result = YtDlpAdapter._collect_media(workspace_root, media_dir, video_id)
            if not result or not result.get("subtitles"):
                logger.warning("no subtitles collected for %s", video_id)
                continue

            media = dict(content.media or {})
            media["subtitles"] = result["subtitles"]
            content.media = media
            updated += 1
            if updated % 50 == 0:
                await session.commit()
                logger.info("committed %d updates", updated)

        if not dry_run:
            await session.commit()

    logger.info("done: processed=%d updated=%d", processed, updated)
    return updated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill YouTube subtitles into content_items.media"
    )
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--workspace-id", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.workspace_id, args.dry_run))
