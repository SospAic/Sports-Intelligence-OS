from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.news import (
    Article,
    EventArticle,
    NewsScoringConfig,
    NewsSyncRun,
    Source,
    TopicEvent,
)

Order = Literal["asc", "desc"]
ArticleRow = tuple[Article, TopicEvent | None]


@dataclass(frozen=True)
class ArticleFilters:
    published_from: datetime | None = None
    published_to: datetime | None = None
    sport: str | None = None
    league: str | None = None
    source: UUID | None = None
    language: str | None = None
    country: str | None = None
    query: str | None = None
    is_duplicate: bool | None = None
    is_bookmarked: bool | None = None
    min_heat: float | None = None
    max_heat: float | None = None


@dataclass(frozen=True)
class EventFilters:
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    sport: str | None = None
    league: str | None = None
    language: str | None = None
    country: str | None = None
    query: str | None = None
    is_bookmarked: bool | None = None
    min_heat: float | None = None
    max_heat: float | None = None


class NewsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def source(self, workspace_id: UUID, source_id: UUID) -> Source | None:
        return cast(
            Source | None,
            await self.session.scalar(
                select(Source).where(Source.workspace_id == workspace_id, Source.id == source_id)
            ),
        )

    async def source_by_name(self, workspace_id: UUID, name: str) -> Source | None:
        return cast(
            Source | None,
            await self.session.scalar(
                select(Source).where(
                    Source.workspace_id == workspace_id,
                    func.lower(Source.name) == name.casefold(),
                )
            ),
        )

    async def list_sources(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        enabled: bool | None,
        include_quarantined: bool = False,
    ) -> tuple[list[Source], int]:
        conditions = [Source.workspace_id == workspace_id]
        if enabled is not None:
            conditions.append(Source.enabled.is_(enabled))
        if not include_quarantined:
            quarantine_value = Source.config_json["quarantined"].as_boolean()
            conditions.append(or_(quarantine_value.is_(None), quarantine_value.is_(False)))
        items = list(
            (
                await self.session.scalars(
                    select(Source)
                    .where(*conditions)
                    .order_by(Source.priority.desc(), Source.name.asc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            (await self.session.scalar(select(func.count()).select_from(Source).where(*conditions)))
            or 0
        )
        return items, total

    async def due_sources(self, due_at: datetime, limit: int = 500) -> list[Source]:
        return list(
            (
                await self.session.scalars(
                    select(Source)
                    .where(
                        Source.enabled.is_(True),
                        Source.source_type != "manual",
                        or_(Source.next_sync_at.is_(None), Source.next_sync_at <= due_at),
                    )
                    .order_by(Source.next_sync_at.asc().nullsfirst(), Source.priority.desc())
                    .limit(limit)
                )
            ).all()
        )

    async def article(self, workspace_id: UUID, article_id: UUID) -> ArticleRow | None:
        statement = (
            select(Article, TopicEvent)
            .options(joinedload(Article.source))
            .outerjoin(EventArticle, EventArticle.article_id == Article.id)
            .outerjoin(TopicEvent, TopicEvent.id == EventArticle.event_id)
            .where(Article.workspace_id == workspace_id, Article.id == article_id)
        )
        row = (await self.session.execute(statement)).first()
        return cast(ArticleRow | None, row)

    async def article_by_external(self, source_id: UUID, external_id: str) -> Article | None:
        return cast(
            Article | None,
            await self.session.scalar(
                select(Article).where(
                    Article.source_id == source_id, Article.external_id == external_id
                )
            ),
        )

    async def duplicate_candidates(
        self,
        workspace_id: UUID,
        *,
        content_hash: str,
        canonical_url: str,
        published_after: datetime,
        limit: int = 100,
    ) -> list[Article]:
        statement = (
            select(Article)
            .where(
                Article.workspace_id == workspace_id,
                or_(
                    Article.content_hash == content_hash,
                    Article.canonical_url == canonical_url,
                    Article.published_at >= published_after,
                ),
            )
            .order_by(Article.published_at.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    async def list_articles(
        self,
        workspace_id: UUID,
        *,
        filters: ArticleFilters,
        sort: str,
        order: Order,
        page: int,
        page_size: int,
    ) -> tuple[list[ArticleRow], int]:
        conditions = [Article.workspace_id == workspace_id]
        # Disabled sources remain available through an explicit source filter
        # for history/audit, but must not pollute the default news feed.
        if filters.source is None:
            conditions.append(Source.enabled.is_(True))
        if filters.published_from is not None:
            conditions.append(Article.published_at >= filters.published_from)
        if filters.published_to is not None:
            conditions.append(Article.published_at <= filters.published_to)
        if filters.sport:
            conditions.append(func.lower(Article.sport) == filters.sport.casefold())
        if filters.league:
            conditions.append(func.lower(Article.league) == filters.league.casefold())
        if filters.source:
            conditions.append(Article.source_id == filters.source)
        if filters.language:
            conditions.append(func.lower(Article.language) == filters.language.casefold())
        if filters.country:
            conditions.append(func.lower(Article.country) == filters.country.casefold())
        if filters.query:
            pattern = f"%{filters.query.casefold()}%"
            conditions.append(
                or_(
                    func.lower(Article.title).like(pattern),
                    func.lower(Article.summary).like(pattern),
                )
            )
        if filters.is_duplicate is not None:
            conditions.append(
                Article.duplicate_group_id.is_not(None)
                if filters.is_duplicate
                else Article.duplicate_group_id.is_(None)
            )
        if filters.is_bookmarked is not None:
            if filters.is_bookmarked:
                conditions.append(
                    or_(Article.is_bookmarked.is_(True), TopicEvent.is_bookmarked.is_(True))
                )
            else:
                conditions.append(
                    and_(
                        Article.is_bookmarked.is_(False),
                        or_(TopicEvent.id.is_(None), TopicEvent.is_bookmarked.is_(False)),
                    )
                )
        if filters.min_heat is not None:
            conditions.append(TopicEvent.heat_score >= filters.min_heat)
        if filters.max_heat is not None:
            conditions.append(TopicEvent.heat_score <= filters.max_heat)

        sort_columns = {
            "published_at": Article.published_at,
            "fetched_at": Article.fetched_at,
            "heat_score": TopicEvent.heat_score,
            "reliability_score": Source.reliability_score,
            "source_count": TopicEvent.source_count,
            "controversy_score": TopicEvent.controversy_score,
            "visual_score": TopicEvent.visual_score,
            "story_score": TopicEvent.story_score,
        }
        sort_column = sort_columns[sort]
        ordering = (
            sort_column.asc().nullslast() if order == "asc" else sort_column.desc().nullslast()
        )
        joins = (
            Article.__table__.join(Source, Source.id == Article.source_id)
            .outerjoin(EventArticle, EventArticle.article_id == Article.id)
            .outerjoin(TopicEvent, TopicEvent.id == EventArticle.event_id)
        )
        statement = (
            select(Article, TopicEvent)
            .select_from(joins)
            .options(joinedload(Article.source))
            .where(*conditions)
            .order_by(ordering, Article.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = [cast(ArticleRow, row) for row in (await self.session.execute(statement)).all()]
        total = int(
            (
                await self.session.scalar(
                    select(func.count(func.distinct(Article.id)))
                    .select_from(joins)
                    .where(*conditions)
                )
            )
            or 0
        )
        return rows, total

    async def event(self, workspace_id: UUID, event_id: UUID) -> TopicEvent | None:
        return cast(
            TopicEvent | None,
            await self.session.scalar(
                select(TopicEvent).where(
                    TopicEvent.workspace_id == workspace_id, TopicEvent.id == event_id
                )
            ),
        )

    async def event_articles(self, event_id: UUID) -> list[Article]:
        statement = (
            select(Article)
            .options(joinedload(Article.source))
            .join(EventArticle, EventArticle.article_id == Article.id)
            .where(EventArticle.event_id == event_id)
            .order_by(Article.published_at.asc().nullslast(), Article.fetched_at.asc())
        )
        return list((await self.session.scalars(statement)).unique().all())

    async def candidate_events(
        self,
        workspace_id: UUID,
        *,
        updated_after: datetime,
        sport: str | None,
        limit: int = 100,
    ) -> list[TopicEvent]:
        conditions = [
            TopicEvent.workspace_id == workspace_id,
            TopicEvent.status != "closed",
            TopicEvent.last_update_time >= updated_after,
            select(Article.id)
            .join(EventArticle, EventArticle.article_id == Article.id)
            .join(Source, Source.id == Article.source_id)
            .where(
                EventArticle.event_id == TopicEvent.id,
                Source.enabled.is_(True),
            )
            .exists(),
        ]
        if sport:
            conditions.append(
                or_(
                    TopicEvent.sport.is_(None),
                    func.lower(TopicEvent.sport) == sport.casefold(),
                )
            )
        return list(
            (
                await self.session.scalars(
                    select(TopicEvent)
                    .where(*conditions)
                    .order_by(TopicEvent.last_update_time.desc())
                    .limit(limit)
                )
            ).all()
        )

    async def list_events(
        self,
        workspace_id: UUID,
        *,
        filters: EventFilters,
        sort: str,
        order: Order,
        page: int,
        page_size: int,
    ) -> tuple[list[TopicEvent], int]:
        conditions = [
            TopicEvent.workspace_id == workspace_id,
            select(Article.id)
            .join(EventArticle, EventArticle.article_id == Article.id)
            .join(Source, Source.id == Article.source_id)
            .where(
                EventArticle.event_id == TopicEvent.id,
                Source.enabled.is_(True),
            )
            .exists(),
        ]
        if filters.updated_from:
            conditions.append(TopicEvent.last_update_time >= filters.updated_from)
        if filters.updated_to:
            conditions.append(TopicEvent.last_update_time <= filters.updated_to)
        if filters.sport:
            conditions.append(func.lower(TopicEvent.sport) == filters.sport.casefold())
        if filters.league:
            conditions.append(func.lower(TopicEvent.league) == filters.league.casefold())
        if filters.query:
            pattern = f"%{filters.query.casefold()}%"
            conditions.append(
                or_(
                    func.lower(TopicEvent.title).like(pattern),
                    func.lower(TopicEvent.summary).like(pattern),
                )
            )
        if filters.is_bookmarked is not None:
            conditions.append(TopicEvent.is_bookmarked.is_(filters.is_bookmarked))
        if filters.min_heat is not None:
            conditions.append(TopicEvent.heat_score >= filters.min_heat)
        if filters.max_heat is not None:
            conditions.append(TopicEvent.heat_score <= filters.max_heat)
        if filters.language or filters.country:
            article_match = [
                EventArticle.event_id == TopicEvent.id,
                EventArticle.article_id == Article.id,
            ]
            if filters.language:
                article_match.append(func.lower(Article.language) == filters.language.casefold())
            if filters.country:
                article_match.append(func.lower(Article.country) == filters.country.casefold())
            conditions.append(select(Article.id).where(and_(*article_match)).exists())
        sort_columns = {
            "last_update_time": TopicEvent.last_update_time,
            "heat_score": TopicEvent.heat_score,
            "reliability_score": TopicEvent.reliability_score,
            "source_count": TopicEvent.source_count,
            "article_count": TopicEvent.article_count,
            "controversy_score": TopicEvent.controversy_score,
            "visual_score": TopicEvent.visual_score,
            "story_score": TopicEvent.story_score,
        }
        sort_column = sort_columns[sort]
        ordering = sort_column.asc() if order == "asc" else sort_column.desc()
        # A topic event is a read-model entity, while the underlying article
        # links are append-only evidence.  Older sync runs can leave multiple
        # active rows with the same normalized title (for example when the
        # same RSS item reappears after the clustering lookback).  Keep the
        # newest/best row visible without deleting historical rows or their
        # audit links.  The requested sort determines which duplicate wins.
        ranked_events = (
            select(
                TopicEvent.id.label("event_id"),
                func.row_number()
                .over(
                    partition_by=(TopicEvent.workspace_id, TopicEvent.normalized_title),
                    order_by=(ordering, TopicEvent.last_update_time.desc(), TopicEvent.id.asc()),
                )
                .label("entity_rank"),
            )
            .where(*conditions)
            .subquery()
        )
        unique_event_ids = ranked_events.c.entity_rank == 1
        items = list(
            (
                await self.session.scalars(
                    select(TopicEvent)
                    .join(ranked_events, TopicEvent.id == ranked_events.c.event_id)
                    .where(unique_event_ids)
                    .order_by(ordering, TopicEvent.id.asc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            (
                await self.session.scalar(
                    select(func.count())
                    .select_from(ranked_events)
                    .where(unique_event_ids)
                )
            )
            or 0
        )
        return items, total

    async def active_scoring_config(self, workspace_id: UUID) -> NewsScoringConfig | None:
        return cast(
            NewsScoringConfig | None,
            await self.session.scalar(
                select(NewsScoringConfig)
                .where(
                    NewsScoringConfig.workspace_id == workspace_id,
                    NewsScoringConfig.is_active.is_(True),
                )
                .order_by(NewsScoringConfig.version.desc())
            ),
        )

    async def run(self, run_id: UUID) -> NewsSyncRun | None:
        return cast(NewsSyncRun | None, await self.session.get(NewsSyncRun, run_id))

    async def active_run(self, lock_key: str) -> NewsSyncRun | None:
        return cast(
            NewsSyncRun | None,
            await self.session.scalar(select(NewsSyncRun).where(NewsSyncRun.lock_key == lock_key)),
        )

    async def list_runs(
        self,
        workspace_id: UUID,
        source_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[NewsSyncRun], int]:
        conditions = (
            NewsSyncRun.workspace_id == workspace_id,
            NewsSyncRun.source_id == source_id,
        )
        items = list(
            (
                await self.session.scalars(
                    select(NewsSyncRun)
                    .where(*conditions)
                    .order_by(NewsSyncRun.queued_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            (
                await self.session.scalar(
                    select(func.count()).select_from(NewsSyncRun).where(*conditions)
                )
            )
            or 0
        )
        return items, total
