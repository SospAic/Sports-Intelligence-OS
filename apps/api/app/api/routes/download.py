"""On-demand video / subtitle download endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentWorkspace, DatabaseSession
from app.schemas.download import DownloadCreate, DownloadPage, DownloadRead
from app.services.download import DownloadService

router = APIRouter(prefix="/downloads", tags=["downloads"])


@router.post("", response_model=DownloadRead, status_code=201)
async def create_download(
    payload: DownloadCreate,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> DownloadRead:
    """Submit a URL for on-demand download; returns the created record.

    The actual fetch runs in the worker (Celery). Poll ``GET /downloads`` or
    ``GET /downloads/{id}`` for status.
    """
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
    return await DownloadService(db).list(
        workspace.workspace_id, page=page, page_size=page_size
    )


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
):
    """Serve a downloaded file (video / subtitle / thumbnail / info-json)."""
    from app.api.routes.media import _safe_media_path
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

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
