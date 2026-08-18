from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.monitoring import Account, ContentItem
from app.models.publication import PerformanceAttribution, Publication
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


def seed_publication() -> str:
    published_at = datetime.now(UTC) - timedelta(days=2)
    with Session(create_engine(PG_SYNC_URL)) as session:
        workspace = session.scalar(select(Workspace).where(Workspace.slug == "test-workspace"))
        user = session.scalar(select(User).where(User.email_normalized == "admin@example.com"))
        assert workspace is not None
        assert user is not None
        account = Account(
            id=uuid4(),
            workspace_id=workspace.id,
            platform_id=TEST_PLATFORM_ID,
            external_id=f"experiment-account-{uuid4()}",
            display_name="实验账号",
            username="experiment-account",
            profile_url="https://example.com/experiment-account",
            source_kind="live",
            source_provider="experiment_test",
            fetched_at=published_at,
            sync_status="success",
        )
        content = ContentItem(
            id=uuid4(),
            workspace_id=workspace.id,
            platform_id=TEST_PLATFORM_ID,
            account_id=account.id,
            external_id=f"experiment-content-{uuid4()}",
            content_type="video",
            title="实验作品",
            canonical_url="https://example.com/experiment-content",
            status="published",
            first_seen_at=published_at,
            last_seen_at=published_at,
            source_kind="live",
            source_provider="experiment_test",
            fetched_at=published_at,
            metadata_json={},
            tags=[],
        )
        publication = Publication(
            id=uuid4(),
            workspace_id=workspace.id,
            created_by=user.id,
            content_item_id=content.id,
            platform_id=TEST_PLATFORM_ID,
            title="实验发布",
            external_id=f"experiment-publication-{uuid4()}",
            canonical_url="https://example.com/experiment-publication",
            status="published",
            published_at=published_at,
            source_kind="imported",
            source_provider="manual",
            metadata_json={},
        )
        attribution = PerformanceAttribution(
            id=uuid4(),
            workspace_id=workspace.id,
            publication_id=publication.id,
            window_key="24h",
            window_seconds=86400,
            target_at=published_at + timedelta(days=1),
            measurement_status="measured",
            captured_at=published_at + timedelta(days=1, minutes=3),
            view_count=10000,
            like_count=500,
            comment_count=100,
            share_count=50,
            favorite_count=25,
            completion_rate=Decimal("0.42"),
            source_kind="live",
            source_provider="experiment_test",
            evidence_json={"content_snapshot_id": str(uuid4())},
        )
        session.add_all([account, content])
        session.flush()
        session.add_all([publication, attribution])
        session.commit()
        return str(publication.id)


def test_observational_experiment_reports_real_attribution(client: TestClient) -> None:
    csrf = authenticate(client)
    publication_id = seed_publication()
    created = client.post(
        "/api/v1/content-experiments",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "标题首句观察",
            "hypothesis": "具体动作开场可能带来更高互动",
            "dimension": "title",
        },
    )
    assert created.status_code == 201, created.text
    experiment_id = created.json()["id"]

    variant = client.post(
        f"/api/v1/content-experiments/{experiment_id}/variants",
        headers={"X-CSRF-Token": csrf},
        json={"label": "A", "publication_id": publication_id},
    )
    assert variant.status_code == 201, variant.text

    report = client.get(f"/api/v1/content-experiments/{experiment_id}/report?window_key=24h")
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["comparison_type"] == "observational"
    assert body["variants"][0]["measured_count"] == 1
    assert body["variants"][0]["average_views"] == 10000.0
    assert any("不代表因果关系" in caveat for caveat in body["caveats"])
