from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User

from .conftest import PG_SYNC_URL, TEST_PASSWORD


def _login(client: TestClient, email: str = "admin@example.com") -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrf_token"])


def test_workspace_invitation_is_hashed_one_time_and_accepts_matching_user(
    client: TestClient,
) -> None:
    owner_csrf = _login(client)
    created = client.post(
        "/api/v1/workspace-invitations",
        headers={"X-CSRF-Token": owner_csrf},
        json={"email": "editor@example.com", "role": "editor", "expires_in_hours": 24},
    )
    assert created.status_code == 201, created.text
    invitation = created.json()
    assert invitation["token"]
    assert invitation["status"] == "pending"

    engine = create_engine(PG_SYNC_URL)
    with Session(engine) as session:
        session.add(
            User(
                id=uuid4(),
                email_normalized="editor@example.com",
                email_display="editor@example.com",
                password_hash=hash_password(TEST_PASSWORD),
                display_name="编辑",
                status="active",
                locale="zh-CN",
                timezone="Asia/Shanghai",
                last_login_at=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()
    engine.dispose()

    editor_csrf = _login(client, "editor@example.com")
    accepted = client.post(
        "/api/v1/workspace-invitations/accept",
        headers={"X-CSRF-Token": editor_csrf},
        json={"token": invitation["token"]},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["email"] == "editor@example.com"
    assert accepted.json()["role"] == "editor"

    repeated = client.post(
        "/api/v1/workspace-invitations/accept",
        headers={"X-CSRF-Token": editor_csrf},
        json={"token": invitation["token"]},
    )
    assert repeated.status_code == 409
    assert repeated.json()["code"] == "invitation_not_pending"
