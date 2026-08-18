from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.monitoring import Account, ContentItem, ContentSnapshot
from app.models.user import User
from app.models.workspace import Workspace

from .conftest import PG_SYNC_URL, TEST_PASSWORD, TEST_PLATFORM_ID


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def seed_tracked_content() -> tuple[str, datetime]:
    published_at = datetime.now(UTC) - timedelta(days=8)
    with Session(create_engine(PG_SYNC_URL)) as session:
        workspace = session.scalar(select(Workspace).where(Workspace.slug == "test-workspace"))
        user = session.scalar(select(User).where(User.email_normalized == "admin@example.com"))
        assert workspace is not None
        assert user is not None
        account = Account(
            id=uuid4(),
            workspace_id=workspace.id,
            platform_id=TEST_PLATFORM_ID,
            external_id=f"account-{uuid4()}",
            display_name="归因测试账号",
            profile_url="https://example.com/account",
            fetched_at=datetime.now(UTC),
            source_kind="live",
            source_provider="test_live_adapter",
        )
        content = ContentItem(
            id=uuid4(),
            workspace_id=workspace.id,
            platform_id=TEST_PLATFORM_ID,
            account_id=account.id,
            external_id=f"content-{uuid4()}",
            content_type="video",
            title="归因测试作品",
            canonical_url="https://example.com/content",
            status="published",
            first_seen_at=published_at,
            last_seen_at=datetime.now(UTC),
            source_kind="live",
            source_provider="test_live_adapter",
            fetched_at=datetime.now(UTC),
            metadata_json={},
            tags=[],
        )
        session.add_all([account, content])
        session.flush()
        snapshot_1h = ContentSnapshot(
            id=uuid4(),
            content_item_id=content.id,
            captured_at=published_at + timedelta(hours=1, minutes=5),
            view_count=1000,
            like_count=100,
            comment_count=10,
            share_count=5,
            favorite_count=8,
            follower_gain=20,
            average_watch_time=Decimal("18.500"),
            completion_rate=Decimal("0.45000000"),
            source_kind="live",
            source_provider="test_live_adapter",
            fetched_at=published_at + timedelta(hours=1, minutes=5),
            metadata_json={},
            created_at=published_at + timedelta(hours=1, minutes=5),
        )
        snapshot_24h = ContentSnapshot(
            id=uuid4(),
            content_item_id=content.id,
            captured_at=published_at + timedelta(hours=24, minutes=10),
            view_count=5000,
            like_count=500,
            comment_count=50,
            share_count=25,
            favorite_count=40,
            follower_gain=100,
            average_watch_time=Decimal("20.000"),
            completion_rate=Decimal("0.50000000"),
            source_kind="live",
            source_provider="test_live_adapter",
            fetched_at=published_at + timedelta(hours=24, minutes=10),
            metadata_json={},
            created_at=published_at + timedelta(hours=24, minutes=10),
        )
        snapshot_7d = ContentSnapshot(
            id=uuid4(),
            content_item_id=content.id,
            captured_at=published_at + timedelta(days=7, minutes=10),
            view_count=20000,
            like_count=2000,
            comment_count=200,
            share_count=100,
            favorite_count=160,
            follower_gain=400,
            average_watch_time=Decimal("22.000"),
            completion_rate=Decimal("0.55000000"),
            source_kind="live",
            source_provider="test_live_adapter",
            fetched_at=published_at + timedelta(days=7, minutes=10),
            metadata_json={},
            created_at=published_at + timedelta(days=7, minutes=10),
        )
        session.add_all([snapshot_1h, snapshot_24h, snapshot_7d])
        session.commit()
        return str(content.id), published_at


def test_publication_attribution_uses_real_content_snapshots(client: TestClient) -> None:
    csrf = authenticate(client)
    content_id, published_at = seed_tracked_content()
    response = client.post(
        "/api/v1/publications",
        headers={"X-CSRF-Token": csrf},
        json={
            "title": "归因测试发布",
            "content_item_id": content_id,
            "status": "published",
            "published_at": published_at.isoformat(),
            "external_id": "published-content-1",
            "canonical_url": "https://example.com/published-content-1",
            "source_kind": "imported",
        },
    )
    assert response.status_code == 201, response.text
    publication = response.json()
    assert publication["status"] == "published"
    assert publication["attributions"] == []

    refresh = client.post(
        f"/api/v1/publications/{publication['id']}/attribution/refresh",
        headers={"X-CSRF-Token": csrf},
    )
    assert refresh.status_code == 200, refresh.text
    result = refresh.json()
    assert result["measured_count"] >= 3
    measured = [item for item in result["attributions"] if item["measurement_status"] == "measured"]
    assert measured
    assert all(item["source_kind"] == "live" for item in measured)
    assert all(item["evidence"]["content_snapshot_id"] for item in measured)
    assert {item["window_key"] for item in result["attributions"]} == {
        "1h",
        "3h",
        "6h",
        "24h",
        "72h",
        "7d",
        "30d",
    }

    detail = client.get(f"/api/v1/publications/{publication['id']}")
    assert detail.status_code == 200
    assert len(detail.json()["attributions"]) == 7


def test_publication_never_claims_published_without_evidence(client: TestClient) -> None:
    csrf = authenticate(client)
    response = client.post(
        "/api/v1/publications",
        headers={"X-CSRF-Token": csrf},
        json={"title": "缺少证据", "status": "published"},
    )
    assert response.status_code == 422

    planned = client.post(
        "/api/v1/publications",
        headers={"X-CSRF-Token": csrf},
        json={"title": "待发布内容"},
    )
    assert planned.status_code == 201
    publication_id = planned.json()["id"]
    refresh = client.post(
        f"/api/v1/publications/{publication_id}/attribution/refresh",
        headers={"X-CSRF-Token": csrf},
    )
    assert refresh.status_code == 409
    assert refresh.json()["code"] == "attribution_publish_time_missing"
