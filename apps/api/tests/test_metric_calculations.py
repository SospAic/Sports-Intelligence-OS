import os
from datetime import UTC, datetime
from decimal import Decimal
from tempfile import mkstemp
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.models.monitoring import (
    Account,
    AccountSnapshot,
    ContentItem,
    ContentSnapshot,
    DerivedMetric,
    Platform,
)
from app.models.workspace import Workspace
from app.services.metric_calculations import (
    percentile_rank,
    ratio_score,
    safe_rate,
    sample_confidence,
    weighted_available_score,
)
from app.services.search import SearchService
from app.services.sync import PlatformSyncExecutor
from app.services.trend_collector import _confidence_adjusted, _optional_int


def test_missing_values_are_not_converted_to_zero() -> None:
    assert safe_rate(None, 100) is None
    assert safe_rate(10, None) is None
    assert safe_rate(10, 0) is None
    assert _optional_int(None) is None
    assert _optional_int(False) is None
    assert _optional_int(0) == 0


def test_percentiles_are_tie_aware_and_singletons_are_neutral() -> None:
    assert percentile_rank(10, [10]) == 50
    assert percentile_rank(10, [10, 10, 20]) == 25
    assert percentile_rank(20, [10, 10, 20]) == 100


def test_weighted_score_requires_evidence_and_renormalizes() -> None:
    missing, weights = weighted_available_score(
        {"views": (80, 0.6), "engagement": (None, 0.4)}, minimum_components=2
    )
    assert missing is None
    assert weights == {}

    score, weights = weighted_available_score(
        {"views": (80, 0.6), "engagement": (40, 0.4)}, minimum_components=2
    )
    assert score == 64
    assert weights == {"views": 0.6, "engagement": 0.4}


def test_confidence_shrinks_uncertain_extremes_towards_neutral() -> None:
    assert sample_confidence(0) == 0
    assert _confidence_adjusted(100, 0) == 50
    assert _confidence_adjusted(100, 0.5) == 75
    assert ratio_score(1) == 50
    assert ratio_score(2) == 75


def test_chinese_search_uses_literal_fallback_on_postgres() -> None:
    service = object.__new__(SearchService)
    service._pg = True
    assert service._uses_tsvector("world cup")
    assert not service._uses_tsvector("世界杯")
    assert service._backend_for("世界杯") == "ilike"


async def test_play_follower_ratio_is_computed() -> None:
    """play_follower_ratio = view_count / latest known account follower_count."""
    fd, path = mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        workspace_id = uuid4()
        platform_id = uuid4()
        account_id = uuid4()
        content_id = uuid4()
        now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

        async with maker() as session:
            session.add(
                Workspace(
                    id=workspace_id,
                    name="ws",
                    slug="ws",
                    status="active",
                    default_timezone="UTC",
                    row_version=1,
                )
            )
            session.add(
                Platform(
                    id=platform_id,
                    key="tp",
                    name="TP",
                    category="video",
                    enabled=True,
                    adapter_key="test_platform",
                    capabilities={},
                )
            )
            session.add(
                Account(
                    id=account_id,
                    workspace_id=workspace_id,
                    platform_id=platform_id,
                    external_id="ext1",
                    username="u",
                    display_name="d",
                    is_verified=False,
                    is_active=True,
                    metadata_json={},
                    last_synced_at=now,
                    sync_status="success",
                    source_kind="live",
                    source_provider="test_platform",
                    fetched_at=now,
                )
            )
            session.add(
                AccountSnapshot(
                    id=uuid4(),
                    account_id=account_id,
                    captured_at=now,
                    follower_count=12500,
                    following_count=0,
                    total_like_count=0,
                    total_view_count=0,
                    video_count=0,
                    engagement_rate=None,
                    metadata_json={},
                    source_kind="live",
                    source_provider="test_platform",
                    fetched_at=now,
                    raw_payload_ref=None,
                    created_at=now,
                )
            )
            session.add(
                ContentItem(
                    id=content_id,
                    workspace_id=workspace_id,
                    platform_id=platform_id,
                    account_id=account_id,
                    external_id="c1",
                    content_type="video",
                    title="t",
                    description="",
                    published_at=datetime(2026, 7, 24, 10, 0, tzinfo=UTC),
                    duration_seconds=Decimal("10"),
                    canonical_url="https://e.invalid/c1",
                    language="zh-CN",
                    status="published",
                    metadata_json={},
                    first_seen_at=now,
                    last_seen_at=now,
                    source_kind="live",
                    source_provider="test_platform",
                    fetched_at=now,
                    source_url=None,
                    raw_payload_ref=None,
                )
            )
            session.add(
                ContentSnapshot(
                    id=uuid4(),
                    content_item_id=content_id,
                    captured_at=now,
                    view_count=1_250_000,
                    like_count=1000,
                    comment_count=100,
                    share_count=50,
                    favorite_count=20,
                    follower_gain=0,
                    average_watch_time=None,
                    completion_rate=None,
                    search_traffic_rate=None,
                    recommendation_traffic_rate=None,
                    profile_traffic_rate=None,
                    revenue=None,
                    rpm=None,
                    metadata_json={},
                    source_kind="live",
                    source_provider="test_platform",
                    fetched_at=now,
                    raw_payload_ref=None,
                    created_at=now,
                )
            )
            await session.commit()

            settings = Settings(
                environment="test",
                database_url=f"sqlite+aiosqlite:///{path}",
                redis_url="redis://127.0.0.1:6399/15",
                secret_key="test-secret",
                session_cookie_secure=False,
                auth_login_max_attempts_per_identity=3,
                cors_origins=["http://testserver"],
            )
            service = PlatformSyncExecutor(session, None, settings)
            account = await session.get(Account, account_id)
            await service._calculate_metrics(account, now)
            await session.commit()

            metric = await session.scalar(
                select(DerivedMetric).where(
                    DerivedMetric.entity_id == content_id,
                    DerivedMetric.metric_key == "play_follower_ratio",
                )
            )
            assert metric is not None
            assert float(metric.value) == 100.0  # 1_250_000 / 12_500
    finally:
        await engine.dispose()
        os.remove(path)
