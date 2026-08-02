import csv
import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.monitoring import Account, AccountSnapshot, ContentItem
from app.models.operations import AuditEntry
from app.repositories.monitoring import (
    AccountFilters,
    AccountRow,
    ContentFilters,
    ContentRow,
    MonitoringRepository,
    Order,
)
from app.schemas.monitoring import (
    AccountComparisonResponse,
    AccountComparisonRow,
    AccountComparisonSnapshot,
    AccountComparisonSummary,
    AccountContentSummary,
    AccountCreate,
    AccountMetricsHistory,
    AccountMetricsHistoryPoint,
    AccountPage,
    AccountRead,
    AccountSnapshotPage,
    AccountSnapshotRead,
    AccountSyncStatus,
    AccountUpdate,
    ContentCreate,
    ContentCalendarBucket,
    ContentCalendarResponse,
    ContentPage,
    ContentRead,
    ContentSnapshotPage,
    ContentSnapshotRead,
    ContentUpdate,
    DerivedMetricPage,
    DerivedMetricRead,
    PlatformRead,
    SourceKind,
    SyncIntervalResponse,
)
from app.services.adaptive_sync import compute_adaptive_interval

RESERVED_METADATA_KEYS = {
    "source_kind",
    "source_provider",
    "provider",
    "fetched_at",
    "raw_payload_ref",
    "is_mock",
    "demo",
    "adapter_config",
}
MAX_METADATA_BYTES = 65_536
MAX_CSV_EXPORT_ROWS = 10_000


class MonitoringError(Exception):
    code = "monitoring_error"
    status_code = 400

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class MonitoringNotFoundError(MonitoringError):
    code = "monitoring_resource_not_found"
    status_code = 404


class MonitoringConflictError(MonitoringError):
    code = "monitoring_resource_conflict"
    status_code = 409


class MonitoringValidationError(MonitoringError):
    code = "monitoring_validation_error"
    status_code = 422


def validate_user_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    reserved = RESERVED_METADATA_KEYS.intersection(metadata)
    if reserved:
        raise MonitoringValidationError(
            "metadata cannot override provenance keys: " + ", ".join(sorted(reserved))
        )
    try:
        encoded = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise MonitoringValidationError("metadata must contain JSON-compatible values") from exc
    if len(encoded) > MAX_METADATA_BYTES:
        raise MonitoringValidationError("metadata exceeds the 64 KiB limit")
    return metadata


def account_read(row: AccountRow) -> AccountRead:
    account, snapshot, growth = row
    response = AccountRead.model_validate(account)
    return response.model_copy(
        update={
            "latest_snapshot": (
                AccountSnapshotRead.model_validate(snapshot) if snapshot is not None else None
            ),
            "follower_growth_24h": float(growth) if growth is not None else None,
        }
    )


def content_read(row: ContentRow) -> ContentRead:
    content, snapshot, growth = row
    response = ContentRead.model_validate(content)
    return response.model_copy(
        update={
            "latest_snapshot": (
                ContentSnapshotRead.model_validate(snapshot) if snapshot is not None else None
            ),
            "view_growth_24h": float(growth) if growth is not None else None,
        }
    )


def safe_csv_cell(value: Any) -> str:
    if value is None:
        return ""
    rendered = str(value)
    if rendered.startswith(("=", "+", "-", "@")):
        return "'" + rendered
    return rendered


