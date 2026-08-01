from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.monitoring import (
    Account,
    AccountSnapshot,
    ContentItem,
    ContentSnapshot,
    DerivedMetric,
)

from .conftest import TEST_PLATFORM_ID
from .test_monitoring_api import authenticate, create_account


def _seed_account_with_two_contents(
    client: TestClient, database_path: Path
) -> UUID:
    csrf_token = authenticate(client)
    account = create_account(client, csrf_token)
    account_id = UUID(account["id"])
    workspace_id = UUID(account["workspace_id"])
    now = datetime.now(UTC)

    content_a = uuid4()
    content_b = uuid4()

    engine = create_engine(f"postgresql+psycopg://sio:sio-local-development-only@127.0.0.1:5432/{database_path}")
    with Session(engine) as session:
        assert session.get(Account, account_id) is not None

        def make_content(cid: UUID, title: str) -> ContentItem:
            return ContentItem(
                id=cid,
                workspace_id=workspace_id,
                platform_id=TEST_PLATFORM_ID,
                account_id=account_id,
                external_id=f"content-{cid.hex[:8]}",
                content_type="video",
                title=title,
                description="",
                published_at=now - timedelta(days=1),
                duration_seconds=Decimal("30.0"),
                canonical_url=f"https://example.com/{cid.hex}",
                cover_url=None,
                language="zh-CN",
                status="published",
                metadata_json={},
                first_seen_at=now - timedelta(days=1),
                last_seen_at=now,
                source_kind="imported",
                source_provider="test_fixture",
                fetched_at=now,
                source_url=f"https://example.com/{cid.hex}",
                raw_payload_ref=None,
            )

        def make_snapshot(
            cid: UUID,
            *,
            views: int,
            like: int,
            comment: int,
            share: int,
            favorite: int,
            completion: float,
            rec: float,
            search: float,
            profile: float,
            growth: int,
        ) -> tuple[ContentSnapshot, DerivedMetric]:
            snap = ContentSnapshot(
                id=uuid4(),
                content_item_id=cid,
                captured_at=now,
                view_count=views,
                like_count=like,
                comment_count=comment,
                share_count=share,
                favorite_count=favorite,
                follower_gain=0,
                average_watch_time=Decimal("32.0"),
                completion_rate=Decimal(str(completion)),
                search_traffic_rate=Decimal(str(search)),
                recommendation_traffic_rate=Decimal(str(rec)),
                profile_traffic_rate=Decimal(str(profile)),
                revenue=None,
                rpm=None,
                metadata_json={},
                source_kind="imported",
                source_provider="test_fixture",
                fetched_at=now,
                raw_payload_ref=None,
                created_at=now,
            )
            metric = DerivedMetric(
                id=uuid4(),
                workspace_id=workspace_id,
                entity_type="content_item",
                entity_id=cid,
                metric_key="view_growth_24h",
                window="24h",
                value=Decimal(str(growth)),
                calculated_at=now,
                metadata_json={"algorithm_version": "test-v1"},
            )
            return snap, metric

        session.add_all(
            [
                make_content(content_a, "高完播爆款"),
                make_content(content_b, "普通作品"),
                *make_snapshot(
                    content_a,
                    views=900_000,
                    like=70_000,
                    comment=4_000,
                    share=8_000,
                    favorite=9_000,
                    completion=0.68,
                    rec=0.70,
                    search=0.20,
                    profile=0.10,
                    growth=350_000,
                ),
                *make_snapshot(
                    content_b,
                    views=100_000,
                    like=5_000,
                    comment=500,
                    share=300,
                    favorite=200,
                    completion=0.40,
                    rec=0.50,
                    search=0.30,
                    profile=0.20,
                    growth=50_000,
                ),
                AccountSnapshot(
                    id=uuid4(),
                    account_id=account_id,
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
            ]
        )
        session.commit()
    engine.dispose()
    return account_id


def test_account_content_summary_aggregates_real_snapshots(
    client: TestClient, database_path: Path
) -> None:
    account_id = _seed_account_with_two_contents(client, database_path)

    summary = client.get(f"/api/v1/accounts/{account_id}/content-summary")
    assert summary.status_code == 200, summary.text
    data = summary.json()

    assert data["content_count"] == 2
    assert data["avg_completion_rate"] == pytest.approx(0.54, rel=1e-3)
    # view-weighted recommendation split: (900000*0.70 + 100000*0.50) / 1_000_000
    assert data["traffic_source_split"]["recommendation"] == pytest.approx(
        0.68, rel=1e-3
    )
    assert data["traffic_source_split"]["search"] == pytest.approx(0.21, rel=1e-3)
    # total interactions: 91000 + 6000
    assert data["total_interactions"] == 97_000
    # recent 24h view growth: 350000 + 50000
    assert data["recent_24h_view_growth"] == 400_000
    # top content by views is the 900k one
    assert data["top_content_views"] == 900_000


@pytest.mark.parametrize(
    "sort_key",
    ["completion_rate", "engagement_rate", "like_count", "share_count"],
)
def test_account_contents_accepts_granular_sort_keys(
    client: TestClient, database_path: Path, sort_key: str
) -> None:
    account_id = _seed_account_with_two_contents(client, database_path)

    response = client.get(
        f"/api/v1/accounts/{account_id}/contents",
        params={"sort": sort_key, "order": "desc"},
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 2
    # Highest completion / engagement / like / share is the 900k content (first).
    assert items[0]["latest_snapshot"]["view_count"] == 900_000
