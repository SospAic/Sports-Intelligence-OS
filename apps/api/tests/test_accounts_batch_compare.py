"""Integration tests for batch account operations, cross-platform comparison,
and the adaptive sync-interval endpoint.

All data here is produced by the real-shaped test adapter (``source_kind='live'``)
or by direct service calls — never by a mock source kind.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.platforms.registry import build_platform_adapter_registry
from app.core.config import Settings
from app.services.sync import PlatformSyncExecutor

from .conftest import TEST_PASSWORD, TEST_PLATFORM_ID, RealShapedTestAdapter


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def create_account(
    client: TestClient, csrf_token: str, *, external_id: str, display_name: str
) -> dict:
    response = client.post(
        "/api/v1/accounts",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "platform_id": str(TEST_PLATFORM_ID),
            "external_id": external_id,
            "username": display_name,
            "display_name": display_name,
            "country": "cn",
            "language": "zh-CN",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def run_sync(client: TestClient, database_path, run_id: UUID) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{database_path}",
        redis_url="redis://127.0.0.1:6399/15",
        secret_key="test-only-secret-not-used-in-production",
        sync_page_limit=2,
    )
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = build_platform_adapter_registry(settings)
    registry.replace(RealShapedTestAdapter(key="youtube_browser", content_count=4))
    try:
        async with session_factory() as session:
            await PlatformSyncExecutor(session, registry, settings).execute_account_run(
                run_id
            )
    finally:
        for adapter in registry.values():
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()


def test_accounts_batch_update_and_delete(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.sync.enqueue_platform_sync", lambda _rid: None)
    csrf = authenticate(client)
    a1 = create_account(client, csrf, external_id="batch-a1", display_name="BatchA1")
    a2 = create_account(client, csrf, external_id="batch-a2", display_name="BatchA2")

    # Batch deactivate.
    patch = client.patch(
        "/api/v1/accounts/batch",
        headers={"X-CSRF-Token": csrf},
        json={"account_ids": [a1["id"], a2["id"]], "is_active": False},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["updated"] == 2
    assert client.get(f"/api/v1/accounts/{a1['id']}").json()["is_active"] is False
    assert client.get(f"/api/v1/accounts/{a2['id']}").json()["is_active"] is False

    # Batch delete (soft) targets only the first account.
    delete = client.post(
        "/api/v1/accounts/batch/delete",
        headers={"X-CSRF-Token": csrf},
        json={"account_ids": [a1["id"]]},
    )
    assert delete.status_code == 200, delete.text
    assert delete.json()["updated"] == 1
    removed = client.get(f"/api/v1/accounts/{a1['id']}")
    assert removed.json()["is_active"] is False
    assert removed.json()["sync_status"] == "disabled"

    # An account outside the workspace is reported as skipped, not accepted.
    unknown = str(UUID("00000000-0000-0000-0000-000000000099"))
    missing = client.patch(
        "/api/v1/accounts/batch",
        headers={"X-CSRF-Token": csrf},
        json={"account_ids": [unknown], "is_active": True},
    )
    assert missing.status_code == 200
    assert missing.json()["updated"] == 0


@pytest.mark.asyncio
async def test_accounts_compare_returns_real_snapshots(
    client: TestClient, database_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.sync.enqueue_platform_sync", lambda _rid: None)
    csrf = authenticate(client)
    a1 = create_account(client, csrf, external_id="cmp-a1", display_name="CmpA1")
    a2 = create_account(client, csrf, external_id="cmp-a2", display_name="CmpA2")

    for account in (a1, a2):
        queued = client.post(
            f"/api/v1/accounts/{account['id']}/sync",
            headers={"X-CSRF-Token": csrf},
        )
        assert queued.status_code == 202
        await run_sync(client, database_path, UUID(queued.json()["id"]))

    response = client.get(
        "/api/v1/accounts/compare",
        params=[("account_ids", a1["id"]), ("account_ids", a2["id"])],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["account_count"] == 2
    assert len(body["rows"]) == 2
    # Totals are deterministic from the real-shaped adapter (follower=12500, views=1_000_000).
    assert body["summary"]["total_followers"] == 25000
    assert body["summary"]["total_views"] == 2_000_000
    assert body["summary"]["best_followers_account_id"] in (a1["id"], a2["id"])
    for row in body["rows"]:
        assert row["latest"] is not None
        assert row["latest"]["source_kind"] == "live"
        assert row["latest"]["follower_count"] == 12500
        assert row["follower_delta"] is None  # only a single snapshot per account


@pytest.mark.asyncio
async def test_account_sync_interval_adaptive_and_default(
    client: TestClient, database_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.sync.enqueue_platform_sync", lambda _rid: None)
    csrf = authenticate(client)

    # No contents yet -> default hourly interval, basis "default".
    empty = create_account(client, csrf, external_id="iv-empty", display_name="IvEmpty")
    default_resp = client.post(
        f"/api/v1/accounts/{empty['id']}/sync-interval",
        headers={"X-CSRF-Token": csrf},
    )
    assert default_resp.status_code == 200, default_resp.text
    assert default_resp.json()["basis"] == "default"
    assert default_resp.json()["sync_interval_seconds"] == 3600

    # After a sync with real-shaped contents, the cadence becomes adaptive and
    # the executor stores it back on the account (clamped to the 300s floor
    # because the test adapter stamps identical published_at on every item).
    seeded = create_account(client, csrf, external_id="iv-seeded", display_name="IvSeeded")
    queued = client.post(
        f"/api/v1/accounts/{seeded['id']}/sync",
        headers={"X-CSRF-Token": csrf},
    )
    await run_sync(client, database_path, UUID(queued.json()["id"]))

    refreshed = client.get(f"/api/v1/accounts/{seeded['id']}")
    assert refreshed.json()["sync_interval_seconds"] == 300  # adaptive floor

    adaptive_resp = client.post(
        f"/api/v1/accounts/{seeded['id']}/sync-interval",
        headers={"X-CSRF-Token": csrf},
    )
    assert adaptive_resp.status_code == 200, adaptive_resp.text
    assert adaptive_resp.json()["basis"] == "adaptive"
    assert 300 <= adaptive_resp.json()["sync_interval_seconds"] <= 86_400
