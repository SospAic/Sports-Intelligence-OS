"""Regression tests for the account-layer avatar cache + display-name guards.

Why this file exists
--------------------
The avatar-update branch in ``PlatformSyncExecutor._sync_account_profile``
calls ``anyio.to_thread.run_sync(cache_avatar_for_account, ...)``. ``anyio``
was used there but **never imported**, so the branch raised
``NameError: name 'anyio' is not defined`` at runtime for *every* sync that
had a new avatar to store — on all four platforms. The full 234-test suite
passed anyway because no test ever produced an adapter response with an
``avatar_url``, leaving the entire branch uncovered.

These tests drive that exact branch so the import can never silently regress,
and pin the cross-platform display-name guard behaviour at the sync layer.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.platforms.base import AdapterCallContext, PlatformAccountData
from app.core.config import Settings
from app.db.base import Base
from app.models.monitoring import Account
from app.models.sync import SyncRun, SyncRunEvent
from app.providers.registry import ProviderRegistry
from app.services.sync import PlatformSyncExecutor

from .conftest import PG_ASYNC_URL, TEST_REDIS_URL, RealShapedTestAdapter
from .test_sync_degraded_status import _seed

ADAPTER_KEY = "test_sync_adapter"
AVATAR_URL = "https://p16-sign.tiktokcdn.com/real-custom-avatar-1024.jpeg"


def _build_settings() -> Settings:
    return Settings(
        environment="test",
        database_url=PG_ASYNC_URL,
        redis_url=TEST_REDIS_URL,
        secret_key="test-only-secret-not-used-in-production",
        session_cookie_secure=False,
    )


def _build_registry(adapter: object) -> ProviderRegistry:
    registry: ProviderRegistry = ProviderRegistry()
    registry.register(adapter)  # type: ignore[arg-type]
    return registry


class _AvatarTestAdapter(RealShapedTestAdapter):
    """Real-shaped adapter that returns an avatar and a configurable name."""

    def __init__(self, *, display_name: str = "测试账号", avatar_url: str | None = AVATAR_URL):
        super().__init__()
        self._display_name = display_name
        self._avatar_url = avatar_url

    async def resolve_account(self, ctx: AdapterCallContext, locator: str) -> PlatformAccountData:
        data = await super().resolve_account(ctx, locator)
        return PlatformAccountData(
            external_id=data.external_id,
            username=data.username,
            display_name=self._display_name,
            profile_url=data.profile_url,
            avatar_url=self._avatar_url,
            description=data.description,
            country=data.country,
            language=data.language,
            is_verified=data.is_verified,
            source_kind=data.source_kind,
            provider=data.provider,
            fetched_at=data.fetched_at,
            metadata=data.metadata,
        )


async def _run_sync(adapter: object, monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, list]:
    """Seed a workspace/account/run, execute the sync, return (account_id, cache_calls)."""
    calls: list = []

    def _fake_cache(account_id: UUID, url: str) -> None:
        calls.append((account_id, url))

    monkeypatch.setattr("app.services.sync.cache_avatar_for_account", _fake_cache)

    engine = create_async_engine(PG_ASYNC_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    workspace_id, platform_id, account_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    registry = _build_registry(adapter)
    async with maker() as session:
        await _seed(session, workspace_id, platform_id, account_id, run_id, ADAPTER_KEY)

    settings = _build_settings()
    async with maker() as session:
        await PlatformSyncExecutor(session, registry, settings).execute_account_run(run_id)

    await engine.dispose()
    return account_id, calls


async def test_avatar_update_reaches_cache_without_nameerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The avatar branch must execute end-to-end (regression: missing `anyio` import)."""
    account_id, calls = await _run_sync(_AvatarTestAdapter(), monkeypatch)

    assert len(calls) == 1, "cache_avatar_for_account should be invoked exactly once"
    assert calls[0][0] == account_id
    assert calls[0][1] == AVATAR_URL

    engine = create_async_engine(PG_ASYNC_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        account = (
            await session.execute(select(Account).where(Account.id == account_id))
        ).scalar_one()
        assert account.avatar_url == AVATAR_URL
    await engine.dispose()


async def test_default_avatar_never_reaches_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """A platform default/placeholder avatar must not be cached (cross-platform guard)."""
    adapter = _AvatarTestAdapter(avatar_url="https://i0.hdslb.com/bfs/face/noface.gif")
    account_id, calls = await _run_sync(adapter, monkeypatch)

    assert calls == [], "a default avatar must never be cached"

    engine = create_async_engine(PG_ASYNC_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        account = (
            await session.execute(select(Account).where(Account.id == account_id))
        ).scalar_one()
        assert account.avatar_url is None
    await engine.dispose()


@pytest.mark.parametrize(
    "bad_name",
    ["404 Not Found", "的抖音", "@https://www.tiktok.com/@olympicsbringsustogether"],
)
async def test_invalid_display_name_degrades_the_run_but_keeps_it_usable(
    bad_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scrape artefact must never be persisted as the account's name.

    All three shapes were real rows in the production database before the
    ``profile_helpers`` guard existed.

    The guard used to raise ``AdapterContractError`` and fail the whole sync.
    That was wrong for account monitoring: the nickname is a non-critical field,
    and hard-failing threw away an otherwise good content sync — for Douyin it
    made the account permanently unsyncable, because the bogus "<name>的抖音"
    fallback is returned on every single attempt. The run now *degrades*: the
    bad name is dropped, the stored name survives, and the reason is recorded in
    the tracklog.
    """
    adapter = _AvatarTestAdapter(display_name=bad_name)
    account_id, _ = await _run_sync(adapter, monkeypatch)

    engine = create_async_engine(PG_ASYNC_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        account = (
            await session.execute(select(Account).where(Account.id == account_id))
        ).scalar_one()
        # The seeded name survives; the corrupt scrape is rejected.
        assert account.display_name == "测试账号"
        assert account.sync_status == "degraded"

        run = (
            (await session.execute(select(SyncRun).where(SyncRun.target_id == account_id)))
            .scalars()
            .first()
        )
        assert run is not None
        assert run.status == "degraded"
        # The lock is released, so the account can be synced again immediately.
        assert run.lock_key is None

        events = (
            (await session.execute(select(SyncRunEvent).where(SyncRunEvent.sync_run_id == run.id)))
            .scalars()
            .all()
        )
        warnings = [e for e in events if e.level == "warn" and "显示名无效" in e.message]
        assert warnings, "the dropped nickname must be visible in the tracklog"
        # Must be stored under a DB-legal event_type — persisting the stage name
        # here violated the CHECK constraint and stalled the run (see
        # tests/test_sync_stall_guards.py).
        assert warnings[0].event_type == "warning"
    await engine.dispose()


async def test_valid_rename_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    """A genuine rename must still be written through."""
    adapter = _AvatarTestAdapter(display_name="NBA Official")
    account_id, _ = await _run_sync(adapter, monkeypatch)

    engine = create_async_engine(PG_ASYNC_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        account = (
            await session.execute(select(Account).where(Account.id == account_id))
        ).scalar_one()
        assert account.display_name == "NBA Official"
    await engine.dispose()


def test_sync_module_imports_anyio() -> None:
    """Direct guard: the module-level name used by the avatar branch must exist."""
    import app.services.sync as sync_module

    assert hasattr(sync_module, "anyio"), "app.services.sync must import anyio"
    assert datetime.now(UTC).tzinfo is UTC  # sanity: module imported cleanly
