import json
from collections.abc import AsyncIterator
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

import app.services.generation as generation_module
from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.core.problems import problem_response
from app.schemas.generation import (
    GenerationCreate,
    GenerationDecisionUpdate,
    GenerationRewriteRequest,
    GenerationRunPage,
    GenerationRunRead,
    PromptCollectionCreate,
    PromptCollectionDetail,
    PromptCollectionPage,
    PromptCollectionRead,
    PromptPreviewRead,
    PromptVersionCreate,
    PromptVersionRead,
    PromptVersionUpdate,
    ProviderDescriptor,
    StreamPreviewRequest,
    WorkflowRead,
)
from app.services.generation import GenerationError, GenerationService

router = APIRouter(tags=["generation"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


async def generation_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, GenerationError):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title="内容生成请求失败",
        detail=str(exc),
    )


def service(request: Request, db: DatabaseSession) -> GenerationService:
    return GenerationService(db, request.app.state.llm_providers, request.app.state.settings)


@router.get("/llm/providers", response_model=list[ProviderDescriptor])
async def list_llm_providers(
    workspace: CurrentWorkspace, db: DatabaseSession, request: Request
) -> list[ProviderDescriptor]:
    return await service(request, db).provider_descriptors(workspace.workspace_id)


@router.get("/prompts", response_model=PromptCollectionPage)
async def list_prompt_collections(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
) -> PromptCollectionPage:
    return await service(request, db).list_prompts(
        workspace.workspace_id, page=page, page_size=page_size
    )


