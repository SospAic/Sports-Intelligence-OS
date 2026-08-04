import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.schemas.trends import (
    CrossPlatformLinkPage,
    CrossPlatformLinkRead,
    DerivativeGenerateRequest,
    DerivativeGenerateResponse,
    DerivativeTopicPage,
    DerivativeTopicRead,
    ScoreExplanation,
    SearchAnalysisRead,
    SearchAnalysisResponse,
    SearchQueryPage,
    SearchQueryRead,
    SearchRequest,
    TrendAggregate,
    TrendDashboard,
    TrendKeywordSnapshotRead,
    TrendTopicPage,
    TrendVideoPage,
)
from app.services.derivative_engine import DerivativeService
from app.services.search_analysis import SearchAnalysisService
from app.services.trends import TrendService

router = APIRouter(prefix="/trends", tags=["trends"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("/dashboard", response_model=TrendDashboard)
async def get_dashboard(
    workspace: CurrentWorkspace, db: DatabaseSession
) -> TrendDashboard:
    return await TrendService(db).get_dashboard(workspace.workspace_id)


@router.get("/stream")
async def stream_dashboard(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    interval: Annotated[float, Query(ge=1.0, le=60.0)] = 5.0,
) -> StreamingResponse:
    """Server-Sent Events stream of the live trend dashboard.

    Pushes the latest :class:`TrendDashboard` snapshot every ``interval``
    seconds so the frontend can refresh without polling. This replaces the
    previously static Recharts view with a real-time feed (STATUS.md known
    limitation: "趋势分析前端使用 Recharts 静态图表，尚未实现实时更新").

    GET is used (not POST) so the browser ``EventSource`` API can subscribe
    without a CSRF header; authentication is enforced via the session cookie
    through ``CurrentWorkspace``. The stream terminates when the client
    disconnects or the request is cancelled.
    """
    service = TrendService(db)

    async def event_generator() -> AsyncIterator[str]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                dashboard = await service.get_dashboard(workspace.workspace_id)
                yield f"data: {dashboard.model_dump_json()}\n\n"
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/topics", response_model=TrendTopicPage)
async def list_topics(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    platform: str | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> TrendTopicPage:
    return await TrendService(db).list_topics(
        workspace.workspace_id,
        platform=platform,
        page=page,
        page_size=page_size,
    )


@router.get("/videos", response_model=TrendVideoPage)
async def list_videos(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    platform: str | None = None,
    sort_by: str = "breakout_score",
    page: Page = 1,
    page_size: PageSize = 20,
) -> TrendVideoPage:
    return await TrendService(db).list_videos(
        workspace.workspace_id,
        platform=platform,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )


@router.get("/keywords", response_model=list[TrendKeywordSnapshotRead])
async def list_keywords(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    keyword: str | None = None,
    platform: str | None = None,
) -> list[TrendKeywordSnapshotRead]:
    return await TrendService(db).list_keywords(
        workspace.workspace_id,
        keyword=keyword,
        platform=platform,
    )


@router.get("/videos/{video_id}/explain", response_model=ScoreExplanation)
async def explain_video(
    video_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> ScoreExplanation:
    """Return the score breakdown for a trend video's breakout_score."""
    return await TrendService(db).explain_video(workspace.workspace_id, video_id)


@router.get("/aggregate", response_model=TrendAggregate)
async def aggregate_trends(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    platforms: str | None = None,
    category: str | None = None,
    days: int = 30,
) -> TrendAggregate:
    """Single/multi-platform + category aggregation for the analytics view.

    ``platforms`` is a comma-separated allow-list (e.g. ``youtube,tiktok``);
    omit for all platforms. ``category`` optionally filters by sport/category.
    """
    plat_list = (
        [p.strip() for p in platforms.split(",") if p.strip()]
        if platforms
        else None
    )
    result = await TrendService(db).aggregate(
        workspace.workspace_id,
        platforms=plat_list,
        category=category,
        days=days,
    )
    return TrendAggregate(**result)


@router.get("/topics/{topic_id}/explain", response_model=ScoreExplanation)
async def explain_topic(
    topic_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> ScoreExplanation:
    """Return the score breakdown for a trend topic's heat_score."""
    return await TrendService(db).explain_topic(workspace.workspace_id, topic_id)


@router.post("/collect", response_model=dict[str, Any], status_code=202)
async def collect_trends(
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
) -> dict[str, Any]:
    """Queue a real trend collection job for the current workspace."""
    require_workspace_role(workspace, {"owner", "admin"})
    from app.tasks.trends import collect_platform_trends

    try:
        task = collect_platform_trends.delay(str(workspace.workspace_id))
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="后台任务 broker 不可用，无法分发趋势采集任务",
        ) from exc
    return {
        "status": "queued",
        "task_id": task.id,
        "message": "trend collection queued",
    }


# ---------------------------------------------------------------------------
# Cross-platform links
# ---------------------------------------------------------------------------


@router.get("/cross-platform-links", response_model=CrossPlatformLinkPage)
async def list_cross_platform_links(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    status: str | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> CrossPlatformLinkPage:
    """List cross-platform same-topic link suggestions."""
    from app.services.cross_platform import CrossPlatformClusterService

    svc = CrossPlatformClusterService(db)
    items, total = await svc.list_links(
        workspace.workspace_id, status=status, page=page, page_size=page_size
    )
    return CrossPlatformLinkPage(
        items=[CrossPlatformLinkRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/cross-platform-links/run", response_model=dict[str, Any], status_code=202)
async def run_cross_platform_clustering(
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
) -> dict[str, Any]:
    """Run cross-platform clustering and generate suggested links."""
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    from app.services.cross_platform import CrossPlatformClusterService

    svc = CrossPlatformClusterService(db)
    new_links = await svc.run_clustering(workspace.workspace_id)
    return {
        "status": "completed",
        "new_suggestions": len(new_links),
        "message": f"跨平台聚类完成，新增 {len(new_links)} 条建议关联",
    }


@router.post("/cross-platform-links/{link_id}/confirm", response_model=CrossPlatformLinkRead)
async def confirm_cross_platform_link(
    link_id: UUID,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
) -> CrossPlatformLinkRead:
    """Confirm a suggested cross-platform link."""
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    from app.services.cross_platform import CrossPlatformClusterService

    svc = CrossPlatformClusterService(db)
    link = await svc.confirm_link(workspace.workspace_id, link_id)
    return CrossPlatformLinkRead.model_validate(link)


@router.post("/cross-platform-links/{link_id}/reject", response_model=CrossPlatformLinkRead)
async def reject_cross_platform_link(
    link_id: UUID,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
) -> CrossPlatformLinkRead:
    """Reject a suggested cross-platform link."""
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    from app.services.cross_platform import CrossPlatformClusterService

    svc = CrossPlatformClusterService(db)
    link = await svc.reject_link(workspace.workspace_id, link_id)
    return CrossPlatformLinkRead.model_validate(link)


# ---------------------------------------------------------------------------
# 衍生话题 (Derivative Topics)
# ---------------------------------------------------------------------------


@router.get("/derivatives", response_model=DerivativeTopicPage)
async def list_derivatives(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    topic_id: UUID | None = None,
    kind: str | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> DerivativeTopicPage:
    """List derivative topics (existing-on-platform + AI-predicted)."""
    svc = DerivativeService(db, request.app.state.llm_providers, request.app.state.settings)
    items, total = await svc.list_derivatives(
        workspace.workspace_id, topic_id=topic_id, kind=kind, page=page, page_size=page_size
    )
    return DerivativeTopicPage(
        items=[DerivativeTopicRead.model_validate(i) for i in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/derivatives/generate", response_model=DerivativeGenerateResponse, status_code=202)
async def generate_derivatives(
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
    payload: DerivativeGenerateRequest,
) -> DerivativeGenerateResponse:
    """Cluster existing derivatives + generate AI-predicted angles for a topic."""
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    svc = DerivativeService(db, request.app.state.llm_providers, request.app.state.settings)
    items, notice = await svc.generate_for_topic(
        workspace.workspace_id, payload.topic_id, workspace.auth.user.id
    )
    return DerivativeGenerateResponse(
        status="completed",
        notice=notice,
        items=[DerivativeTopicRead.model_validate(i) for i in items],
    )


@router.post("/derivatives/{derivative_id}/adopt", response_model=DerivativeTopicRead)
async def adopt_derivative(
    derivative_id: UUID,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> DerivativeTopicRead:
    """Mark a derivative topic as adopted (hand off to creation flow)."""
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    svc = DerivativeService(db, request.app.state.llm_providers, request.app.state.settings)
    item = await svc.adopt(workspace.workspace_id, derivative_id, workspace.auth.user.id)
    return DerivativeTopicRead.model_validate(item)


# ---------------------------------------------------------------------------
# 智能搜索 (Smart Search Analysis)
# ---------------------------------------------------------------------------


@router.post("/search", response_model=SearchAnalysisResponse, status_code=202)
async def run_search(
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
    payload: SearchRequest,
) -> SearchAnalysisResponse:
    """Run a natural-language search across platforms and analyse the results."""
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    svc = SearchAnalysisService(db, request.app.state.llm_providers, request.app.state.settings)
    query, analysis, results, notice = await svc.analyze(
        workspace.workspace_id,
        workspace.auth.user.id,
        payload.query_text,
        payload.platform,
        payload.limit,
    )
    return SearchAnalysisResponse(
        query=SearchQueryRead.model_validate(query),
        analysis=SearchAnalysisRead.model_validate(analysis),
        results=results,
        notice=notice,
    )


@router.get("/search", response_model=SearchQueryPage)
async def list_searches(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
) -> SearchQueryPage:
    """List past smart-search queries for the workspace."""
    svc = SearchAnalysisService(db, request.app.state.llm_providers, request.app.state.settings)
    items, total = await svc.list_queries(workspace.workspace_id, page=page, page_size=page_size)
    return SearchQueryPage(
        items=[SearchQueryRead.model_validate(i) for i in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/search/{query_id}", response_model=SearchAnalysisResponse)
async def get_search(
    query_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
) -> SearchAnalysisResponse:
    """Fetch a single smart-search query + its analysis (with raw results)."""
    svc = SearchAnalysisService(db, request.app.state.llm_providers, request.app.state.settings)
    query, analysis = await svc.get_analysis(workspace.workspace_id, query_id)
    results = analysis.results_json or []
    return SearchAnalysisResponse(
        query=SearchQueryRead.model_validate(query),
        analysis=SearchAnalysisRead.model_validate(analysis),
        results=results,
        notice=None,
    )
