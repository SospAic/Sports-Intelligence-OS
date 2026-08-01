from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.adapters.platforms.registry import build_platform_adapter_registry
from app.core.config import Settings
from app.models.monitoring import (
    Account,
    AccountSnapshot,
    ContentItem,
    ContentSnapshot,
    DerivedMetric,
)
from app.models.workspace import Workspace
from app.services.monitoring_seed import seed_demo_monitoring
from app.services.sync import PlatformSyncExecutor

from .conftest import TEST_PASSWORD, TEST_PLATFORM_ID


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def create_account(client: TestClient, csrf_token: str, *, display_name: str = "测试账号") -> dict:
    response = client.post(
        "/api/v1/accounts",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "platform_id": str(TEST_PLATFORM_ID),
            "external_id": "external-account-001",
            "username": "sports_creator",
            "display_name": display_name,
            "profile_url": "https://example.com/sports_creator",
            "country": "cn",
            "language": "zh-CN",
            "metadata": {"team": "test"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_platform_and_account_crud_are_authenticated_and_auditable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatched: list[UUID] = []
    monkeypatch.setattr(
        "app.services.sync.enqueue_platform_sync", lambda run_id: dispatched.append(run_id)
    )
    assert client.get("/api/v1/platforms").status_code == 401
    csrf_token = authenticate(client)

    platforms = client.get("/api/v1/platforms")
    assert platforms.status_code == 200
    assert platforms.json()[0]["key"] == "test_platform"

    account = create_account(client, csrf_token)
    assert account["source_kind"] == "imported"
    assert account["source_provider"] == "manual"
    assert account["metadata"]["input_mode"] == "manual"

    duplicate = client.post(
        "/api/v1/accounts",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "platform_id": str(TEST_PLATFORM_ID),
            "external_id": "external-account-001",
            "display_name": "重复账号",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "monitoring_resource_conflict"

    listing = client.get(
        "/api/v1/accounts",
        params={"platform": "test_platform", "query": "sports", "page_size": 1},
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["id"] == account["id"]

    reserved_metadata = client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={"metadata": {"source_kind": "live"}},
    )
    assert reserved_metadata.status_code == 422

    updated = client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={"display_name": "更新后的账号"},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "更新后的账号"

    sync = client.post(
        f"/api/v1/accounts/{account['id']}/sync",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert sync.status_code == 202
    assert sync.json()["status"] == "queued"
    assert dispatched == [UUID(sync.json()["id"])]
    runs = client.get(f"/api/v1/accounts/{account['id']}/sync-runs")
    assert runs.status_code == 200
    assert runs.json()["items"][0]["status"] == "queued"

    deleted = client.delete(
        f"/api/v1/accounts/{account['id']}",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert deleted.status_code == 204
    preserved = client.get(f"/api/v1/accounts/{account['id']}")
    assert preserved.status_code == 200
    assert preserved.json()["is_active"] is False
    assert preserved.json()["sync_status"] == "disabled"


@pytest.mark.asyncio
async def test_mock_sync_executes_end_to_end_and_remains_clearly_mock(
    client: TestClient,
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.sync.enqueue_platform_sync", lambda _run_id: None)
    csrf_token = authenticate(client)
    account = create_account(client, csrf_token)
    queued = client.post(
        f"/api/v1/accounts/{account['id']}/sync",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert queued.status_code == 202

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
    try:
        async with session_factory() as session:
            await PlatformSyncExecutor(session, registry, settings).execute_account_run(
                UUID(queued.json()["id"])
            )
    finally:
        for adapter in registry.values():
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()

    refreshed = client.get(f"/api/v1/accounts/{account['id']}")
    assert refreshed.status_code == 200
    assert refreshed.json()["sync_status"] == "success"
    assert refreshed.json()["source_kind"] == "mock"
    assert refreshed.json()["source_provider"] == "mock_platform"
    assert refreshed.json()["last_sync_error_code"] is None
    assert refreshed.json()["next_sync_at"] is not None

    snapshots = client.get(f"/api/v1/accounts/{account['id']}/snapshots")
    contents = client.get(f"/api/v1/accounts/{account['id']}/contents")
    runs = client.get(f"/api/v1/accounts/{account['id']}/sync-runs")
    assert snapshots.json()["items"][0]["source_kind"] == "mock"
    assert contents.json()["total"] == 12
    assert all(item["source_kind"] == "mock" for item in contents.json()["items"])
    assert runs.json()["items"][0]["status"] == "success"
    first_content = contents.json()["items"][0]
    metrics = client.get(f"/api/v1/contents/{first_content['id']}/metrics")
    metric_keys = {item["metric_key"] for item in metrics.json()["items"]}
    assert metric_keys >= {
        "engagement_rate",
        "median_views_30d",
        "viral_score",
    }
    assert "view_velocity" not in metric_keys
    assert "view_acceleration" not in metric_keys
    viral = next(item for item in metrics.json()["items"] if item["metric_key"] == "viral_score")
    assert set(viral["metadata"]["incomplete_components"]) == {"view_velocity"}


def test_content_filters_history_metrics_and_csv_export(
    client: TestClient, database_path: Path
) -> None:
    csrf_token = authenticate(client)
    account_data = create_account(client, csrf_token, display_name="=账号公式")
    account_id = account_data["id"]
    now = datetime.now(UTC)
    content_id = uuid4()

    engine = create_engine(f"sqlite:///{database_path}")
    with Session(engine) as session:
        account = session.get(Account, UUID(account_id))
        assert account is not None
        content = ContentItem(
            id=content_id,
            workspace_id=account.workspace_id,
            platform_id=TEST_PLATFORM_ID,
            account_id=account.id,
            external_id="content-001",
            content_type="video",
            title='=HYPERLINK("https://invalid")',
            description="最后一分钟逆转",
            published_at=now - timedelta(days=1),
            duration_seconds=Decimal("45.500"),
            canonical_url="https://example.com/content-001",
            cover_url=None,
            language="zh-CN",
            status="published",
            metadata_json={"field_from_platform": "kept-in-metadata"},
            first_seen_at=now - timedelta(days=1),
            last_seen_at=now,
            source_kind="imported",
            source_provider="test_fixture",
            fetched_at=now,
            source_url="https://example.com/content-001",
            raw_payload_ref=None,
        )
        session.add(content)
        session.add_all(
            [
                AccountSnapshot(
                    id=uuid4(),
                    account_id=account.id,
                    captured_at=now,
                    follower_count=5000,
                    following_count=10,
                    total_like_count=20000,
                    total_view_count=2_000_000,
                    video_count=20,
                    engagement_rate=Decimal("0.08"),
                    metadata_json={},
                    source_kind="imported",
                    source_provider="test_fixture",
                    fetched_at=now,
                    raw_payload_ref=None,
                    created_at=now,
                ),
                ContentSnapshot(
                    id=uuid4(),
                    content_item_id=content_id,
                    captured_at=now - timedelta(hours=1),
                    view_count=900_000,
                    like_count=70_000,
                    comment_count=4_000,
                    share_count=8_000,
                    favorite_count=9_000,
                    follower_gain=500,
                    average_watch_time=Decimal("31.2"),
                    completion_rate=Decimal("0.68"),
                    search_traffic_rate=Decimal("0.20"),
                    recommendation_traffic_rate=Decimal("0.70"),
                    profile_traffic_rate=Decimal("0.10"),
                    revenue=None,
                    rpm=None,
                    metadata_json={},
                    source_kind="imported",
                    source_provider="test_fixture",
                    fetched_at=now - timedelta(hours=1),
                    raw_payload_ref=None,
                    created_at=now - timedelta(hours=1),
                ),
                ContentSnapshot(
                    id=uuid4(),
                    content_item_id=content_id,
                    captured_at=now,
                    view_count=1_250_000,
                    like_count=100_000,
                    comment_count=6_000,
                    share_count=12_000,
                    favorite_count=14_000,
                    follower_gain=800,
                    average_watch_time=Decimal("34.8"),
                    completion_rate=Decimal("0.75"),
                    search_traffic_rate=Decimal("0.18"),
                    recommendation_traffic_rate=Decimal("0.72"),
                    profile_traffic_rate=Decimal("0.10"),
                    revenue=None,
                    rpm=None,
                    metadata_json={},
                    source_kind="imported",
                    source_provider="test_fixture",
                    fetched_at=now,
                    raw_payload_ref=None,
                    created_at=now,
                ),
                DerivedMetric(
                    id=uuid4(),
                    workspace_id=account.workspace_id,
                    entity_type="content_item",
                    entity_id=content_id,
                    metric_key="view_growth_24h",
                    window="24h",
                    value=Decimal("350000"),
                    calculated_at=now,
                    metadata_json={"algorithm_version": "test-v1"},
                ),
            ]
        )
        session.commit()
    engine.dispose()

    contents = client.get(
        "/api/v1/contents",
        params={
            "min_views": 1_000_000,
            "sort": "view_growth_24h",
            "order": "desc",
            "query": "逆转",
        },
    )
    assert contents.status_code == 200, contents.text
    item = contents.json()["items"][0]
    assert item["latest_snapshot"]["view_count"] == 1_250_000
    assert item["view_growth_24h"] == 350_000

    snapshots = client.get(f"/api/v1/contents/{content_id}/snapshots")
    assert snapshots.status_code == 200
    assert snapshots.json()["total"] == 2
    assert snapshots.json()["items"][0]["view_count"] == 1_250_000

    metrics = client.get(f"/api/v1/contents/{content_id}/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["items"][0]["metric_key"] == "view_growth_24h"

    account_snapshots = client.get(f"/api/v1/accounts/{account_id}/snapshots")
    assert account_snapshots.status_code == 200
    assert account_snapshots.json()["items"][0]["follower_count"] == 5000

    nested = client.get(f"/api/v1/accounts/{account_id}/contents")
    assert nested.status_code == 200
    assert nested.json()["total"] == 1

    accounts_csv = client.get("/api/v1/accounts/export.csv")
    contents_csv = client.get("/api/v1/contents/export.csv")
    assert accounts_csv.status_code == 200
    assert "'=账号公式" in accounts_csv.text
    assert contents_csv.status_code == 200
    assert "'=HYPERLINK" in contents_csv.text
    assert "imported" in contents_csv.text


def test_account_metrics_history_returns_ascending_series_within_window(
    client: TestClient, database_path: Path
) -> None:
    csrf_token = authenticate(client)
    account = create_account(client, csrf_token)
    account_id = UUID(account["id"])
    now = datetime.now(UTC)

    engine = create_engine(f"sqlite:///{database_path}")
    with Session(engine) as session:
        assert session.get(Account, account_id) is not None
        session.add_all(
            [
                AccountSnapshot(
                    id=uuid4(),
                    account_id=account_id,
                    captured_at=now - timedelta(days=45),
                    follower_count=1000,
                    video_count=10,
                    total_view_count=50_000,
                    metadata_json={},
                    source_kind="mock",
                    source_provider="manual",
                    fetched_at=now - timedelta(days=45),
                    created_at=now - timedelta(days=45),
                ),
                AccountSnapshot(
                    id=uuid4(),
                    account_id=account_id,
                    captured_at=now - timedelta(days=20),
                    follower_count=2000,
                    video_count=20,
                    total_view_count=120_000,
                    metadata_json={},
                    source_kind="mock",
                    source_provider="manual",
                    fetched_at=now - timedelta(days=20),
                    created_at=now - timedelta(days=20),
                ),
                AccountSnapshot(
                    id=uuid4(),
                    account_id=account_id,
                    captured_at=now - timedelta(days=5),
                    follower_count=3500,
                    video_count=25,
                    total_view_count=210_000,
                    metadata_json={},
                    source_kind="mock",
                    source_provider="manual",
                    fetched_at=now - timedelta(days=5),
                    created_at=now - timedelta(days=5),
                ),
            ]
        )
        session.commit()
    engine.dispose()

    history = client.get(
        f"/api/v1/accounts/{account_id}/metrics/history",
        params={"days": 30},
    )
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["account_id"] == str(account_id)
    assert body["days"] == 30
    # The 45-day-old snapshot must fall outside the 30-day window.
    assert len(body["points"]) == 2
    captured = [p["captured_at"] for p in body["points"]]
    assert captured == sorted(captured)  # ascending for charting
    assert [p["follower_count"] for p in body["points"]] == [2000, 3500]

    narrow = client.get(
        f"/api/v1/accounts/{account_id}/metrics/history",
        params={"days": 10},
    )
    assert narrow.status_code == 200
    assert len(narrow.json()["points"]) == 1
    assert narrow.json()["points"][0]["follower_count"] == 3500

    bad = client.get(
        f"/api/v1/accounts/{account_id}/metrics/history",
        params={"days": 0},
    )
    assert bad.status_code == 422


def test_database_uniqueness_prevents_duplicate_content_and_snapshot(
    client: TestClient, database_path: Path
) -> None:
    csrf_token = authenticate(client)
    account_data = create_account(client, csrf_token)
    now = datetime.now(UTC)
    engine = create_engine(f"sqlite:///{database_path}")
    with Session(engine) as session:
        account = session.get(Account, UUID(account_data["id"]))
        assert account is not None
        common = {
            "workspace_id": account.workspace_id,
            "platform_id": TEST_PLATFORM_ID,
            "account_id": account.id,
            "external_id": "duplicate-content",
            "content_type": "video",
            "title": "duplicate check",
            "description": None,
            "published_at": now,
            "duration_seconds": Decimal("1"),
            "canonical_url": "https://example.com/duplicate",
            "cover_url": None,
            "language": "en",
            "status": "published",
            "metadata_json": {},
            "first_seen_at": now,
            "last_seen_at": now,
            "source_kind": "imported",
            "source_provider": "test_fixture",
            "fetched_at": now,
            "source_url": None,
            "raw_payload_ref": None,
        }
        session.add_all([ContentItem(id=uuid4(), **common), ContentItem(id=uuid4(), **common)])
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        content = ContentItem(id=uuid4(), **common)
        session.add(content)
        session.commit()
        snapshot_common = {
            "content_item_id": content.id,
            "captured_at": now,
            "view_count": 1,
            "like_count": None,
            "comment_count": None,
            "share_count": None,
            "favorite_count": None,
            "follower_gain": None,
            "average_watch_time": None,
            "completion_rate": None,
            "search_traffic_rate": None,
            "recommendation_traffic_rate": None,
            "profile_traffic_rate": None,
            "revenue": None,
            "rpm": None,
            "metadata_json": {},
            "source_kind": "imported",
            "source_provider": "test_fixture",
            "fetched_at": now,
            "raw_payload_ref": None,
            "created_at": now,
        }
        session.add_all(
            [
                ContentSnapshot(id=uuid4(), **snapshot_common),
                ContentSnapshot(id=uuid4(), **snapshot_common),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        immutable_snapshot = ContentSnapshot(id=uuid4(), **snapshot_common)
        session.add(immutable_snapshot)
        session.commit()
        immutable_snapshot.view_count = 2
        with pytest.raises(RuntimeError, match="append-only"):
            session.commit()
        session.rollback()
    engine.dispose()


@pytest.mark.asyncio
async def test_demo_seed_is_idempotent_and_always_marked_mock(
    client: TestClient, database_path: Path
) -> None:
    authenticate(client)
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            workspace_id = await session.scalar(
                select(Workspace.id).where(Workspace.slug == "test-workspace")
            )
            assert workspace_id is not None
            first = await seed_demo_monitoring(session, workspace_id)
            second = await seed_demo_monitoring(session, workspace_id)
            assert first == {"accounts_created": 1, "contents_created": 1}
            assert second == {"accounts_created": 0, "contents_created": 0}
    finally:
        await engine.dispose()

    demo_accounts = client.get("/api/v1/accounts", params={"platform": "demo_mock"})
    demo_contents = client.get("/api/v1/contents", params={"platform": "demo_mock"})
    assert demo_accounts.status_code == 200
    assert demo_accounts.json()["items"][0]["source_kind"] == "mock"
    assert demo_accounts.json()["items"][0]["metadata"]["demo"] is True
    assert demo_contents.status_code == 200
    assert demo_contents.json()["items"][0]["source_kind"] == "mock"


def test_account_view_preferences_route_is_not_shadowed_by_account_id(
    client: TestClient,
) -> None:
    """GET /accounts/view-preferences must resolve to the view-preferences route,
    not be captured by GET /accounts/{account_id} (which would 422 on the UUID)."""
    csrf_token = authenticate(client)
    get_response = client.get("/api/v1/accounts/view-preferences")
    assert get_response.status_code == 200
    put_response = client.put(
        "/api/v1/accounts/view-preferences",
        headers={"X-CSRF-Token": csrf_token},
        json={"preferences": {"platform": "all", "activeState": "all", "visibility": {}}},
    )
    assert put_response.status_code == 200
    assert put_response.json()["preferences"]["platform"] == "all"
