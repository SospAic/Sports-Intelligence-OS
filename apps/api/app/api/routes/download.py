"""On-demand video / subtitle download endpoints."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime
from uuid import UUID

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.models.download import Download
from app.schemas.download import (
    DownloadCreate,
    DownloadPage,
    DownloadPreviewCreate,
    DownloadPreviewEnqueue,
    DownloadPreviewPoll,
    DownloadPreviewRead,
    DownloadRead,
    SubtitleExportCreate,
    SubtitlePreviewRead,
    YtDlpRuntimeRead,
)
from app.services.artifact_registry import reconcile_manifest
from app.services.download import DownloadService
from app.services.subtitle_tools import (
    SubtitleExport,
    build_subtitle_export,
    subtitle_preview,
    write_subtitle_export,
)
from app.tasks.celery_app import celery_app
from app.tasks.monitoring import preview_download_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/downloads", tags=["downloads"])


def _runtime_read(status: object) -> YtDlpRuntimeRead:
    from app.services.ytdlp_runtime import YtDlpRuntimeStatus

    if not isinstance(status, YtDlpRuntimeStatus):
        raise TypeError("invalid yt-dlp runtime status")
    ready = status.node_available and bool(status.yt_dlp_version)
    detail = (
        "Node.js 与 yt-dlp[default] 已就绪"
        if ready
        else "Node.js 未就绪；非 YouTube 解析仍可运行，但 YouTube 可能缺少完整格式"
    )
    return YtDlpRuntimeRead(
        **status.model_dump(),
        status="ready" if ready else "degraded",
        detail=detail,
    )


@router.get("/runtime", response_model=YtDlpRuntimeRead)
async def ytdlp_runtime(request: Request, workspace: CurrentWorkspace) -> YtDlpRuntimeRead:
    del workspace
    from app.services.ytdlp_runtime import runtime_status

    settings = request.app.state.settings
    status = await runtime_status(update_enabled=bool(settings.ytdlp_allow_runtime_update))
    return _runtime_read(status)


@router.post("/runtime/update", response_model=YtDlpRuntimeRead)
async def update_ytdlp_runtime(
    request: Request,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
) -> YtDlpRuntimeRead:
    require_workspace_role(workspace, {"owner", "admin"})
    settings = request.app.state.settings
    if not settings.ytdlp_allow_runtime_update:
        raise HTTPException(
            status_code=409,
            detail=(
                "运行时更新已关闭；请设置 SIO_YTDLP_ALLOW_RUNTIME_UPDATE=true，"
                "或重新构建 API/Worker 镜像。"
            ),
        )
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pip",
            "install",
            "-U",
            "yt-dlp[default]",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
    except (OSError, TimeoutError) as exc:
        logger.warning("yt-dlp runtime update failed: %s", exc)
        raise HTTPException(
            status_code=503, detail="yt-dlp 更新失败，请检查 API 服务日志后重试。"
        ) from exc
    if proc.returncode != 0:
        logger.warning("yt-dlp runtime update exited with code %s", proc.returncode)
        raise HTTPException(status_code=503, detail="yt-dlp 更新失败，请检查 API 服务日志后重试。")
    from app.services.ytdlp_runtime import runtime_status

    status = await runtime_status(update_enabled=True)
    return _runtime_read(status)


@router.post("/preview", response_model=DownloadPreviewEnqueue)
async def preview_download(
    payload: DownloadPreviewCreate,
    workspace: CurrentWorkspace,
) -> DownloadPreviewEnqueue:
    """Enqueue a yt-dlp metadata parse.

    The actual work runs in Celery (``preview_download_task``) so a slow or
    hung parse never holds the API event loop open.  Poll
    ``GET /downloads/preview/{task_id}`` for the result — the same async
    pattern already used by ``POST /downloads`` → ``GET /downloads/{id}``.
    """

    task = preview_download_task.delay(payload.url.strip(), str(workspace.workspace_id))
    return DownloadPreviewEnqueue(task_id=task.id)


@router.get("/preview/{task_id}", response_model=DownloadPreviewPoll)
async def preview_download_status(task_id: str, workspace: CurrentWorkspace) -> DownloadPreviewPoll:
    """Poll the Celery result of a ``POST /downloads/preview`` request."""

    del workspace
    result = AsyncResult(task_id, app=celery_app)
    if result.state == "SUCCESS":
        payload = result.result
        if isinstance(payload, dict) and payload.get("status") == "ok":
            preview = payload.get("preview")
            return DownloadPreviewPoll(
                task_id=task_id,
                state="SUCCESS",
                preview=DownloadPreviewRead.model_validate(preview) if preview else None,
            )
        if isinstance(payload, dict) and payload.get("status") == "error":
            return DownloadPreviewPoll(
                task_id=task_id,
                state="FAILURE",
                error_code=payload.get("error_code"),
                error_detail=payload.get("error_detail"),
            )
        return DownloadPreviewPoll(task_id=task_id, state="FAILURE", error_detail="未知的解析结果")
    if result.state == "FAILURE":
        detail = str(result.result) if result.result else "解析失败"
        return DownloadPreviewPoll(task_id=task_id, state="FAILURE", error_detail=detail[:300])
    return DownloadPreviewPoll(task_id=task_id, state=result.state)


@router.post("", response_model=DownloadRead, status_code=201)
async def create_download(
    payload: DownloadCreate,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    _: CsrfProtectedAuth,
) -> DownloadRead:
    """Submit a URL for on-demand download; returns the created record.

    The actual fetch runs in the worker (Celery). Poll ``GET /downloads`` or
    ``GET /downloads/{id}`` for status.
    """
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    from app.tasks.monitoring import download_url_task

    record = await DownloadService(db).create(workspace.workspace_id, payload)
    download_url_task.delay(str(record.id))
    return record


@router.get("", response_model=DownloadPage)
async def list_downloads(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> DownloadPage:
    return await DownloadService(db).list(workspace.workspace_id, page=page, page_size=page_size)


@router.get("/{download_id}", response_model=DownloadRead)
async def get_download(
    download_id: UUID, workspace: CurrentWorkspace, db: DatabaseSession
) -> DownloadRead:
    record = await DownloadService(db).get(download_id)
    if record is None or record.workspace_id != workspace.workspace_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="download not found")
    return DownloadRead.model_validate(record)


def _save_export_metadata(record: Download, export: SubtitleExport) -> None:
    """Append a generated artifact without dropping the original media list."""

    media = dict(getattr(record, "media", None) or {})
    exports = [
        item
        for item in (media.get("subtitle_exports") or [])
        if isinstance(item, dict) and item.get("file") != export.filename
    ]
    exports.append(export.media_entry)
    media["subtitle_exports"] = exports
    record.media = media


@router.post("/{download_id}/subtitle-preview", response_model=SubtitlePreviewRead)
async def preview_subtitle_export(
    download_id: UUID,
    payload: SubtitleExportCreate,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> SubtitlePreviewRead:
    """Preview a composed subtitle without re-running yt-dlp."""

    record = await DownloadService(db).get(download_id)
    if record is None or record.workspace_id != workspace.workspace_id:
        raise HTTPException(status_code=404, detail="download not found")
    try:
        export = build_subtitle_export(
            dict(record.media or {}),
            primary_lang=payload.primary_lang,
            secondary_lang=payload.secondary_lang,
            output_format=payload.format,
            show_timestamps=payload.show_timestamps,
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    preview = subtitle_preview(export, show_timestamps=payload.show_timestamps, max_cues=5000)
    preview["generated_file"] = None
    return SubtitlePreviewRead.model_validate(preview)


@router.post("/{download_id}/subtitle-export")
async def export_subtitle(
    download_id: UUID,
    payload: SubtitleExportCreate,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    _: CsrfProtectedAuth,
) -> FileResponse:
    """Generate and serve a selected subtitle format from archived tracks."""

    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    record = await DownloadService(db).get(download_id)
    if record is None or record.workspace_id != workspace.workspace_id:
        raise HTTPException(status_code=404, detail="download not found")
    try:
        export = build_subtitle_export(
            dict(record.media or {}),
            primary_lang=payload.primary_lang,
            secondary_lang=payload.secondary_lang,
            output_format=payload.format,
            show_timestamps=payload.show_timestamps,
        )
        path = write_subtitle_export(export, dict(record.media or {}))
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _save_export_metadata(record, export)
    record.updated_at = datetime.now(UTC)
    await reconcile_manifest(
        db,
        workspace_id=record.workspace_id,
        download_id=record.id,
        media=dict(record.media or {}),
        source_kind="live",
        source_provider="subtitle_export",
        source_url=record.url,
        commit=True,
    )
    media_type = {
        "vtt": "text/vtt",
        "srt": "application/x-subrip",
        "txt": "text/plain; charset=utf-8",
        "json": "application/json",
        "ass": "text/x-ssa",
    }[payload.format]
    return FileResponse(path, media_type=media_type, filename=export.filename)


@router.get("/{download_id}/file/{file}")
async def download_file(
    download_id: UUID, file: str, workspace: CurrentWorkspace, db: DatabaseSession
) -> FileResponse:
    """Serve a downloaded file (video / subtitle / thumbnail / info-json)."""
    from fastapi import HTTPException

    from app.api.routes.media import _allowed_files, _safe_media_path

    record = await DownloadService(db).get(download_id)
    if record is None or record.workspace_id != workspace.workspace_id:
        raise HTTPException(status_code=404, detail="download not found")
    if not record.media or not record.media.get("base"):
        raise HTTPException(status_code=404, detail="no media")
    # Only serve files we explicitly recorded for this download — the same
    # defense-in-depth as serve_content_media — to avoid stray file disclosure.
    allowed = {os.path.basename(value) for value in _allowed_files(record.media)}
    if allowed and os.path.basename(file) not in allowed:
        raise HTTPException(status_code=404, detail="invalid file")
    # ``base`` already includes the workspace id (e.g. "<ws>/downloads/<id>/<vid>")
    safe = _safe_media_path(record.media["base"], file)
    if safe is None:
        raise HTTPException(status_code=400, detail="invalid file")
    return FileResponse(safe)
