from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
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


def _seed_database(database_path: Path) -> None:
    """Create tables and seed test data using a synchronous engine."""
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
    sync_engine.dispose()


def _build_test_app(database_path: Path) -> FastAPI:
    """Build a configured FastAPI app pointing at the test database."""
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{database_path}",
        redis_url="redis://127.0.0.1:6399/15",
        secret_key="test-only-secret-not-used-in-production",
        session_cookie_secure=False,
        auth_login_max_attempts_per_identity=3,
        cors_origins=["http://testserver"],
    )
    return create_app(settings)


@pytest.fixture
def client(database_path: Path) -> Iterator[TestClient]:
    """Synchronous test client (Starlette TestClient backed by httpx)."""
    _seed_database(database_path)
    app = _build_test_app(database_path)
    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client


@pytest.fixture
async def async_client(database_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    """Async test client using httpx.AsyncClient with ASGITransport.

    This is the modern replacement for the deprecated ``app=`` shortcut on
    httpx.AsyncClient.  Use this fixture for ``async def test_*`` functions
    that need to exercise the ASGI app without a running server.
    """
    _seed_database(database_path)
    app = _build_test_app(database_path)
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac
