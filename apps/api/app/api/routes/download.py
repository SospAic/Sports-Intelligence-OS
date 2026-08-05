"""On-demand video / subtitle download endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.schemas.download import (
    DownloadCreate,
    DownloadPage,
    DownloadPreviewCreate,
    DownloadPreviewRead,
    DownloadRead,
)
from app.services.download import DownloadService

router = APIRouter(prefix="/downloads", tags=["downloads"])


@router.post("/preview", response_model=DownloadPreviewRead)
async def preview_download(
    payload: DownloadPreviewCreate,
    workspace: CurrentWorkspace,
) -> DownloadPreviewRead:
    del workspace
    from app.adapters.platforms.yt_dlp import YtDlpAdapter
    from app.providers.news.utils import ensure_public_endpoint

    url = payload.url.strip()
    try:
        url = await ensure_public_endpoint(url, allow_secret_query=False)
        entries, _ = await YtDlpAdapter()._run_yt_dlp(
            url,
            download={},
            playlist_end=1,
        )
    except Exception as exc:  # noqa: BLE001 - expose a safe, actionable preview error
        raise HTTPException(status_code=422, detail=f"无法解析地址：{str(exc)[:500]}") from exc
    if not entries:
        raise HTTPException(status_code=422, detail="地址未返回可识别的视频信息")
    item = entries[0]
    subtitle_languages = sorted(
        {
            str(language)
            for key in ("subtitles", "automatic_captions")
            for language in (item.get(key) or {})
            if language
        }
    )
    return DownloadPreviewRead(
        url=url,
        platform=str(item.get("extractor") or item.get("ie_key") or "") or None,
        external_id=str(item.get("id")) if item.get("id") else None,
        title=str(item.get("title")) if item.get("title") else None,
        uploader=str(item.get("uploader") or item.get("channel") or "") or None,
        thumbnail=str(item.get("thumbnail")) if item.get("thumbnail") else None,
        duration_seconds=float(item["duration"]) if item.get("duration") is not None else None,
        description=str(item.get("description")) if item.get("description") else None,
        subtitle_languages=subtitle_languages,
    )


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


@router.get("/{download_id}/file/{file}")
async def download_file(
    download_id: UUID, file: str, workspace: CurrentWorkspace, db: DatabaseSession
) -> FileResponse:
    """Serve a downloaded file (video / subtitle / thumbnail / info-json)."""
    from fastapi import HTTPException

    from app.api.routes.media import _safe_media_path

    record = await DownloadService(db).get(download_id)
    if record is None or record.workspace_id != workspace.workspace_id:
        raise HTTPException(status_code=404, detail="download not found")
    if not record.media or not record.media.get("base"):
        raise HTTPException(status_code=404, detail="no media")
    # ``base`` already includes the workspace id (e.g. "<ws>/downloads/<id>/<vid>")
    safe = _safe_media_path(record.media["base"], file)
    if safe is None:
        raise HTTPException(status_code=400, detail="invalid file")
    return FileResponse(safe)
