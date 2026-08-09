import json
import logging
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
from app.models.operations import SystemEvent
from app.models.topics import SavedTopic
from app.providers.news.base import (
    NewsArticleData,
    NewsCallContext,
    NewsProvider,
    NewsProviderContractError,
    NewsProviderError,
    NewsProviderTransientError,
)
from app.providers.news.utils import (
    article_hash,
    ensure_public_endpoint,
    normalize_title,
    title_similarity,
)
from app.providers.registry import ProviderRegistry
from app.repositories.news import ArticleFilters, ArticleRow, EventFilters, NewsRepository, Order
from app.schemas.news import (
    ArticlePage,
    ArticleRead,
    ArticleUpdate,
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
from app.services.audit import build_audit_entry, build_external_call_attempt
from app.services.error_detail import business_hint_for

logger = logging.getLogger(__name__)

PROVIDER_BY_SOURCE_TYPE = {
    "rss": "rss",
    "atom": "atom",
    "json": "generic_json",
    "web": "browser_news",
    "manual": "manual_news",
}
DEFAULT_PROVIDER_FALLBACKS = {
    "rss": ("rss", "atom", "generic_json", "browser_news"),
    "atom": ("atom", "rss", "generic_json", "browser_news"),
    "json": ("generic_json", "rss", "atom", "browser_news"),
    "web": ("browser_news", "rss", "atom", "generic_json"),
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
ARTICLE_BODY_SCRAPE_CONFIRMATIONS = (
    "public_access_confirmed",
    "terms_or_license_confirmed",
    "robots_or_permission_confirmed",
    "field_necessity_confirmed",
    "rate_limit_confirmed",
)


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
        include_quarantined: bool = False,
    ) -> SourcePage:
        items, total = await self.repository.list_sources(
            workspace_id,
            page=page,
            page_size=page_size,
            enabled=enabled,
            include_quarantined=include_quarantined,
        )
        source_reads: list[SourceRead] = []
        for item in items:
            active = await self.repository.active_run(f"news_source:{item.id}")
            source_reads.append(
                SourceRead.model_validate(item).model_copy(
                    update={
                        "active_sync_run_id": active.id if active else None,
                        "active_sync_status": active.status if active else None,
                    }
                )
            )
        return SourcePage(
            items=source_reads,
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_source(self, workspace_id: UUID, source_id: UUID) -> SourceRead:
        source = await self.repository.source(workspace_id, source_id)
        if source is None:
            raise NewsNotFoundError("source was not found")
        active = await self.repository.active_run(f"news_source:{source.id}")
        return SourceRead.model_validate(source).model_copy(
            update={
                "active_sync_run_id": active.id if active else None,
                "active_sync_status": active.status if active else None,
            }
        )

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

    async def set_source_enabled(
        self, workspace_id: UUID, source_id: UUID, actor_id: UUID, *, enabled: bool
    ) -> SourceRead:
        source = await self.repository.source(workspace_id, source_id)
        if source is None:
            raise NewsNotFoundError("source was not found")
        source.enabled = enabled
        if enabled:
            source.next_sync_at = datetime.now(UTC)
        else:
            source.next_sync_at = None
        self._audit(
            workspace_id,
            actor_id,
            "news.source.enabled" if enabled else "news.source.disabled",
            "news_source",
            source.id,
            {"enabled": enabled, "articles_preserved": True},
        )
        await self.session.commit()
        await self.session.refresh(source)
        active = await self.repository.active_run(f"news_source:{source.id}")
        return SourceRead.model_validate(source).model_copy(
            update={
                "active_sync_run_id": active.id if active else None,
                "active_sync_status": active.status if active else None,
            }
        )

    async def disable_source(self, workspace_id: UUID, source_id: UUID, actor_id: UUID) -> None:
        await self.set_source_enabled(workspace_id, source_id, actor_id, enabled=False)

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

    async def update_article(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        article_id: UUID,
        payload: ArticleUpdate,
    ) -> ArticleRead:
        row = await self.repository.article(workspace_id, article_id)
        if row is None:
            raise NewsNotFoundError("article was not found")
        article = row[0]
        changes = payload.model_dump(exclude_unset=True)
        if "canonical_url" in changes and changes["canonical_url"]:
            changes["canonical_url"] = str(changes["canonical_url"])
        for field, value in changes.items():
            setattr(article, field, value)
        self._audit(
            workspace_id,
            actor_id,
            "news.article.updated",
            "article",
            article.id,
            {"fields": sorted(payload.model_fields_set)},
        )
        await self.session.flush()
        row = await self.repository.article(workspace_id, article_id)
        return article_read(row)  # type: ignore[arg-type]

    async def delete_article(self, workspace_id: UUID, actor_id: UUID, article_id: UUID) -> None:
        row = await self.repository.article(workspace_id, article_id)
        if row is None:
            raise NewsNotFoundError("article was not found")
        article = row[0]
        self._audit(
            workspace_id,
            actor_id,
            "news.article.deleted",
            "article",
            article.id,
            {"title": article.title},
        )
        # Remove event-article links first
        links = (
            (
                await self.session.execute(
                    select(EventArticle).where(EventArticle.article_id == article.id)
                )
            )
            .scalars()
            .all()
        )
        for link in links:
            await self.session.delete(link)
        await self.session.delete(article)

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

    async def cancel_sync_run(
        self,
        workspace_id: UUID,
        source_id: UUID,
        run_id: UUID,
        actor_id: UUID,
    ) -> NewsSyncRunRead:
        run = await self.repository.run(run_id)
        if run is None or run.workspace_id != workspace_id or run.source_id != source_id:
            raise NewsNotFoundError("news sync run was not found")
        if run.status not in ("queued", "running"):
            return NewsSyncRunRead.model_validate(run)
        now = datetime.now(UTC)
        run.status = "cancelled"
        run.finished_at = now
        run.error_code = "cancelled_by_user"
        run.error_message = "同步任务已由用户停止"
        run.error_detail = run.error_message
        run.error_hint = "已记录停止操作；已获取的历史文章不会删除。"
        run.metadata_json = {**run.metadata_json, "cancelled_by_user": True}
        run.lock_key = None
        self._audit(
            workspace_id,
            actor_id,
            "news.source.sync_cancelled",
            "news_sync_run",
            run.id,
            {"source_id": str(source_id), "status": "cancelled"},
        )
        await self.session.commit()
        try:
            from app.tasks.news import sync_news_source

            sync_news_source.revoke(str(run.id), terminate=True)
        except Exception as exc:  # pragma: no cover - broker may be unavailable in dev/test
            logger.debug("news_sync_revoke_unavailable", exc_info=exc)
        return NewsSyncRunRead.model_validate(run)

    async def execute_sync(self, run_id: UUID) -> None:
        run = await self.repository.run(run_id)
        if run is None:
            raise NewsNotFoundError("news sync run was not found")
        if run.status in ("success", "cancelled"):
            return
        source = await self.repository.source(run.workspace_id, run.source_id)
        if source is None:
            await self._sync_error(run, None, "source_not_found", "source was deleted")
            return
        now = datetime.now(UTC)
        run.status = "running"
        run.started_at = run.started_at or now
        run.error_code = None
        run.error_message = None
        source.last_attempt_at = now
        await self.session.commit()
        ctx = NewsCallContext(
            config=self._provider_config(source), fetched_at=now, request_id=run.request_id
        )
        created = updated = duplicates = 0
        attempt_number = int(run.metadata_json.get("retry_count", 0)) + 1
        strategy_attempts: list[dict[str, Any]] = []
        selected_provider_key: str | None = None
        selected_items: list[NewsArticleData] | None = None
        last_error: NewsProviderError | None = None
        has_retryable_error = False
        for provider_key in self._provider_candidates(source):
            try:
                provider = self.providers.get(provider_key)
            except LookupError:
                continue
            attempt_started = datetime.now(UTC)
            try:
                items = await self._fetch_provider_items(provider, ctx, run)
                if items is None:
                    return
            except NewsProviderError as exc:
                last_error = exc
                has_retryable_error = has_retryable_error or exc.retryable
                strategy_attempts.append(
                    {"provider": provider_key, "status": "failed", "code": exc.code}
                )
                self._record_external_attempt(
                    run,
                    source,
                    attempt_started,
                    attempt_number,
                    provider_key=provider_key,
                    status="failed",
                    error_code=exc.code,
                    error_detail=str(exc),
                    retryable=exc.retryable,
                )
                attempt_number += 1
                continue
            except Exception as raw_exc:  # noqa: BLE001 - try the next acquisition strategy
                exc = NewsProviderTransientError(
                    f"{provider_key} failed unexpectedly: {type(raw_exc).__name__}"
                )
                last_error = exc
                has_retryable_error = True
                strategy_attempts.append(
                    {"provider": provider_key, "status": "failed", "code": exc.code}
                )
                self._record_external_attempt(
                    run,
                    source,
                    attempt_started,
                    attempt_number,
                    provider_key=provider_key,
                    status="failed",
                    error_code=exc.code,
                    error_detail=str(raw_exc),
                    retryable=True,
                )
                attempt_number += 1
                continue
            selected_provider_key = provider_key
            selected_items = items
            strategy_attempts.append(
                {"provider": provider_key, "status": "selected", "items": len(items)}
            )
            self._record_external_attempt(
                run,
                source,
                attempt_started,
                attempt_number,
                provider_key=provider_key,
                status="success",
                response_summary={"items": len(items)},
            )
            break

        run.metadata_json = {
            **run.metadata_json,
            "acquisition_strategy": strategy_attempts,
            "selected_provider": selected_provider_key,
        }
        if selected_items is None:
            exc = last_error or NewsProviderContractError("all news acquisition strategies failed")
            message = "多策略采集均失败：" + "; ".join(
                f"{item['provider']}={item.get('code', 'unknown')}" for item in strategy_attempts
            )
            if has_retryable_error:
                run.status = "queued"
                run.error_code = exc.code
                run.error_message = message[:2000]
                run.error_detail = str(exc)[:2000]
                run.error_hint = business_hint_for(exc.code, category="news_sync")
                run.metadata_json = {
                    **run.metadata_json,
                    "retry_count": int(run.metadata_json.get("retry_count", 0)) + 1,
                }
                source.last_error_code = exc.code
                source.last_error_message = message[:2000]
                self._schedule_source_backoff(source)
                await self.session.commit()
                raise RetryableNewsSyncError(message) from exc
            await self._sync_error(run, source, exc.code, message)
            return

        try:
            for data in selected_items:
                _, was_created, duplicate = await self._ingest(source, data)
                created += int(was_created)
                updated += int(not was_created)
                duplicates += int(duplicate)
        except NewsProviderError as exc:
            await self._sync_error(run, source, exc.code, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - keep already-fetched items durable
            await self._sync_error(run, source, "unexpected_news_sync_error", str(exc))
            return
        await self.session.refresh(run)
        if run.status == "cancelled":
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
        source.consecutive_failures = 0
        await self.session.commit()

    def _provider_candidates(self, source: Source) -> tuple[str, ...]:
        configured = source.config_json.get("acquisition_fallbacks")
        raw = (
            configured
            if isinstance(configured, list)
            else DEFAULT_PROVIDER_FALLBACKS.get(
                source.source_type, (source.provider_key, "browser_news")
            )
        )
        candidates = [source.provider_key, *(str(item) for item in raw)]
        return tuple(dict.fromkeys(candidates))

    async def _fetch_provider_items(
        self, provider: NewsProvider, ctx: NewsCallContext, run: NewsSyncRun
    ) -> list[NewsArticleData] | None:
        await provider.validate_source(ctx.config)
        items: list[NewsArticleData] = []
        cursor: str | None = None
        max_pages = max(1, min(int(ctx.config.get("max_pages", 10)), 50))
        for _ in range(max_pages):
            await self.session.refresh(run)
            if run.status == "cancelled":
                return None
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
            items.extend(page.items)
            if not page.next_cursor:
                break
            cursor = page.next_cursor
        return items

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
            run.error_detail = "Task exceeded its execution lease and was released"
            run.error_hint = business_hint_for("stale_task_recovered", category="news_sync")
            run.lock_key = None
            source = await self.repository.source(run.workspace_id, run.source_id)
            if source is not None:
                source.last_error_code = run.error_code
                source.last_error_message = run.error_message
                self._schedule_source_backoff(source, now=now)
            recovered += 1
        if recovered:
            await self.session.commit()
        return recovered

    async def _sync_error(
        self, run: NewsSyncRun, source: Source | None, code: str, message: str
    ) -> None:
        finished_at = datetime.now(UTC)
        run.status = "error"
        run.finished_at = finished_at
        run.error_code = code
        run.error_message = message[:2000]
        run.error_detail = message[:2000]
        run.error_hint = business_hint_for(code, category="news_sync")
        run.lock_key = None
        if source is not None:
            source.last_error_code = code
            source.last_error_message = message[:2000]
            self._schedule_source_backoff(source, now=finished_at)
            self.session.add(
                SystemEvent(
                    id=uuid4(),
                    workspace_id=source.workspace_id,
                    severity="error",
                    category="news_sync",
                    event_type="news.source.sync_failed",
                    message=f"新闻源「{source.name}」同步失败",
                    resource_type="news_source",
                    resource_id=source.id,
                    status="open",
                    error_code=code,
                    error_detail=message[:2000],
                    error_hint=business_hint_for(code, category="news_sync"),
                    metadata_safe_json={
                        "provider_key": source.provider_key,
                        "error_code": code,
                        "next_sync_at": source.next_sync_at.isoformat()
                        if source.next_sync_at
                        else None,
                    },
                    trace_id=uuid4(),
                    created_at=finished_at,
                )
            )
        await self.session.commit()

    @staticmethod
    def _schedule_source_backoff(source: Source, *, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        source.consecutive_failures += 1
        base = max(300, int(source.config_json.get("sync_interval_seconds", 900)))
        delay = min(21_600, base * (2 ** min(source.consecutive_failures - 1, 6)))
        source.next_sync_at = current + timedelta(seconds=delay)

    def _record_external_attempt(
        self,
        run: NewsSyncRun,
        source: Source,
        started_at: datetime,
        attempt_number: int,
        *,
        provider_key: str | None = None,
        status: str,
        error_code: str | None = None,
        error_detail: str | None = None,
        retryable: bool | None = None,
        response_summary: dict[str, Any] | None = None,
    ) -> None:
        finished_at = datetime.now(UTC)
        self.session.add(
            build_external_call_attempt(
                id=uuid4(),
                workspace_id=run.workspace_id,
                call_type="news_sync",
                provider_key=provider_key or run.provider_key,
                entity_type="news_source",
                entity_id=source.id,
                attempt_number=attempt_number,
                status=status,
                target_url=source.url,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
                http_status=None,
                error_code=error_code,
                error_detail_safe=error_detail[:500] if error_detail else None,
                retryable=retryable,
                request_summary={"run_id": str(run.id), "source_type": source.source_type},
                response_summary=response_summary,
            )
        )

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
        # Full article-page extraction is opt-in because an RSS/Atom URL does not
        # itself grant permission to scrape the linked publisher page.
        if (
            not article.content
            and article.canonical_url
            and self._article_body_scrape_allowed(source.config_json)
        ):
            scraped = await self._scrape_article_body(article.canonical_url)
            if scraped:
                article.content = scraped
                article.metadata_json = {
                    **article.metadata_json,
                    "body_scraped": True,
                    "body_scraped_at": datetime.now(UTC).isoformat(),
                }
        duplicate = await self._classify_duplicate(article, config)
        await self._cluster_article(article, config)
        return article, created, duplicate

    @staticmethod
    def _article_body_scrape_allowed(config: dict[str, Any]) -> bool:
        return config.get("article_body_scrape_enabled") is True and all(
            config.get(field) is True for field in ARTICLE_BODY_SCRAPE_CONFIRMATIONS
        )

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
        # Extract entities for enhanced clustering
        from app.services.entity_extraction import (
            compute_entity_similarity,
            extract_article_entities,
        )

        article_entities = extract_article_entities(article.title, article.summary or "")
        entity_data = [
            {"text": e.text, "type": e.entity_type.value, "confidence": round(e.confidence, 2)}
            for e in article_entities
        ]
        article.metadata_json = {
            **article.metadata_json,
            "extracted_entities": entity_data,
        }

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
        best_components: dict[str, float] = {}
        for event in candidates:
            title_score = title_similarity(event.title, article.title)
            # Entity similarity bonus (0-0.3)
            event_entities_raw = (event.metadata_json or {}).get("extracted_entities", [])
            event_entities = []
            for raw in event_entities_raw:
                from app.services.entity_extraction import EntityType, ExtractedEntity

                try:
                    event_entities.append(
                        ExtractedEntity(
                            text=raw["text"],
                            entity_type=EntityType(raw["type"]),
                            confidence=raw["confidence"],
                        )
                    )
                except (KeyError, ValueError):
                    continue
            entity_score = (
                compute_entity_similarity(article_entities, event_entities)
                if event_entities
                else 0.0
            )
            weighted_score = title_score * 0.65 + entity_score * 0.35
            strong_entity_score = (
                entity_score * 0.85 if entity_score >= 0.7 and title_score >= 0.2 else 0.0
            )
            # Entity enrichment must never reduce a strong title match.  The
            # previous weighted-only formula made a title score of 0.85 fail
            # the default 0.62 threshold whenever entity extraction was empty.
            score = max(title_score, weighted_score, strong_entity_score)
            if score >= threshold and score > best_score:
                best_event = event
                best_score = score
                best_components = {
                    "title": round(title_score, 4),
                    "entity": round(entity_score, 4),
                    "combined": round(score, 4),
                }
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
                metadata_json={
                    "cluster_algorithm": "entity-enhanced-v2",
                    "extracted_entities": entity_data,
                },
                is_bookmarked=False,
                bookmarked_at=None,
            )
            self.session.add(best_event)
            await self.session.flush()
            best_score = 1.0
            best_components = {"title": 1.0, "entity": 1.0, "combined": 1.0}
        article.metadata_json = {
            **article.metadata_json,
            "cluster_match": {
                "algorithm": "entity-enhanced-v2",
                "event_id": str(best_event.id),
                **best_components,
            },
        }
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
        unique_articles = list({item.content_hash: item for item in articles}.values())
        event.article_count = len(articles)
        unique_sources = {item.source_id: item.source for item in articles}
        event.source_count = len(unique_sources)
        reported_times: list[datetime] = []
        for item in unique_articles:
            reported_time = item.event_time or item.published_at
            if reported_time is not None:
                reported_times.append(self._utc(reported_time))
        event.start_time = min(reported_times) if reported_times else None
        event.last_update_time = max(self._utc(item.fetched_at) for item in articles)
        reliabilities = [float(source.reliability_score) for source in unique_sources.values()]
        event.reliability_score = Decimal(str(sum(reliabilities) / len(reliabilities)))

        def metadata_average(key: str) -> float:
            values = [
                float(item.metadata_json.get(key, 0))
                for item in unique_articles
                if isinstance(item.metadata_json.get(key, 0), (int, float))
            ]
            return sum(values) / len(values) if values else 0.0

        event.controversy_score = Decimal(str(metadata_average("controversy_score")))
        event.visual_score = Decimal(str(metadata_average("visual_score")))
        event.story_score = Decimal(str(metadata_average("story_score")))
        freshness_times: list[datetime] = []
        for item in unique_articles:
            candidate_time = item.event_time or item.published_at
            if candidate_time is not None:
                freshness_times.append(self._utc(candidate_time))
        freshness_basis = max(freshness_times) if freshness_times else event.last_update_time
        if freshness_basis is None:
            freshness_basis = datetime.now(UTC)
        freshness_basis_kind = "event_or_published_at" if freshness_times else "fetched_at_fallback"
        age_hours = max(
            0.0, (datetime.now(UTC) - self._utc(freshness_basis)).total_seconds() / 3600
        )
        freshness = math.pow(0.5, age_hours / float(config.freshness_half_life_hours))
        objective_weight = max(
            1.0,
            float(config.source_weight)
            + float(config.freshness_weight)
            + float(config.source_count_weight)
            + float(config.article_count_weight),
        )
        objective = (
            float(config.source_weight) * (float(event.reliability_score) / 100)
            + float(config.freshness_weight) * freshness
            + float(config.source_count_weight)
            * min(event.source_count / SOURCE_COUNT_SATURATION, 1)
            + float(config.article_count_weight)
            * min(len(unique_articles) / ARTICLE_COUNT_SATURATION, 1)
        )
        heat = 100.0 * objective / objective_weight
        recommendation_score = min(
            100.0,
            heat + float(config.user_interest_weight) * int(event.is_bookmarked),
        )
        event.heat_score = Decimal(str(min(100.0, max(0.0, heat))))
        event.metadata_json = {
            **event.metadata_json,
            "heat_algorithm": "objective-weighted-news-heat-v2",
            "scoring_config_version": config.version,
            "freshness_basis": freshness_basis_kind,
            "freshness_timestamp": freshness_basis.isoformat(),
            "recommendation_score": round(recommendation_score, 4),
            "score_availability": {
                key: any(
                    isinstance(item.metadata_json.get(key), (int, float))
                    for item in unique_articles
                )
                for key in ("controversy_score", "visual_score", "story_score")
            },
            "unique_article_count": len(unique_articles),
            "unique_source_count": len(unique_sources),
        }

    async def explain_event(self, workspace_id: UUID, event_id: UUID) -> dict[str, Any]:
        """Return a breakdown of how the heat_score was calculated for an event."""
        event = await self.repository.event(workspace_id, event_id)
        if event is None:
            raise NewsNotFoundError("topic event was not found")

        meta = event.metadata_json or {}
        algorithm = meta.get("heat_algorithm", "objective-weighted-news-heat-v2")
        config_version = meta.get("scoring_config_version")
        freshness_basis = meta.get("freshness_basis")
        freshness_timestamp = meta.get("freshness_timestamp")
        unique_article_count = meta.get("unique_article_count", event.article_count)
        unique_source_count = meta.get("unique_source_count", event.source_count)
        recommendation_score = meta.get("recommendation_score")

        config = await self._scoring_config(workspace_id)
        total_weight = (
            float(config.source_weight)
            + float(config.freshness_weight)
            + float(config.source_count_weight)
            + float(config.article_count_weight)
        )

        # Reconstruct component values from stored data
        source_reliability = float(event.reliability_score) if event.reliability_score else 0.0
        freshness_value = None
        if freshness_timestamp:
            try:
                from datetime import datetime as dt

                ft = dt.fromisoformat(freshness_timestamp)
                age_hours = max(0.0, (datetime.now(UTC) - self._utc(ft)).total_seconds() / 3600)
                import math as _math

                freshness_value = round(
                    _math.pow(0.5, age_hours / float(config.freshness_half_life_hours)), 4
                )
            except (ValueError, TypeError):
                pass

        source_count_ratio = min(event.source_count / SOURCE_COUNT_SATURATION, 1.0)
        article_count_ratio = min((unique_article_count or 0) / ARTICLE_COUNT_SATURATION, 1.0)

        components: list[dict[str, object]] = [
            {
                "name": "来源可靠度",
                "raw_value": round(source_reliability, 2),
                "percentile": None,
                "weight": (
                    round(float(config.source_weight) / total_weight, 4) if total_weight else 0
                ),
                "weighted_contribution": round(
                    float(config.source_weight) * (source_reliability / 100) / total_weight * 100, 2
                )
                if total_weight
                else None,
                "missing": False,
                "note": "工作区对新闻源配置的0-100先验评分",
            },
            {
                "name": "新鲜度",
                "raw_value": freshness_value,
                "percentile": None,
                "weight": (
                    round(float(config.freshness_weight) / total_weight, 4) if total_weight else 0
                ),
                "weighted_contribution": round(
                    float(config.freshness_weight) * (freshness_value or 0) / total_weight * 100, 2
                )
                if total_weight and freshness_value is not None
                else None,
                "missing": freshness_value is None,
                "note": (
                    f"半衰期{config.freshness_half_life_hours}h；基准: {freshness_basis}"
                    if freshness_basis
                    else None
                ),
            },
            {
                "name": "独立来源数",
                "raw_value": float(event.source_count),
                "percentile": None,
                "weight": (
                    round(float(config.source_count_weight) / total_weight, 4)
                    if total_weight
                    else 0
                ),
                "weighted_contribution": round(
                    float(config.source_count_weight) * source_count_ratio / total_weight * 100, 2
                )
                if total_weight
                else None,
                "missing": False,
                "note": (
                    f"饱和值={SOURCE_COUNT_SATURATION}，当前比率={round(source_count_ratio, 2)}"
                ),
            },
            {
                "name": "独立文章数",
                "raw_value": float(unique_article_count or 0),
                "percentile": None,
                "weight": (
                    round(float(config.article_count_weight) / total_weight, 4)
                    if total_weight
                    else 0
                ),
                "weighted_contribution": round(
                    float(config.article_count_weight) * article_count_ratio / total_weight * 100, 2
                )
                if total_weight
                else None,
                "missing": False,
                "note": f"饱和值={ARTICLE_COUNT_SATURATION}，去重后独立内容数",
            },
        ]

        missing_fields = [c["name"] for c in components if c["missing"]]
        confidence = None
        confidence_reason = None
        if event.source_count < 2:
            confidence = 0.4
            confidence_reason = "单来源事件，未交叉验证"
        elif event.source_count < 4:
            confidence = 0.65
            confidence_reason = f"来源数({event.source_count})较少"
        else:
            confidence = 0.85
            confidence_reason = "多来源覆盖"
        if freshness_basis == "fetched_at_fallback":
            confidence = max(0.0, (confidence or 0.5) - 0.15)
            confidence_reason += "；新鲜度降级为抓取时间"

        return {
            "entity_id": str(event.id),
            "entity_type": "topic_event",
            "score_field": "heat_score",
            "score_value": float(event.heat_score),
            "algorithm_version": algorithm,
            "components": components,
            "missing_fields": missing_fields,
            "sample_window": {
                "start": event.start_time.isoformat() if event.start_time else None,
                "end": event.last_update_time.isoformat() if event.last_update_time else None,
                "freshness_basis": freshness_basis,
                "freshness_timestamp": freshness_timestamp,
            },
            "confidence": confidence,
            "confidence_reason": confidence_reason,
            "metadata": {
                "scoring_config_version": config_version,
                "recommendation_score": recommendation_score,
                "unique_article_count": unique_article_count,
                "unique_source_count": unique_source_count,
                "source_count": event.source_count,
                "article_count": event.article_count,
            },
        }

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    async def _scrape_article_body(url: str) -> str | None:
        """Fetch and extract the main article body text from a URL.

        Uses httpx for fetching and BeautifulSoup for parsing.  The content
        extraction applies a readability-like scoring algorithm that evaluates
        candidate container elements based on text density, class/id signals
        and link density.  Returns None on any failure (non-critical).
        """
        import logging
        import re

        _logger = logging.getLogger(__name__)
        try:
            await ensure_public_endpoint(url)

            import httpx
            from bs4 import BeautifulSoup, Tag

            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=False,
                headers={"User-Agent": "SportsIntelligenceOS/1.0 (article-body-extractor)"},
            ) as client:
                response = await client.get(url)
                if response.status_code != 200:
                    return None
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type:
                    return None

            soup = BeautifulSoup(response.text, "html.parser")

            # Phase 1: Remove clearly non-content elements
            _JUNK_TAGS = frozenset(
                {
                    "script",
                    "style",
                    "nav",
                    "header",
                    "footer",
                    "aside",
                    "iframe",
                    "noscript",
                    "form",
                    "button",
                    "input",
                    "select",
                }
            )
            for tag in soup.find_all(_JUNK_TAGS):
                tag.decompose()

            # Also remove elements with strongly negative class/id patterns
            _NEGATIVE_RE = re.compile(
                r"ad[sb]?[-_]?|banner|combx|comment|community|disqus|extra|footer|"
                r"gdpr|header|instapaper_ignore|masthead|media|meta|outbrain|"
                r"promo|related|scroll|share|shoutbox|sidebar|social|sponsor|"
                r"story-below|taboola|tags|toolbar|widget",
                re.IGNORECASE,
            )
            for el in soup.find_all(True):
                if not isinstance(el, Tag):
                    continue
                class_value = el.get("class")
                cls = (
                    " ".join(str(value) for value in class_value)
                    if isinstance(class_value, list)
                    else str(class_value or "")
                )
                id_value = el.get("id")
                eid = id_value if isinstance(id_value, str) else ""
                combined = f"{cls} {eid}"
                if _NEGATIVE_RE.search(combined):
                    el.decompose()

            # Phase 2: Score candidate container elements
            _POSITIVE_RE = re.compile(
                r"article|body|content|entry|main|post|story|text|blog|hentry",
                re.IGNORECASE,
            )
            _PARAGRAPHS_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
            candidates: list[tuple[Tag, float]] = []

            for el in soup.find_all(["div", "section", "article", "main"]):
                if not isinstance(el, Tag):
                    continue
                text = el.get_text(separator="\n", strip=True)
                if len(text) < 100:
                    continue

                score = 0.0

                # Positive class/id signals
                class_value = el.get("class")
                cls = (
                    " ".join(str(value) for value in class_value)
                    if isinstance(class_value, list)
                    else str(class_value or "")
                )
                id_value = el.get("id")
                eid = id_value if isinstance(id_value, str) else ""
                combined = f"{cls} {eid}"
                if _POSITIVE_RE.search(combined):
                    score += 25.0

                # Text density: count paragraphs and their lengths
                inner_html = str(el)
                paragraphs = _PARAGRAPHS_RE.findall(inner_html)
                p_count = len(paragraphs)
                if p_count > 0:
                    avg_p_len = sum(len(p.strip()) for p in paragraphs) / p_count
                    score += min(p_count * 3.0, 30.0)
                    score += min(avg_p_len / 10.0, 10.0)

                # Penalise high link density (navigation-like blocks)
                link_text = " ".join(a.get_text(strip=True) for a in el.find_all("a"))
                if text:
                    link_density = len(link_text) / len(text)
                    if link_density > 0.5:
                        score -= 30.0
                    elif link_density > 0.25:
                        score -= 10.0

                # Bonus for total text length (prefer substantial blocks)
                text_len = len(text)
                if text_len > 500:
                    score += 5.0
                if text_len > 2000:
                    score += 5.0

                candidates.append((el, score))

            if candidates:
                candidates.sort(key=lambda c: c[1], reverse=True)
                target = candidates[0][0]
            else:
                target = soup.find("body") or soup

            # Phase 3: Extract clean text
            text = target.get_text(separator="\n", strip=True)
            # Collapse excessive blank lines
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text[:50_000] if text else None
        except Exception:
            _logger.debug("scrape_article_body_failed", extra={"url": url})
            return None

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        summary: dict[str, Any],
        *,
        status: str = "success",
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        self.session.add(
            build_audit_entry(
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
                status=status,
                error_code=error_code,
                error_detail=error_detail,
            )
        )


def enqueue_news_sync(run_id: UUID) -> None:
    from app.tasks.news import sync_news_source

    sync_news_source.delay(str(run_id))