class MonitoringService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = MonitoringRepository(session)

    async def list_platforms(self, enabled: bool | None = None) -> list[PlatformRead]:
        platforms = await self._repository.list_platforms(enabled=enabled)
        return [PlatformRead.model_validate(platform) for platform in platforms]

    async def create_account(
        self, workspace_id: UUID, actor_id: UUID, payload: AccountCreate
    ) -> AccountRead:
        platform = await self._repository.get_platform(payload.platform_id)
        if platform is None or not platform.enabled:
            raise MonitoringValidationError("platform does not exist or is disabled")
        duplicate = await self._repository.get_account_by_external_id(
            workspace_id, platform.id, payload.external_id
        )
        if duplicate is not None:
            raise MonitoringConflictError("this external account is already registered")

        now = datetime.now(UTC)
        metadata = validate_user_metadata(payload.metadata)
        account = Account(
            id=uuid4(),
            workspace_id=workspace_id,
            platform_id=platform.id,
            external_id=payload.external_id,
            username=payload.username,
            display_name=payload.display_name,
            profile_url=str(payload.profile_url) if payload.profile_url else None,
            avatar_url=str(payload.avatar_url) if payload.avatar_url else None,
            description=payload.description,
            country=payload.country,
            language=payload.language,
            is_verified=payload.is_verified,
            is_active=True,
            metadata_json={**metadata, "input_mode": "manual"},
            last_synced_at=None,
            sync_interval_seconds=payload.sync_interval_seconds,
            sync_status="never",
            source_kind="imported",
            source_provider="manual",
            fetched_at=now,
            source_url=str(payload.profile_url) if payload.profile_url else None,
            raw_payload_ref=None,
        )
        self._repository.add_account(account)
        self._session.add(
            AuditEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action="monitoring.account.created",
                resource_type="account",
                resource_id=account.id,
                before_hash=None,
                after_hash=None,
                change_summary_json={
                    "platform_id": str(platform.id),
                    "external_id": payload.external_id,
                    "source_kind": "imported",
                },
                reason="manual account registration",
                ip_hash=None,
                trace_id=uuid4(),
                created_at=now,
            )
        )
        await self._session.commit()
        row = await self._repository.get_account(workspace_id, account.id)
        if row is None:
            raise RuntimeError("created account could not be reloaded")
        return account_read(row)

    async def list_accounts(
        self,
        workspace_id: UUID,
        *,
        filters: AccountFilters,
        sort: str,
        order: Order,
        page: int,
        page_size: int,
    ) -> AccountPage:
        rows, total = await self._repository.list_accounts(
            workspace_id,
            filters=filters,
            sort=sort,
            order=order,
            page=page,
            page_size=page_size,
        )
        return AccountPage(
            items=[account_read(row) for row in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_account(self, workspace_id: UUID, account_id: UUID) -> AccountRead:
        row = await self._repository.get_account(workspace_id, account_id)
        if row is None:
            raise MonitoringNotFoundError("account was not found")
        return account_read(row)

    async def update_account(
        self,
        workspace_id: UUID,
        account_id: UUID,
        actor_id: UUID,
        payload: AccountUpdate,
    ) -> AccountRead:
        row = await self._repository.get_account(workspace_id, account_id)
        if row is None:
            raise MonitoringNotFoundError("account was not found")
        account = row[0]
        changes = payload.model_dump(exclude_unset=True)
        if changes.get("sync_interval_seconds") is None:
            changes.pop("sync_interval_seconds", None)
        if "metadata" in changes:
            metadata = changes.pop("metadata")
            if metadata is not None:
                account.metadata_json = {
                    **validate_user_metadata(metadata),
                    "input_mode": account.metadata_json.get("input_mode", "manual"),
                }
        for url_field in ("profile_url", "avatar_url"):
            if url_field in changes:
                changes[url_field] = str(changes[url_field]) if changes[url_field] else None
        for field, value in changes.items():
            setattr(account, field, value)
        if payload.is_active is False:
            account.sync_status = "disabled"
        elif payload.is_active is True and account.sync_status == "disabled":
            account.sync_status = "never"

        now = datetime.now(UTC)
        self._session.add(
            AuditEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action="monitoring.account.updated",
                resource_type="account",
                resource_id=account.id,
                before_hash=None,
                after_hash=None,
                change_summary_json={"fields": sorted(payload.model_fields_set)},
                reason="account settings update",
                ip_hash=None,
                trace_id=uuid4(),
                created_at=now,
            )
        )
        await self._session.commit()
        refreshed = await self._repository.get_account(workspace_id, account.id)
        if refreshed is None:
            raise RuntimeError("updated account could not be reloaded")
        return account_read(refreshed)

    async def disable_account(self, workspace_id: UUID, account_id: UUID, actor_id: UUID) -> None:
        row = await self._repository.get_account(workspace_id, account_id)
        if row is None:
            raise MonitoringNotFoundError("account was not found")
        account = row[0]
        account.is_active = False
        account.sync_status = "disabled"
        now = datetime.now(UTC)
        self._session.add(
            AuditEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action="monitoring.account.disabled",
                resource_type="account",
                resource_id=account.id,
                before_hash=None,
                after_hash=None,
                change_summary_json={"is_active": False, "history_preserved": True},
                reason="account removed from active monitoring",
                ip_hash=None,
                trace_id=uuid4(),
                created_at=now,
            )
        )
        await self._session.commit()

    async def batch_update_accounts(
        self, workspace_id: UUID, account_ids: list[UUID], is_active: bool, actor_id: UUID
    ) -> int:
        """Activate or deactivate many accounts at once. Returns updated count."""
        statement = (
            update(Account)
            .where(Account.workspace_id == workspace_id, Account.id.in_(account_ids))
            .values(is_active=is_active, updated_at=datetime.now(UTC))
        )
        result = await self._session.execute(statement)
        await self._session.commit()
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def batch_disable_accounts(
        self, workspace_id: UUID, account_ids: list[UUID], actor_id: UUID
    ) -> int:
        """Soft-delete many accounts (deactivate + stop syncing). Returns count."""
        statement = (
            update(Account)
            .where(Account.workspace_id == workspace_id, Account.id.in_(account_ids))
            .values(is_active=False, sync_status="disabled", updated_at=datetime.now(UTC))
        )
        result = await self._session.execute(statement)
        await self._session.commit()
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def compare_accounts(
        self, workspace_id: UUID, account_ids: list[UUID]
    ) -> AccountComparisonResponse:
        if not account_ids:
            raise MonitoringValidationError("at least one account_id is required")
        statement = (
            select(Account)
            .where(Account.workspace_id == workspace_id, Account.id.in_(account_ids))
            .options(selectinload(Account.platform))
        )
        accounts = list(await self._session.scalars(statement))
        found = {a.id for a in accounts}
        missing = [str(aid) for aid in account_ids if aid not in found]
        if missing:
            raise MonitoringNotFoundError(
                "accounts not found in workspace: " + ", ".join(missing)
            )

        rows: list[AccountComparisonRow] = []
        total_followers = total_views = 0
        best_followers_id = best_views_id = best_engagement_id = None
        best_followers_v = best_views_v = best_engagement_v = None

        for account in accounts:
            snapshots = list(
                await self._session.scalars(
                    select(AccountSnapshot)
                    .where(AccountSnapshot.account_id == account.id)
                    .order_by(AccountSnapshot.captured_at.desc())
                    .limit(2)
                )
            )
            latest = snapshots[0] if snapshots else None
            previous = snapshots[1] if len(snapshots) > 1 else None

            def _snapshot_dto(snap: AccountSnapshot) -> AccountComparisonSnapshot:
                return AccountComparisonSnapshot(
                    captured_at=snap.captured_at,
                    follower_count=snap.follower_count,
                    total_view_count=snap.total_view_count,
                    video_count=snap.video_count,
                    engagement_rate=(
                        float(snap.engagement_rate)
                        if snap.engagement_rate is not None
                        else None
                    ),
                    source_kind=cast("SourceKind", snap.source_kind),
                )

            latest_dto = _snapshot_dto(latest) if latest is not None else None
            previous_dto = _snapshot_dto(previous) if previous is not None else None

            follower_delta = view_delta = None
            window_hours = None
            if latest is not None and previous is not None:
                if (
                    latest.follower_count is not None
                    and previous.follower_count is not None
                ):
                    follower_delta = latest.follower_count - previous.follower_count
                if (
                    latest.total_view_count is not None
                    and previous.total_view_count is not None
                ):
                    view_delta = latest.total_view_count - previous.total_view_count
                window_hours = round(
                    (latest.captured_at - previous.captured_at).total_seconds() / 3600.0, 2
                )

            rows.append(
                AccountComparisonRow(
                    account_id=account.id,
                    platform_key=account.platform.key if account.platform else "",
                    display_name=account.display_name,
                    username=account.username,
                    is_active=account.is_active,
                    sync_status=cast("AccountSyncStatus", account.sync_status),
                    latest=latest_dto,
                    previous=previous_dto,
                    follower_delta=follower_delta,
                    view_delta=view_delta,
                    window_hours=window_hours,
                )
            )

            if latest is not None:
                if latest.follower_count is not None:
                    total_followers += latest.follower_count
                    if best_followers_v is None or latest.follower_count > best_followers_v:
                        best_followers_v = latest.follower_count
                        best_followers_id = account.id
                if latest.total_view_count is not None:
                    total_views += latest.total_view_count
                    if best_views_v is None or latest.total_view_count > best_views_v:
                        best_views_v = latest.total_view_count
                        best_views_id = account.id
                if latest.engagement_rate is not None:
                    eng = float(latest.engagement_rate)
                    if best_engagement_v is None or eng > best_engagement_v:
                        best_engagement_v = eng
                        best_engagement_id = account.id

        summary = AccountComparisonSummary(
            account_count=len(rows),
            total_followers=total_followers or None,
            total_views=total_views or None,
            total_videos=None,
            best_followers_account_id=best_followers_id,
            best_views_account_id=best_views_id,
            best_engagement_account_id=best_engagement_id,
        )
        return AccountComparisonResponse(rows=rows, summary=summary)

    async def recompute_account_sync_interval(
        self, workspace_id: UUID, account_id: UUID
    ) -> SyncIntervalResponse:
        account = (
            await self._session.scalars(
                select(Account).where(
                    Account.workspace_id == workspace_id, Account.id == account_id
                )
            )
        ).first()
        if account is None:
            raise MonitoringNotFoundError("account was not found")
        interval, median_gap = await compute_adaptive_interval(self._session, account_id)
        account.sync_interval_seconds = interval
        await self._session.commit()
        basis: Literal["adaptive", "default"] = (
            "adaptive" if median_gap is not None else "default"
        )
        return SyncIntervalResponse(
            account_id=account.id,
            sync_interval_seconds=interval,
            basis=basis,
            posting_median_gap_seconds=median_gap,
        )

    async def account_snapshots(
        self, workspace_id: UUID, account_id: UUID, *, page: int, page_size: int
    ) -> AccountSnapshotPage:
        await self.get_account(workspace_id, account_id)
        snapshots, total = await self._repository.list_account_snapshots(
            workspace_id, account_id, page=page, page_size=page_size
        )
        return AccountSnapshotPage(
            items=[AccountSnapshotRead.model_validate(item) for item in snapshots],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def account_metrics_history(
        self, workspace_id: UUID, account_id: UUID, *, days: int
    ) -> AccountMetricsHistory:
        """Return an ascending time series of account metric snapshots for charts."""
        await self.get_account(workspace_id, account_id)
        since = datetime.now(UTC) - timedelta(days=days)
        snapshots = await self._repository.list_account_snapshots_history(
            workspace_id, account_id, since=since
        )
        return AccountMetricsHistory(
            account_id=account_id,
            days=days,
            points=[AccountMetricsHistoryPoint.model_validate(s) for s in snapshots],
        )

    async def list_contents(
        self,
        workspace_id: UUID,
        *,
        filters: ContentFilters,
        sort: str,
        order: Order,
        page: int,
        page_size: int,
    ) -> ContentPage:
        self._validate_content_filters(filters)
        rows, total = await self._repository.list_contents(
            workspace_id,
            filters=filters,
            sort=sort,
            order=order,
            page=page,
            page_size=page_size,
        )
        return ContentPage(
            items=[content_read(row) for row in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def contents_calendar(
        self,
        workspace_id: UUID,
        *,
        filters: ContentFilters,
        year: int,
        month: int,
    ) -> ContentCalendarResponse:
        """Per-day aggregation of published works for a month (calendar view)."""
        import calendar

        _, last_day = calendar.monthrange(year, month)
        month_filters = ContentFilters(
            platform=filters.platform,
            account=filters.account,
            query=filters.query,
            published_from=datetime(year, month, 1, 0, 0, 0, tzinfo=UTC),
            published_to=datetime(
                year, month, last_day, 23, 59, 59, 999999, tzinfo=UTC
            ),
        )
        rows = await self._repository.contents_calendar(
            workspace_id, filters=month_filters
        )
        buckets = [
            ContentCalendarBucket(
                date=date, count=count, total_views=total_views, total_likes=total_likes
            )
            for date, count, total_views, total_likes in rows
        ]
        return ContentCalendarResponse(
            year=year,
            month=month,
            platform=filters.platform,
            account=filters.account,
            buckets=buckets,
            total_count=sum(b.count for b in buckets),
            total_views=sum(b.total_views for b in buckets),
        )

    async def summarize_account_contents(
        self, workspace_id: UUID, account_id: UUID
    ) -> AccountContentSummary:
        """Aggregated content-level overview for an account.

        Builds on top of ``AccountContentSummary``: all numbers come from real
        snapshots the adapter returned. Missing (API-gated) fields stay ``None``
        and the UI renders the required acquisition condition instead of faking.
        """
        await self.get_account(workspace_id, account_id)
        summary = await self._repository.summarize_account_contents(
            workspace_id, account_id
        )
        return AccountContentSummary(account_id=account_id, **summary)

    @staticmethod
    def _validate_content_filters(filters: ContentFilters) -> None:
        if (
            filters.min_views is not None
            and filters.max_views is not None
            and filters.min_views > filters.max_views
        ):
            raise MonitoringValidationError("min_views cannot be greater than max_views")
        if (
            filters.published_from is not None
            and filters.published_to is not None
            and filters.published_from > filters.published_to
        ):
            raise MonitoringValidationError("published_from cannot be after published_to")

    async def get_content(self, workspace_id: UUID, content_id: UUID) -> ContentRead:
        row = await self._repository.get_content(workspace_id, content_id)
        if row is None:
            raise MonitoringNotFoundError("content item was not found")
        return content_read(row)

    async def content_snapshots(
        self, workspace_id: UUID, content_id: UUID, *, page: int, page_size: int
    ) -> ContentSnapshotPage:
        await self.get_content(workspace_id, content_id)
        snapshots, total = await self._repository.list_content_snapshots(
            workspace_id, content_id, page=page, page_size=page_size
        )
        return ContentSnapshotPage(
            items=[ContentSnapshotRead.model_validate(item) for item in snapshots],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def content_metrics(
        self, workspace_id: UUID, content_id: UUID, *, page: int, page_size: int
    ) -> DerivedMetricPage:
        await self.get_content(workspace_id, content_id)
        metrics, total = await self._repository.list_content_metrics(
            workspace_id, content_id, page=page, page_size=page_size
        )
        return DerivedMetricPage(
            items=[DerivedMetricRead.model_validate(item) for item in metrics],
            page=page,
            page_size=page_size,
            total=total,
        )

    # -- Content CRUD (manual) -------------------------------------------------

    async def create_content(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: ContentCreate,
    ) -> ContentRead:
        from sqlalchemy import select

        # Validate the account belongs to this workspace
        account = await self._session.get(Account, payload.account_id)
        if account is None or account.workspace_id != workspace_id:
            raise MonitoringNotFoundError("account was not found")

        # Check for duplicate external_id within workspace + platform
        existing = await self._session.scalar(
            select(ContentItem).where(
                ContentItem.workspace_id == workspace_id,
                ContentItem.platform_id == account.platform_id,
                ContentItem.external_id == payload.external_id,
            )
        )
        if existing is not None:
            raise MonitoringConflictError(
                "作品外部 ID 在该平台下已存在", code="content_duplicate"
            )

        now = datetime.now(UTC)
        content = ContentItem(
            id=uuid4(),
            workspace_id=workspace_id,
            platform_id=account.platform_id,
            account_id=payload.account_id,
            external_id=payload.external_id,
            content_type=payload.content_type,
            title=payload.title,
            description=payload.description,
            published_at=payload.published_at,
            duration_seconds=payload.duration_seconds,
            canonical_url=payload.canonical_url,
            cover_url=payload.cover_url,
            language=payload.language,
            status=payload.status,
            metadata_json={**payload.metadata, "input_mode": "manual"},
            first_seen_at=now,
            last_seen_at=now,
            source_kind="imported",
            source_provider="manual",
            fetched_at=now,
        )
        self._session.add(content)

        self._session.add(
            AuditEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action="monitoring.content.created",
                resource_type="content",
                resource_id=content.id,
                before_hash=None,
                after_hash=None,
                change_summary_json={"external_id": payload.external_id},
                reason="manual content creation",
                ip_hash=None,
                trace_id=uuid4(),
                created_at=now,
            )
        )
        await self._session.flush()
        row = await self._repository.get_content(workspace_id, content.id)
        return content_read(row)  # type: ignore[arg-type]

    async def update_content(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        content_id: UUID,
        payload: ContentUpdate,
    ) -> ContentRead:
        row = await self._repository.get_content(workspace_id, content_id)
        if row is None:
            raise MonitoringNotFoundError("content item was not found")
        content = row[0]
        changes = payload.model_dump(exclude_unset=True)
        if "metadata" in changes:
            metadata = changes.pop("metadata")
            if metadata is not None:
                existing = dict(content.metadata_json) if content.metadata_json else {}
                content.metadata_json = {
                    **existing,
                    **validate_user_metadata(metadata),
                }
        for field, value in changes.items():
            setattr(content, field, value)

        now = datetime.now(UTC)
        self._session.add(
            AuditEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action="monitoring.content.updated",
                resource_type="content",
                resource_id=content.id,
                before_hash=None,
                after_hash=None,
                change_summary_json={"fields": sorted(payload.model_fields_set)},
                reason="content update",
                ip_hash=None,
                trace_id=uuid4(),
                created_at=now,
            )
        )
        await self._session.flush()
        row = await self._repository.get_content(workspace_id, content_id)
        return content_read(row)  # type: ignore[arg-type]

    async def delete_content(
        self, workspace_id: UUID, actor_id: UUID, content_id: UUID
    ) -> None:
        row = await self._repository.get_content(workspace_id, content_id)
        if row is None:
            raise MonitoringNotFoundError("content item was not found")
        content = row[0]
        now = datetime.now(UTC)
        self._session.add(
            AuditEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action="monitoring.content.deleted",
                resource_type="content",
                resource_id=content.id,
                before_hash=None,
                after_hash=None,
                change_summary_json={"title": content.title},
                reason="content deletion",
                ip_hash=None,
                trace_id=uuid4(),
                created_at=now,
            )
        )
        await self._session.delete(content)

    async def export_accounts_csv(
        self, workspace_id: UUID, filters: AccountFilters, sort: str, order: Order
    ) -> str:
        rows, total = await self._repository.list_accounts(
            workspace_id,
            filters=filters,
            sort=sort,
            order=order,
            page=1,
            page_size=MAX_CSV_EXPORT_ROWS,
        )
        if total > MAX_CSV_EXPORT_ROWS:
            raise MonitoringValidationError(
                "account export exceeds 10,000 rows; narrow the filters"
            )
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "platform",
                "external_id",
                "username",
                "display_name",
                "source_kind",
                "follower_count",
                "total_view_count",
                "follower_growth_24h",
                "last_synced_at",
            ]
        )
        for account, snapshot, growth in rows:
            writer.writerow(
                [
                    account.id,
                    safe_csv_cell(account.platform.key),
                    safe_csv_cell(account.external_id),
                    safe_csv_cell(account.username),
                    safe_csv_cell(account.display_name),
                    account.source_kind,
                    snapshot.follower_count if snapshot else None,
                    snapshot.total_view_count if snapshot else None,
                    growth,
                    account.last_synced_at,
                ]
            )
        return "\ufeff" + output.getvalue()

    async def export_contents_csv(
        self, workspace_id: UUID, filters: ContentFilters, sort: str, order: Order
    ) -> str:
        self._validate_content_filters(filters)
        rows, total = await self._repository.list_contents(
            workspace_id,
            filters=filters,
            sort=sort,
            order=order,
            page=1,
            page_size=MAX_CSV_EXPORT_ROWS,
        )
        if total > MAX_CSV_EXPORT_ROWS:
            raise MonitoringValidationError(
                "content export exceeds 10,000 rows; narrow the filters"
            )
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "platform",
                "account_id",
                "external_id",
                "title",
                "published_at",
                "source_kind",
                "view_count",
                "view_growth_24h",
                "canonical_url",
            ]
        )
        for content, snapshot, growth in rows:
            writer.writerow(
                [
                    content.id,
                    safe_csv_cell(content.platform.key),
                    content.account_id,
                    safe_csv_cell(content.external_id),
                    safe_csv_cell(content.title),
                    content.published_at,
                    content.source_kind,
                    snapshot.view_count if snapshot else None,
                    growth,
                    safe_csv_cell(content.canonical_url),
                ]
            )
        return "\ufeff" + output.getvalue()
