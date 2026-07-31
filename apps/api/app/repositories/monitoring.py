from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.monitoring import (
    Account,
    AccountSnapshot,
    ContentItem,
    ContentSnapshot,
    DerivedMetric,
    Platform,
)

Order = Literal["asc", "desc"]


@dataclass(frozen=True)
class AccountFilters:
    platform: str | None = None
    query: str | None = None
    is_active: bool | None = None


@dataclass(frozen=True)
class ContentFilters:
    platform: str | None = None
    account: UUID | None = None
    published_from: datetime | None = None
    published_to: datetime | None = None
    min_views: int | None = None
    max_views: int | None = None
    query: str | None = None


AccountRow = tuple[Account, AccountSnapshot | None, Any]
ContentRow = tuple[ContentItem, ContentSnapshot | None, Any]


class MonitoringRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_platforms(self, *, enabled: bool | None = None) -> list[Platform]:
        statement = select(Platform)
        if enabled is not None:
            statement = statement.where(Platform.enabled.is_(enabled))
        result = await self._session.scalars(statement.order_by(Platform.name.asc()))
        return list(result.all())

    async def get_platform(self, platform_id: UUID) -> Platform | None:
        return await self._session.get(Platform, platform_id)

    def _account_conditions(self, workspace_id: UUID, filters: AccountFilters) -> list[Any]:
        conditions: list[Any] = [Account.workspace_id == workspace_id]
        if filters.platform:
            conditions.append(Platform.key == filters.platform.casefold())
        if filters.is_active is not None:
            conditions.append(Account.is_active.is_(filters.is_active))
        if filters.query:
            pattern = f"%{filters.query.strip()}%"
            conditions.append(
                or_(
                    Account.display_name.ilike(pattern),
                    Account.username.ilike(pattern),
                    Account.external_id.ilike(pattern),
                    Account.description.ilike(pattern),
                )
            )
        return conditions

    def _latest_account_snapshot_id(self) -> Any:
        return (
            select(AccountSnapshot.id)
            .where(AccountSnapshot.account_id == Account.id)
            .order_by(AccountSnapshot.captured_at.desc(), AccountSnapshot.id.desc())
            .limit(1)
            .correlate(Account)
            .scalar_subquery()
        )

    def _latest_metric_value(self, entity_type: str, entity_id: Any, metric_key: str) -> Any:
        return (
            select(DerivedMetric.value)
            .where(
                DerivedMetric.entity_type == entity_type,
                DerivedMetric.entity_id == entity_id,
                DerivedMetric.metric_key == metric_key,
            )
            .order_by(DerivedMetric.calculated_at.desc(), DerivedMetric.id.desc())
            .limit(1)
            .correlate(Account, ContentItem)
            .scalar_subquery()
        )

    async def list_accounts(
        self,
        workspace_id: UUID,
        *,
        filters: AccountFilters,
        sort: str,
        order: Order,
        page: int,
        page_size: int,
    ) -> tuple[list[AccountRow], int]:
        latest_snapshot_id = self._latest_account_snapshot_id()
        follower_growth = self._latest_metric_value("account", Account.id, "follower_growth_24h")
        conditions = self._account_conditions(workspace_id, filters)
        statement = (
            select(Account, AccountSnapshot, follower_growth.label("follower_growth_24h"))
            .join(Platform, Account.platform_id == Platform.id)
            .outerjoin(AccountSnapshot, AccountSnapshot.id == latest_snapshot_id)
            .options(joinedload(Account.platform))
            .where(*conditions)
        )
        sort_columns: dict[str, Any] = {
            "created_at": Account.created_at,
            "updated_at": Account.updated_at,
            "display_name": Account.display_name,
            "last_synced_at": Account.last_synced_at,
            "follower_count": AccountSnapshot.follower_count,
            "total_view_count": AccountSnapshot.total_view_count,
            "follower_growth_24h": follower_growth,
        }
        sort_column = sort_columns[sort]
        ordering = sort_column.asc() if order == "asc" else sort_column.desc()
        statement = (
            statement.order_by(ordering.nullslast(), Account.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._session.execute(statement)

        count_statement = (
            select(func.count())
            .select_from(Account)
            .join(Platform, Account.platform_id == Platform.id)
            .where(*conditions)
        )
        total = int((await self._session.scalar(count_statement)) or 0)
        return [(row[0], row[1], row[2]) for row in result.all()], total

    async def get_account(self, workspace_id: UUID, account_id: UUID) -> AccountRow | None:
        latest_snapshot_id = self._latest_account_snapshot_id()
        follower_growth = self._latest_metric_value("account", Account.id, "follower_growth_24h")
        statement = (
            select(Account, AccountSnapshot, follower_growth)
            .outerjoin(AccountSnapshot, AccountSnapshot.id == latest_snapshot_id)
            .options(joinedload(Account.platform))
            .where(Account.id == account_id, Account.workspace_id == workspace_id)
        )
        row = (await self._session.execute(statement)).one_or_none()
        return (row[0], row[1], row[2]) if row else None

    async def get_account_by_external_id(
        self, workspace_id: UUID, platform_id: UUID, external_id: str
    ) -> Account | None:
        return cast(
            Account | None,
            await self._session.scalar(
                select(Account).where(
                    Account.workspace_id == workspace_id,
                    Account.platform_id == platform_id,
                    Account.external_id == external_id,
                )
            ),
        )

    def add_account(self, account: Account) -> None:
        self._session.add(account)

    def add_account_snapshot(self, snapshot: AccountSnapshot) -> None:
        self._session.add(snapshot)

    async def list_account_snapshots(
        self, workspace_id: UUID, account_id: UUID, *, page: int, page_size: int
    ) -> tuple[list[AccountSnapshot], int]:
        base_condition = (
            AccountSnapshot.account_id == account_id,
            Account.workspace_id == workspace_id,
        )
        statement = (
            select(AccountSnapshot)
            .join(Account, AccountSnapshot.account_id == Account.id)
            .where(*base_condition)
            .order_by(AccountSnapshot.captured_at.desc(), AccountSnapshot.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        snapshots = list((await self._session.scalars(statement)).all())
        count_statement = (
            select(func.count())
            .select_from(AccountSnapshot)
            .join(Account, AccountSnapshot.account_id == Account.id)
            .where(*base_condition)
        )
        total = int((await self._session.scalar(count_statement)) or 0)
        return snapshots, total

    async def list_account_snapshots_history(
        self, workspace_id: UUID, account_id: UUID, *, since: datetime
    ) -> list[AccountSnapshot]:
        """Return every account snapshot captured at/after ``since`` (ascending)."""
        statement = (
            select(AccountSnapshot)
            .join(Account, AccountSnapshot.account_id == Account.id)
            .where(
                AccountSnapshot.account_id == account_id,
                Account.workspace_id == workspace_id,
                AccountSnapshot.captured_at >= since,
            )
            .order_by(AccountSnapshot.captured_at.asc(), AccountSnapshot.id.asc())
        )
        return list((await self._session.scalars(statement)).all())

    def _latest_content_snapshot_id(self) -> Any:
        return (
            select(ContentSnapshot.id)
            .where(ContentSnapshot.content_item_id == ContentItem.id)
            .order_by(ContentSnapshot.captured_at.desc(), ContentSnapshot.id.desc())
            .limit(1)
            .correlate(ContentItem)
            .scalar_subquery()
        )

    def _content_conditions(
        self,
        workspace_id: UUID,
        filters: ContentFilters,
    ) -> list[Any]:
        conditions: list[Any] = [ContentItem.workspace_id == workspace_id]
        if filters.platform:
            conditions.append(Platform.key == filters.platform.casefold())
        if filters.account:
            conditions.append(ContentItem.account_id == filters.account)
        if filters.published_from:
            conditions.append(ContentItem.published_at >= filters.published_from)
        if filters.published_to:
            conditions.append(ContentItem.published_at <= filters.published_to)
        if filters.min_views is not None:
            conditions.append(ContentSnapshot.view_count >= filters.min_views)
        if filters.max_views is not None:
            conditions.append(ContentSnapshot.view_count <= filters.max_views)
        if filters.query:
            pattern = f"%{filters.query.strip()}%"
            conditions.append(
                or_(
                    ContentItem.title.ilike(pattern),
                    ContentItem.description.ilike(pattern),
                    ContentItem.external_id.ilike(pattern),
                )
            )
        return conditions

    async def list_contents(
        self,
        workspace_id: UUID,
        *,
        filters: ContentFilters,
        sort: str,
        order: Order,
        page: int,
        page_size: int,
    ) -> tuple[list[ContentRow], int]:
        latest_snapshot_id = self._latest_content_snapshot_id()
        view_growth = self._latest_metric_value("content_item", ContentItem.id, "view_growth_24h")
        conditions = self._content_conditions(workspace_id, filters)
        statement: Select[Any] = (
            select(ContentItem, ContentSnapshot, view_growth.label("view_growth_24h"))
            .join(Platform, ContentItem.platform_id == Platform.id)
            .outerjoin(ContentSnapshot, ContentSnapshot.id == latest_snapshot_id)
            .options(joinedload(ContentItem.platform))
            .where(*conditions)
        )
        sort_columns: dict[str, Any] = {
            "published_at": ContentItem.published_at,
            "first_seen_at": ContentItem.first_seen_at,
            "last_seen_at": ContentItem.last_seen_at,
            "title": ContentItem.title,
            "view_count": ContentSnapshot.view_count,
            "view_growth_24h": view_growth,
        }
        sort_column = sort_columns[sort]
        ordering = sort_column.asc() if order == "asc" else sort_column.desc()
        statement = (
            statement.order_by(ordering.nullslast(), ContentItem.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._session.execute(statement)

        count_statement = (
            select(func.count())
            .select_from(ContentItem)
            .join(Platform, ContentItem.platform_id == Platform.id)
            .outerjoin(ContentSnapshot, ContentSnapshot.id == latest_snapshot_id)
            .where(*conditions)
        )
        total = int((await self._session.scalar(count_statement)) or 0)
        return [(row[0], row[1], row[2]) for row in result.all()], total

    async def get_content(self, workspace_id: UUID, content_id: UUID) -> ContentRow | None:
        latest_snapshot_id = self._latest_content_snapshot_id()
        view_growth = self._latest_metric_value("content_item", ContentItem.id, "view_growth_24h")
        statement = (
            select(ContentItem, ContentSnapshot, view_growth)
            .outerjoin(ContentSnapshot, ContentSnapshot.id == latest_snapshot_id)
            .options(joinedload(ContentItem.platform))
            .where(ContentItem.id == content_id, ContentItem.workspace_id == workspace_id)
        )
        row = (await self._session.execute(statement)).one_or_none()
        return (row[0], row[1], row[2]) if row else None

    def add_content(self, content: ContentItem) -> None:
        self._session.add(content)

    def add_content_snapshot(self, snapshot: ContentSnapshot) -> None:
        self._session.add(snapshot)

    def add_derived_metric(self, metric: DerivedMetric) -> None:
        self._session.add(metric)

    async def list_content_snapshots(
        self, workspace_id: UUID, content_id: UUID, *, page: int, page_size: int
    ) -> tuple[list[ContentSnapshot], int]:
        base_condition = (
            ContentSnapshot.content_item_id == content_id,
            ContentItem.workspace_id == workspace_id,
        )
        statement = (
            select(ContentSnapshot)
            .join(ContentItem, ContentSnapshot.content_item_id == ContentItem.id)
            .where(*base_condition)
            .order_by(ContentSnapshot.captured_at.desc(), ContentSnapshot.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        snapshots = list((await self._session.scalars(statement)).all())
        count_statement = (
            select(func.count())
            .select_from(ContentSnapshot)
            .join(ContentItem, ContentSnapshot.content_item_id == ContentItem.id)
            .where(*base_condition)
        )
        total = int((await self._session.scalar(count_statement)) or 0)
        return snapshots, total

    async def list_content_metrics(
        self, workspace_id: UUID, content_id: UUID, *, page: int, page_size: int
    ) -> tuple[list[DerivedMetric], int]:
        conditions = (
            DerivedMetric.workspace_id == workspace_id,
            DerivedMetric.entity_type == "content_item",
            DerivedMetric.entity_id == content_id,
        )
        statement = (
            select(DerivedMetric)
            .where(*conditions)
            .order_by(DerivedMetric.calculated_at.desc(), DerivedMetric.metric_key.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        metrics = list((await self._session.scalars(statement)).all())
        total = int(
            (
                await self._session.scalar(
                    select(func.count()).select_from(DerivedMetric).where(*conditions)
                )
            )
            or 0
        )
        return metrics, total
