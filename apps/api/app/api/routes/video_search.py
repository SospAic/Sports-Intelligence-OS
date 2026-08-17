from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.schemas.topics import TopicRead
from app.schemas.video_search import (
    VideoSearchCandidatePage,
    VideoSearchCandidateRead,
    VideoSearchCapabilities,
    VideoSearchPlanCreate,
    VideoSearchPlanPage,
    VideoSearchPlanRead,
    VideoSearchPlanUpdate,
    VideoSearchRunPage,
    VideoSearchRunRead,
    VideoSearchRunResponse,
    VideoSearchSummaryRead,
    VideoSearchSummaryRequest,
    VideoSearchTopicCreate,
)
from app.services.video_content_search import (
    VideoContentSearchService,
    VideoSearchCandidateError,
)

router = APIRouter(prefix="/video-search", tags=["video-search"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def _service(request: Request, db: DatabaseSession) -> VideoContentSearchService:
    return VideoContentSearchService(db, request.app.state.settings)


async def _dispatch_run(run: Any, db: DatabaseSession) -> None:
    from app.tasks.video_search import run_video_search

    try:
        task = run_video_search.delay(str(run.id))
    except Exception as exc:  # noqa: BLE001 - return actionable broker error to the UI
        run.status = "failed"
        run.error_detail = "任务队列不可用：" + str(exc)[:3800]
        await db.flush()
        raise HTTPException(status_code=503, detail="任务队列不可用，视频搜索未能启动") from exc
    run.task_id = task.id
    await db.flush()


@router.get("/capabilities", response_model=VideoSearchCapabilities)
async def get_capabilities(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
) -> VideoSearchCapabilities:
    return VideoSearchCapabilities(**await _service(request, db).capabilities())


@router.get("/plans", response_model=VideoSearchPlanPage)
async def list_plans(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
) -> VideoSearchPlanPage:
    items, total = await _service(request, db).list_plans(
        workspace.workspace_id, page=page, page_size=page_size
    )
    return VideoSearchPlanPage(
        items=[VideoSearchPlanRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/plans", response_model=VideoSearchPlanRead, status_code=201)
async def create_plan(
    payload: VideoSearchPlanCreate,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> VideoSearchPlanRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    service = _service(request, db)
    plan = await service.create_plan(workspace.workspace_id, workspace.auth.user.id, payload)
    if payload.run_now:
        run = await service.create_run(workspace.workspace_id, plan.id)
        if run:
            await _dispatch_run(run, db)
    return VideoSearchPlanRead.model_validate(plan)


@router.patch("/plans/{plan_id}", response_model=VideoSearchPlanRead)
async def update_plan(
    plan_id: UUID,
    payload: VideoSearchPlanUpdate,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> VideoSearchPlanRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    plan = await _service(request, db).update_plan(workspace.workspace_id, plan_id, payload)
    if plan is None:
        raise HTTPException(status_code=404, detail="视频搜索计划不存在")
    return VideoSearchPlanRead.model_validate(plan)


@router.post("/plans/{plan_id}/run", response_model=VideoSearchRunResponse, status_code=202)
async def run_plan(
    plan_id: UUID,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> VideoSearchRunResponse:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    service = _service(request, db)
    run = await service.create_run(workspace.workspace_id, plan_id)
    if run is None:
        raise HTTPException(status_code=404, detail="视频搜索计划不存在")
    was_queued = run.status == "queued" and run.task_id is None
    if was_queued:
        await _dispatch_run(run, db)
    message = "视频内容搜索已提交" if was_queued else "该计划已有运行中的任务"
    return VideoSearchRunResponse(run=VideoSearchRunRead.model_validate(run), message=message)


@router.post("/plans/{plan_id}/stop", response_model=VideoSearchRunRead)
async def stop_plan(
    plan_id: UUID,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> VideoSearchRunRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    run = await _service(request, db).stop_latest_run(workspace.workspace_id, plan_id)
    if run is None:
        raise HTTPException(status_code=404, detail="没有可停止的视频搜索运行")
    return VideoSearchRunRead.model_validate(run)


@router.get("/runs", response_model=VideoSearchRunPage)
async def list_runs(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    plan_id: UUID | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> VideoSearchRunPage:
    items, total = await _service(request, db).list_runs(
        workspace.workspace_id, page=page, page_size=page_size, plan_id=plan_id
    )
    return VideoSearchRunPage(
        items=[VideoSearchRunRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/results", response_model=VideoSearchCandidatePage)
async def list_results(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    plan_id: UUID | None = None,
    status: str = Query(default="matched"),
    platform: str | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> VideoSearchCandidatePage:
    if status not in {"discovered", "analyzing", "matched", "rejected", "unavailable", "failed"}:
        raise HTTPException(status_code=422, detail="不支持的结果状态")
    items, total = await _service(request, db).list_candidates(
        workspace.workspace_id,
        page=page,
        page_size=page_size,
        plan_id=plan_id,
        status=status,
        platform=platform,
    )
    return VideoSearchCandidatePage(
        # Evidence JSON is intentionally returned in full so users can audit timestamps.
        items=[VideoSearchCandidateRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/results/{candidate_id}/topic",
    response_model=TopicRead,
    status_code=201,
)
async def create_topic_from_result(
    candidate_id: UUID,
    payload: VideoSearchTopicCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> TopicRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    try:
        return await _service(request, db).create_topic_from_candidate(
            workspace.workspace_id,
            auth.user.id,
            candidate_id,
            payload,
        )
    except VideoSearchCandidateError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "detail": str(exc)},
        ) from exc


@router.post("/summarize", response_model=VideoSearchSummaryRead)
async def summarize(
    payload: VideoSearchSummaryRequest,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
) -> VideoSearchSummaryRead:
    """Statistical digest + heuristic sentiment/heat for merged search results.

    v1 returns a platform/engine distribution, top items, and a per-item
    sentiment/heat without requiring an LLM gateway. ``llm_summary`` is reserved
    for a future narrative generated by the LLM provider.
    """
    from app.services.video_search_summarize import summarize_results

    return VideoSearchSummaryRead(**summarize_results(payload.model_dump()))
