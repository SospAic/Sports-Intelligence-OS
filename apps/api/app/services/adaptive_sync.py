"""Adaptive sync-frequency scheduling.

The monitoring beat dispatches every account whose ``next_sync_at`` is due
(see ``app.tasks.monitoring.sync_all_due_accounts``). The cadence is driven by
``Account.sync_interval_seconds``. Instead of a fixed hourly interval, this
module derives the interval from each account's *recent posting cadence*: an
account that publishes several videos a day is polled far more often than a
dormant one, so we spend sync budget where signal actually appears.

The result is clamped to conservative bounds and stored back on the account, so
the existing Beat pipeline needs no change to become adaptive.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.monitoring import ContentItem

# Polling cadence bounds (seconds). Never poll faster than once an hour (to avoid
# hammering platforms / hitting rate limits) and never slower than once a day.
# The default is ~8 hours: account monitoring auto-updates on a relaxed cadence.
ADAPTIVE_SYNC_MIN_INTERVAL_SECONDS = 3_600
ADAPTIVE_SYNC_MAX_INTERVAL_SECONDS = 86_400
ADAPTIVE_SYNC_DEFAULT_INTERVAL_SECONDS = 28_800
ADAPTIVE_SYNC_SAMPLE_SIZE = 12

# Poll at roughly a quarter of the median posting gap: frequent enough to catch
# new uploads quickly, loose enough to stay polite.
ADAPTIVE_SYNC_GAP_RATIO = 0.25


async def compute_adaptive_interval(
    session: AsyncSession, account_id: UUID
) -> tuple[int, int | None]:
    """Return ``(interval_seconds, median_gap_seconds | None)``.

    The median gap between the account's most recent ``published_at`` timestamps
    sets the cadence. When there is not enough signal (fewer than two dated
    contents) we fall back to the default hourly interval and report
    ``median_gap_seconds=None`` so callers can flag the basis as ``"default"``.
    """
    statement = (
        select(ContentItem.published_at)
        .where(
            ContentItem.account_id == account_id,
            ContentItem.published_at.is_not(None),
        )
        .order_by(ContentItem.published_at.desc())
        .limit(ADAPTIVE_SYNC_SAMPLE_SIZE)
    )
    rows = [t for t in (await session.scalars(statement)).all() if t is not None]
    if len(rows) < 2:
        return ADAPTIVE_SYNC_DEFAULT_INTERVAL_SECONDS, None

    rows.sort()
    gaps = [
        (rows[i] - rows[i - 1]).total_seconds() for i in range(1, len(rows))
    ]
    gaps.sort()
    mid = len(gaps) // 2
    median_gap = (
        gaps[mid]
        if len(gaps) % 2 == 1
        else (gaps[mid - 1] + gaps[mid]) / 2.0
    )

    interval = int(median_gap * ADAPTIVE_SYNC_GAP_RATIO)
    interval = max(
        ADAPTIVE_SYNC_MIN_INTERVAL_SECONDS,
        min(ADAPTIVE_SYNC_MAX_INTERVAL_SECONDS, interval),
    )
    return interval, int(median_gap)


def interval_for_next_sync(
    base: datetime, interval_seconds: int
) -> datetime:
    """Compute the next due timestamp from a finished sync time."""
    return base + timedelta(seconds=interval_seconds)


def utcnow() -> datetime:
    return datetime.now(UTC)
