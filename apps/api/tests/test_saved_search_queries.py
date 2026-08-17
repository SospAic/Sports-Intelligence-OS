from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models.trends import SearchQuery

from .conftest import PG_SYNC_URL, TEST_PASSWORD


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def seed_search_query() -> str:
    with Session(create_engine(PG_SYNC_URL)) as session:
        workspace_id = session.execute(
            text("SELECT id FROM workspaces WHERE slug = 'test-workspace'")
        ).scalar_one()
        item = SearchQuery(
            id=uuid4(),
            workspace_id=workspace_id,
            query_text="决赛最后一分钟的反转",
            platform_scope="all",
            status="completed",
            result_count=4,
        )
        session.add(item)
        session.commit()
        return str(item.id)


def test_saved_search_is_workspace_scoped_and_named(client: TestClient) -> None:
    csrf = authenticate(client)
    query_id = seed_search_query()
    save = client.patch(
        f"/api/v1/trends/search/{query_id}/saved",
        headers={"X-CSRF-Token": csrf},
        json={"is_saved": True, "saved_name": "决赛反转素材"},
    )
    assert save.status_code == 200, save.text
    assert save.json()["is_saved"] is True
    assert save.json()["saved_name"] == "决赛反转素材"

    saved = client.get("/api/v1/trends/search?saved_only=true")
    assert saved.status_code == 200, saved.text
    assert [item["id"] for item in saved.json()["items"]] == [query_id]

    unsave = client.patch(
        f"/api/v1/trends/search/{query_id}/saved",
        headers={"X-CSRF-Token": csrf},
        json={"is_saved": False},
    )
    assert unsave.status_code == 200, unsave.text
    assert unsave.json()["is_saved"] is False
    assert unsave.json()["saved_name"] is None
