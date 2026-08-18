"""Redis-backed daily budget gates for the shared YouTube API key.

YouTube's granular quota buckets are project-wide, not workspace-wide.  The
collector therefore keeps a conservative, key-scoped budget in Redis and
fails closed when the guard is unavailable.  Public RSS/Atom collection can
continue independently when an API window is skipped or exhausted.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings

_PACIFIC = ZoneInfo("America/Los_Angeles")
_RESERVE_SCRIPT = """
local current = tonumber(redis.call('get', KEYS[1]) or '0')
local budget = tonumber(ARGV[1])
local amount = tonumber(ARGV[2])
if current + amount > budget then
  return -1
end
local next_value = current + amount
redis.call('set', KEYS[1], next_value, 'EX', ARGV[3])
return next_value
"""


QuotaBucket = Literal["search", "general"]


@dataclass(frozen=True, slots=True)
class QuotaDecision:
    allowed: bool
    reason: str
    used: int | None = None
    remaining: int | None = None


def quota_day(now: datetime | None = None) -> date:
    """Return the YouTube quota day, which resets at midnight Pacific time."""

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(_PACIFIC).date()


def seconds_until_quota_reset(now: datetime | None = None) -> int:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    local = current.astimezone(_PACIFIC)
    next_midnight = (local + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(60, int((next_midnight - local).total_seconds()))


class YouTubeQuotaBudget:
    """Conservative, distributed quota gates for one YouTube API key."""

    def __init__(self, settings: Settings, *, api_key: str, redis: Any | None = None) -> None:
        self._settings = settings
        self._scope = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
        self._redis: Any = redis or Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
        )
        self._owns_redis = redis is None

    @property
    def scope(self) -> str:
        """Return a non-secret identifier useful for logs and diagnostics."""

        return self._scope

    def _counter_key(self, bucket: QuotaBucket) -> str:
        return f"sio:youtube:quota:{self._scope}:{bucket}:{quota_day().isoformat()}"

    def _gate_key(self, name: str, bucket: str) -> str:
        return f"sio:youtube:gate:{self._scope}:{name}:{bucket}"

    def _budget(self, bucket: QuotaBucket) -> int:
        if bucket == "search":
            return self._settings.youtube_search_daily_budget
        return self._settings.youtube_general_daily_budget

    async def reserve(self, bucket: QuotaBucket, amount: int = 1) -> QuotaDecision:
        """Reserve quota before a request; Redis failures fail closed."""

        if amount < 1:
            raise ValueError("quota reservation amount must be positive")
        budget = self._budget(bucket)
        try:
            used = int(
                await self._redis.eval(
                    _RESERVE_SCRIPT,
                    1,
                    self._counter_key(bucket),
                    str(budget),
                    str(amount),
                    str(seconds_until_quota_reset()),
                )
            )
        except (RedisError, OSError, TimeoutError):
            return QuotaDecision(False, "quota_guard_unavailable")
        if used < 0:
            return QuotaDecision(False, "daily_budget_exhausted", remaining=0)
        return QuotaDecision(True, "reserved", used=used, remaining=max(0, budget - used))

    async def claim_daily_lane_sweep(self, workspace_id: UUID) -> QuotaDecision:
        """Allow one lane sweep per workspace and quota day."""

        day = quota_day().isoformat()
        key = self._gate_key("lane-sweep", f"{day}:{workspace_id}")
        try:
            claimed = await self._redis.set(
                key,
                "1",
                nx=True,
                ex=seconds_until_quota_reset(),
            )
        except (RedisError, OSError, TimeoutError):
            return QuotaDecision(False, "quota_guard_unavailable")
        if not claimed:
            return QuotaDecision(False, "lane_sweep_already_claimed")
        return QuotaDecision(True, "lane_sweep_claimed")

    async def claim_chart_window(self) -> QuotaDecision:
        """Allow one global chart refresh in the configured time window."""

        interval = self._settings.youtube_chart_refresh_seconds
        bucket = str(int(datetime.now(UTC).timestamp()) // interval)
        key = self._gate_key("chart", bucket)
        try:
            claimed = await self._redis.set(key, "1", nx=True, ex=interval + 120)
        except (RedisError, OSError, TimeoutError):
            return QuotaDecision(False, "quota_guard_unavailable")
        if not claimed:
            return QuotaDecision(False, "chart_window_already_claimed")
        return QuotaDecision(True, "chart_window_claimed")

    async def aclose(self) -> None:
        if self._owns_redis:
            await self._redis.aclose()
