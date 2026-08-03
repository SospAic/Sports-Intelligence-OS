import json
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
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
from app.providers.llm.base import (
    LLMHealth,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMUsage,
)

TEST_PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - test fixture only
TEST_PLATFORM_ID = uuid4()

# ---------------------------------------------------------------------------
# PostgreSQL is the only supported database (Sports Intelligence OS "official"
# data chain). Tests run against a dedicated test database so the development
# database is never touched. Each test is isolated by truncating every table
# before it runs (see the ``isolate_db`` autouse fixture).
# ---------------------------------------------------------------------------
POSTGRES_TEST_DB = "sports_intelligence_test"
_PG_USER = "sio"
_PG_PASSWORD = "sio-local-development-only"  # noqa: S105 local-dev-only test DB password
_PG_HOST = "127.0.0.1"
_PG_PORT = 5432

PG_ASYNC_URL = (
    f"postgresql+asyncpg://{_PG_USER}:{_PG_PASSWORD}@{_PG_HOST}:{_PG_PORT}/{POSTGRES_TEST_DB}"
)
PG_SYNC_URL = (
    f"postgresql+psycopg://{_PG_USER}:{_PG_PASSWORD}@{_PG_HOST}:{_PG_PORT}/{POSTGRES_TEST_DB}"
)

_TRUNCATE_ALL = (
    "DO $$ DECLARE r RECORD; BEGIN "
    "FOR r IN SELECT tablename FROM pg_tables "
    "WHERE schemaname = 'public' AND tablename <> 'alembic_version' "
    "LOOP EXECUTE format('TRUNCATE TABLE public.%I RESTART IDENTITY CASCADE', r.tablename); "
    "END LOOP; END $$;"
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db() -> Iterator[None]:
    """Create (or recreate) the dedicated test database and schema per session.

    The database is dropped and rebuilt each session so schema changes in the
    models (new columns / tables) are always reflected. A persistent test
    database would keep its stale schema because ``Base.metadata.create_all``
    only ever *adds* missing tables — it never alters tables that already
    exist, which is exactly how a just-added column (e.g. ``content_items.media``)
    gets silently missed and breaks every test touching that table.
    """
    admin_engine = create_engine(
        f"postgresql+psycopg://{_PG_USER}:{_PG_PASSWORD}@{_PG_HOST}:{_PG_PORT}/postgres",
        isolation_level="AUTOCOMMIT",
    )
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": POSTGRES_TEST_DB},
        ).scalar()
        if exists:
            # Force-disconnect any lingering sessions, then drop so a stale
            # schema can never block a fresh build from the current models.
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": POSTGRES_TEST_DB},
            )
            conn.execute(text(f'DROP DATABASE "{POSTGRES_TEST_DB}"'))
        conn.execute(text(f'CREATE DATABASE "{POSTGRES_TEST_DB}"'))
    admin_engine.dispose()

    engine = create_engine(PG_SYNC_URL)
    Base.metadata.create_all(engine)
    engine.dispose()
    yield


@pytest.fixture(autouse=True)
def isolate_db() -> Iterator[None]:
    """Truncate every table before each test so tests never leak state."""
    engine = create_engine(PG_SYNC_URL)
    with engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")
        conn.execute(text(_TRUNCATE_ALL))
    engine.dispose()
    yield


@pytest.fixture
def database_path() -> str:
    """Name of the dedicated PostgreSQL test database (shared across tests).

    Tests build their engine URLs from this name; per-test isolation is handled
    by the ``isolate_db`` autouse fixture, mirroring the previous per-file
    SQLite database behaviour.
    """
    return POSTGRES_TEST_DB


def _seed_database(database_path: str) -> None:
    """Create tables and seed test data using a synchronous engine."""
    sync_engine = create_engine(
        f"postgresql+psycopg://{_PG_USER}:{_PG_PASSWORD}@{_PG_HOST}:{_PG_PORT}/{database_path}"
    )
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


def _build_test_app(database_path: str) -> FastAPI:
    """Build a configured FastAPI app pointing at the test database."""
    settings = Settings(
        environment="test",
        database_url=(
            f"postgresql+asyncpg://{_PG_USER}:{_PG_PASSWORD}@{_PG_HOST}:{_PG_PORT}/{database_path}"
        ),
        redis_url="redis://127.0.0.1:6399/15",
        secret_key="test-only-secret-not-used-in-production",
        session_cookie_secure=False,
        auth_login_max_attempts_per_identity=3,
        cors_origins=["http://testserver"],
    )
    return create_app(settings)


@pytest.fixture
def client(database_path: str) -> Iterator[TestClient]:
    """Synchronous test client (Starlette TestClient backed by httpx)."""
    _seed_database(database_path)
    app = _build_test_app(database_path)
    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client


@pytest.fixture
async def async_client(database_path: str) -> AsyncIterator[httpx.AsyncClient]:
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
        view_offset: int = 0,
    ) -> None:
        self._key = key
        self._analytics_all_none = analytics_all_none
        self._content_count = content_count
        self._view_offset = view_offset
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
                    "view_count": 1000 * (idx + 1) + self._view_offset,
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


