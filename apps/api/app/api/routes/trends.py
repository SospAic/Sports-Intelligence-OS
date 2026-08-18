import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.providers.translation.http import TranslationUnavailable
from app.schemas.trends import (
    CrossPlatformLinkPage,
    CrossPlatformLinkRead,
    DerivativeGenerateRequest,
    DerivativeGenerateResponse,
    DerivativeRunDetail,
    DerivativeRunPage,
    DerivativeRunRead,
    DerivativeTopicPage,
    DerivativeTopicRead,
    DerivativeTranslationRequest,
    ScoreExplanation,
    SearchAnalysisRead,
    SearchAnalysisResponse,
    SearchQueryPage,
    SearchQueryRead,
    SearchQuerySaveRequest,
    SearchRequest,
    SearchTranslationRequest,
    SearchTranslationResponse,
    TrendAggregate,
    TrendCategorySummary,
    TrendDashboard,
    TrendKeywordSnapshotRead,
    TrendSportCatalogRead,
    TrendTopicEvidence,
    TrendTopicPage,
    TrendVideoPage,
)
from app.services.derivative_engine import DerivativeService
from app.services.search_analysis import SearchAnalysisService
from app.services.trends import TrendService
from app.tasks.celery_app import celery_app

router = APIRouter(prefix="/trends", tags=["trends"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
WindowHours = Annotated[int, Query(ge=24, le=72)]
AnalyticsDays = Annotated[int, Query(ge=1, le=90)]


@router.get("/dashboard", response_model=TrendDashboard)
async def get_dashboard(
    workspace: CurrentWorkspace, db: DatabaseSession, window_hours: WindowHours = 24
) -> TrendDashboard:
    return await TrendService(db).get_dashboard(
        workspace.workspace_id, window_hours=window_hours
    )


@router.get("/stream")
async def stream_dashboard(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    interval: Annotated[float, Query(ge=1.0, le=60.0)] = 5.0,
    window_hours: WindowHours = 24,
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
                dashboard = await service.get_dashboard(
                    workspace.workspace_id, window_hours=window_hours
                )
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
    category: str | None = None,
    window_hours: WindowHours = 24,
    page: Page = 1,
    page_size: PageSize = 20,
) -> TrendTopicPage:
    return await TrendService(db).list_topics(
        workspace.workspace_id,
        platform=platform,
        category=category,
        window_hours=window_hours,
        page=page,
        page_size=page_size,
    )


@router.get("/videos", response_model=TrendVideoPage)
async def list_videos(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    platform: str | None = None,
    category: str | None = None,
    sort_by: str = "breakout_score",
    window_hours: WindowHours = 24,
    page: Page = 1,
    page_size: PageSize = 20,
) -> TrendVideoPage:
    return await TrendService(db).list_videos(
        workspace.workspace_id,
        platform=platform,
        category=category,
        sort_by=sort_by,
        window_hours=window_hours,
        page=page,
        page_size=page_size,
    )


@router.get("/categories", response_model=list[TrendCategorySummary])
async def list_categories(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    platform: str | None = None,
    window_hours: WindowHours = 24,
) -> list[TrendCategorySummary]:
    """Return categories with real live samples in the current window."""

    return await TrendService(db).list_categories(
        workspace.workspace_id,
        platform=platform,
        window_hours=window_hours,
    )


@router.get("/sports-catalog", response_model=TrendSportCatalogRead)
async def get_sports_catalog(
    request: Request,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    window_hours: WindowHours = 24,
) -> TrendSportCatalogRead:
    """Return the 50 + 30 sport lanes and their real live coverage status."""

    settings = request.app.state.settings
    return await TrendService(db).sports_catalog(
        workspace.workspace_id,
        window_hours=window_hours,
        mainstream_target_items=settings.hotspot_mainstream_target_items,
        general_target_items=settings.hotspot_general_target_items,
    )


@router.get("/keywords", response_model=list[TrendKeywordSnapshotRead])
async def list_keywords(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    keyword: str | None = None,
    platform: str | None = None,
    window_hours: WindowHours = 24,
) -> list[TrendKeywordSnapshotRead]:
    return await TrendService(db).list_keywords(
        workspace.workspace_id,
        keyword=keyword,
        platform=platform,
        window_hours=window_hours,
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
    days: AnalyticsDays = 30,
) -> TrendAggregate:
    """Single/multi-platform + category aggregation for the analytics view.

    ``platforms`` is a comma-separated allow-list (e.g. ``youtube,tiktok``);
    omit for all platforms. ``category`` optionally filters by sport/category.
    """
    plat_list = [p.strip() for p in platforms.split(",") if p.strip()] if platforms else None
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


@router.get("/topics/{topic_id}/evidence", response_model=TrendTopicEvidence)
async def topic_evidence(
    topic_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> TrendTopicEvidence:
    """Return the news links and video samples behind one hotspot topic."""
    return await TrendService(db).topic_evidence(workspace.workspace_id, topic_id)


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


@router.get("/collect/{task_id}", response_model=dict[str, Any])
async def get_collection_status(
    task_id: str,
    workspace: CurrentWorkspace,
) -> dict[str, Any]:
    """Return the bounded live log for one trend collection task."""
    _ = workspace
    result = AsyncResult(task_id, app=celery_app)
    raw_state = str(result.state or "PENDING").upper()
    state_map = {
        "PENDING": "queued",
        "STARTED": "running",
        "PROGRESS": "running",
        "RETRY": "running",
        "SUCCESS": "success",
        "FAILURE": "failed",
        "REVOKED": "cancelled",
    }
    state = state_map.get(raw_state, "running")
    info = result.info if isinstance(result.info, dict) else {}
    task_workspace_id = info.get("workspace_id")
    if task_workspace_id and str(task_workspace_id) != str(workspace.workspace_id):
        raise HTTPException(status_code=404, detail="采集任务不存在")
    payload: dict[str, Any] = {
        "task_id": task_id,
        "state": state,
        "stage": info.get("stage", "queued" if state == "queued" else state),
        "message": info.get("message", "等待后台任务开始执行"),
        "log": info.get("log", []),
        "updated_at": info.get("updated_at"),
    }
    if raw_state == "SUCCESS" and isinstance(result.result, dict):
        completion_meta = result.result.get("_progress")
        if isinstance(completion_meta, dict):
            payload.update(
                {
                    "stage": completion_meta.get("stage", payload["stage"]),
                    "message": completion_meta.get("message", payload["message"]),
                    "log": completion_meta.get("log", payload["log"]),
                    "updated_at": completion_meta.get(
                        "updated_at", payload["updated_at"]
                    ),
                }
            )
        payload["result"] = {
            key: value for key, value in result.result.items() if key != "_progress"
        }
    if raw_state == "FAILURE":
        payload["error"] = str(result.result or "热点情报采集失败")
    return payload


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


def _derivative_detail_response(data: dict[str, Any]) -> DerivativeRunDetail:
    run = DerivativeRunRead.model_validate(data["run"])
    # ``DerivativeRunRead`` exposes the ORM ``process_log_json`` column under
    # the public ``process_log`` field.  Do not pass that field once through
    # ``model_dump`` and again as the canonical value from the service, or
    # Python raises ``got multiple values for keyword argument`` before
    # FastAPI can serialize the detail response.
    run_data = run.model_dump(exclude={"process_log"})
    return DerivativeRunDetail(
        **run_data,
        items=[DerivativeTopicRead.model_validate(item) for item in data["items"]],
        source_results=data["source_results"],
        process_log=data["process_log"],
        language=data.get("language", "en"),
    )


@router.get("/derivatives/runs", response_model=DerivativeRunPage)
async def list_derivative_runs(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
) -> DerivativeRunPage:
    svc = DerivativeService(db, request.app.state.llm_providers, request.app.state.settings)
    items, total = await svc.list_runs(workspace.workspace_id, page=page, page_size=page_size)
    return DerivativeRunPage(
        items=[DerivativeRunRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/derivatives/runs/{run_id}", response_model=DerivativeRunDetail)
async def get_derivative_run(
    run_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
) -> DerivativeRunDetail:
    svc = DerivativeService(db, request.app.state.llm_providers, request.app.state.settings)
    try:
        return _derivative_detail_response(await svc.get_run_detail(workspace.workspace_id, run_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/derivatives/runs/{run_id}/translate", response_model=DerivativeRunDetail)
async def translate_derivative_run(
    run_id: UUID,
    payload: DerivativeTranslationRequest,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> DerivativeRunDetail:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    svc = DerivativeService(db, request.app.state.llm_providers, request.app.state.settings)
    try:
        return _derivative_detail_response(
            await svc.translate_run(workspace.workspace_id, run_id, payload.target_language)
        )
    except (ValueError, TranslationUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
    run_id = next((item.derivative_run_id for item in items if item.derivative_run_id), None)
    if run_id is None:
        latest_run = await svc.latest_run_for_topic(workspace.workspace_id, payload.topic_id)
        run_id = latest_run.id if latest_run else None
    detail = await svc.get_run_detail(workspace.workspace_id, run_id) if run_id else None
    return DerivativeGenerateResponse(
        status="completed",
        notice=notice,
        items=[DerivativeTopicRead.model_validate(i) for i in items],
        run_id=run_id,
        process_log=detail["process_log"] if detail else [],
        source_results=detail["source_results"] if detail else [],
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
    saved_only: bool = False,
) -> SearchQueryPage:
    """List past smart-search queries for the workspace."""
    svc = SearchAnalysisService(db, request.app.state.llm_providers, request.app.state.settings)
    items, total = await svc.list_queries(
        workspace.workspace_id, page=page, page_size=page_size, saved_only=saved_only
    )


    return SearchQueryPage(
        items=[SearchQueryRead.model_validate(i) for i in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.patch("/search/{query_id}/saved", response_model=SearchQueryRead)
async def save_search(
    query_id: UUID,
    payload: SearchQuerySaveRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> SearchQueryRead:
    """Persist a named workspace search without changing its analysis evidence."""
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    svc = SearchAnalysisService(db, request.app.state.llm_providers, request.app.state.settings)
    try:
        query = await svc.save_query(
            workspace.workspace_id,
            auth.user.id,
            query_id,
            is_saved=payload.is_saved,
            saved_name=payload.saved_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SearchQueryRead.model_validate(query)


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
        language="en",
        notice=None,
    )


@router.post("/search/{query_id}/translate", response_model=SearchTranslationResponse)
async def translate_search(
    query_id: UUID,
    payload: SearchTranslationRequest,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> SearchTranslationResponse:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    svc = SearchAnalysisService(db, request.app.state.llm_providers, request.app.state.settings)
    try:
        data = await svc.translate_analysis(
            workspace.workspace_id, query_id, payload.target_language
        )
    except (ValueError, TranslationUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    query = SearchQueryRead.model_validate(data["query"])
    analysis = SearchAnalysisRead.model_validate(data["analysis"])
    if data.get("translated_query_text"):
        query.query_text = str(data["translated_query_text"])
    if data.get("translated_summary") is not None:
        analysis.summary = data["translated_summary"]
    if data.get("process_log") is not None:
        analysis.process_log = data["process_log"]
    return SearchTranslationResponse(
        query=query,
        analysis=analysis,
        results=data.get("results", []),
        language=data.get("language", payload.target_language),
        notice=None,
    )
