from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.monitoring import Account
from app.models.user import User
from app.models.workspace import WorkspaceMembership

from .conftest import PG_SYNC_URL, TEST_PASSWORD, TEST_PLATFORM_ID


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


def test_account_grant_limits_non_admin_reads_and_is_audited(client: TestClient) -> None:
    _login(client)
    engine = create_engine(PG_SYNC_URL)
    now = datetime.now(UTC)
    with Session(engine) as session:
        owner = session.scalar(select(User).where(User.email_normalized == "admin@example.com"))
        assert owner is not None
        membership = session.scalar(
            select(WorkspaceMembership).where(WorkspaceMembership.user_id == owner.id)
        )
        assert membership is not None
        editor = User(
            id=uuid4(),
            email_normalized="editor@example.com",
            email_display="editor@example.com",
            password_hash=hash_password(TEST_PASSWORD),
            display_name="编辑",
            status="active",
            locale="zh-CN",
            timezone="Asia/Shanghai",
            last_login_at=None,
            created_at=now,
            updated_at=now,
        )
        editor_membership = WorkspaceMembership(
            id=uuid4(),
            workspace_id=membership.workspace_id,
            user_id=editor.id,
            role="editor",
            status="active",
            invited_by=owner.id,
            joined_at=now,
        )
        accounts = [
            Account(
                id=uuid4(),
                workspace_id=membership.workspace_id,
                platform_id=TEST_PLATFORM_ID,
                external_id=f"account-{index}",
                display_name=f"账号 {index}",
                fetched_at=now,
            )
            for index in range(2)
        ]
        session.add_all([editor, editor_membership, *accounts])
        session.commit()
        editor_id = editor.id
        workspace_id = membership.workspace_id
        allowed_account_id = accounts[0].id
        denied_account_id = accounts[1].id
    engine.dispose()

    editor_csrf = _login(client, "editor@example.com")
    visible_before = client.get(
        "/api/v1/accounts", headers={"X-Workspace-Id": str(workspace_id)}
    )
    assert visible_before.status_code == 200, visible_before.text
    assert visible_before.json()["total"] == 2

    owner_csrf = _login(client)
    grant = client.post(
        "/api/v1/workspace-account-grants",
        headers={"X-CSRF-Token": owner_csrf, "X-Workspace-Id": str(workspace_id)},
        json={
            "account_id": str(allowed_account_id),
            "user_id": str(editor_id),
            "permission": "viewer",
        },
    )
    assert grant.status_code == 201, grant.text

    owner_csrf = _login(client)
    publication_ids: dict[str, str] = {}
    for label, account_id in (
        ("allowed", allowed_account_id),
        ("denied", denied_account_id),
    ):
        publication = client.post(
            "/api/v1/publications",
            headers={"X-CSRF-Token": owner_csrf, "X-Workspace-Id": str(workspace_id)},
            json={
                "title": f"授权测试发布-{label}",
                "account_id": str(account_id),
                "status": "planned",
                "source_kind": "imported",
                "source_provider": "test",
            },
        )
        assert publication.status_code == 201, publication.text
        publication_ids[label] = publication.json()["id"]

    editor_csrf = _login(client, "editor@example.com")
    visible_after = client.get(
        "/api/v1/accounts", headers={"X-Workspace-Id": str(workspace_id)}
    )
    assert visible_after.status_code == 200, visible_after.text
    assert visible_after.json()["total"] == 1
    denied = client.get(
        f"/api/v1/accounts/{denied_account_id}",
        headers={"X-Workspace-Id": str(workspace_id)},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "account_access_denied"
    write_denied = client.patch(
        f"/api/v1/accounts/{allowed_account_id}",
        headers={
            "X-CSRF-Token": editor_csrf,
            "X-Workspace-Id": str(workspace_id),
        },
        json={"display_name": "不应被写入"},
    )
    assert write_denied.status_code == 403
    assert write_denied.json()["code"] == "account_write_denied"
    publications = client.get(
        "/api/v1/publications",
        headers={"X-Workspace-Id": str(workspace_id)},
    )
    assert publications.status_code == 200, publications.text
    publication_titles = {item["title"] for item in publications.json()["items"]}
    assert "授权测试发布-allowed" in publication_titles
    assert "授权测试发布-denied" not in publication_titles
    denied_publication = client.get(
        f"/api/v1/publications/{publication_ids['denied']}",
        headers={"X-Workspace-Id": str(workspace_id)},
    )
    assert denied_publication.status_code == 403
    assert denied_publication.json()["code"] == "account_access_denied"