class StubLLMProvider(LLMProvider):
    """Test-only LLM provider implementing the REAL provider contract.

    It is never registered in production. It returns deterministic,
    real-shaped responses (``source_kind='live'``) so the generation
    workflow can be exercised offline and end-to-end without a ``mock``
    source kind and without any external API credential. It is a contract /
    transport stand-in, not a data source: it does not claim live research
    or independent fact verification (the generated run keeps
    ``verification_incomplete``), it only guarantees provenance honesty.
    """

    key = "stub_llm"
    name = "Stub LLM (test fixture)"
    is_mock = False
    supports_streaming = True

    def __init__(self, *, key: str = "stub_llm") -> None:
        self.key = key

    @property
    def configured(self) -> bool:
        return True

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        return None

    async def generate(self, request: LLMRequest) -> LLMResponse:
        minimum = int(request.parameters.get("target_min_chars", 1180))
        maximum = int(request.parameters.get("target_max_chars", 1220))
        target = max(minimum, min(maximum, (minimum + maximum) // 2))
        title = str(request.metadata.get("title") or "the supplied sports event").strip()
        base = (
            "STUB LLM OUTPUT — This deterministic narration validates the Sports Intelligence "
            f"OS workflow for {title}. It does not claim live research or independent fact "
            "verification. The sequence remains tied to the supplied input, keeps each sentence "
            "focused on one job, and records every step for review. "
        )
        filler = (
            "The test follows the event timeline, separates supplied claims from verified facts, "
            "and preserves a clear cause-and-result structure without inventing competition data. "
        )
        narration = base
        while len(narration) < target:
            narration += filler
        narration = narration[:target].rstrip()
        if len(narration) < minimum:
            narration += " " * (minimum - len(narration))
        final_bundle: dict[str, Any] = {
            "event_fact_summary": "STUB LLM OUTPUT：仅复述已冻结输入，不代表联网核实。",
            "fact_sources": request.metadata.get("sources", []),
            "story_value": {
                "qualified": True,
                "reason": "Stub provider workflow contract test only",
            },
            "tts_en": narration.replace("\n", " "),
            "translation_zh": "桩测试输出：该内容只用于验证工作流，不代表真实联网生成结果。",
            "video_title_en": "🏟️ STUB LLM — Sports Workflow Verification",
            "video_title_zh": "🏟️ 桩流程验证",
            "search_keywords": ["STUB SPORTS WORKFLOW", "TEST EVENT TIMELINE"],
            "material_keywords": ["stub sports footage", "workflow test timeline"],
            "tags": ["STUB", "TEST_ONLY", "SPORTS_WORKFLOW"],
            "project_filename": "桩流程验证",
            "qa_report": {"provider": self.key, "stub": True},
            "used_rules": request.metadata.get("used_rules", []),
            "rewrite_reasons": request.metadata.get("rewrite_reasons", []),
            "spoken_char_count": len(narration.replace("\n", " ")),
            "event_identity": {
                "sport": "STUB",
                "league": None,
                "athletes": ["STUB_ATHLETE"],
                "teams": [],
                "date": None,
                "location": None,
                "note": "Stub provider — event identity not derived from real facts",
            },
            "story_format": "consequence-first-decision",
            "story_format_reason": "Stub provider: default format selected for contract test.",
            "central_question": "STUB: What caused the outcome in the supplied event?",
            "selected_hook": {
                "type": "scene-first-anomaly",
                "score": 75,
                "text": "STUB TEST HOOK — opens on the anomalous moment.",
                "reason": "Stub provider: default hook selected for contract test.",
            },
            "cmssml": narration.replace("\n", " "),
            "ev3": narration.replace("\n", " "),
            "story_architecture": {
                "primary_format": "consequence-first-decision",
                "depth_axis": "micro-action-and-body-mechanics",
                "narrative_trajectory": "participant-action-trajectory",
                "lcr_enabled": False,
                "lcr_reason": "Stub provider: LCR conditions not evaluated.",
                "functional_turns": [],
                "note": "Stub provider — architecture not derived from real facts",
            },
            "lcr_enabled": False,
            "lcr_reason": None,
            "hook_candidates": [],
            "answer_word_map": None,
            "reaction_relay": None,
            "evidence_rewards": None,
            "exclusion_ladder": None,
            "dialogue_notes": None,
            "audio_performance_map": None,
            "tts_settings": None,
            "video_material_plan": None,
            "edit_map": None,
            "caption_map": None,
            "original_audio_plan": None,
            "srt_output": None,
            "source_kind": "live",
        }
        step_key = str(request.metadata.get("step_key", "generate_draft"))
        content: str | Mapping[str, Any] = (
            final_bundle if step_key == "final_formatting" else narration
        )
        input_tokens = max(1, sum(len(item.content) for item in request.messages) // 4)
        output_size = len(json.dumps(content, ensure_ascii=False))
        usage = LLMUsage(
            input_tokens=input_tokens,
            output_tokens=max(1, output_size // 4),
            total_tokens=input_tokens + max(1, output_size // 4),
            source="estimated",
        )
        return LLMResponse(
            content=content,
            provider_request_id=f"stub-{request.idempotency_key}",
            model=request.model,
            finish_reason="stop",
            usage=usage,
            provider_metadata={"source_kind": "live", "test_output": True},
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        response = await self.generate(request)
        text = (
            response.content
            if isinstance(response.content, str)
            else json.dumps(response.content, ensure_ascii=False)
        )
        for start in range(0, len(text), 80):
            yield text[start : start + 80]

    async def estimate_cost(self, usage: LLMUsage, config: Mapping[str, Any]) -> Decimal | None:
        return Decimal("0")

    async def health_check(self) -> LLMHealth:
        return LLMHealth(status="ok", detail="Stub provider is available for test output only")
