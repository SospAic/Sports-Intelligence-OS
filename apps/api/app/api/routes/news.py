from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

import app.services.news as news_module
from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.core.problems import problem_response
from app.repositories.news import ArticleFilters, EventFilters
from app.schemas.news import (
    ArticlePage,
    ArticleRead,
    BookmarkRequest,
    EventMergeRequest,
    EventSort,
    EventSplitRequest,
    ManualArticleCreate,
    NewsScoringConfigRead,
    NewsScoringConfigUpdate,
    NewsSort,
    NewsSyncRequest,
    NewsSyncRunPage,
    NewsSyncRunRead,
    SortOrder,
    SourceCreate,
    SourcePage,
    SourceRead,
    SourceUpdate,
    TopicEventDetail,
    TopicEventPage,
    TopicEventRead,
)
from app.services.news import NewsDispatchError, NewsError, NewsService

router = APIRouter(prefix="/news", tags=["news"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


async def news_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, NewsError):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title="新闻数据请求失败",
        detail=str(exc),
    )


def service(request: Request, db: DatabaseSession) -> NewsService:
    return NewsService(db, request.app.state.news_providers)


@router.post("/sources", response_model=SourceRead, status_code=201)
async def create_source(
    payload: SourceCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> SourceRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(request, db).create_source(workspace.workspace_id, auth.user.id, payload)


@router.get("/sources", response_model=SourcePage)
async def list_sources(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
    enabled: bool | None = None,
) -> SourcePage:
    return await service(request, db).list_sources(
        workspace.workspace_id, page=page, page_size=page_size, enabled=enabled
    )


@router.get("/sources/{source_id}", response_model=SourceRead)
async def get_source(
    source_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
) -> SourceRead:
    return await service(request, db).get_source(workspace.workspace_id, source_id)


@router.patch("/sources/{source_id}", response_model=SourceRead)
async def update_source(
    source_id: UUID,
    payload: SourceUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> SourceRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(request, db).update_source(
        workspace.workspace_id, source_id, auth.user.id, payload
    )


@router.delete("/sources/{source_id}", status_code=204)
async def disable_source(
    source_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> None:
    require_workspace_role(workspace, {"owner", "admin"})
    await service(request, db).disable_source(workspace.workspace_id, source_id, auth.user.id)


@router.post("/sources/{source_id}/sync", response_model=NewsSyncRunRead, status_code=202)
async def sync_source(
    source_id: UUID,
    payload: NewsSyncRequest,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> NewsSyncRunRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    news = service(request, db)
    run, created = await news.request_sync(
        workspace.workspace_id,
        source_id,
        str(request.state.request_id),
        payload,
    )
    if created:
        try:
            news_module.enqueue_news_sync(run.id)
        except Exception as exc:
            await news.mark_dispatch_failure(run.id)
            raise NewsDispatchError("background task broker is unavailable") from exc
    return run


@router.get("/sources/{source_id}/sync-runs", response_model=NewsSyncRunPage)
async def source_sync_runs(
    source_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
) -> NewsSyncRunPage:
    return await service(request, db).list_sync_runs(
        workspace.workspace_id, source_id, page=page, page_size=page_size
    )


@router.post("/articles/manual", response_model=ArticleRead, status_code=201)
async def create_manual_article(
    payload: ManualArticleCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> ArticleRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(request, db).create_manual_article(
        workspace.workspace_id, auth.user.id, payload
    )


@router.get("/articles", response_model=ArticlePage)
async def list_articles(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    sort: NewsSort = "published_at",
    order: SortOrder = "desc",
    page: Page = 1,
    page_size: PageSize = 20,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    sport: str | None = None,
    league: str | None = None,
    source: UUID | None = None,
    language: str | None = None,
    country: str | None = None,
    query: str | None = None,
    is_duplicate: bool | None = None,
    is_bookmarked: bool | None = None,
    min_heat: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_heat: Annotated[float | None, Query(ge=0, le=100)] = None,
) -> ArticlePage:
    return await service(request, db).list_articles(
        workspace.workspace_id,
        filters=ArticleFilters(
            published_from=published_from,
            published_to=published_to,
            sport=sport,
            league=league,
            source=source,
            language=language,
            country=country,
            query=query,
            is_duplicate=is_duplicate,
            is_bookmarked=is_bookmarked,
            min_heat=min_heat,
            max_heat=max_heat,
        ),
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )


@router.get("/articles/{article_id}", response_model=ArticleRead)
async def get_article(
    article_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
) -> ArticleRead:
    return await service(request, db).get_article(workspace.workspace_id, article_id)


@router.get("/events", response_model=TopicEventPage)
async def list_events(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    sort: EventSort = "last_update_time",
    order: SortOrder = "desc",
    page: Page = 1,
    page_size: PageSize = 20,
    updated_from: datetime | None = None,
    updated_to: datetime | None = None,
    sport: str | None = None,
    league: str | None = None,
    language: str | None = None,
    country: str | None = None,
    query: str | None = None,
    is_bookmarked: bool | None = None,
    min_heat: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_heat: Annotated[float | None, Query(ge=0, le=100)] = None,
) -> TopicEventPage:
    return await service(request, db).list_events(
        workspace.workspace_id,
        filters=EventFilters(
            updated_from=updated_from,
            updated_to=updated_to,
            sport=sport,
            league=league,
            language=language,
            country=country,
            query=query,
            is_bookmarked=is_bookmarked,
            min_heat=min_heat,
            max_heat=max_heat,
        ),
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )


@router.get("/events/{event_id}", response_model=TopicEventDetail)
async def get_event(
    event_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
) -> TopicEventDetail:
    return await service(request, db).get_event(workspace.workspace_id, event_id)


@router.post("/events/merge", response_model=TopicEventDetail)
async def merge_events(
    payload: EventMergeRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> TopicEventDetail:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(request, db).merge_events(workspace.workspace_id, auth.user.id, payload)


@router.post("/events/{event_id}/split", response_model=TopicEventDetail)
async def split_event(
    event_id: UUID,
    payload: EventSplitRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> TopicEventDetail:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(request, db).split_event(
        workspace.workspace_id, event_id, auth.user.id, payload
    )


@router.patch("/events/{event_id}/bookmark", response_model=TopicEventRead)
async def bookmark_event(
    event_id: UUID,
    payload: BookmarkRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> TopicEventRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    return await service(request, db).bookmark_event(
        workspace.workspace_id, event_id, auth.user.id, payload.bookmarked
    )


@router.get("/scoring-config", response_model=NewsScoringConfigRead)
async def get_scoring_config(
    workspace: CurrentWorkspace, db: DatabaseSession, request: Request
) -> NewsScoringConfigRead:
    return await service(request, db).scoring_config(workspace.workspace_id)


@router.put("/scoring-config", response_model=NewsScoringConfigRead)
async def update_scoring_config(
    payload: NewsScoringConfigUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> NewsScoringConfigRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await service(request, db).update_scoring_config(
        workspace.workspace_id, auth.user.id, payload
    )
