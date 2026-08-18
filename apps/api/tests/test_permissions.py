from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

from .conftest import PG_SYNC_URL, TEST_PLATFORM_ID

VIEWER_PASSWORD = "viewer-correct-horse-battery-staple"  # noqa: S105 - test fixture


def test_viewer_cannot_mutate_and_cross_workspace_access_is_denied(
    client: TestClient, database_path: Path
) -> None:
    engine = create_engine(PG_SYNC_URL)
    with Session(engine) as session:
        workspace = session.scalar(select(Workspace))
        assert workspace is not None
        viewer = User(
            id=uuid4(),
            email_normalized="viewer@example.com",
            email_display="viewer@example.com",
            password_hash=hash_password(VIEWER_PASSWORD),
            display_name="只读用户",
            status="active",
            locale="zh-CN",
            timezone="Asia/Shanghai",
        )
        membership = WorkspaceMembership(
            id=uuid4(),
            workspace_id=workspace.id,
            user_id=viewer.id,
            role="viewer",
            status="active",
            invited_by=None,
            joined_at=datetime.now(UTC),
        )
        foreign_workspace = Workspace(
            id=uuid4(),
            name="其他工作区",
            slug="other-workspace",
            status="active",
            default_timezone="UTC",
            row_version=1,
        )
        session.add_all([viewer, membership, foreign_workspace])
        session.commit()
        foreign_workspace_id = foreign_workspace.id
    engine.dispose()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@example.com", "password": VIEWER_PASSWORD},
    )
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    assert client.get("/api/v1/accounts").status_code == 200
    denied = client.post(
        "/api/v1/accounts",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform_id": str(TEST_PLATFORM_ID),
            "external_id": "viewer-must-not-create",
            "display_name": "禁止创建",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"

    cross_workspace = client.get(
        "/api/v1/accounts",
        headers={"X-Workspace-Id": str(foreign_workspace_id)},
    )
    assert cross_workspace.status_code == 403
    assert cross_workspace.json()["code"] == "workspace_access_denied"
