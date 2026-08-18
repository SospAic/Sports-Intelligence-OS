from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.artifact import MediaArtifact
from app.models.download import Download

from .conftest import PG_SYNC_URL, TEST_PASSWORD


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def test_media_rights_preserves_unknown_state_and_audits_approved_review(
    client: TestClient,
) -> None:
    csrf = authenticate(client)
    workspace_id = UUID(
        client.get("/api/v1/me").json()["memberships"][0]["workspace_id"]
    )
    download_id = uuid4()
    artifact_id = uuid4()
    now = datetime.now(UTC)
    engine = create_engine(PG_SYNC_URL)
    with Session(engine) as session:
        session.add(
            Download(
                id=download_id,
                workspace_id=workspace_id,
                url="https://example.com/video",
                platform="youtube",
                status="completed",
                media={},
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            MediaArtifact(
                id=artifact_id,
                workspace_id=workspace_id,
                download_id=download_id,
                artifact_kind="video",
                file_name="clip.mp4",
                relative_path="downloads/clip.mp4",
                status="ready",
                source_kind="imported",
                source_provider="test_fixture",
                metadata_json={},
            )
        )
        session.commit()
    engine.dispose()

    listing = client.get("/api/v1/storage/rights?page=1&page_size=20")
    assert listing.status_code == 200, listing.text
    item = next(row for row in listing.json()["items"] if row["artifact_id"] == str(artifact_id))
    assert item["id"] is None
    assert item["rights_status"] == "unknown"
    assert item["source_kind"] == "imported"

    update = client.patch(
        f"/api/v1/storage/artifacts/{artifact_id}/rights",
        headers={"X-CSRF-Token": csrf},
        json={
            "rights_status": "approved",
            "license_type": "授权采购",
            "rights_holder": "测试权利人",
            "territories": ["CN", "CN"],
            "evidence_url": "https://rights.example.test/license/1",
            "source_kind": "imported",
        },
    )
    assert update.status_code == 200, update.text
    body = update.json()
    assert body["rights_status"] == "approved"
    assert body["territories"] == ["CN"]
    assert body["verified_by"] is not None

    invalid = client.patch(
        f"/api/v1/storage/artifacts/{artifact_id}/rights",
        headers={"X-CSRF-Token": csrf},
        json={"rights_status": "approved", "source_kind": "imported"},
    )
    assert invalid.status_code == 422
