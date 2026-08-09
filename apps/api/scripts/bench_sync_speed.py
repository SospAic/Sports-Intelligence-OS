"""Measure real listing speed: legacy single-shot vs fast enumerate+parallel.

Why this exists
---------------
The requirement is that syncing an account is as fast as running the standalone
downloader by hand. That is a claim about wall-clock time against a live
platform, so it cannot be verified by unit tests — those stub the subprocess
away. This script drives the *real* adapter against a *real* account and prints
a side-by-side comparison, including data-completeness counters so a "faster"
result that quietly lost fields is immediately visible.

It runs four scenarios that mirror how sync actually behaves over an account's
lifetime:

1. ``legacy``      — one ``--dump-json`` call for the whole window (old path).
2. ``all new``     — fast path with nothing stored yet (worst case).
3. ``incremental`` — fast path with all but the newest few already stored.
4. ``steady``      — fast path with everything already stored (the common case,
                     i.e. a scheduled sync that finds one or two new works).

Usage (inside the api container, needs outbound network to the platform)::

    python scripts/bench_sync_speed.py --handle @NBA --count 20
    python scripts/bench_sync_speed.py --platform tiktok --handle <handle>

Nothing here touches the database; it only exercises the adapter. Only the
platforms with a yt-dlp adapter are covered — Bilibili syncs through the
browser adapter and has no fast path to compare against.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import time
from datetime import UTC, datetime

from app.adapters.platforms.base import AdapterCallContext, AdapterPage
from app.adapters.platforms.yt_dlp import (
    DouyinYtDlpAdapter,
    TikTokYtDlpAdapter,
    YouTubeYtDlpAdapter,
)

ADAPTERS = {
    "youtube": YouTubeYtDlpAdapter,
    "tiktok": TikTokYtDlpAdapter,
    "douyin": DouyinYtDlpAdapter,
}


def _ctx(**overrides: object) -> AdapterCallContext:
    base = AdapterCallContext(
        config={"yt_dlp": {}},
        observed_at=datetime.now(UTC),
        request_id="bench-sync-speed",
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


async def _run(
    adapter: object, label: str, ctx: AdapterCallContext, handle: str, count: int
) -> AdapterPage:
    started = time.perf_counter()
    page: AdapterPage = await adapter.list_contents(  # type: ignore[attr-defined]
        ctx, handle, published_after=None, cursor=None, page_size=count
    )
    elapsed = time.perf_counter() - started
    # Completeness counters: a speed win that drops these is a regression, not
    # an optimisation.
    described = sum(1 for item in page.items if item.description)
    dated = sum(1 for item in page.items if item.published_at)
    liked = sum(1 for item in page.items if item.metadata.get("yt_like_count") is not None)
    print(
        f"{label:<34} {elapsed:6.1f}s  items={len(page.items):>3}  "
        f"desc={described:>3} published={dated:>3} like={liked:>3}",
        flush=True,
    )
    return page


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default="youtube", choices=sorted(ADAPTERS))
    parser.add_argument("--handle", default="@NBA", help="account handle / id on the platform")
    parser.add_argument("--count", type=int, default=20, help="works to list per scenario")
    parser.add_argument("--concurrency", type=int, default=8, help="requested detail concurrency")
    parser.add_argument(
        "--skip-legacy",
        action="store_true",
        help="skip the slow baseline run when you only want fast-path numbers",
    )
    args = parser.parse_args()

    adapter = ADAPTERS[args.platform]()
    print(f"platform={args.platform} handle={args.handle} count={args.count}\n")

    if not args.skip_legacy:
        # concurrency=1 and skip_known=False makes list_contents take the old
        # single-shot branch, which is exactly the baseline we want to beat.
        await _run(
            adapter,
            "legacy single-shot",
            _ctx(fetch_concurrency=1, skip_known=False),
            args.handle,
            args.count,
        )

    page = await _run(
        adapter,
        "fast, all new",
        _ctx(fetch_concurrency=args.concurrency, skip_known=False),
        args.handle,
        args.count,
    )

    ids = [item.external_id for item in page.items]
    if len(ids) > 2:
        known = frozenset(ids[2:])
        await _run(
            adapter,
            f"fast, incremental ({len(known)} known)",
            _ctx(
                fetch_concurrency=args.concurrency,
                skip_known=True,
                known_external_ids=known,
            ),
            args.handle,
            args.count,
        )

    await _run(
        adapter,
        "fast, steady state (all known)",
        _ctx(
            fetch_concurrency=args.concurrency,
            skip_known=True,
            known_external_ids=frozenset(ids),
        ),
        args.handle,
        args.count,
    )


if __name__ == "__main__":
    asyncio.run(main())
