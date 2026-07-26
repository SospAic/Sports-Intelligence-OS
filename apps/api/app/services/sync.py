import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.platforms.base import (
    AdapterCallContext,
    PlatformAdapter,
    PlatformAdapterError,
    PlatformContentData,
    PlatformMetricsData,
)
from app.core.config import Settings
from app.models.monitoring import (
    Account,
    AccountSnapshot,
    ContentItem,
    ContentSnapshot,
    DerivedMetric,
)
from app.models.sync import SyncRun
from app.providers.registry import ProviderRegistry
from app.repositories.sync import SyncRepository
from app.schemas.monitoring import SyncRunPage, SyncRunRead

logger = logging.getLogger(__name__)


class SyncError(Exception):
    code = "sync_error"
    status_code = 400


class SyncNotFoundError(SyncError):
    code = "sync_resource_not_found"
    status_code = 404


class SyncValidationError(SyncError):
    code = "sync_validation_error"
    status_code = 422


class SyncDispatchError(SyncError):
    code = "sync_queue_unavailable"
    status_code = 503


class RetryableSyncError(Exception):
    pass


def _as_int(value: int | float | None) -> int | None:
    return int(value) if value is not None else None


def _as_decimal(value: int | float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SyncService:
    def __init__(
        self,
        session: AsyncSession,
        registry: ProviderRegistry[PlatformAdapter],
        settings: Settings,
    ) -> None:
        self.session = session
        self.repository = SyncRepository(session)
        self.registry = registry
        self.settings = settings

    @staticmethod
    def settings_now() -> datetime:
        return datetime.now(UTC)

    async def request_account_sync(
        self,
        workspace_id: UUID,
        account_id: UUID,
        request_id: str,
    ) -> tuple[SyncRunRead, bool]:
        account = await self.repository.get_account(workspace_id, account_id)
        if account is None:
            raise SyncNotFoundError("account was not found")
        if not account.is_active or account.sync_status == "disabled":
            raise SyncValidationError("disabled accounts cannot be synchronized")
        try:
            adapter = self.registry.get(account.platform.adapter_key)
        except LookupError as exc:
            raise SyncValidationError("platform adapter is not registered") from exc
        if adapter.descriptor.implementation_status != "implemented":
            raise SyncValidationError("platform adapter is a skeleton and cannot synchronize")

        lock_key = f"account:{account.id}"
        active = await self.repository.get_active_run(lock_key)
        if active is not None:
            return SyncRunRead.model_validate(active), False

        now = datetime.now(UTC)
        run = SyncRun(
            id=uuid4(),
            workspace_id=workspace_id,
            target_type="account",
            target_id=account.id,
            adapter_key=adapter.key,
            request_id=request_id,
            queued_at=now,
            started_at=None,
            finished_at=None,
            status="queued",
            records_created=0,
            records_updated=0,
            error_code=None,
            error_message=None,
            metadata_json={"trigger": "manual", "retry_count": 0},
            lock_key=lock_key,
        )
        account.sync_status = "queued"
        account.last_sync_error_code = None
        account.last_sync_error_message = None
        self.session.add(run)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            active = await self.repository.get_active_run(lock_key)
            if active is None:
                raise
            return SyncRunRead.model_validate(active), False
        return SyncRunRead.model_validate(run), True

    async def mark_dispatch_failure(self, run_id: UUID) -> None:
        run = await self.repository.get_run(run_id)
        if run is None:
            return
        account = await self.repository.get_account_unscoped(run.target_id)
        now = datetime.now(UTC)
        run.status = "error"
        run.finished_at = now
        run.error_code = "queue_dispatch_failed"
        run.error_message = "Background task broker is unavailable"
        run.lock_key = None
        if account is not None:
            account.sync_status = "error"
            account.last_sync_error_code = run.error_code
            account.last_sync_error_message = run.error_message
        await self.session.commit()

    async def list_account_runs(
        self,
        workspace_id: UUID,
        account_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> SyncRunPage:
        account = await self.repository.get_account(workspace_id, account_id)
        if account is None:
            raise SyncNotFoundError("account was not found")
        runs, total = await self.repository.list_runs(
            workspace_id, account_id, page=page, page_size=page_size
        )
        return SyncRunPage(
            items=[SyncRunRead.model_validate(item) for item in runs],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def recover_stale_runs(self, stale_before: datetime) -> int:
        runs = list(
            (
                await self.session.scalars(
                    select(SyncRun)
                    .where(
                        SyncRun.lock_key.is_not(None),
                        SyncRun.status.in_(("queued", "running")),
                    )
                    .limit(500)
                )
            ).all()
        )
        recovered = 0
        now = datetime.now(UTC)
        for run in runs:
            last_active = run.started_at or run.queued_at
            if _utc(last_active) >= _utc(stale_before):
                continue
            run.status = "error"
            run.finished_at = now
            run.error_code = "stale_task_recovered"
            run.error_message = "Task exceeded its execution lease and was released"
            run.lock_key = None
            account = await self.repository.get_account_unscoped(run.target_id)
            if account is not None:
                account.sync_status = "error"
                account.last_sync_error_code = run.error_code
                account.last_sync_error_message = run.error_message
                account.next_sync_at = now
            recovered += 1
        if recovered:
            await self.session.commit()
        return recovered


class PlatformSyncExecutor:
    def __init__(
        self,
        session: AsyncSession,
        registry: ProviderRegistry[PlatformAdapter],
        settings: Settings,
    ) -> None:
        self.session = session
        self.repository = SyncRepository(session)
        self.registry = registry
        self.settings = settings

    def _config_for(self, account: Account) -> dict[str, Any]:
        adapter_config = account.metadata_json.get("adapter_config", {})
        if not isinstance(adapter_config, dict):
            adapter_config = {}
        config = dict(adapter_config)
        if account.platform.adapter_key == "youtube":
            if self.settings.youtube_api_key is None:
                return config
            config["api_key"] = self.settings.youtube_api_key.get_secret_value()
        return config

    async def execute_account_run(self, run_id: UUID) -> None:
        run = await self.repository.get_run(run_id)
        if run is None:
            raise SyncNotFoundError("sync run was not found")
        if run.status == "success":
            return
        account = await self.repository.get_account(run.workspace_id, run.target_id)
        if account is None:
            await self._terminal_error(run, None, "account_not_found", "account was deleted")
            return
        adapter = self.registry.get(run.adapter_key)
        now = datetime.now(UTC)
        run.status = "running"
        run.started_at = run.started_at or now
        run.error_code = None
        run.error_message = None
        account.sync_status = "syncing"
        await self.session.commit()

        ctx = AdapterCallContext(
            config=self._config_for(account),
            observed_at=now,
            request_id=run.request_id,
        )
        try:
            await adapter.validate_config(ctx.config)
            created, updated = await self._sync_account(account, adapter, ctx)
            content_created, content_updated = await self._sync_contents(account, adapter, ctx)
            created += content_created
            updated += content_updated
            await self._calculate_metrics(account, ctx.observed_at)
        except PlatformAdapterError as exc:
            if exc.retryable:
                run.status = "queued"
                run.error_code = exc.code
                run.error_message = str(exc)[:2000]
                run.metadata_json = {
                    **run.metadata_json,
                    "retry_count": int(run.metadata_json.get("retry_count", 0)) + 1,
                }
                account.sync_status = "queued"
                account.last_sync_error_code = exc.code
                account.last_sync_error_message = str(exc)[:2000]
                await self.session.commit()
                raise RetryableSyncError(str(exc)) from exc
            await self._terminal_error(run, account, exc.code, str(exc))
            return
        except Exception:
            logger.exception(
                "platform_sync_unexpected_error",
                extra={"event": "platform.sync.failed", "sync_run_id": str(run.id)},
            )
            await self._terminal_error(
                run, account, "unexpected_sync_error", "Unexpected synchronization error"
            )
            raise

        finished = datetime.now(UTC)
        run.status = "success"
        run.finished_at = finished
        run.records_created = created
        run.records_updated = updated
        run.error_code = None
        run.error_message = None
        run.lock_key = None
        account.sync_status = "success"
        account.last_synced_at = finished
        account.next_sync_at = finished + timedelta(seconds=account.sync_interval_seconds)
        account.last_sync_error_code = None
        account.last_sync_error_message = None
        await self.session.commit()

    async def mark_retry_exhausted(self, run_id: UUID, message: str) -> None:
        run = await self.repository.get_run(run_id)
        if run is None:
            return
        account = await self.repository.get_account_unscoped(run.target_id)
        await self._terminal_error(run, account, "retry_exhausted", message)

    async def calculate_account_metrics(self, account_id: UUID) -> None:
        account = await self.repository.get_account_unscoped(account_id)
        if account is None:
            raise SyncNotFoundError("account was not found")
        await self._calculate_metrics(account, datetime.now(UTC))
        await self.session.commit()

    async def _terminal_error(
        self,
        run: SyncRun,
        account: Account | None,
        code: str,
        message: str,
    ) -> None:
        run.status = "error"
        run.finished_at = datetime.now(UTC)
        run.error_code = code
        run.error_message = message[:2000]
        run.lock_key = None
        if account is not None:
            account.sync_status = "error"
            account.last_sync_error_code = code
            account.last_sync_error_message = message[:2000]
            account.next_sync_at = datetime.now(UTC) + timedelta(
                seconds=account.sync_interval_seconds
            )
        await self.session.commit()

    async def _sync_account(
        self,
        account: Account,
        adapter: PlatformAdapter,
        ctx: AdapterCallContext,
    ) -> tuple[int, int]:
        data = await adapter.resolve_account(ctx, account.external_id)
        metrics = await adapter.fetch_account_analytics(ctx, data.external_id)
        original_locator = account.external_id
        account.external_id = data.external_id
        account.username = data.username
        account.display_name = data.display_name
        account.profile_url = data.profile_url
        account.avatar_url = data.avatar_url
        account.description = data.description
        account.country = data.country
        account.language = data.language
        account.is_verified = data.is_verified
        account.metadata_json = {
            **account.metadata_json,
            **dict(data.metadata),
            "original_locator": account.metadata_json.get("original_locator", original_locator),
        }
        account.source_kind = data.source_kind
        account.source_provider = data.provider
        account.fetched_at = data.fetched_at
        account.source_url = data.profile_url
        self.session.add(self._account_snapshot(account, metrics))
        await self.session.flush()
        return 1, 1

    def _account_snapshot(self, account: Account, data: PlatformMetricsData) -> AccountSnapshot:
        metrics = data.metrics
        return AccountSnapshot(
            id=uuid4(),
            account_id=account.id,
            captured_at=data.captured_at,
            follower_count=_as_int(metrics.get("follower_count")),
            following_count=_as_int(metrics.get("following_count")),
            total_like_count=_as_int(metrics.get("total_like_count")),
            total_view_count=_as_int(metrics.get("total_view_count")),
            video_count=_as_int(metrics.get("video_count")),
            engagement_rate=_as_decimal(metrics.get("engagement_rate")),
            metadata_json={
                **dict(data.metadata),
                "unavailable_metrics": list(data.unavailable_metrics),
            },
            source_kind=data.source_kind,
            source_provider=data.provider,
            fetched_at=data.fetched_at,
            raw_payload_ref=None,
            created_at=datetime.now(UTC),
        )

    async def _sync_contents(
        self,
        account: Account,
        adapter: PlatformAdapter,
        ctx: AdapterCallContext,
    ) -> tuple[int, int]:
        cursor: str | None = None
        created = 0
        updated = 0
        newest_seen = await self.session.scalar(
            select(ContentItem.published_at)
            .where(ContentItem.account_id == account.id)
            .order_by(ContentItem.published_at.desc())
            .limit(1)
        )
        for _ in range(self.settings.sync_page_limit):
            page = await adapter.list_contents(
                ctx,
                account.external_id,
                published_after=_utc(newest_seen) if newest_seen is not None else None,
                cursor=cursor,
                page_size=50,
            )
            page_items: list[ContentItem] = []
            for data in page.items:
                content, was_created = await self._upsert_content(account, data)
                page_items.append(content)
                created += int(was_created)
                updated += int(not was_created)
            await self.session.flush()
            analytics = await adapter.fetch_content_analytics(
                ctx, [item.external_id for item in page_items]
            )
            by_external_id = {item.external_id: item for item in page_items}
            for analytics_data in analytics:
                matched_content = by_external_id.get(analytics_data.external_id)
                if matched_content is not None and analytics_data.metrics:
                    self.session.add(self._content_snapshot(matched_content.id, analytics_data))
                    created += 1
            if not page.next_cursor:
                break
            cursor = page.next_cursor
        return created, updated

    async def _upsert_content(
        self, account: Account, data: PlatformContentData
    ) -> tuple[ContentItem, bool]:
        content = await self.session.scalar(
            select(ContentItem).where(
                ContentItem.workspace_id == account.workspace_id,
                ContentItem.platform_id == account.platform_id,
                ContentItem.external_id == data.external_id,
            )
        )
        created = content is None
        if content is None:
            content = ContentItem(
                id=uuid4(),
                workspace_id=account.workspace_id,
                platform_id=account.platform_id,
                account_id=account.id,
                external_id=data.external_id,
                content_type=data.content_type,
                title=data.title,
                description=data.description,
                published_at=data.published_at,
                duration_seconds=_as_decimal(data.duration_seconds),
                canonical_url=data.canonical_url,
                cover_url=data.cover_url,
                language=data.language,
                status=data.status,
                metadata_json=dict(data.metadata),
                first_seen_at=data.fetched_at,
                last_seen_at=data.fetched_at,
                source_kind=data.source_kind,
                source_provider=data.provider,
                fetched_at=data.fetched_at,
                source_url=data.canonical_url,
                raw_payload_ref=None,
            )
            self.session.add(content)
        else:
            content.title = data.title
            content.description = data.description
            content.published_at = data.published_at
            content.duration_seconds = _as_decimal(data.duration_seconds)
            content.canonical_url = data.canonical_url
            content.cover_url = data.cover_url
            content.language = data.language
            content.status = data.status
            content.metadata_json = {**content.metadata_json, **dict(data.metadata)}
            content.last_seen_at = data.fetched_at
            content.source_kind = data.source_kind
            content.source_provider = data.provider
            content.fetched_at = data.fetched_at
            content.source_url = data.canonical_url
        return content, created

    def _content_snapshot(self, content_id: UUID, data: PlatformMetricsData) -> ContentSnapshot:
        value = data.metrics
        return ContentSnapshot(
            id=uuid4(),
            content_item_id=content_id,
            captured_at=data.captured_at,
            view_count=_as_int(value.get("view_count")),
            like_count=_as_int(value.get("like_count")),
            comment_count=_as_int(value.get("comment_count")),
            share_count=_as_int(value.get("share_count")),
            favorite_count=_as_int(value.get("favorite_count")),
            follower_gain=_as_int(value.get("follower_gain")),
            average_watch_time=_as_decimal(value.get("average_watch_time")),
            completion_rate=_as_decimal(value.get("completion_rate")),
            search_traffic_rate=_as_decimal(value.get("search_traffic_rate")),
            recommendation_traffic_rate=_as_decimal(value.get("recommendation_traffic_rate")),
            profile_traffic_rate=_as_decimal(value.get("profile_traffic_rate")),
            revenue=_as_decimal(value.get("revenue")),
            rpm=_as_decimal(value.get("rpm")),
            metadata_json={
                **dict(data.metadata),
                "unavailable_metrics": list(data.unavailable_metrics),
            },
            source_kind=data.source_kind,
            source_provider=data.provider,
            fetched_at=data.fetched_at,
            raw_payload_ref=None,
            created_at=datetime.now(UTC),
        )

    async def _calculate_metrics(self, account: Account, calculated_at: datetime) -> None:
        await self.session.flush()
        account_snapshots = list(
            (
                await self.session.scalars(
                    select(AccountSnapshot)
                    .where(AccountSnapshot.account_id == account.id)
                    .order_by(AccountSnapshot.captured_at.desc())
                )
            ).all()
        )
        if account_snapshots:
            latest_account = account_snapshots[0]
            previous = self._account_snapshot_before(
                account_snapshots, _utc(latest_account.captured_at) - timedelta(hours=24)
            )
            if (
                latest_account.follower_count is not None
                and previous is not None
                and previous.follower_count is not None
            ):
                self._metric(
                    account,
                    account.id,
                    "account",
                    "follower_growth_24h",
                    "24h",
                    latest_account.follower_count - previous.follower_count,
                    calculated_at,
                )

        contents = await self.repository.contents_for_account(account.id)
        latest_views: list[int] = []
        baseline_cutoff = _utc(calculated_at) - timedelta(days=30)
        snapshots_by_content: dict[UUID, list[ContentSnapshot]] = {}
        for content in contents:
            snapshots = list(
                (
                    await self.session.scalars(
                        select(ContentSnapshot)
                        .where(ContentSnapshot.content_item_id == content.id)
                        .order_by(ContentSnapshot.captured_at.desc())
                    )
                ).all()
            )
            snapshots_by_content[content.id] = snapshots
            if (
                snapshots
                and snapshots[0].view_count is not None
                and content.published_at is not None
                and _utc(content.published_at) >= baseline_cutoff
            ):
                latest_views.append(snapshots[0].view_count)
        baseline = float(median(latest_views)) if latest_views else None
        for content in contents:
            snapshots = snapshots_by_content[content.id]
            if not snapshots:
                continue
            latest = snapshots[0]
            views = latest.view_count or 0
            likes = latest.like_count or 0
            comments = latest.comment_count or 0
            shares = latest.share_count or 0
            favorites = latest.favorite_count or 0
            engagement = (likes + comments + shares) / views if views else 0.0
            share_rate = shares / views if views else 0.0
            favorite_rate = favorites / views if views else 0.0
            growth: dict[int, float] = {}
            for hours in (1, 6, 24):
                prior = self._content_snapshot_before(
                    snapshots, _utc(latest.captured_at) - timedelta(hours=hours)
                )
                if prior is not None and prior.view_count is not None:
                    growth[hours] = float(views - prior.view_count)
                    self._metric(
                        account,
                        content.id,
                        "content_item",
                        f"view_growth_{hours}h",
                        f"{hours}h",
                        growth[hours],
                        calculated_at,
                    )
            velocity = growth.get(1)
            if velocity is None and 6 in growth:
                velocity = growth[6] / 6
            acceleration = growth[1] - growth[6] / 6 if 1 in growth and 6 in growth else None
            baseline_ratio = views / baseline if baseline else None
            viral_score = min(
                100.0,
                engagement / 0.1 * 25
                + share_rate / 0.02 * 25
                + min((baseline_ratio or 0) / 5, 1) * 25
                + min(max(velocity or 0, 0) / 100_000, 1) * 25,
            )
            values: dict[str, tuple[str, float]] = {
                "engagement_rate": ("current", engagement),
                "share_rate": ("current", share_rate),
                "favorite_rate": ("current", favorite_rate),
                "viral_score": ("current", viral_score),
            }
            if velocity is not None:
                values["view_velocity"] = ("1h", velocity)
            if acceleration is not None:
                values["view_acceleration"] = ("6h", acceleration)
            if baseline is not None:
                values["median_views_30d"] = ("30d", baseline)
            if baseline_ratio is not None:
                values["account_baseline_ratio"] = ("30d", baseline_ratio)
            for key, (window, value) in values.items():
                self._metric(
                    account,
                    content.id,
                    "content_item",
                    key,
                    window,
                    value,
                    calculated_at,
                    metadata={
                        "incomplete_components": [
                            component
                            for component, available in {
                                "view_velocity": velocity is not None,
                                "median_views_30d": baseline is not None,
                            }.items()
                            if not available
                        ]
                    }
                    if key == "viral_score"
                    else None,
                )

    @staticmethod
    def _account_snapshot_before(
        snapshots: list[AccountSnapshot], target: datetime
    ) -> AccountSnapshot | None:
        return next(
            (item for item in snapshots if _utc(item.captured_at) <= target),
            None,
        )

    @staticmethod
    def _content_snapshot_before(
        snapshots: list[ContentSnapshot], target: datetime
    ) -> ContentSnapshot | None:
        return next(
            (item for item in snapshots if _utc(item.captured_at) <= target),
            None,
        )

    def _metric(
        self,
        account: Account,
        entity_id: UUID,
        entity_type: str,
        key: str,
        window: str,
        value: int | float,
        calculated_at: datetime,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.session.add(
            DerivedMetric(
                id=uuid4(),
                workspace_id=account.workspace_id,
                entity_type=entity_type,
                entity_id=entity_id,
                metric_key=key,
                window=window,
                value=Decimal(str(value)),
                calculated_at=calculated_at,
                metadata_json={
                    "algorithm_version": "monitoring-derived-v2",
                    "source": "calculated_not_platform_metric",
                    **dict(metadata or {}),
                },
            )
        )


def enqueue_platform_sync(run_id: UUID) -> None:
    from app.tasks.monitoring import sync_account

    sync_account.delay(str(run_id))
