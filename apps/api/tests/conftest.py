from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterCapability,
    AdapterDescriptor,
    AdapterHealth,
    AdapterPage,
    PlatformAccountData,
    PlatformAdapter,
    PlatformContentData,
    PlatformMetricsData,
)
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
            adapter_key="youtube_browser",
            capabilities={
                "PUBLIC_PROFILE": True,
                "ACCOUNT_ANALYTICS": True,
                "CONTENT_LIST": True,
                "CONTENT_ANALYTICS": True,
                "TRAFFIC_SOURCES": False,
                "RETENTION": False,
                "REVENUE": False,
                "COMMENTS": False,
                "SEARCH_TERMS": False,
            },
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


class RealShapedTestAdapter(PlatformAdapter):
    """Test-only adapter implementing the REAL adapter contract (source_kind='live').

    It is never registered in production and exists only to exercise the sync
    engine's status-decision and audit logic deterministically and offline,
    without a ``mock`` source kind. Treat it as a transport/contract stand-in,
    not a data source: it emits real-shaped, deterministic ``source_kind='live'``
    data so the system under test is honest about provenance (no falsified
    success, no synthetic data labelled as live platform data).
    """

    def __init__(
        self,
        *,
        key: str = "test_sync_adapter",
        analytics_all_none: bool = False,
        content_count: int = 0,
    ) -> None:
        self._key = key
        self._analytics_all_none = analytics_all_none
        self._content_count = content_count
        self.descriptor = AdapterDescriptor(
            key=key,
            name="Test Sync Adapter",
            implementation_status="implemented",
            capabilities={
                AdapterCapability.PUBLIC_PROFILE: True,
                AdapterCapability.ACCOUNT_ANALYTICS: True,
                AdapterCapability.CONTENT_LIST: True,
                AdapterCapability.CONTENT_ANALYTICS: True,
            },
            config_fields=(),
            source_kinds=frozenset({"live"}),
        )

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        return None

    async def resolve_account(
        self, ctx: AdapterCallContext, locator: str
    ) -> PlatformAccountData:
        return PlatformAccountData(
            external_id=locator,
            username="test_handle",
            display_name="测试账号",
            profile_url=f"https://example.com/@{locator}",
            avatar_url=None,
            description=None,
            country=None,
            language="zh-CN",
            is_verified=False,
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.observed_at,
            metadata={},
        )

    async def fetch_account(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformAccountData:
        return await self.resolve_account(ctx, external_id)

    async def list_contents(
        self,
        ctx: AdapterCallContext,
        external_account_id: str,
        *,
        published_after: datetime | None,
        cursor: str | None,
        page_size: int,
    ) -> AdapterPage:
        items = tuple(
            PlatformContentData(
                external_id=f"c{i}",
                account_external_id=external_account_id,
                content_type="video",
                title=f"测试作品 {i}",
                description="",
                published_at=datetime(2026, 7, 24, 10, 0, tzinfo=UTC),
                duration_seconds=30.0,
                canonical_url=f"https://example.com/c{i}",
                cover_url=None,
                language="zh-CN",
                status="published",
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                metadata={},
            )
            for i in range(self._content_count)
        )
        return AdapterPage(items=items, next_cursor=None)

    async def fetch_content(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformContentData:
        raise NotImplementedError("test adapter does not fetch a single content")

    async def fetch_account_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformMetricsData:
        if self._analytics_all_none:
            metrics: dict[str, int | float | None] = {
                "follower_count": None,
                "following_count": None,
                "total_like_count": None,
                "total_view_count": None,
                "video_count": None,
                "engagement_rate": None,
            }
        else:
            metrics = {
                "follower_count": 12500,
                "following_count": 200,
                "total_like_count": 50000,
                "total_view_count": 1_000_000,
                "video_count": 30,
                "engagement_rate": 0.05,
            }
        return PlatformMetricsData(
            external_id=external_id,
            captured_at=ctx.observed_at,
            metrics=metrics,
            source_kind="live",
            provider=self.key,
            fetched_at=ctx.observed_at,
            metadata={},
        )

    async def fetch_content_analytics(
        self, ctx: AdapterCallContext, external_ids: Sequence[str]
    ) -> tuple[PlatformMetricsData, ...]:
        return tuple(
            PlatformMetricsData(
                external_id=ext_id,
                captured_at=ctx.observed_at,
                metrics={
                    "view_count": 1000 * (idx + 1),
                    "like_count": 100 * (idx + 1),
                    "comment_count": 10 * (idx + 1),
                    "share_count": 5 * (idx + 1),
                    "favorite_count": None,
                    "follower_gain": None,
                    "average_watch_time": None,
                    "completion_rate": None,
                    "search_traffic_rate": None,
                    "recommendation_traffic_rate": None,
                    "profile_traffic_rate": None,
                    "revenue": None,
                    "rpm": None,
                },
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                metadata={},
            )
            for idx, ext_id in enumerate(external_ids)
        )

    async def health_check(self, ctx: AdapterCallContext) -> AdapterHealth:
        return AdapterHealth(status="ok", checked_at=ctx.observed_at, detail="test adapter")
