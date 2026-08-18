"""Account-sync health harness — measures availability, latency and error rate.

Account monitoring is the core of this product, and it carries three hard
requirements: it must work, it must stay responsive (no long stalls, no hangs),
and it must not throw errors. This script is how we *prove* those three, instead
of guessing from anecdotes.

It drives the real production path (``SyncService.request_account_sync`` ->
Celery -> adapter -> DB) rather than mocks, then reports per-platform:

  * availability : share of runs that ended usable (success or degraded)
  * latency      : p50 / p95 / max wall-clock seconds
  * stalls       : runs that never reached a terminal state inside the budget
  * errors       : grouped by error_code with the real root cause attached

Usage (inside the api container):

    python scripts/sync_healthcheck.py --mode baseline
    python scripts/sync_healthcheck.py --mode live --platforms youtube,tiktok
    python scripts/sync_healthcheck.py --mode live --concurrency 4 --json out.json

Modes
-----
baseline  Read-only. Summarises the runs already in the database over a window.
          Zero platform load — safe to run any time.
live      Actively enqueues syncs for real accounts and waits for them, so it
          measures the code as deployed right now. Hits the real platforms.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, "/workspace/apps/api")

from app.adapters.platforms.registry import build_platform_adapter_registry  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import create_engine_and_session  # noqa: E402
from app.models.monitoring import Account, Platform  # noqa: E402
from app.models.sync import SyncRun  # noqa: E402

# A sync that has not reached a terminal state within this many seconds is
# reported as a stall. The scheduler's own per-run cap is higher; we deliberately
# flag earlier because "still running after 10 minutes" already breaks the
# responsiveness requirement even if it eventually finishes.
DEFAULT_STALL_BUDGET_SECONDS = 600
TERMINAL_STATUSES = frozenset({"success", "degraded", "error", "cancelled"})
USABLE_STATUSES = frozenset({"success", "degraded"})


@dataclass
class RunOutcome:
    """One observed sync run, normalised for reporting."""

    account_id: str
    platform: str
    adapter_key: str
    run_id: str
    status: str
    seconds: float | None
    error_code: str | None
    error_message: str | None
    root_cause: str | None
    stalled: bool = False

    @property
    def usable(self) -> bool:
        return self.status in USABLE_STATUSES


@dataclass
class PlatformReport:
    platform: str
    outcomes: list[RunOutcome] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def usable(self) -> int:
        return sum(1 for o in self.outcomes if o.usable)

    @property
    def stalled(self) -> int:
        return sum(1 for o in self.outcomes if o.stalled)

    @property
    def availability_pct(self) -> float:
        return round(100.0 * self.usable / self.total, 1) if self.total else 0.0

    def latencies(self) -> list[float]:
        return sorted(o.seconds for o in self.outcomes if o.seconds is not None)

    def percentile(self, pct: float) -> float | None:
        values = self.latencies()
        if not values:
            return None
        if len(values) == 1:
            return round(values[0], 1)
        idx = min(int(round((pct / 100.0) * (len(values) - 1))), len(values) - 1)
        return round(values[idx], 1)

    def error_breakdown(self) -> dict[str, dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for outcome in self.outcomes:
            if outcome.usable:
                continue
            code = outcome.error_code or ("stalled" if outcome.stalled else "unknown")
            slot = grouped.setdefault(code, {"count": 0, "sample": None})
            slot["count"] += 1
            if slot["sample"] is None:
                slot["sample"] = (outcome.root_cause or outcome.error_message or "")[:200]
        return grouped


def _root_cause(error_detail: str | None) -> str | None:
    """Pull the concrete exception out of the ``code_level_detail`` string.

    ``error_detail`` looks like ``builtins.TypeError: boom | adapter=x | run=y``.
    The first segment is the only part that identifies the real fault; the rest
    is correlation metadata that would otherwise defeat grouping.
    """
    if not error_detail:
        return None
    return error_detail.split(" | ", 1)[0].strip() or None


async def _platform_of(session: AsyncSession, adapter_key: str) -> str:
    return adapter_key.replace("_browser", "").replace("_ytdlp", "")


async def collect_baseline(session: AsyncSession, hours: int) -> dict[str, PlatformReport]:
    """Summarise runs already recorded in the last ``hours`` (no platform load)."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = (
        (
            await session.execute(
                select(SyncRun).where(
                    SyncRun.target_type == "account",
                    SyncRun.queued_at >= since,
                )
            )
        )
        .scalars()
        .all()
    )
    reports: dict[str, PlatformReport] = {}
    for run in rows:
        platform = await _platform_of(session, run.adapter_key)
        report = reports.setdefault(platform, PlatformReport(platform))
        seconds = None
        if run.started_at and run.finished_at:
            seconds = (run.finished_at - run.started_at).total_seconds()
        report.outcomes.append(
            RunOutcome(
                account_id=str(run.target_id),
                platform=platform,
                adapter_key=run.adapter_key,
                run_id=str(run.id),
                status=run.status,
                seconds=seconds,
                error_code=run.error_code,
                error_message=run.error_message,
                root_cause=_root_cause(run.error_detail),
                stalled=run.status not in TERMINAL_STATUSES,
            )
        )
    return reports


