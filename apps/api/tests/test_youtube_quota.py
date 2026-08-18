"""Unit tests for the shared YouTube daily quota gates."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.youtube_quota import YouTubeQuotaBudget, quota_day


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int | str] = {}

    async def eval(
        self,
        _script: str,
        _key_count: int,
        key: str,
        budget: str,
        amount: str,
        _ttl: str,
    ) -> int:
        current = int(self.values.get(key, 0))
        requested = int(amount)
        if current + requested > int(budget):
            return -1
        self.values[key] = current + requested
        return current + requested

    async def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
        _ = ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def aclose(self) -> None:
        return None


def test_quota_day_follows_pacific_reset() -> None:
    before_reset = datetime(2026, 8, 19, 6, 59, tzinfo=UTC)
    after_reset = datetime(2026, 8, 19, 7, 0, tzinfo=UTC)

    assert quota_day(before_reset).isoformat() == "2026-08-18"
    assert quota_day(after_reset).isoformat() == "2026-08-19"


@pytest.mark.asyncio
async def test_quota_budget_reserves_and_stops_at_daily_limit() -> None:
    settings = Settings(
        redis_url="redis://test",
        youtube_search_daily_budget=2,
        youtube_general_daily_budget=3,
    )
    budget = YouTubeQuotaBudget(settings, api_key="test-key", redis=_FakeRedis())

    first = await budget.reserve("search")
    second = await budget.reserve("search")
    third = await budget.reserve("search")

    assert first.allowed and first.remaining == 1
    assert second.allowed and second.remaining == 0
    assert not third.allowed and third.reason == "daily_budget_exhausted"


@pytest.mark.asyncio
async def test_lane_and_chart_gates_are_idempotent() -> None:
    settings = Settings(redis_url="redis://test")
    budget = YouTubeQuotaBudget(settings, api_key="test-key", redis=_FakeRedis())
    workspace_id = uuid4()

    lane_first = await budget.claim_daily_lane_sweep(workspace_id)
    lane_second = await budget.claim_daily_lane_sweep(workspace_id)
    chart_first = await budget.claim_chart_window()
    chart_second = await budget.claim_chart_window()

    assert lane_first.allowed and lane_first.reason == "lane_sweep_claimed"
    assert not lane_second.allowed and lane_second.reason == "lane_sweep_already_claimed"
    assert chart_first.allowed and chart_first.reason == "chart_window_claimed"
    assert not chart_second.allowed and chart_second.reason == "chart_window_already_claimed"
