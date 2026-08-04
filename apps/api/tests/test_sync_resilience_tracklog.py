"""Regression tests for resilient account sync + append-only tracklog.

Before this work, a single failing content upsert (or a failed per-page
analytics call) bubbled up to the top-level ``except`` in
``execute_account_run`` and aborted the *entire* sync — which is exactly the
"accounts only ever sync a partial, inconsistent slice of works" symptom the
user reported. The sync engine now isolates per-item and per-page failures:

* a content upsert that raises is counted in ``items_failed`` and the sync
  *continues* (the work is recorded in the tracklog, not silently dropped);
* a per-page analytics failure degrades the run (``content_analytics_failed``)
  but never discards the works already ingested;
* every meaningful step (stage / page / item / analytics / external_call /
  error / summary) is appended to ``sync_run_events`` so the new detail page
  can replay exactly what happened.

These tests drive the REAL adapter contract (``source_kind='live'``) through
test-only fixtures (``RealShapedTestAdapter`` in conftest, plus small
subclasses below) so the assertions cover the engine's resilience/tracklog
logic deterministically and offline — no ``mock`` source kind, no live data,
no falsified success.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.platforms.base import AdapterCallContext
from app.core.config import Settings
from app.db.base import Base
from app.models.monitoring import Account, Platform
from app.models.sync import SyncRun, SyncRunEvent
from app.models.workspace import Workspace
from app.providers.registry import ProviderRegistry
from app.services.sync import PlatformSyncExecutor, SyncService

from .conftest import PG_ASYNC_URL, RealShapedTestAdapter

ADAPTER_KEY = "test_sync_adapter"
# External id that the failing-item executor forces to raise on upsert.
BAD_EXTERNAL_ID = "c2"


def _build_settings() -> Settings:
    return Settings(
        environment="test",
        database_url=PG_ASYNC_URL,
        redis_url="redis://127.0.0.1:6399/15",
        secret_key="test-only-secret-not-used-in-production",
        session_cookie_secure=False,
    )


def _build_registry(adapter: object) -> ProviderRegistry:
    registry: ProviderRegistry = ProviderRegistry()
    registry.register(adapter)  # type: ignore[arg-type]
    return registry


async def _seed(
    session: object,
    workspace_id: object,
    platform_id: object,
    account_id: object,
    run_id: object,
    adapter_key: str,
) -> None:
    s = session  # type: ignore[assignment]
    s.add_all(
        [
            Workspace(
                id=workspace_id,
                name="ws",
                slug="ws",
                status="active",
                default_timezone="UTC",
                row_version=1,
            ),
            Platform(
                id=platform_id,
                key="test_platform",
                name="Test",
                category="video",
                enabled=True,
                adapter_key=adapter_key,
                capabilities={},
            ),
            Account(
                id=account_id,
                workspace_id=workspace_id,
                platform_id=platform_id,
                external_id="external-001",
                display_name="测试账号",
                source_kind="imported",
                source_provider="manual",
                fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
            ),
        ]
    )
    await s.commit()
    s.add(
        SyncRun(
            id=run_id,
            workspace_id=workspace_id,
            target_type="account",
            target_id=account_id,
            adapter_key=adapter_key,
            request_id="req-resilience",
            queued_at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
            status="queued",
            metadata_json={},
        )
    )
    await s.commit()


class FailingItemExecutor(PlatformSyncExecutor):
    """Force a deterministic upsert failure on one specific content item.

    The production code wraps every ``_upsert_content`` call in a try/except
    and counts the failure in ``items_failed`` instead of aborting the sync.
    This subclass reproduces that failure path so we can assert the sync
    survives it and continues to ingest the *other* works.
    """

    async def _upsert_content(self, account, data, skip_existing=False):
        if data.external_id == BAD_EXTERNAL_ID:
            raise RuntimeError(f"simulated upsert failure for {data.external_id}")
        return await super()._upsert_content(account, data, skip_existing=skip_existing)


class FailingAnalyticsAdapter(RealShapedTestAdapter):
    """Adapter whose per-page analytics call always raises.

    Used to exercise the graceful-degradation path: a failed analytics fetch
    must not discard the works already ingested on that page.
    """

    async def fetch_content_analytics(
        self, ctx: AdapterCallContext, external_ids: Sequence[str]
    ) -> tuple[object, ...]:
        raise RuntimeError("simulated content analytics failure")


async def _event_rows(session: object, run_id: object) -> list[SyncRunEvent]:
    s = session  # type: ignore[assignment]
    return list(
        (await s.scalars(select(SyncRunEvent).where(SyncRunEvent.sync_run_id == run_id))).all()
    )


async def test_single_item_failure_continues_sync_and_records_tracklog() -> None:
    """A single content upsert that raises must NOT abort the sync.

    The sync must finish (status success), ingest the other works, count the
    failure in items_failed, and append an item-level error event to the
    tracklog capturing exactly which work failed.
    """
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    workspace_id = uuid4()
    platform_id = uuid4()
    account_id = uuid4()
    run_id = uuid4()

    registry = _build_registry(RealShapedTestAdapter(key=ADAPTER_KEY, content_count=5))
    async with maker() as session:
        await _seed(session, workspace_id, platform_id, account_id, run_id, ADAPTER_KEY)

    settings = _build_settings()
    async with maker() as session:
        await FailingItemExecutor(session, registry, settings).execute_account_run(run_id)

    async with maker() as session:
        run = await session.get(SyncRun, run_id)
        account = await session.get(Account, account_id)
        # Sync finished successfully despite the one bad item.
        assert run.status == "success", run.error_message
        assert account.sync_status == "success"
        # The bad item still counts toward the processed total, but is recorded
        # as a separate failure rather than aborting everything.
        assert run.items_processed == 5
        assert run.metadata_json.get("items_failed") == 1
        events = await _event_rows(session, run_id)
        assert events, "tracklog must record events for the run"

        # The failing item must appear as an item-level error event.
        item_errors = [
            e
            for e in events
            if e.event_type == "item" and e.level == "error"
        ]
        assert len(item_errors) == 1, "exactly one item error event expected"
        assert item_errors[0].payload.get("external_id") == BAD_EXTERNAL_ID
        assert item_errors[0].payload.get("action") == "failed"

        # The 4 healthy items must each appear as a created/updated item event.
        item_ok = [
            e
            for e in events
            if e.event_type == "item" and e.level == "info"
        ]
        assert len(item_ok) == 4

        # Detail endpoint must return the run plus the same ordered events.
        detail = await SyncService(session, registry, settings).get_run_detail(
            workspace_id, account_id, run_id
        )
        assert detail.run.id == run_id
        assert [e.sequence for e in detail.events] == sorted(
            e.sequence for e in detail.events
        )
        assert detail.events[0].sequence == 1
        assert detail.events[-1].event_type == "summary"
    await engine.dispose()


async def test_analytics_failure_degrades_run_and_records_tracklog() -> None:
    """A per-page analytics failure must degrade (not abort) the sync.

    The works are still ingested; the run ends ``degraded`` with
    ``content_analytics_failed`` set, and a warn-level analytics event records
    which page failed.
    """
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    workspace_id = uuid4()
    platform_id = uuid4()
    account_id = uuid4()
    run_id = uuid4()

    registry = _build_registry(FailingAnalyticsAdapter(key=ADAPTER_KEY, content_count=5))
    async with maker() as session:
        await _seed(session, workspace_id, platform_id, account_id, run_id, ADAPTER_KEY)

    settings = _build_settings()
    async with maker() as session:
        await PlatformSyncExecutor(session, registry, settings).execute_account_run(run_id)

    async with maker() as session:
        run = await session.get(SyncRun, run_id)
        account = await session.get(Account, account_id)
        assert run.status == "degraded", run.error_message
        assert account.sync_status == "degraded"
        assert run.metadata_json.get("content_analytics_failed") is True
        # Works were still ingested despite the analytics failure.
        assert run.items_processed == 5

        events = await _event_rows(session, run_id)
        analytics_events = [
            e for e in events if e.event_type == "analytics" and e.level == "warn"
        ]
        assert len(analytics_events) == 1
        assert (
            analytics_events[0].payload.get("requested") == 5
        ), "analytics event must note how many items were requested"
    await engine.dispose()


async def test_combined_item_and_analytics_failure_records_full_tracklog() -> None:
    """Both an item failure and an analytics failure in one run.

    The run must still finish (degraded), record both failure classes, and the
    tracklog must contain the item error, the analytics warn, and the summary.
    """
    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    workspace_id = uuid4()
    platform_id = uuid4()
    account_id = uuid4()
    run_id = uuid4()

    registry = _build_registry(FailingAnalyticsAdapter(key=ADAPTER_KEY, content_count=5))
    async with maker() as session:
        await _seed(session, workspace_id, platform_id, account_id, run_id, ADAPTER_KEY)

    settings = _build_settings()
    async with maker() as session:
        await FailingItemExecutor(session, registry, settings).execute_account_run(run_id)

    async with maker() as session:
        run = await session.get(SyncRun, run_id)
        assert run.status == "degraded"
        meta = run.metadata_json
        assert meta.get("items_failed") == 1
        assert meta.get("content_analytics_failed") is True

        events = await _event_rows(session, run_id)
        types = {e.event_type for e in events}
        assert "item" in types and "analytics" in types and "summary" in types
        item_errors = [e for e in events if e.event_type == "item" and e.level == "error"]
        assert len(item_errors) == 1
        assert item_errors[0].payload.get("external_id") == BAD_EXTERNAL_ID
    await engine.dispose()


async def test_first_page_failure_still_raises_as_outage() -> None:
    """A first-page list_contents failure (nothing collected yet) is a genuine
    outage and must propagate as an error — NOT be silently swallowed."""

    class FirstPageFailingAdapter(RealShapedTestAdapter):
        async def list_contents(self, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("first page unavailable")

    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    workspace_id = uuid4()
    platform_id = uuid4()
    account_id = uuid4()
    run_id = uuid4()

    registry = _build_registry(FirstPageFailingAdapter(key=ADAPTER_KEY))
    async with maker() as session:
        await _seed(session, workspace_id, platform_id, account_id, run_id, ADAPTER_KEY)

    settings = _build_settings()
    raised = False
    async with maker() as session:
        try:
            await PlatformSyncExecutor(session, registry, settings).execute_account_run(run_id)
        except Exception:  # noqa: BLE001
            raised = True
    assert raised, "first-page failure must raise (handled as retry/error upstream)"
    await engine.dispose()
