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
    Comment,
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
    tags: list[str] | None = None


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

    async def get_platform_by_key(self, key: str) -> Platform | None:
        """Resolve a platform record by its stable key (e.g. ``"youtube"``).

        Used by the URL-based account auto-detection path so operators only
        need to paste a profile URL and the system infers the platform.
        """
        statement = select(Platform).where(Platform.key == key.casefold())
        result: Platform | None = await self._session.scalar(statement)
        return result

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
        if filters.tags:
            # multi-select: match contents carrying ANY of the chosen tags
            conditions.append(ContentItem.tags.overlap(filters.tags))
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
            "like_count": ContentSnapshot.like_count,
            "comment_count": ContentSnapshot.comment_count,
            "share_count": ContentSnapshot.share_count,
            "completion_rate": ContentSnapshot.completion_rate,
            "engagement_rate": (
                (
                    func.coalesce(ContentSnapshot.like_count, 0)
                    + func.coalesce(ContentSnapshot.comment_count, 0)
                    + func.coalesce(ContentSnapshot.share_count, 0)
                    + func.coalesce(ContentSnapshot.favorite_count, 0)
                )
                / func.nullif(ContentSnapshot.view_count, 0)
            ),
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

    async def list_content_tags(self, workspace_id: UUID) -> list[str]:
        """Distinct, sorted tags across a workspace's contents (for the filter)."""
        statement = (
            select(func.distinct(func.unnest(ContentItem.tags)))
            .where(ContentItem.workspace_id == workspace_id)
            .where(ContentItem.tags.isnot(None))
        )
        result = await self._session.execute(statement)
        return sorted(tag for (tag,) in result.all() if tag)

    async def list_content_comments(self, content_item_id: UUID, limit: int = 20) -> list[Comment]:
        """Top comments for a content item, ranked by engagement.

        Score = likes + 3×replies (replies weighted higher as they signal
        discussion depth). NULL counts count as 0 so unranked comments sink.
        Capped at ``limit`` (default 20) for the hot-comments widget.
        """
        score = (
            func.coalesce(Comment.like_count, 0) + 3 * func.coalesce(Comment.reply_count, 0)
        ).label("score")
        statement = (
            select(Comment)
            .where(Comment.content_item_id == content_item_id)
            .order_by(score.desc(), Comment.like_count.desc().nullslast())
            .limit(limit)
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def contents_calendar(
        self,
        workspace_id: UUID,
        *,
        filters: ContentFilters,
    ) -> list[tuple[str, int, int, int]]:
        """Aggregate published works by calendar day for a given month.

        Returns tuples of (date_str, count, total_views, total_likes) keyed by
        ``YYYY-MM-DD``. All numbers come from real snapshots the adapter stored;
        missing snapshot metrics contribute zero rather than being faked.
        """
        latest_snapshot_id = self._latest_content_snapshot_id()
        conditions = self._content_conditions(workspace_id, filters)
        day = func.to_char(func.date_trunc("day", ContentItem.published_at), "YYYY-MM-DD").label(
            "day"
        )
        statement = (
            select(
                day,
                func.count(ContentItem.id).label("content_count"),
                func.coalesce(func.sum(func.coalesce(ContentSnapshot.view_count, 0)), 0).label(
                    "total_views"
                ),
                func.coalesce(func.sum(func.coalesce(ContentSnapshot.like_count, 0)), 0).label(
                    "total_likes"
                ),
            )
            .join(Platform, ContentItem.platform_id == Platform.id)
            .outerjoin(ContentSnapshot, ContentSnapshot.id == latest_snapshot_id)
            .where(*conditions)
            .group_by(day)
            .order_by(day.asc())
        )
        result = await self._session.execute(statement)
        return [
            (str(row.day), int(row.content_count), int(row.total_views), int(row.total_likes))
            for row in result.all()
        ]

    async def summarize_account_contents(
        self, workspace_id: UUID, account_id: UUID
    ) -> dict[str, Any]:
        """Aggregate content-level metrics for an account overview.

        Every value is computed from the latest snapshot the adapter actually
        returned. Traffic-source proportions are view-weighted so a few viral
        videos don't get drowned out by low-view catalogue items. Fields the
        adapter could not obtain (e.g. completion rate via a public-browse only
        path) come back as ``None`` and the UI shows the required condition.
        """
        latest_snapshot_id = self._latest_content_snapshot_id()
        view_growth = self._latest_metric_value("content_item", ContentItem.id, "view_growth_24h")
        interactions = (
            func.coalesce(ContentSnapshot.like_count, 0)
            + func.coalesce(ContentSnapshot.comment_count, 0)
            + func.coalesce(ContentSnapshot.share_count, 0)
            + func.coalesce(ContentSnapshot.favorite_count, 0)
        )
        statement = (
            select(
                func.count(ContentItem.id).label("content_count"),
                func.avg(ContentSnapshot.completion_rate).label("avg_completion_rate"),
                func.avg(ContentSnapshot.average_watch_time).label("avg_watch_time"),
                func.avg(interactions / func.nullif(ContentSnapshot.view_count, 0)).label(
                    "avg_engagement_rate"
                ),
                func.sum(interactions).label("total_interactions"),
                func.sum(
                    ContentSnapshot.view_count
                    * func.coalesce(ContentSnapshot.recommendation_traffic_rate, 0)
                ).label("rec_weighted"),
                func.sum(
                    ContentSnapshot.view_count
                    * func.coalesce(ContentSnapshot.search_traffic_rate, 0)
                ).label("search_weighted"),
                func.sum(
                    ContentSnapshot.view_count
                    * func.coalesce(ContentSnapshot.profile_traffic_rate, 0)
                ).label("profile_weighted"),
                func.sum(func.coalesce(ContentSnapshot.view_count, 0)).label("view_sum"),
                func.sum(view_growth).label("recent_view_growth"),
            )
            .select_from(ContentItem)
            .join(Platform, ContentItem.platform_id == Platform.id)
            .outerjoin(ContentSnapshot, ContentSnapshot.id == latest_snapshot_id)
            .where(
                ContentItem.workspace_id == workspace_id,
                ContentItem.account_id == account_id,
            )
        )
        row = (await self._session.execute(statement)).one()
        mapping = row._mapping
        content_count = int(mapping["content_count"] or 0)
        view_sum = float(mapping["view_sum"] or 0)

        def weighted(column: str) -> float | None:
            value = mapping[column]
            if value is None or view_sum <= 0:
                return None
            return float(value) / view_sum

        traffic_split = {
            "recommendation": weighted("rec_weighted"),
            "search": weighted("search_weighted"),
            "profile": weighted("profile_weighted"),
        }

        top_statement = (
            select(ContentItem.id, ContentItem.title, ContentSnapshot.view_count)
            .select_from(ContentItem)
            .outerjoin(ContentSnapshot, ContentSnapshot.id == latest_snapshot_id)
            .where(
                ContentItem.workspace_id == workspace_id,
                ContentItem.account_id == account_id,
            )
            .order_by(ContentSnapshot.view_count.desc().nullslast(), ContentItem.id.asc())
            .limit(1)
        )
        top_row = (await self._session.execute(top_statement)).one_or_none()
        latest_account_snap = await self._session.scalar(
            select(AccountSnapshot)
            .where(AccountSnapshot.account_id == account_id)
            .order_by(AccountSnapshot.captured_at.desc())
            .limit(1)
        )
        account_total_likes = (
            latest_account_snap.total_like_count if latest_account_snap is not None else None
        )
        account_total_views = (
            latest_account_snap.total_view_count if latest_account_snap is not None else None
        )
        return {
            "content_count": content_count,
            "avg_completion_rate": mapping["avg_completion_rate"],
            "avg_watch_time_seconds": mapping["avg_watch_time"],
            "avg_engagement_rate": mapping["avg_engagement_rate"],
            "total_interactions": (
                int(mapping["total_interactions"])
                if mapping["total_interactions"] is not None
                else None
            ),
            "account_total_likes": account_total_likes,
            "account_total_views": account_total_views,
            "traffic_source_split": traffic_split,
            "recent_24h_view_growth": (
                int(mapping["recent_view_growth"])
                if mapping["recent_view_growth"] is not None
                else None
            ),
            "top_content_id": top_row[0] if top_row else None,
            "top_content_title": top_row[1] if top_row else None,
            "top_content_views": top_row[2] if top_row else None,
        }

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
