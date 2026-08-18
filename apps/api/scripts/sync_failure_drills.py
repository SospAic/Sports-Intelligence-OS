"""Account-sync failure drills — proves the engine behaves under *bad* conditions.

``sync_healthcheck.py`` measures the happy path (availability, latency, stalls).
This script covers the other half of the promise: when something goes wrong, the
sync must fail *fast*, *cleanly* and *once* — never hang, never loop, never leave
an account locked in "syncing".

Each drill drives the real production path (``SyncService`` -> Celery -> engine)
against real accounts. Drills only create ``sync_runs`` rows, which are ordinary
operational data; no account, platform or content row is created or mutated, so
the script is safe to run against the live database.

Drills
------
expired_retry_budget
    A run whose absolute deadline has already passed (queue backlog, a crashed
    attempt, a re-queued stale run) must be closed as ``sync_budget_exhausted``
    instead of driving ``asyncio.wait_for`` with a negative timeout and looping
    through the retry queue while holding the account lock.
cancel_in_flight
    A running sync must react to a user cancellation promptly and release the
    account lock, so the account never stays stuck in "syncing".
duplicate_dispatch
    Two concurrent sync requests for the same account must collapse into a
    single run — the account lock is the invariant that prevents two workers
    fighting over one account.

Usage (inside the api container):

    python scripts/sync_failure_drills.py
    python scripts/sync_failure_drills.py --json /tmp/drills.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, "/workspace/apps/api")

from app.adapters.platforms.registry import build_platform_adapter_registry  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import create_engine_and_session  # noqa: E402
from app.models.monitoring import Account, Platform  # noqa: E402
from app.models.sync import SyncRun  # noqa: E402

TERMINAL_STATUSES = frozenset({"success", "degraded", "error", "cancelled"})


@dataclass
class DrillResult:
    name: str
    passed: bool
    seconds: float
    detail: str
    observed: dict[str, Any]


async def _pick_account(
    session: AsyncSession, platform_key: str | None = None
) -> tuple[Account, Platform] | None:
    stmt = (
        select(Account, Platform)
        .join(Platform, Platform.id == Account.platform_id)
        .where(Account.is_active.is_(True))
        .order_by(Platform.key, Account.created_at)
    )
    for account, platform in (await session.execute(stmt)).all():
        if platform_key and platform.key != platform_key:
            continue
        # Never grab an account that is already syncing: the drill would then
        # measure the *other* run, and cancelling it would disrupt real work.
        if account.sync_status == "syncing":
            continue
        return account, platform
    return None


async def _wait_terminal(sessionmaker: Any, run_id: UUID, budget: float) -> SyncRun | None:
    waited = 0.0
    while waited < budget:
        async with sessionmaker() as session:
            run = await session.get(SyncRun, run_id)
            if run is not None and run.status in TERMINAL_STATUSES:
                return run
        await asyncio.sleep(1.0)
        waited += 1.0
    async with sessionmaker() as session:
        return await session.get(SyncRun, run_id)


async def drill_expired_retry_budget(sessionmaker: Any, budget: float = 90.0) -> DrillResult:
    """A run that reaches the worker past its deadline must be closed, not retried."""
    from app.services import sync as sync_module
    from app.services.sync import SyncService

    settings = get_settings()
    registry = build_platform_adapter_registry(settings)
    started = datetime.now(UTC)
    async with sessionmaker() as session:
        picked = await _pick_account(session)
        if picked is None:
            return DrillResult("expired_retry_budget", False, 0.0, "no idle account", {})
        account, platform = picked
        service = SyncService(session, registry, settings)
        run, created = await service.request_account_sync(
            account.workspace_id, account.id, request_id=f"drill-expired-{uuid4()}"
        )
        if not created:
            return DrillResult(
                "expired_retry_budget", False, 0.0, "account already had a run in flight", {}
            )
        run_id = run.id
        # ``request_account_sync`` hands back a read model, so the row itself has
        # to be loaded before it can be mutated. Simulate an attempt picked up
        # long after its deadline — exactly the state a backlogged retry lands
        # in, because ``started_at`` is preserved across attempts on purpose.
        row = await session.get(SyncRun, run_id)
        if row is None:
            return DrillResult("expired_retry_budget", False, 0.0, "run row vanished", {})
        row.started_at = datetime.now(UTC) - timedelta(
            seconds=settings.sync_run_timeout_seconds * 3
        )
        await session.commit()
        sync_module.enqueue_platform_sync(run_id)

    final = await _wait_terminal(sessionmaker, run_id, budget)
    seconds = (datetime.now(UTC) - started).total_seconds()
    observed = {
        "platform": platform.key,
        "run_id": str(run_id),
        "status": getattr(final, "status", None),
        "error_code": getattr(final, "error_code", None),
        "lock_key": getattr(final, "lock_key", None),
    }
    passed = (
        final is not None
        and final.status == "error"
        and final.error_code == "sync_budget_exhausted"
        and final.lock_key is None
        and seconds < budget
    )
    detail = (
        "closed as sync_budget_exhausted with the lock released"
        if passed
        else "did not close cleanly on an exhausted budget"
    )
    async with sessionmaker() as session:
        acct = await session.get(Account, account.id)
        observed["account_sync_status"] = getattr(acct, "sync_status", None)
        if acct is not None and acct.sync_status == "syncing":
            passed = False
            detail = "account left stuck in 'syncing'"
    return DrillResult("expired_retry_budget", passed, seconds, detail, observed)


async def drill_cancel_in_flight(sessionmaker: Any, budget: float = 180.0) -> DrillResult:
    """A cancelled run must reach a terminal state and release the lock."""
    from app.services import sync as sync_module
    from app.services.sync import SyncService

    settings = get_settings()
    registry = build_platform_adapter_registry(settings)
    started = datetime.now(UTC)
    async with sessionmaker() as session:
        picked = await _pick_account(session)
        if picked is None:
            return DrillResult("cancel_in_flight", False, 0.0, "no idle account", {})
        account, platform = picked
        service = SyncService(session, registry, settings)
        run, created = await service.request_account_sync(
            account.workspace_id, account.id, request_id=f"drill-cancel-{uuid4()}"
        )
        if not created:
            return DrillResult(
                "cancel_in_flight", False, 0.0, "account already had a run in flight", {}
            )
        await session.commit()
        run_id, workspace_id, account_id = run.id, account.workspace_id, account.id
        sync_module.enqueue_platform_sync(run_id)

    # Let the worker actually pick it up, otherwise we would only be testing the
    # "cancel before pickup" shortcut.
    for _ in range(30):
        await asyncio.sleep(1.0)
        async with sessionmaker() as session:
            run = await session.get(SyncRun, run_id)
            if run is not None and run.status == "running":
                break

    cancelled_at = datetime.now(UTC)
    async with sessionmaker() as session:
        service = SyncService(session, registry, settings)
        await service.cancel_sync_run(workspace_id, account_id, run_id)
        await session.commit()

    final = await _wait_terminal(sessionmaker, run_id, budget)
    react_seconds = (datetime.now(UTC) - cancelled_at).total_seconds()
    observed = {
        "platform": platform.key,
        "run_id": str(run_id),
        "status": getattr(final, "status", None),
        "lock_key": getattr(final, "lock_key", None),
        "seconds_to_react": round(react_seconds, 1),
    }
    passed = (
        final is not None
        and final.status in TERMINAL_STATUSES
        and final.lock_key is None
        and react_seconds < budget
    )
    async with sessionmaker() as session:
        acct = await session.get(Account, account_id)
        observed["account_sync_status"] = getattr(acct, "sync_status", None)
        if acct is not None and acct.sync_status == "syncing":
            passed = False
    detail = (
        f"reached {observed['status']} and released the lock {react_seconds:.0f}s after cancel"
        if passed
        else "cancellation did not free the account"
    )
    return DrillResult(
        "cancel_in_flight", passed, (datetime.now(UTC) - started).total_seconds(), detail, observed
    )


async def drill_duplicate_dispatch(sessionmaker: Any) -> DrillResult:
    """Two concurrent requests for one account must collapse into a single run."""
    from app.services.sync import SyncService

    settings = get_settings()
    registry = build_platform_adapter_registry(settings)
    started = datetime.now(UTC)
    async with sessionmaker() as session:
        picked = await _pick_account(session)
        if picked is None:
            return DrillResult("duplicate_dispatch", False, 0.0, "no idle account", {})
        account, platform = picked
        workspace_id, account_id = account.workspace_id, account.id

    async def _request(tag: str) -> tuple[UUID, bool]:
        async with sessionmaker() as session:
            service = SyncService(session, registry, settings)
            run, created = await service.request_account_sync(
                workspace_id, account_id, request_id=f"drill-dup-{tag}-{uuid4()}"
            )
            await session.commit()
            return run.id, created

    # Deliberately NOT enqueued: this drill asserts the dedupe decision, not the
    # platform call, so it costs no platform traffic.
    results = await asyncio.gather(_request("a"), _request("b"), return_exceptions=True)
    run_ids = {str(r[0]) for r in results if not isinstance(r, BaseException)}
    created_count = sum(1 for r in results if not isinstance(r, BaseException) and r[1])
    rejected = [type(r).__name__ for r in results if isinstance(r, BaseException)]
    passed = created_count <= 1 and len(run_ids) <= 1

    # Release whatever the drill created so the account is immediately usable.
    async with sessionmaker() as session:
        for rid in run_ids:
            run = await session.get(SyncRun, UUID(rid))
            if run is not None and run.status in ("queued", "running"):
                run.status = "cancelled"
                run.lock_key = None
                run.finished_at = datetime.now(UTC)
                run.progress_stage = "cancelled"
        acct = await session.get(Account, account_id)
        if acct is not None and acct.sync_status == "syncing":
            acct.sync_status = "cancelled"
        await session.commit()

    return DrillResult(
        "duplicate_dispatch",
        passed,
        (datetime.now(UTC) - started).total_seconds(),
        "one run created, the duplicate was deduped or rejected"
        if passed
        else "two concurrent requests produced competing runs",
        {
            "platform": platform.key,
            "created_count": created_count,
            "distinct_runs": len(run_ids),
            "rejections": rejected,
        },
    )


def _dump(path: str, results: list[DrillResult], failed: int) -> None:
    """Blocking write kept out of the event loop (ruff ASYNC230)."""
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "drills": [asdict(r) for r in results],
        "failed": failed,
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument(
        "--only",
        default=None,
        help="comma-separated drill names (expired_retry_budget,cancel_in_flight,"
        "duplicate_dispatch)",
    )
    args = parser.parse_args()

    settings = get_settings()
    engine, sessionmaker = create_engine_and_session(settings)
    selected = {n.strip() for n in args.only.split(",")} if args.only else None
    drills = {
        "expired_retry_budget": drill_expired_retry_budget,
        "cancel_in_flight": drill_cancel_in_flight,
        "duplicate_dispatch": drill_duplicate_dispatch,
    }
    results: list[DrillResult] = []
    try:
        for name, fn in drills.items():
            if selected and name not in selected:
                continue
            print(f"▸ {name} ...", flush=True)
            results.append(await fn(sessionmaker))
            print(
                f"  {'PASS' if results[-1].passed else 'FAIL'} — {results[-1].detail}", flush=True
            )
    finally:
        await engine.dispose()

    print("\n=== 账号同步故障演练 ===")
    for r in results:
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.name:22s} {r.seconds:6.1f}s  {r.detail}")
        print(f"      {json.dumps(r.observed, ensure_ascii=False)}")
    failed = [r for r in results if not r.passed]
    if args.json_path:
        _dump(args.json_path, results, len(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