async def _pick_accounts(
    session: AsyncSession, platforms: list[str] | None, per_platform: int
) -> list[tuple[Account, Platform]]:
    stmt = (
        select(Account, Platform)
        .join(Platform, Platform.id == Account.platform_id)
        .where(Account.is_active.is_(True))
        .order_by(Platform.key, Account.created_at)
    )
    rows = (await session.execute(stmt)).all()
    picked: dict[str, list[tuple[Account, Platform]]] = {}
    for account, platform in rows:
        if platforms and platform.key not in platforms:
            continue
        bucket = picked.setdefault(platform.key, [])
        if len(bucket) < per_platform:
            bucket.append((account, platform))
    return [pair for bucket in picked.values() for pair in bucket]


async def _wait_for_run(
    sessionmaker: Any, run_id: UUID, budget: int, poll: float = 3.0
) -> tuple[str, float | None, str | None, str | None, str | None, bool]:
    """Poll a run to completion. Returns (status, secs, code, msg, cause, stalled)."""
    waited = 0.0
    while waited < budget:
        async with sessionmaker() as session:
            run = await session.get(SyncRun, run_id)
            if run is not None and run.status in TERMINAL_STATUSES:
                seconds = None
                if run.started_at and run.finished_at:
                    seconds = (run.finished_at - run.started_at).total_seconds()
                return (
                    run.status,
                    seconds,
                    run.error_code,
                    run.error_message,
                    _root_cause(run.error_detail),
                    False,
                )
        await asyncio.sleep(poll)
        waited += poll
    async with sessionmaker() as session:
        run = await session.get(SyncRun, run_id)
        status = run.status if run else "missing"
    return (status, float(budget), "stalled", f"no terminal state in {budget}s", None, True)


async def collect_live(
    sessionmaker: Any,
    platforms: list[str] | None,
    per_platform: int,
    concurrency: int,
    budget: int,
) -> dict[str, PlatformReport]:
    """Enqueue real syncs and wait for them — measures the code as deployed."""
    from app.services import sync as sync_module
    from app.services.sync import SyncService

    settings = get_settings()
    registry = build_platform_adapter_registry(settings)
    async with sessionmaker() as session:
        targets = await _pick_accounts(session, platforms, per_platform)
    if not targets:
        print("no active accounts matched the filter", file=sys.stderr)
        return {}

    reports: dict[str, PlatformReport] = {}
    gate = asyncio.Semaphore(concurrency)

    async def _one(account: Account, platform: Platform) -> RunOutcome:
        async with gate:
            async with sessionmaker() as session:
                service = SyncService(session, registry, settings)
                run, created = await service.request_account_sync(
                    account.workspace_id,
                    account.id,
                    request_id=f"healthcheck-{uuid4()}",
                )
                await session.commit()
                if created:
                    sync_module.enqueue_platform_sync(run.id)
            status, secs, code, msg, cause, stalled = await _wait_for_run(
                sessionmaker, run.id, budget
            )
            return RunOutcome(
                account_id=str(account.id),
                platform=platform.key,
                adapter_key=run.adapter_key,
                run_id=str(run.id),
                status=status,
                seconds=secs,
                error_code=code,
                error_message=msg,
                root_cause=cause,
                stalled=stalled,
            )

    results = await asyncio.gather(
        *(_one(a, p) for a, p in targets), return_exceptions=True
    )
    for target, result in zip(targets, results, strict=True):
        account, platform = target
        report = reports.setdefault(platform.key, PlatformReport(platform.key))
        if isinstance(result, BaseException):
            report.outcomes.append(
                RunOutcome(
                    account_id=str(account.id),
                    platform=platform.key,
                    adapter_key=platform.adapter_key,
                    run_id="-",
                    status="error",
                    seconds=None,
                    error_code="harness_exception",
                    error_message=str(result)[:300],
                    root_cause=f"{type(result).__name__}: {result}"[:300],
                )
            )
        else:
            report.outcomes.append(result)
    return reports


