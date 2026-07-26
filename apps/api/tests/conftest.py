from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.main import create_app
from app.models.monitoring import Platform
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

TEST_PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - test fixture only
TEST_PLATFORM_ID = uuid4()


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def client(database_path: Path) -> Iterator[TestClient]:
    sync_engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(sync_engine)

    workspace_id = uuid4()
    user_id = uuid4()
    with Session(sync_engine) as session:
        workspace = Workspace(
            id=workspace_id,
            name="测试工作区",
            slug="test-workspace",
            status="active",
            default_timezone="Asia/Shanghai",
            row_version=1,
        )
        user = User(
            id=user_id,
            email_normalized="admin@example.com",
            email_display="admin@example.com",
            password_hash=hash_password(TEST_PASSWORD),
            display_name="测试管理员",
            status="active",
            locale="zh-CN",
            timezone="Asia/Shanghai",
        )
        membership = WorkspaceMembership(
            id=uuid4(),
            workspace_id=workspace_id,
            user_id=user_id,
            role="owner",
            status="active",
            invited_by=None,
            joined_at=datetime.now(UTC),
        )
        platform = Platform(
            id=TEST_PLATFORM_ID,
            key="test_platform",
            name="Test Platform",
            category="test",
            enabled=True,
            adapter_key="mock_platform",
            capabilities={"source_kind": "mock", "demo_only": True},
        )
        session.add_all([workspace, user, membership, platform])
        session.commit()

    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{database_path}",
        redis_url="redis://127.0.0.1:6399/15",
        secret_key="test-only-secret-not-used-in-production",
        session_cookie_secure=False,
        cors_origins=["http://testserver"],
    )
    app = create_app(settings)
    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client
    sync_engine.dispose()
