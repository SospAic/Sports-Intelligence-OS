import json
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import (
    Article,
    EventArticle,
    NewsScoringConfig,
    NewsSyncRun,
    Source,
    TopicEvent,
)
from app.models.operations import AuditEntry
from app.models.topics import SavedTopic
from app.providers.news.base import (
    NewsArticleData,
    NewsCallContext,
    NewsProvider,
    NewsProviderError,
)
from app.providers.news.utils import article_hash, normalize_title, title_similarity
from app.providers.registry import ProviderRegistry
from app.repositories.news import ArticleFilters, ArticleRow, EventFilters, NewsRepository, Order
from app.schemas.news import (
    ArticlePage,
    ArticleRead,
    EventMergeRequest,
    EventSplitRequest,
    ManualArticleCreate,
    NewsScoringConfigRead,
    NewsScoringConfigUpdate,
    NewsSyncRequest,
    NewsSyncRunPage,
    NewsSyncRunRead,
    SourceCreate,
    SourcePage,
    SourceRead,
    SourceUpdate,
    TopicEventDetail,
    TopicEventPage,
    TopicEventRead,
)

PROVIDER_BY_SOURCE_TYPE = {
    "rss": "rss",
    "atom": "atom",
    "json": "generic_json",
    "manual": "manual_news",
}
SECRET_CONFIG_MARKERS = ("password", "secret", "token", "api_key", "authorization", "cookie")
MAX_CONFIG_BYTES = 65_536
DEFAULT_NEWS_SCORING = {
    "source_weight": "25",
    "freshness_weight": "30",
    "source_count_weight": "20",
    "article_count_weight": "15",
    "user_interest_weight": "10",
    "freshness_half_life_hours": "12",
    "title_similarity_threshold": "0.86",
    "event_similarity_threshold": "0.62",
}
DUPLICATE_LOOKBACK_DAYS = 7
EVENT_LOOKBACK_HOURS = 72
SOURCE_COUNT_SATURATION = 5
ARTICLE_COUNT_SATURATION = 10


class NewsError(Exception):
    code = "news_error"
    status_code = 400


class NewsNotFoundError(NewsError):
    code = "news_resource_not_found"
    status_code = 404


class NewsConflictError(NewsError):
    code = "news_resource_conflict"
    status_code = 409


class NewsValidationError(NewsError):
    code = "news_validation_error"
    status_code = 422


class NewsDispatchError(NewsError):
    code = "news_queue_unavailable"
    status_code = 503


class RetryableNewsSyncError(Exception):
    pass


def validate_source_config(config: dict[str, Any]) -> dict[str, Any]:
    def inspect(value: object, path: str = "config") -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key).casefold()
                if any(marker in normalized for marker in SECRET_CONFIG_MARKERS):
                    raise NewsValidationError(
                        f"{path}.{key} looks like a secret; use a future secret resolver"
                    )
                inspect(nested, f"{path}.{key}")
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                inspect(nested, f"{path}[{index}]")

    inspect(config)
    try:
        encoded = json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise NewsValidationError("source config must contain JSON-compatible values") from exc
    if len(encoded) > MAX_CONFIG_BYTES:
        raise NewsValidationError("source config exceeds 64 KiB")
    return config


def article_read(row: ArticleRow) -> ArticleRead:
    article, event = row
    response = ArticleRead.model_validate(article)
    return response.model_copy(
        update={
            "is_duplicate": article.duplicate_group_id is not None,
            "event_id": event.id if event else None,
            "heat_score": float(event.heat_score) if event else None,
        }
    )