def render(reports: dict[str, PlatformReport], title: str) -> str:
    lines = [f"\n{'=' * 78}", f" {title}", f"{'=' * 78}"]
    header = f"{'platform':<12}{'runs':>6}{'usable':>8}{'avail%':>9}{'p50s':>8}{'p95s':>8}{'max s':>8}{'stall':>7}"
    lines.append(header)
    lines.append("-" * 78)
    all_outcomes: list[RunOutcome] = []
    for platform in sorted(reports):
        r = reports[platform]
        all_outcomes.extend(r.outcomes)
        lines.append(
            f"{platform:<12}{r.total:>6}{r.usable:>8}{r.availability_pct:>9}"
            f"{str(r.percentile(50) or '-'):>8}{str(r.percentile(95) or '-'):>8}"
            f"{str(r.percentile(100) or '-'):>8}{r.stalled:>7}"
        )
    lines.append("-" * 78)
    total = len(all_outcomes)
    usable = sum(1 for o in all_outcomes if o.usable)
    stalled = sum(1 for o in all_outcomes if o.stalled)
    overall = round(100.0 * usable / total, 1) if total else 0.0
    lats = sorted(o.seconds for o in all_outcomes if o.seconds is not None)
    p50 = round(statistics.median(lats), 1) if lats else "-"
    lines.append(f"{'TOTAL':<12}{total:>6}{usable:>8}{overall:>9}{str(p50):>8}{'':>8}{'':>8}{stalled:>7}")

    lines.append("\n错误明细（按平台 / error_code 聚合，附真实根因）")
    lines.append("-" * 78)
    any_error = False
    for platform in sorted(reports):
        breakdown = reports[platform].error_breakdown()
        if not breakdown:
            continue
        any_error = True
        lines.append(f"\n[{platform}]")
        for code, info in sorted(breakdown.items(), key=lambda kv: -kv[1]["count"]):
            lines.append(f"  {code} x{info['count']}")
            if info["sample"]:
                lines.append(f"      -> {info['sample']}")
    if not any_error:
        lines.append("  (无错误)")
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("baseline", "live"), default="baseline")
    parser.add_argument("--hours", type=int, default=3, help="baseline window")
    parser.add_argument("--platforms", default="", help="comma list, e.g. youtube,tiktok")
    parser.add_argument("--per-platform", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument(
        "--budget", type=int, default=DEFAULT_STALL_BUDGET_SECONDS, help="stall budget seconds"
    )
    parser.add_argument("--json", default="", help="also write raw results to this path")
    args = parser.parse_args()

    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()] or None
    settings = get_settings()
    engine, sessionmaker = create_engine_and_session(settings)

    if args.mode == "baseline":
        async with sessionmaker() as session:
            await session.execute(text("SELECT 1"))
            reports = await collect_baseline(session, args.hours)
        title = f"账号同步基线（数据库回溯，近 {args.hours} 小时，无平台负载）"
    else:
        reports = await collect_live(
            sessionmaker, platforms, args.per_platform, args.concurrency, args.budget
        )
        title = (
            f"账号同步实测（真实触发，每平台 {args.per_platform} 个账号，"
            f"并发 {args.concurrency}，超时预算 {args.budget}s）"
        )

    print(render(reports, title))

    if args.json:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "mode": args.mode,
            "platforms": {
                name: {
                    "total": r.total,
                    "usable": r.usable,
                    "availability_pct": r.availability_pct,
                    "p50_seconds": r.percentile(50),
                    "p95_seconds": r.percentile(95),
                    "max_seconds": r.percentile(100),
                    "stalled": r.stalled,
                    "errors": r.error_breakdown(),
                    "runs": [vars(o) for o in r.outcomes],
                }
                for name, r in reports.items()
            },
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"\nraw results -> {args.json}")

    # Non-zero exit when anything stalled: that is the requirement most likely to
    # go unnoticed in a green-looking run.
    return 1 if any(r.stalled for r in reports.values()) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
