"""Local semantic / hybrid search over archived content.

这条链路完全不经过 LLM：查询走本地 embedding 服务转成向量，在 pgvector 里比
余弦距离，再和关键词召回做 RRF 融合。LLM 只在用户另行要求"总结命中结果"时才
介入，属于可选后置步骤。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.schemas.report_export import ReportExportRequest, ReportExportResponse
from app.schemas.semantic_search import (
    ReindexRequest,
    ReindexResponse,
    ScoreBreakdown,
    SemanticSearchChunk,
    SemanticSearchHit,
    SemanticSearchRequest,
    SemanticSearchResponse,
    SemanticSearchStatus,
)
from app.services.report_export import build_report
from app.services.semantic_search import (
    ChunkHit,
    ItemHit,
    SemanticSearchDisabledError,
    SemanticSearchService,
)

router = APIRouter(prefix="/semantic-search", tags=["semantic-search"])


def _service(request: Request, db: DatabaseSession) -> SemanticSearchService:
    return SemanticSearchService(db, request.app.state.settings)


def _breakdown(chunk: ChunkHit) -> ScoreBreakdown | None:
    if chunk.breakdown is None:
        return None
    return ScoreBreakdown(
        vector_score=chunk.breakdown.vector_score,
        keyword_score=chunk.breakdown.keyword_score,
        rrf_score=chunk.breakdown.rrf_score,
        rerank_score=chunk.breakdown.rerank_score,
        explanation=chunk.breakdown.explanation,
    )


def _serialise(hit: ItemHit) -> SemanticSearchHit:
    chunks = [
        SemanticSearchChunk(
            chunk_kind=chunk.chunk_kind,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            start_ms=chunk.start_ms,
            end_ms=chunk.end_ms,
            source_ref=chunk.source_ref,
            distance=chunk.distance,
            score=chunk.score,
            matched_by=list(chunk.matched_by),
            score_breakdown=_breakdown(chunk),
        )
        for chunk in hit.chunks
    ]
    item = hit.item
    return SemanticSearchHit(
        content_item_id=item.id,
        title=item.title,
        canonical_url=item.canonical_url,
        cover_url=item.cover_url,
        platform_id=item.platform_id,
        account_id=item.account_id,
        published_at=item.published_at,
        duration_seconds=(
            float(item.duration_seconds) if item.duration_seconds is not None else None
        ),
        score=hit.score,
        best_chunk=chunks[0],
        chunks=chunks,
        score_breakdown=chunks[0].score_breakdown,
    )


@router.get("/status", response_model=SemanticSearchStatus)
async def get_status(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
) -> SemanticSearchStatus:
    payload = await _service(request, db).status(workspace.workspace_id)
    return SemanticSearchStatus(**payload)


@router.post("/query", response_model=SemanticSearchResponse)
async def run_search(
    payload: SemanticSearchRequest,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
) -> SemanticSearchResponse:
    service = _service(request, db)
    try:
        result: dict[str, Any] = await service.search(
            workspace.workspace_id,
            query=payload.query,
            mode=payload.mode,
            limit=payload.limit,
            candidates=payload.candidates,
            chunk_kinds=payload.chunk_kinds,
            platform_ids=payload.platform_ids,
            account_ids=payload.account_ids,
            published_after=payload.published_after,
            published_before=payload.published_before,
            debug=payload.debug,
        )
    except SemanticSearchDisabledError as exc:
        raise HTTPException(
            status_code=501,
            detail={"code": "semantic_search_disabled", "detail": str(exc)},
        ) from exc

    return SemanticSearchResponse(
        query=result["query"],
        mode_requested=result["mode_requested"],
        mode_used=result["mode_used"],
        degraded=result["degraded"],
        model=result["model"],
        total=result["total"],
        items=[_serialise(hit) for hit in result["items"]],
        took_ms=result["took_ms"],
    )


@router.post("/export", response_model=ReportExportResponse)
async def export_report(
    payload: ReportExportRequest,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
) -> ReportExportResponse:
    """Render the merged search results into a downloadable report.

    The caller posts the results it is currently showing, so the report always
    matches the on-screen state (filters included). Rendering happens here so
    the Markdown download and the browser's print-to-PDF share one layout.
    """
    return ReportExportResponse(**build_report(payload.model_dump()))


@router.post("/reindex", response_model=ReindexResponse, status_code=202)
async def trigger_reindex(
    payload: ReindexRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> ReindexResponse:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    service = _service(request, db)
    if not service.embedder.enabled:
        raise HTTPException(
            status_code=501,
            detail={
                "code": "embedding_backend_disabled",
                "detail": "未配置 embedding 后端，请设置 SIO_EMBEDDING_BACKEND",
            },
        )

    from app.tasks.embedding import backfill_content_embeddings

    try:
        task = backfill_content_embeddings.delay(
            str(workspace.workspace_id), payload.limit, payload.reindex
        )
    except Exception as exc:  # noqa: BLE001 - surface broker outage to the UI
        raise HTTPException(status_code=503, detail="任务队列不可用，索引任务未能启动") from exc

    return ReindexResponse(task_id=str(task.id), limit=payload.limit, reindex=payload.reindex)