@router.post("/prompts", response_model=PromptCollectionRead, status_code=201)
async def create_prompt_collection(
    payload: PromptCollectionCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> PromptCollectionRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(request, db).create_prompt_collection(
        workspace.workspace_id, auth.user.id, payload
    )


@router.get("/prompts/{collection_id}", response_model=PromptCollectionDetail)
async def get_prompt_collection(
    collection_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
) -> PromptCollectionDetail:
    return await service(request, db).prompt_detail(workspace.workspace_id, collection_id)


@router.post("/prompts/{collection_id}/versions", response_model=PromptVersionRead, status_code=201)
async def create_prompt_version(
    collection_id: UUID,
    payload: PromptVersionCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> PromptVersionRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(request, db).create_prompt_version(
        workspace.workspace_id, collection_id, auth.user.id, payload
    )


@router.get("/prompts/{collection_id}/versions/{version_id}", response_model=PromptVersionRead)
async def get_prompt_version(
    collection_id: UUID,
    version_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
) -> PromptVersionRead:
    return await service(request, db).prompt_version(
        workspace.workspace_id, collection_id, version_id
    )


@router.patch("/prompts/{collection_id}/versions/{version_id}", response_model=PromptVersionRead)
async def update_prompt_version(
    collection_id: UUID,
    version_id: UUID,
    payload: PromptVersionUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> PromptVersionRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(request, db).update_prompt_version(
        workspace.workspace_id, collection_id, version_id, auth.user.id, payload
    )


@router.post(
    "/prompts/{collection_id}/versions/{version_id}/publish", response_model=PromptVersionRead
)
async def publish_prompt_version(
    collection_id: UUID,
    version_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> PromptVersionRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await service(request, db).publish_prompt(
        workspace.workspace_id, collection_id, version_id, auth.user.id
    )


@router.post(
    "/prompts/{collection_id}/versions/{version_id}/rollback", response_model=PromptVersionRead
)
async def rollback_prompt_version(
    collection_id: UUID,
    version_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> PromptVersionRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await service(request, db).rollback_prompt(
        workspace.workspace_id, collection_id, version_id, auth.user.id
    )


@router.get("/workflows", response_model=list[WorkflowRead])
async def list_workflows(
    workspace: CurrentWorkspace, db: DatabaseSession, request: Request
) -> list[WorkflowRead]:
    return await service(request, db).workflows(workspace.workspace_id)


@router.get("/workflows/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(
    workflow_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
) -> WorkflowRead:
    return await service(request, db).workflow(workspace.workspace_id, workflow_id)


@router.post("/generations/preview", response_model=PromptPreviewRead)
async def preview_generation_prompt(
    payload: GenerationCreate,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> PromptPreviewRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    return await service(request, db).preview(workspace.workspace_id, payload)


@router.post("/generations/stream-preview")
async def stream_preview(
    payload: StreamPreviewRequest,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> StreamingResponse:
    """Stream LLM tokens via Server-Sent Events for prompt testing.

    Accepts a system prompt, user prompt, and model parameters, then streams
    the LLM response token-by-token.  Falls back to non-streaming generate()
    if the active provider does not support streaming.
    """
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    svc = service(request, db)
    try:
        provider = await svc._provider(workspace.workspace_id, payload.provider_key)
    except (GenerationError, LookupError):
        provider = svc.providers.get(payload.provider_key)
    if provider is None:
        raise GenerationError(
            f"未知的 LLM provider: {payload.provider_key}",
            code="provider_not_found",
            status_code=404,
        )

    from app.providers.llm.base import LLMMessage, LLMRequest

    llm_request = LLMRequest(
        model=payload.model,
        messages=(
            LLMMessage(role="system", content=payload.system_prompt),
            LLMMessage(role="user", content=payload.user_prompt),
        ),
        parameters=payload.model_params,
        response_schema=None,
        timeout_seconds=float(payload.model_params.get("timeout_seconds", 120)),
        idempotency_key=f"stream-preview:{uuid4()}",
    )

    async def event_generator() -> AsyncIterator[str]:
        try:
            if provider.supports_streaming:
                async for token in provider.stream(llm_request):
                    yield f"data: {json.dumps({'token': token})}\n\n"
            else:
                response = await provider.generate(llm_request)
                content = (
                    response.content
                    if isinstance(response.content, str)
                    else json.dumps(response.content, ensure_ascii=False)
                )
                yield f"data: {json.dumps({'token': content})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/generations", response_model=GenerationRunRead, status_code=202)
async def create_generation(
    payload: GenerationCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> GenerationRunRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    generation = service(request, db)
    run, created = await generation.create_run(
        workspace.workspace_id,
        auth.user.id,
        payload,
        (idempotency_key or str(uuid4()))[:255],
    )
    if created:
        try:
            generation_module.enqueue_generation(run.id)
        except Exception as exc:
            await generation.mark_dispatch_failure(workspace.workspace_id, run.id)
            raise GenerationError(
                "后台生成任务分发失败", code="generation_dispatch_failed", status_code=503
            ) from exc
    return run


@router.get("/generations", response_model=GenerationRunPage)
async def list_generations(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
    status: Literal["queued", "running", "completed", "failed", "cancelled"] | None = None,
) -> GenerationRunPage:
    return await service(request, db).list_runs(
        workspace.workspace_id, page=page, page_size=page_size, status=status
    )


@router.get("/generations/{run_id}", response_model=GenerationRunRead)
async def get_generation(
    run_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
) -> GenerationRunRead:
    return await service(request, db).get_run(workspace.workspace_id, run_id)


@router.post("/generations/{run_id}/retry", response_model=GenerationRunRead, status_code=202)
async def retry_generation(
    run_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> GenerationRunRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    generation = service(request, db)
    run = await generation.queue_retry(workspace.workspace_id, run_id, auth.user.id)
    try:
        generation_module.enqueue_generation(run.id)
    except Exception as exc:
        await generation.mark_dispatch_failure(workspace.workspace_id, run.id)
        raise GenerationError(
            "后台生成任务分发失败", code="generation_dispatch_failed", status_code=503
        ) from exc
    return run


@router.post("/generations/{run_id}/rewrite", response_model=GenerationRunRead, status_code=202)
async def rewrite_generation(
    run_id: UUID,
    payload: GenerationRewriteRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> GenerationRunRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    generation = service(request, db)
    run = await generation.clone_for_manual_rewrite(
        workspace.workspace_id, run_id, auth.user.id, payload.instruction
    )
    try:
        generation_module.enqueue_generation(run.id)
    except Exception as exc:
        await generation.mark_dispatch_failure(workspace.workspace_id, run.id)
        raise GenerationError(
            "后台重写任务分发失败", code="generation_dispatch_failed", status_code=503
        ) from exc
    return run


@router.patch("/generations/{run_id}/decision", response_model=GenerationRunRead)
async def update_generation_decision(
    run_id: UUID,
    payload: GenerationDecisionUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> GenerationRunRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    return await service(request, db).update_decision(
        workspace.workspace_id, run_id, auth.user.id, payload
    )


@router.get("/generations/{run_id}/export")
async def export_generation(
    run_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    format: Literal["json", "txt"] = "json",
) -> Response:
    run = await service(request, db).get_run(workspace.workspace_id, run_id)
    if format == "json":
        return JSONResponse(
            content=json.loads(run.model_dump_json(by_alias=True)),
            headers={"Content-Disposition": f'attachment; filename="generation-{run_id}.json"'},
        )
    output = run.final_output or {}
    sections = [
        ("事件事实摘要", output.get("event_fact_summary")),
        ("英文 TTS", output.get("tts_en")),
        ("中文翻译", output.get("translation_zh")),
        ("英文标题", output.get("video_title_en")),
        ("中文标题", output.get("video_title_zh")),
        ("搜索关键词", output.get("search_keywords")),
        ("素材关键词", output.get("material_keywords")),
        ("标签", output.get("tags")),
        ("工程文件名", output.get("project_filename")),
    ]
    content = "\n\n".join(
        f"{title}\n{json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value}"
        for title, value in sections
        if value is not None
    )
    return PlainTextResponse(
        content,
        headers={"Content-Disposition": f'attachment; filename="generation-{run_id}.txt"'},
    )
