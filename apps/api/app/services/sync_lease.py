"""Redis-backed concurrency leases for account synchronization.

The adapter-level semaphores protect one process.  These leases protect the
whole Compose deployment (and remain usable when more workers are added), so
platform request pressure is bounded across workers and worker restarts.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from redis.asyncio import from_url
from redis.exceptions import RedisError

from app.core.config import Settings

_SAFE_PART = re.compile(r"[^a-zA-Z0-9_.:-]+")
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class SyncLeaseUnavailable(RuntimeError):
    """The global or platform budget was unavailable before the wait deadline."""


def _safe_part(value: str) -> str:
    return _SAFE_PART.sub("_", value.strip().casefold())[:80] or "unknown"


@dataclass(frozen=True, slots=True)
class SyncLeaseHandle:
    token: str
    keys: tuple[str, ...]
    platform_key: str
    global_slot: int
    platform_slot: int
    waited_seconds: float


class SyncConcurrencyLease:
    """Acquire one global and one platform slot with crash-safe TTLs."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._redis: Any = from_url(  # type: ignore[no-untyped-call]
            settings.redis_url, decode_responses=True
        )
        self._handle: SyncLeaseHandle | None = None

    def _global_key(self, slot: int) -> str:
        return f"sio:sync:global:{slot}"

    def _platform_key(self, platform: str, slot: int) -> str:
        return f"sio:sync:platform:{_safe_part(platform)}:{slot}"

    async def _try_slot(self, key: str, token: str) -> bool:
        lease_ttl = max(
            30,
            int(
                self._settings.sync_run_timeout_seconds
                + self._settings.sync_stale_grace_seconds
            ),
        )
        return bool(
            await self._redis.set(
                key,
                token,
                nx=True,
                ex=lease_ttl,
            )
        )

    async def acquire(self, run_id: UUID, platform_key: str) -> SyncLeaseHandle:
        token = f"{run_id}:{uuid4()}"
        started = time.monotonic()
        deadline = started + float(self._settings.sync_lease_wait_seconds)
        platform = _safe_part(platform_key)
        while True:
            acquired_global: tuple[str, int] | None = None
            try:
                for slot in range(self._settings.sync_global_concurrency):
                    key = self._global_key(slot)
                    if await self._try_slot(key, token):
                        acquired_global = (key, slot)
                        break
                if acquired_global is not None:
                    for slot in range(self._settings.sync_platform_concurrency):
                        key = self._platform_key(platform, slot)
                        if await self._try_slot(key, token):
                            handle = SyncLeaseHandle(
                                token=token,
                                keys=(acquired_global[0], key),
                                platform_key=platform_key,
                                global_slot=acquired_global[1],
                                platform_slot=slot,
                                waited_seconds=round(time.monotonic() - started, 3),
                            )
                            self._handle = handle
                            return handle
                    await self._release_key(acquired_global[0], token)
            except RedisError as exc:
                raise SyncLeaseUnavailable(f"sync concurrency lease unavailable: {exc}") from exc
            if time.monotonic() >= deadline:
                raise SyncLeaseUnavailable(
                    f"sync concurrency budget is full for {platform_key}; retrying later"
                )
            await asyncio.sleep(0.5)

    async def _release_key(self, key: str, token: str) -> None:
        await self._redis.eval(_RELEASE_SCRIPT, 1, key, token)

    async def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            await self._redis.aclose()
            return
        try:
            for key in handle.keys:
                await self._release_key(key, handle.token)
        except RedisError:
            # TTL remains the safety net when Redis is unavailable during a
            # worker crash/restart; do not mask the original sync result.
            pass
        finally:
            await self._redis.aclose()