class NewsService:
    def __init__(
        self,
        session: AsyncSession,
        providers: ProviderRegistry[NewsProvider],
    ) -> None:
        self.session = session
        self.repository = NewsRepository(session)
        self.providers = providers

    def _provider_config(self, source: Source) -> dict[str, Any]:
        return {
            **source.config_json,
            "url": source.url,
            "language": source.language,
            "country": source.country,
        }

    async def create_source(
        self, workspace_id: UUID, actor_id: UUID, payload: SourceCreate
    ) -> SourceRead:
        if await self.repository.source_by_name(workspace_id, payload.name) is not None:
            raise NewsConflictError("source name already exists")
        provider_key = PROVIDER_BY_SOURCE_TYPE[payload.source_type]
        provider = self.providers.get(provider_key)
        config = validate_source_config(payload.config)
        provider_config = {
            **config,
            "url": str(payload.url) if payload.url else None,
            "language": payload.language,
            "country": payload.country,
        }
        try:
            await provider.validate_source(provider_config)
        except NewsProviderError as exc:
            raise NewsValidationError(str(exc)) from exc
        source = Source(
            id=uuid4(),
            workspace_id=workspace_id,
            name=payload.name.strip(),
            source_type=payload.source_type,
            url=str(payload.url) if payload.url else None,
            category=payload.category.strip(),
            language=payload.language,
            country=payload.country.upper() if payload.country else None,
            reliability_score=Decimal(str(payload.reliability_score)),
            priority=payload.priority,
            enabled=payload.enabled,
            provider_key=provider_key,
            config_json=config,
            last_synced_at=None,
            next_sync_at=None,
            last_error_code=None,
            last_error_message=None,
        )
        self.session.add(source)
        self._audit(
            workspace_id,
            actor_id,
            "news.source.created",
            "news_source",
            source.id,
            {"provider_key": provider_key, "url": source.url},
        )
        await self.session.commit()
        await self.session.refresh(source)
        return SourceRead.model_validate(source)

    async def list_sources(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        enabled: bool | None,
    ) -> SourcePage:
        items, total = await self.repository.list_sources(
            workspace_id, page=page, page_size=page_size, enabled=enabled
        )
        return SourcePage(
            items=[SourceRead.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_source(self, workspace_id: UUID, source_id: UUID) -> SourceRead:
        source = await self.repository.source(workspace_id, source_id)
        if source is None:
            raise NewsNotFoundError("source was not found")
        return SourceRead.model_validate(source)

    async def update_source(
        self,
        workspace_id: UUID,
        source_id: UUID,
        actor_id: UUID,
        payload: SourceUpdate,
    ) -> SourceRead:
        source = await self.repository.source(workspace_id, source_id)
        if source is None:
            raise NewsNotFoundError("source was not found")
        changes = payload.model_dump(exclude_unset=True)
        if "config" in changes:
            config = changes.pop("config")
            if config is not None:
                source.config_json = validate_source_config(config)
        if "url" in changes:
            source.url = str(changes.pop("url")) if changes["url"] else None
        for key, value in changes.items():
            if value is not None:
                setattr(source, key, value)
        provider = self.providers.get(source.provider_key)
        try:
            await provider.validate_source(self._provider_config(source))
        except NewsProviderError as exc:
            raise NewsValidationError(str(exc)) from exc
        self._audit(
            workspace_id,
            actor_id,
            "news.source.updated",
            "news_source",
            source.id,
            {"fields": sorted(payload.model_fields_set)},
        )
        await self.session.commit()
        await self.session.refresh(source)
        return SourceRead.model_validate(source)

    async def disable_source(self, workspace_id: UUID, source_id: UUID, actor_id: UUID) -> None:
        source = await self.repository.source(workspace_id, source_id)
        if source is None:
            raise NewsNotFoundError("source was not found")
        source.enabled = False
        source.next_sync_at = None
        self._audit(
            workspace_id,
            actor_id,
            "news.source.disabled",
            "news_source",
            source.id,
            {"enabled": False, "articles_preserved": True},
        )
        await self.session.commit()

    async def list_articles(
        self,
        workspace_id: UUID,
        *,
        filters: ArticleFilters,
        sort: str,
        order: Order,
        page: int,
        page_size: int,
    ) -> ArticlePage:
        self._validate_article_filters(filters)
        rows, total = await self.repository.list_articles(
            workspace_id,
            filters=filters,
            sort=sort,
            order=order,
            page=page,
            page_size=page_size,
        )
        return ArticlePage(
            items=[article_read(row) for row in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    @staticmethod
    def _validate_article_filters(filters: ArticleFilters) -> None:
        if (
            filters.published_from
            and filters.published_to
            and filters.published_from > filters.published_to
        ):
            raise NewsValidationError("published_from cannot be after published_to")
        if filters.min_heat is not None and filters.max_heat is not None:
            if filters.min_heat > filters.max_heat:
                raise NewsValidationError("min_heat cannot be greater than max_heat")

    async def get_article(self, workspace_id: UUID, article_id: UUID) -> ArticleRead:
        row = await self.repository.article(workspace_id, article_id)
        if row is None:
            raise NewsNotFoundError("article was not found")
        return article_read(row)

    async def create_manual_article(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: ManualArticleCreate,
    ) -> ArticleRead:
        source = await self.repository.source(workspace_id, payload.source_id)
        if source is None or source.source_type != "manual":
            raise NewsValidationError("manual article requires a manual source")
        provider = self.providers.get(source.provider_key)
        now = datetime.now(UTC)
        raw = payload.model_dump(mode="json", exclude={"source_id"})
        ctx = NewsCallContext(
            config=self._provider_config(source), fetched_at=now, request_id=str(uuid4())
        )
        data = await provider.normalize_article(raw, ctx)
        data = NewsArticleData(
            **{
                **data.__dict__,
                "metadata": {
                    **dict(data.metadata),
                    "controversy_score": payload.controversy_score,
                    "visual_score": payload.visual_score,
                    "story_score": payload.story_score,
                },
            }
        )
        article, _, _ = await self._ingest(source, data)
        self._audit(
            workspace_id,
            actor_id,
            "news.article.created_manual",
            "article",
            article.id,
            {"source_kind": "imported", "source_id": str(source.id)},
        )
        await self.session.commit()
        row = await self.repository.article(workspace_id, article.id)
        if row is None:
            raise RuntimeError("manual article could not be reloaded")
        return article_read(row)

    async def list_events(
        self,
        workspace_id: UUID,
        *,
        filters: EventFilters,
        sort: str,
        order: Order,
        page: int,
        page_size: int,
    ) -> TopicEventPage:
        if filters.min_heat is not None and filters.max_heat is not None:
            if filters.min_heat > filters.max_heat:
                raise NewsValidationError("min_heat cannot be greater than max_heat")
        events, total = await self.repository.list_events(
            workspace_id,
            filters=filters,
            sort=sort,
            order=order,
            page=page,
            page_size=page_size,
        )
        return TopicEventPage(
            items=[TopicEventRead.model_validate(item) for item in events],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_event(self, workspace_id: UUID, event_id: UUID) -> TopicEventDetail:
        event = await self.repository.event(workspace_id, event_id)
        if event is None:
            raise NewsNotFoundError("topic event was not found")
        articles = await self.repository.event_articles(event.id)
        base = TopicEventRead.model_validate(event)
        return TopicEventDetail(
            **base.model_dump(),
            articles=[article_read((article, event)) for article in articles],
        )

    async def merge_events(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: EventMergeRequest,
    ) -> TopicEventDetail:
        unique_ids = list(dict.fromkeys(payload.event_ids))
        if len(unique_ids) < 2:
            raise NewsValidationError("at least two distinct events are required")
        events = [await self.repository.event(workspace_id, item) for item in unique_ids]
        if any(item is None for item in events):
            raise NewsNotFoundError("one or more topic events were not found")
        resolved = [item for item in events if item is not None]
        target = resolved[0]
        for source_event in resolved[1:]:
            links = list(
                (
                    await self.session.scalars(
                        select(EventArticle).where(EventArticle.event_id == source_event.id)
                    )
                ).all()
            )
            existing_article_ids = {
                item
                for item in (
                    await self.session.scalars(
                        select(EventArticle.article_id).where(EventArticle.event_id == target.id)
                    )
                ).all()
            }
            for link in links:
                if link.article_id in existing_article_ids:
                    await self.session.delete(link)
                else:
                    link.event_id = target.id
                    link.linked_by = "manual_merge"
            source_event.status = "closed"
            source_event.metadata_json = {
                **source_event.metadata_json,
                "merged_into": str(target.id),
            }
        if payload.title:
            target.title = payload.title
            target.normalized_title = normalize_title(payload.title)
        config = await self._scoring_config(workspace_id)
        await self.session.flush()
        await self._recalculate_event(target, config)
        self._audit(
            workspace_id,
            actor_id,
            "news.event.merged",
            "topic_event",
            target.id,
            {"event_ids": [str(item) for item in unique_ids]},
        )
        await self.session.commit()
        return await self.get_event(workspace_id, target.id)

    async def split_event(
        self,
        workspace_id: UUID,
        event_id: UUID,
        actor_id: UUID,
        payload: EventSplitRequest,
    ) -> TopicEventDetail:
        source_event = await self.repository.event(workspace_id, event_id)
        if source_event is None:
            raise NewsNotFoundError("topic event was not found")
        links = list(
            (
                await self.session.scalars(
                    select(EventArticle).where(
                        EventArticle.event_id == event_id,
                        EventArticle.article_id.in_(payload.article_ids),
                    )
                )
            ).all()
        )
        if len(links) != len(set(payload.article_ids)):
            raise NewsValidationError("all split articles must belong to the source event")
        if source_event.article_count <= len(links):
            raise NewsValidationError("split must leave at least one article in the source event")
        first_article = await self.session.get(Article, links[0].article_id)
        if first_article is None:
            raise NewsNotFoundError("split article was not found")
        now = datetime.now(UTC)
        title = payload.title or first_article.title
        new_event = TopicEvent(
            id=uuid4(),
            workspace_id=workspace_id,
            title=title,
            normalized_title=normalize_title(title),
            summary=first_article.summary,
            sport=first_article.sport,
            league=first_article.league,
            start_time=first_article.event_time or first_article.published_at,
            last_update_time=now,
            article_count=0,
            source_count=0,
            heat_score=Decimal("0"),
            reliability_score=Decimal("0"),
            controversy_score=Decimal("0"),
            visual_score=Decimal("0"),
            story_score=Decimal("0"),
            status="active",
            metadata_json={"created_by": "manual_split", "split_from": str(event_id)},
            is_bookmarked=False,
            bookmarked_at=None,
        )
        self.session.add(new_event)
        await self.session.flush()
        for link in links:
            link.event_id = new_event.id
            link.linked_by = "manual_split"
        config = await self._scoring_config(workspace_id)
        await self.session.flush()
        await self._recalculate_event(source_event, config)
        await self._recalculate_event(new_event, config)
        self._audit(
            workspace_id,
            actor_id,
            "news.event.split",
            "topic_event",
            new_event.id,
            {
                "split_from": str(event_id),
                "article_ids": [str(item) for item in payload.article_ids],
            },
        )
        await self.session.commit()
        return await self.get_event(workspace_id, new_event.id)

    async def bookmark_event(
        self, workspace_id: UUID, event_id: UUID, actor_id: UUID, bookmarked: bool
    ) -> TopicEventRead:
        event = await self.repository.event(workspace_id, event_id)
        if event is None:
            raise NewsNotFoundError("topic event was not found")
        event.is_bookmarked = bookmarked
        event.bookmarked_at = datetime.now(UTC) if bookmarked else None
        saved_topic = await self.session.scalar(
            select(SavedTopic).where(
                SavedTopic.workspace_id == workspace_id,
                SavedTopic.source_type == "event",
                SavedTopic.source_id == event.id,
            )
        )
        if bookmarked and saved_topic is None:
            saved_topic = SavedTopic(
                id=uuid4(),
                workspace_id=workspace_id,
                created_by=actor_id,
                title=event.title,
                summary=event.summary,
                source_type="event",
                source_id=event.id,
                status="inbox",
                priority=50,
                notes=None,
                metadata_json={"source_kind": "aggregated", "provider": "news_event"},
            )
            self.session.add(saved_topic)
            self._audit(
                workspace_id,
                actor_id,
                "topic.created",
                "saved_topic",
                saved_topic.id,
                {"source_type": "event", "source_id": str(event.id)},
            )
        elif not bookmarked and saved_topic is not None:
            self._audit(
                workspace_id,
                actor_id,
                "topic.deleted",
                "saved_topic",
                saved_topic.id,
                {"source_type": "event", "source_id": str(event.id)},
            )
            await self.session.delete(saved_topic)
        config = await self._scoring_config(workspace_id)
        await self._recalculate_event(event, config)
        self._audit(
            workspace_id,
            actor_id,
            "news.event.bookmark_changed",
            "topic_event",
            event.id,
            {"bookmarked": bookmarked},
        )
        await self.session.commit()
        await self.session.refresh(event)
        return TopicEventRead.model_validate(event)

    async def request_sync(
        self,
        workspace_id: UUID,
        source_id: UUID,
        request_id: str,
        payload: NewsSyncRequest,
    ) -> tuple[NewsSyncRunRead, bool]:
        source = await self.repository.source(workspace_id, source_id)
        if source is None:
            raise NewsNotFoundError("source was not found")
        if not source.enabled:
            raise NewsValidationError("disabled source cannot be synchronized")
        if source.source_type == "manual":
            raise NewsValidationError("manual source cannot be synchronized")
        lock_key = f"news_source:{source.id}"
        active = await self.repository.active_run(lock_key)
        if active is not None:
            return NewsSyncRunRead.model_validate(active), False
        now = datetime.now(UTC)
        run = NewsSyncRun(
            id=uuid4(),
            workspace_id=workspace_id,
            source_id=source.id,
            provider_key=source.provider_key,
            request_id=request_id,
            queued_at=now,
            started_at=None,
            finished_at=None,
            status="queued",
            records_created=0,
            records_updated=0,
            duplicate_count=0,
            error_code=None,
            error_message=None,
            metadata_json={
                "start": payload.start.isoformat() if payload.start else None,
                "end": payload.end.isoformat() if payload.end else None,
                "retry_count": 0,
            },
            lock_key=lock_key,
        )
        self.session.add(run)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            active = await self.repository.active_run(lock_key)
            if active is None:
                raise
            return NewsSyncRunRead.model_validate(active), False
        return NewsSyncRunRead.model_validate(run), True

    async def execute_sync(self, run_id: UUID) -> None:
        run = await self.repository.run(run_id)
        if run is None:
            raise NewsNotFoundError("news sync run was not found")
        if run.status == "success":
            return
        source = await self.repository.source(run.workspace_id, run.source_id)
        if source is None:
            await self._sync_error(run, None, "source_not_found", "source was deleted")
            return
        provider = self.providers.get(run.provider_key)
        now = datetime.now(UTC)
        run.status = "running"
        run.started_at = run.started_at or now
        run.error_code = None
        run.error_message = None
        await self.session.commit()
        ctx = NewsCallContext(
            config=self._provider_config(source), fetched_at=now, request_id=run.request_id
        )
        cursor: str | None = None
        created = updated = duplicates = 0
        try:
            await provider.validate_source(ctx.config)
            for _ in range(int(source.config_json.get("max_pages", 10))):
                start_value = run.metadata_json.get("start")
                end_value = run.metadata_json.get("end")
                if isinstance(start_value, str) and isinstance(end_value, str):
                    page = await provider.fetch_range(
                        ctx,
                        start=datetime.fromisoformat(start_value),
                        end=datetime.fromisoformat(end_value),
                        cursor=cursor,
                        limit=100,
                    )
                else:
                    page = await provider.fetch_latest(ctx, cursor=cursor, limit=100)
                for data in page.items:
                    _, was_created, duplicate = await self._ingest(source, data)
                    created += int(was_created)
                    updated += int(not was_created)
                    duplicates += int(duplicate)
                if not page.next_cursor:
                    break
                cursor = page.next_cursor
        except NewsProviderError as exc:
            if exc.retryable:
                run.status = "queued"
                run.error_code = exc.code
                run.error_message = str(exc)[:2000]
                run.metadata_json = {
                    **run.metadata_json,
                    "retry_count": int(run.metadata_json.get("retry_count", 0)) + 1,
                }
                source.last_error_code = exc.code
                source.last_error_message = str(exc)[:2000]
                await self.session.commit()
                raise RetryableNewsSyncError(str(exc)) from exc
            await self._sync_error(run, source, exc.code, str(exc))
            return
        finished = datetime.now(UTC)
        run.status = "success"
        run.finished_at = finished
        run.records_created = created
        run.records_updated = updated
        run.duplicate_count = duplicates
        run.lock_key = None
        source.last_synced_at = finished
        source.next_sync_at = finished + timedelta(
            seconds=int(source.config_json.get("sync_interval_seconds", 900))
        )
        source.last_error_code = None
        source.last_error_message = None
        await self.session.commit()

    async def mark_retry_exhausted(self, run_id: UUID, message: str) -> None:
        run = await self.repository.run(run_id)
        if run is None:
            return
        source = await self.repository.source(run.workspace_id, run.source_id)
        await self._sync_error(run, source, "retry_exhausted", message)

    async def mark_dispatch_failure(self, run_id: UUID) -> None:
        run = await self.repository.run(run_id)
        if run is None:
            return
        source = await self.repository.source(run.workspace_id, run.source_id)
        await self._sync_error(
            run, source, "queue_dispatch_failed", "Background task broker is unavailable"
        )

    async def recover_stale_syncs(self, stale_before: datetime) -> int:
        runs = list(
            (
                await self.session.scalars(
                    select(NewsSyncRun)
                    .where(
                        NewsSyncRun.lock_key.is_not(None),
                        NewsSyncRun.status.in_(("queued", "running")),
                    )
                    .limit(500)
                )
            ).all()
        )
        recovered = 0
        now = datetime.now(UTC)
        for run in runs:
            last_active = run.started_at or run.queued_at
            if self._utc(last_active) >= self._utc(stale_before):
                continue
            run.status = "error"
            run.finished_at = now
            run.error_code = "stale_task_recovered"
            run.error_message = "Task exceeded its execution lease and was released"
            run.lock_key = None
            source = await self.repository.source(run.workspace_id, run.source_id)
            if source is not None:
                source.last_error_code = run.error_code
                source.last_error_message = run.error_message
                source.next_sync_at = now
            recovered += 1
        if recovered:
            await self.session.commit()
        return recovered

    async def _sync_error(
        self, run: NewsSyncRun, source: Source | None, code: str, message: str
    ) -> None:
        run.status = "error"
        run.finished_at = datetime.now(UTC)
        run.error_code = code
        run.error_message = message[:2000]
        run.lock_key = None
        if source is not None:
            source.last_error_code = code
            source.last_error_message = message[:2000]
        await self.session.commit()

    async def list_sync_runs(
        self,
        workspace_id: UUID,
        source_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> NewsSyncRunPage:
        if await self.repository.source(workspace_id, source_id) is None:
            raise NewsNotFoundError("source was not found")
        runs, total = await self.repository.list_runs(
            workspace_id, source_id, page=page, page_size=page_size
        )
        return NewsSyncRunPage(
            items=[NewsSyncRunRead.model_validate(item) for item in runs],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def scoring_config(self, workspace_id: UUID) -> NewsScoringConfigRead:
        return NewsScoringConfigRead.model_validate(await self._scoring_config(workspace_id))

    async def update_scoring_config(
        self, workspace_id: UUID, actor_id: UUID, payload: NewsScoringConfigUpdate
    ) -> NewsScoringConfigRead:
        current = await self._scoring_config(workspace_id)
        current.is_active = False
        config = NewsScoringConfig(
            id=uuid4(),
            workspace_id=workspace_id,
            version=current.version + 1,
            is_active=True,
            **{key: Decimal(str(value)) for key, value in payload.model_dump().items()},
        )
        self.session.add(config)
        events = list(
            (
                await self.session.scalars(
                    select(TopicEvent).where(TopicEvent.workspace_id == workspace_id)
                )
            ).all()
        )
        for event in events:
            await self._recalculate_event(event, config)
        self._audit(
            workspace_id,
            actor_id,
            "news.scoring_config.updated",
            "news_scoring_config",
            config.id,
            {"version": config.version},
        )
        await self.session.commit()
        return NewsScoringConfigRead.model_validate(config)

    async def _scoring_config(self, workspace_id: UUID) -> NewsScoringConfig:
        config = await self.repository.active_scoring_config(workspace_id)
        if config is not None:
            return config
        config = NewsScoringConfig(
            id=uuid4(),
            workspace_id=workspace_id,
            version=1,
            is_active=True,
            **{key: Decimal(value) for key, value in DEFAULT_NEWS_SCORING.items()},
        )
        self.session.add(config)
        await self.session.flush()
        return config

    async def _ingest(self, source: Source, data: NewsArticleData) -> tuple[Article, bool, bool]:
        config = await self._scoring_config(source.workspace_id)
        hash_value = article_hash(data.title, data.canonical_url, data.summary)
        existing = await self.repository.article_by_external(source.id, data.external_id)
        created = existing is None
        if existing is None:
            article = Article(
                id=uuid4(),
                workspace_id=source.workspace_id,
                source_id=source.id,
                external_id=data.external_id,
                canonical_url=data.canonical_url,
                title=data.title,
                summary=data.summary,
                content=data.content,
                author=data.author,
                published_at=data.published_at,
                event_time=data.event_time,
                fetched_at=data.fetched_at,
                language=data.language or source.language,
                sport=data.sport,
                league=data.league,
                country=data.country or source.country,
                metadata_json=dict(data.metadata),
                content_hash=hash_value,
                duplicate_group_id=None,
                is_bookmarked=False,
                source_kind=data.source_kind,
                source_provider=data.provider,
                source_url=data.canonical_url,
                raw_payload_ref=None,
            )
            self.session.add(article)
        else:
            article = existing
            article.canonical_url = data.canonical_url
            article.title = data.title
            article.summary = data.summary
            article.content = data.content
            article.author = data.author
            article.published_at = data.published_at
            article.event_time = data.event_time
            article.fetched_at = data.fetched_at
            article.language = data.language or source.language
            article.sport = data.sport
            article.league = data.league
            article.country = data.country or source.country
            article.metadata_json = {**article.metadata_json, **dict(data.metadata)}
            article.content_hash = hash_value
            article.source_kind = data.source_kind
            article.source_provider = data.provider
            article.source_url = data.canonical_url
        await self.session.flush()
        duplicate = await self._classify_duplicate(article, config)
        await self._cluster_article(article, config)
        return article, created, duplicate

    async def _classify_duplicate(self, article: Article, config: NewsScoringConfig) -> bool:
        candidates = await self.repository.duplicate_candidates(
            article.workspace_id,
            content_hash=article.content_hash,
            canonical_url=article.canonical_url,
            published_after=(article.published_at or article.fetched_at)
            - timedelta(days=DUPLICATE_LOOKBACK_DAYS),
        )
        threshold = float(config.title_similarity_threshold)
        best: Article | None = None
        best_score = 0.0
        for candidate in candidates:
            if candidate.id == article.id:
                continue
            exact = (
                candidate.content_hash == article.content_hash
                or candidate.canonical_url == article.canonical_url
            )
            score = 1.0 if exact else title_similarity(candidate.title, article.title)
            if score >= threshold and score > best_score:
                best = candidate
                best_score = score
        if best is None:
            article.duplicate_group_id = None
            return False
        group_id = best.duplicate_group_id or uuid4()
        best.duplicate_group_id = group_id
        article.duplicate_group_id = group_id
        article.metadata_json = {**article.metadata_json, "duplicate_match_score": best_score}
        return True

    async def _cluster_article(self, article: Article, config: NewsScoringConfig) -> TopicEvent:
        current_link = await self.session.scalar(
            select(EventArticle).where(EventArticle.article_id == article.id)
        )
        if current_link is not None:
            event = await self.session.get(TopicEvent, current_link.event_id)
            if event is None:
                raise RuntimeError("event link points to a missing event")
            await self._recalculate_event(event, config)
            return event
        candidates = await self.repository.candidate_events(
            article.workspace_id,
            updated_after=article.fetched_at - timedelta(hours=EVENT_LOOKBACK_HOURS),
            sport=article.sport,
        )
        threshold = float(config.event_similarity_threshold)
        best_event: TopicEvent | None = None
        best_score = 0.0
        for event in candidates:
            score = title_similarity(event.title, article.title)
            if score >= threshold and score > best_score:
                best_event = event
                best_score = score
        if best_event is None:
            best_event = TopicEvent(
                id=uuid4(),
                workspace_id=article.workspace_id,
                title=article.title,
                normalized_title=normalize_title(article.title),
                summary=article.summary,
                sport=article.sport,
                league=article.league,
                start_time=article.event_time or article.published_at,
                last_update_time=article.fetched_at,
                article_count=0,
                source_count=0,
                heat_score=Decimal("0"),
                reliability_score=Decimal("0"),
                controversy_score=Decimal("0"),
                visual_score=Decimal("0"),
                story_score=Decimal("0"),
                status="active",
                metadata_json={"cluster_algorithm": "title-similarity-v1"},
                is_bookmarked=False,
                bookmarked_at=None,
            )
            self.session.add(best_event)
            await self.session.flush()
            best_score = 1.0
        self.session.add(
            EventArticle(
                id=uuid4(),
                event_id=best_event.id,
                article_id=article.id,
                match_score=Decimal(str(best_score)),
                linked_by="automatic",
                created_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        await self._recalculate_event(best_event, config)
        return best_event

    async def _recalculate_event(self, event: TopicEvent, config: NewsScoringConfig) -> None:
        articles = await self.repository.event_articles(event.id)
        if not articles:
            event.article_count = 0
            event.source_count = 0
            event.heat_score = Decimal("0")
            return
        event.article_count = len(articles)
        event.source_count = len({item.source_id for item in articles})
        reported_times: list[datetime] = []
        for item in articles:
            reported_time = item.event_time or item.published_at
            if reported_time is not None:
                reported_times.append(self._utc(reported_time))
        event.start_time = min(reported_times) if reported_times else None
        event.last_update_time = max(self._utc(item.fetched_at) for item in articles)
        reliabilities = [float(item.source.reliability_score) for item in articles]
        event.reliability_score = Decimal(str(sum(reliabilities) / len(reliabilities)))

        def metadata_average(key: str) -> float:
            values = [
                float(item.metadata_json.get(key, 0))
                for item in articles
                if isinstance(item.metadata_json.get(key, 0), (int, float))
            ]
            return sum(values) / len(values) if values else 0.0

        event.controversy_score = Decimal(str(metadata_average("controversy_score")))
        event.visual_score = Decimal(str(metadata_average("visual_score")))
        event.story_score = Decimal(str(metadata_average("story_score")))
        age_hours = max(
            0.0, (datetime.now(UTC) - self._utc(event.last_update_time)).total_seconds() / 3600
        )
        freshness = math.pow(0.5, age_hours / float(config.freshness_half_life_hours))
        heat = (
            float(config.source_weight) * (float(event.reliability_score) / 100)
            + float(config.freshness_weight) * freshness
            + float(config.source_count_weight)
            * min(event.source_count / SOURCE_COUNT_SATURATION, 1)
            + float(config.article_count_weight)
            * min(event.article_count / ARTICLE_COUNT_SATURATION, 1)
            + float(config.user_interest_weight) * int(event.is_bookmarked)
        )
        event.heat_score = Decimal(str(min(100.0, max(0.0, heat))))
        event.metadata_json = {
            **event.metadata_json,
            "heat_algorithm": "weighted-news-heat-v1",
            "scoring_config_version": config.version,
            "freshness_basis": "last_fetched_update",
        }

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        summary: dict[str, Any],
    ) -> None:
        self.session.add(
            AuditEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                before_hash=None,
                after_hash=None,
                change_summary_json=summary,
                reason="news management operation",
                ip_hash=None,
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )


def enqueue_news_sync(run_id: UUID) -> None:
    from app.tasks.news import sync_news_source

    sync_news_source.delay(str(run_id))
