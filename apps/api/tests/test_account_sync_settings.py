"""Tests for per-account sync settings override (service + executor merge).

These tests exercise the logic without the auth/CSRF middleware (which needs a
running Redis broker), so they run in environments where only PostgreSQL is up.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.monitoring import Account, Platform
from app.models.workspace import Workspace
from app.schemas.monitoring import AccountSyncSettingsOverride
from app.services.monitoring import MonitoringService
from app.services.sync import PlatformSyncExecutor

from .conftest import PG_ASYNC_URL


@pytest.fixture
async def session():
    engine = create_async_engine(PG_ASYNC_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        workspace = Workspace(
            id=uuid4(),
            name="测试工作区",
            slug="test-workspace-ss",
            status="active",
            default_timezone="Asia/Shanghai",
            row_version=1,
        )
        platform = Platform(
            id=uuid4(),
            key="youtube_ytdlp",
            name="YouTube",
            category="video",
            enabled=True,
            adapter_key="youtube_ytdlp",
            capabilities={},
        )
        s.add_all([workspace, platform])
        await s.commit()

        account = Account(
            id=uuid4(),
            workspace_id=workspace.id,
            platform_id=platform.id,
            external_id="olympics",
            display_name="Olympics",
            sync_status="never",
            source_kind="imported",
            source_provider="manual",
            fetched_at=datetime.now(UTC),
        )
        s.add(account)
        await s.commit()
        # Detach so the fixture's session is the only writer; reload in tests.
        await s.refresh(account)
        yield SimpleNamespace(
            session=s, workspace_id=workspace.id, account_id=account.id
        )
    await engine.dispose()


async def test_service_get_and_update_override(session) -> None:
    svc = MonitoringService(session.session)
    ws_id, acc_id = session.workspace_id, session.account_id

    # No override initially → None (inherits workspace policy).
    assert await svc.get_account_sync_settings(ws_id, acc_id) is None

    payload = AccountSyncSettingsOverride(
        download={"download_video": True, "video_format": "best[height<=720]"}
    )
    saved = await svc.update_account_sync_settings(ws_id, acc_id, uuid4(), payload)
    assert saved.download.download_video is True
    assert saved.download.video_format == "best[height<=720]"

    # Re-read returns the persisted override.
    fetched = await svc.get_account_sync_settings(ws_id, acc_id)
    assert fetched is not None
    assert fetched.download.download_video is True

    # Replacing the override overwrites the previous one.
    payload2 = AccountSyncSettingsOverride(download={"write_info_json": True})
    await svc.update_account_sync_settings(ws_id, acc_id, uuid4(), payload2)
    fetched2 = await svc.get_account_sync_settings(ws_id, acc_id)
    assert fetched2 is not None
    assert fetched2.download.write_info_json is True
    # The previous download_video flag is gone (replaced, not merged client-side).
    assert fetched2.download.download_video is False


async def test_service_get_missing_account_raises(session) -> None:
    from app.services.monitoring import MonitoringNotFoundError

    svc = MonitoringService(session.session)
    with pytest.raises(MonitoringNotFoundError):
        await svc.get_account_sync_settings(session.workspace_id, uuid4())


def test_deep_merge_download_overrides_base() -> None:
    base = {
        "write_thumbnail": True,
        "write_subtitles": True,
        "subtitle_langs": "zh.*,en.*",
        "download_video": False,
        "video_format": "best",
        "write_info_json": False,
    }
    override = {"download_video": True, "video_format": "best[height<=720]"}
    merged = PlatformSyncExecutor._deep_merge_download(base, override)
    assert merged["download_video"] is True
    assert merged["video_format"] == "best[height<=720]"
    # Sibling keys from the base are preserved.
    assert merged["write_thumbnail"] is True
    assert merged["subtitle_langs"] == "zh.*,en.*"


async def test_executor_config_for_applies_override(monkeypatch) -> None:
    # Build the executor without touching DB-backed registry/settings.
    executor = PlatformSyncExecutor.__new__(PlatformSyncExecutor)
    executor.session = None  # type: ignore[assignment]
    executor.registry = None  # type: ignore[assignment]
    executor.settings = SimpleNamespace(browser_first_mode=False)

    captured = {}

    async def _fake_resolve(workspace_id, platform_key):  # noqa: ANN001
        return "api", {}

    async def _fake_get_sync_settings_config(workspace_id):  # noqa: ANN001
        captured["workspace_id"] = workspace_id
        return {
            "max_contents": None,
            "skip_existing": True,
            "yt_dlp": {},
            "download": {
                "write_thumbnail": True,
                "write_subtitles": True,
                "write_auto_subtitles": False,
                "subtitle_langs": "zh.*,en.*",
                "download_video": False,
                "video_format": "best",
                "write_info_json": False,
            },
        }

    class _FakeRepo:
        async def get_sync_settings_config(self, workspace_id):  # noqa: ANN001
            return await _fake_get_sync_settings_config(workspace_id)

    executor.repository = _FakeRepo()  # type: ignore[assignment]

    class _FakeCredService:
        def __init__(self, *args, **kwargs):  # noqa: ANN001
            pass

        @staticmethod
        async def resolve(workspace_id, platform_key):  # noqa: ANN001
            return "api", {}

    monkeypatch.setattr(
        "app.services.sync.PlatformCredentialService", _FakeCredService
    )

    account = SimpleNamespace(
        workspace_id=uuid4(),
        platform=SimpleNamespace(key="youtube_ytdlp"),
        sync_settings_override={
            "download": {"download_video": True, "video_format": "best[height<=720]"}
        },
    )
    config = await executor._config_for(account)
    assert config["download"]["download_video"] is True
    assert config["download"]["video_format"] == "best[height<=720]"
    # Base siblings preserved through the deep merge.
    assert config["download"]["write_thumbnail"] is True


async def test_executor_config_for_no_override_keeps_workspace(monkeypatch) -> None:
    executor = PlatformSyncExecutor.__new__(PlatformSyncExecutor)
    executor.session = None  # type: ignore[assignment]
    executor.registry = None  # type: ignore[assignment]
    executor.settings = SimpleNamespace(browser_first_mode=False)

    async def _fake_resolve(workspace_id, platform_key):  # noqa: ANN001
        return "api", {}

    async def _fake_get_sync_settings_config(workspace_id):  # noqa: ANN001
        return {
            "max_contents": None,
            "skip_existing": True,
            "yt_dlp": {},
            "download": {
                "write_thumbnail": True,
                "write_subtitles": True,
                "subtitle_langs": "zh.*,en.*",
                "download_video": False,
                "video_format": "best",
                "write_info_json": False,
            },
        }

    class _FakeRepo:
        async def get_sync_settings_config(self, workspace_id):  # noqa: ANN001
            return await _fake_get_sync_settings_config(workspace_id)

    executor.repository = _FakeRepo()  # type: ignore[assignment]

    class _FakeCredService:
        def __init__(self, *args, **kwargs):  # noqa: ANN001
            pass

        @staticmethod
        async def resolve(workspace_id, platform_key):  # noqa: ANN001
            return "api", {}

    monkeypatch.setattr(
        "app.services.sync.PlatformCredentialService", _FakeCredService
    )

    account = SimpleNamespace(
        workspace_id=uuid4(),
        platform=SimpleNamespace(key="youtube_ytdlp"),
        sync_settings_override=None,
    )
    config = await executor._config_for(account)
    assert config["download"]["download_video"] is False
    assert config["download"]["video_format"] == "best"


async def test_executor_config_for_forces_thumbnail_for_expiring_platforms(
    monkeypatch,
) -> None:
    # TikTok / Douyin covers are short-lived signed CDN links; the executor
    # must archive a local, permanent thumbnail even when no workspace download
    # policy is configured at all.
    executor = PlatformSyncExecutor.__new__(PlatformSyncExecutor)
    executor.session = None  # type: ignore[assignment]
    executor.registry = None  # type: ignore[assignment]
    executor.settings = SimpleNamespace(browser_first_mode=False)

    class _FakeRepo:
        async def get_sync_settings_config(self, workspace_id):  # noqa: ANN001
            return {"max_contents": None, "skip_existing": True, "yt_dlp": {}}

    executor.repository = _FakeRepo()  # type: ignore[assignment]

    class _FakeCredService:
        def __init__(self, *args, **kwargs):  # noqa: ANN001
            pass

        @staticmethod
        async def resolve(workspace_id, platform_key):  # noqa: ANN001
            return "api", {}

    monkeypatch.setattr(
        "app.services.sync.PlatformCredentialService", _FakeCredService
    )

    account = SimpleNamespace(
        workspace_id=uuid4(),
        platform=SimpleNamespace(key="tiktok"),
        sync_settings_override=None,
    )
    config = await executor._config_for(account)
    assert config["download"]["write_thumbnail"] is True
    # A non-expiring platform must NOT be forced on.
    account.platform.key = "youtube"
    config_youtube = await executor._config_for(account)
    assert "download" not in config_youtube


async def test_executor_config_for_explicit_thumbnail_off_respected(
    monkeypatch,
) -> None:
    # An explicit operator opt-out of thumbnail archiving must be honoured for
    # the otherwise-forced platforms.
    executor = PlatformSyncExecutor.__new__(PlatformSyncExecutor)
    executor.session = None  # type: ignore[assignment]
    executor.registry = None  # type: ignore[assignment]
    executor.settings = SimpleNamespace(browser_first_mode=False)

    class _FakeRepo:
        async def get_sync_settings_config(self, workspace_id):  # noqa: ANN001
            return {
                "max_contents": None,
                "skip_existing": True,
                "yt_dlp": {},
                "download": {"write_thumbnail": False},
            }

    executor.repository = _FakeRepo()  # type: ignore[assignment]

    class _FakeCredService:
        def __init__(self, *args, **kwargs):  # noqa: ANN001
            pass

        @staticmethod
        async def resolve(workspace_id, platform_key):  # noqa: ANN001
            return "api", {}

    monkeypatch.setattr(
        "app.services.sync.PlatformCredentialService", _FakeCredService
    )

    account = SimpleNamespace(
        workspace_id=uuid4(),
        platform=SimpleNamespace(key="douyin"),
        sync_settings_override=None,
    )
    config = await executor._config_for(account)
    assert config["download"]["write_thumbnail"] is False

