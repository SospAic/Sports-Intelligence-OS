from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.schemas.experiments import (
    ExperimentCreate,
    ExperimentDetail,
    ExperimentPage,
    ExperimentReport,
    ExperimentUpdate,
    ExperimentVariantCreate,
)
from app.services.experiments import ExperimentError, ExperimentService

router = APIRouter(prefix="/content-experiments", tags=["content-experiments"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
WindowKey = Literal["1h", "3h", "6h", "24h", "72h", "7d", "30d"]


def _raise(exc: ExperimentError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "detail": str(exc)})


@router.get("", response_model=ExperimentPage)
async def list_experiments(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
) -> ExperimentPage:
    return await ExperimentService(db).list_experiments(
        workspace.workspace_id, page=page, page_size=page_size
    )


@router.post("", response_model=ExperimentDetail, status_code=201)
async def create_experiment(
    payload: ExperimentCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> ExperimentDetail:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    return await ExperimentService(db).create(workspace.workspace_id, auth.user.id, payload)


@router.get("/{experiment_id}", response_model=ExperimentDetail)
async def get_experiment(
    experiment_id: UUID, workspace: CurrentWorkspace, db: DatabaseSession
) -> ExperimentDetail:
    try:
        return await ExperimentService(db).get(workspace.workspace_id, experiment_id)
    except ExperimentError as exc:
        raise _raise(exc) from exc


@router.patch("/{experiment_id}", response_model=ExperimentDetail)
async def update_experiment(
    experiment_id: UUID,
    payload: ExperimentUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> ExperimentDetail:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    try:
        return await ExperimentService(db).update(
            workspace.workspace_id, auth.user.id, experiment_id, payload
        )
    except ExperimentError as exc:
        raise _raise(exc) from exc


@router.post("/{experiment_id}/variants", response_model=ExperimentDetail, status_code=201)
async def add_experiment_variant(
    experiment_id: UUID,
    payload: ExperimentVariantCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> ExperimentDetail:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    try:
        return await ExperimentService(db).add_variant(
            workspace.workspace_id, auth.user.id, experiment_id, payload
        )
    except ExperimentError as exc:
        raise _raise(exc) from exc


@router.get("/{experiment_id}/report", response_model=ExperimentReport)
async def experiment_report(
    experiment_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    window_key: WindowKey = "24h",
) -> ExperimentReport:
    try:
        return await ExperimentService(db).report(workspace.workspace_id, experiment_id, window_key)
    except ExperimentError as exc:
        raise _raise(exc) from exc
