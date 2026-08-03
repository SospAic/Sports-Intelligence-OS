from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

import app.services.sync as sync_module
from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.core.problems import problem_response
from app.repositories.monitoring import AccountFilters, ContentFilters
from app.schemas.monitoring import (
    AccountBatchDeleteRequest,
    AccountBatchResult,
    AccountBatchSyncItem,
    AccountBatchSyncRequest,
    AccountBatchSyncResult,
    AccountBatchUpdateRequest,
    AccountComparisonResponse,
    AccountContentSummary,
    AccountCreate,
    AccountMetricsHistory,
    AccountPage,
    AccountRead,
    AccountSnapshotPage,
    AccountSort,
    AccountSyncSettingsOverride,
    AccountUpdate,
    ContentCalendarResponse,
    ContentCreate,
    ContentPage,
    ContentRead,
    ContentSnapshotPage,
    ContentSort,
    ContentUpdate,
    DerivedMetricPage,
    PlatformRead,
    SortOrder,
    SyncIntervalResponse,
    SyncRunPage,
    SyncRunRead,
)
from app.services.monitoring import MonitoringError, MonitoringService
from app.services.sync import SyncDispatchError, SyncError, SyncService

router = APIRouter(tags=["monitoring"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


async def monitoring_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, MonitoringError):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title="监控数据请求失败",
        detail=str(exc),
    )


async def sync_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, SyncError):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title="平台同步请求失败",
        detail=str(exc),
    )


@router.get("/platforms", response_model=list[PlatformRead])
async def list_platforms(
    _: CurrentAuth,
    db: DatabaseSession,
    enabled: bool | None = None,
) -> list[PlatformRead]:
    return await MonitoringService(db).list_platforms(enabled=enabled)


@router.post("/accounts", response_model=AccountRead, status_code=201)
async def create_account(
    payload: AccountCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> AccountRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await MonitoringService(db).create_account(workspace.workspace_id, auth.user.id, payload)


@router.get("/accounts/export.csv")
async def export_accounts(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    sort: AccountSort = "created_at",
    order: SortOrder = "desc",
    platform: str | None = None,
    query: str | None = None,
    is_active: bool | None = None,
) -> Response:
    csv_text = await MonitoringService(db).export_accounts_csv(
        workspace.workspace_id,
        AccountFilters(platform=platform, query=query, is_active=is_active),
        sort,
        order,
    )
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="accounts.csv"'},
    )


@router.get("/accounts", response_model=AccountPage)
async def list_accounts(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    sort: AccountSort = "created_at",
    order: SortOrder = "desc",
    page: Page = 1,
    page_size: PageSize = 20,
    platform: str | None = None,
    query: str | None = None,
    is_active: bool | None = None,
) -> AccountPage:
    return await MonitoringService(db).list_accounts(
        workspace.workspace_id,
        filters=AccountFilters(platform=platform, query=query, is_active=is_active),
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )


@router.get("/accounts/compare", response_model=AccountComparisonResponse)
async def compare_accounts(
    account_ids: Annotated[list[UUID], Query()],
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> AccountComparisonResponse:
    """Side-by-side comparison of several accounts across platforms.

    Only real observations (``source_kind`` is ``live``/``imported``) are
    returned; nothing here is synthesised or mocked.
    """
    return await MonitoringService(db).compare_accounts(workspace.workspace_id, account_ids)


@router.patch("/accounts/batch", response_model=AccountBatchResult)
async def batch_update_accounts(
    payload: AccountBatchUpdateRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> AccountBatchResult:
    """Activate or deactivate many accounts at once."""
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    updated = await MonitoringService(db).batch_update_accounts(
        workspace.workspace_id, payload.account_ids, payload.is_active, auth.user.id
    )
    return AccountBatchResult(updated=updated, account_ids=payload.account_ids)


@router.post("/accounts/batch/delete", response_model=AccountBatchResult)
async def batch_delete_accounts(
    payload: AccountBatchDeleteRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> AccountBatchResult:
    """Soft-delete many accounts (deactivate and stop syncing)."""
    require_workspace_role(workspace, {"owner", "admin"})
    updated = await MonitoringService(db).batch_disable_accounts(
        workspace.workspace_id, payload.account_ids, auth.user.id
    )
    return AccountBatchResult(updated=updated, account_ids=payload.account_ids)


@router.post("/accounts/batch/sync", response_model=AccountBatchSyncResult, status_code=202)
async def batch_sync_accounts(
    payload: AccountBatchSyncRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> AccountBatchSyncResult:
    """Request a sync for several accounts at once.

    Each account is validated for workspace membership and dispatched like the
    single-account endpoint. The response reports per-account outcome so a
    caller can tell which were accepted, skipped (not found) or failed.
    """
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    service = SyncService(
        db,
        request.app.state.platform_adapters,
        request.app.state.settings,
    )
    monitoring = MonitoringService(db)
    items: list[AccountBatchSyncItem] = []
    accepted = skipped = failed = 0
    for account_id in payload.account_ids:
        try:
            await monitoring.get_account(workspace.workspace_id, account_id)
        except MonitoringError:
            skipped += 1
            items.append(
                AccountBatchSyncItem(
                    account_id=account_id, status="skipped", detail="not found in workspace"
                )
            )
            continue
        try:
            run, created = await service.request_account_sync(
                workspace.workspace_id,
                account_id,
                request_id=str(request.state.request_id),
            )
        except SyncError as exc:
            failed += 1
            items.append(
                AccountBatchSyncItem(
                    account_id=account_id, status="failed", detail=str(exc)
                )
            )
            continue
        if created:
            try:
                sync_module.enqueue_platform_sync(run.id)
            except Exception:
                failed += 1
                items.append(
                    AccountBatchSyncItem(
                        account_id=account_id,
                        status="failed",
                        detail="background task broker is unavailable",
                    )
                )
                continue
        accepted += 1
        items.append(
            AccountBatchSyncItem(
                account_id=account_id, status="accepted", sync_run_id=run.id
            )
        )
    return AccountBatchSyncResult(
        accepted=accepted, skipped=skipped, failed=failed, items=items
    )


@router.get("/accounts/{account_id}", response_model=AccountRead)
async def get_account(
    account_id: UUID, workspace: CurrentWorkspace, db: DatabaseSession
) -> AccountRead:
    return await MonitoringService(db).get_account(workspace.workspace_id, account_id)


@router.get(
    "/accounts/{account_id}/sync-settings",
    response_model=AccountSyncSettingsOverride | None,
)
async def get_account_sync_settings(
    account_id: UUID, workspace: CurrentWorkspace, db: DatabaseSession
) -> AccountSyncSettingsOverride | None:
    """Return the account's per-account sync settings override (None = inherit)."""
    return await MonitoringService(db).get_account_sync_settings(
        workspace.workspace_id, account_id
    )


@router.patch(
    "/accounts/{account_id}/sync-settings",
    response_model=AccountSyncSettingsOverride,
)
async def update_account_sync_settings(
    account_id: UUID,
    payload: AccountSyncSettingsOverride,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> AccountSyncSettingsOverride:
    """Set a per-account sync settings override layered on the workspace policy."""
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await MonitoringService(db).update_account_sync_settings(
        workspace.workspace_id, account_id, auth.user.id, payload
    )


@router.patch("/accounts/{account_id}", response_model=AccountRead)
async def update_account(
    account_id: UUID,
    payload: AccountUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> AccountRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await MonitoringService(db).update_account(
        workspace.workspace_id, account_id, auth.user.id, payload
    )


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> None:
    require_workspace_role(workspace, {"owner", "admin"})
    await MonitoringService(db).disable_account(workspace.workspace_id, account_id, auth.user.id)


@router.post("/accounts/{account_id}/sync", response_model=SyncRunRead, status_code=202)
async def request_account_sync(
    account_id: UUID,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> SyncRunRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    service = SyncService(
        db,
        request.app.state.platform_adapters,
        request.app.state.settings,
    )
    run, created = await service.request_account_sync(
        workspace.workspace_id,
        account_id,
        request_id=str(request.state.request_id),
    )
    if created:
        try:
            sync_module.enqueue_platform_sync(run.id)
        except Exception as exc:
            await service.mark_dispatch_failure(run.id)
            raise SyncDispatchError("background task broker is unavailable") from exc
    return run


@router.post("/accounts/{account_id}/sync/{run_id}/cancel", response_model=SyncRunRead)
async def cancel_account_sync(
    account_id: UUID,
    run_id: UUID,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
    request: Request,
) -> SyncRunRead:
    """Terminate a queued or running account sync run.

    Idempotent for runs that have already reached a terminal state. Honors the
    project's no-fake-success rule: it only records the cancellation against the
    persisted run and releases the account lock; it does not assert a successful
    platform call.
    """
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    return await SyncService(
        db,
        request.app.state.platform_adapters,
        request.app.state.settings,
    ).cancel_sync_run(workspace.workspace_id, account_id, run_id)


@router.post("/accounts/{account_id}/sync-interval", response_model=SyncIntervalResponse)
async def recompute_sync_interval(
    account_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> SyncIntervalResponse:
    """Recompute the adaptive sync interval from recent posting cadence."""
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await MonitoringService(db).recompute_account_sync_interval(
        workspace.workspace_id, account_id
    )


@router.get("/accounts/{account_id}/sync-runs", response_model=SyncRunPage)
async def list_account_sync_runs(
    account_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    request: Request,
    page: Page = 1,
    page_size: PageSize = 20,
) -> SyncRunPage:
    return await SyncService(
        db,
        request.app.state.platform_adapters,
        request.app.state.settings,
    ).list_account_runs(
        workspace.workspace_id,
        account_id,
        page=page,
        page_size=page_size,
    )


@router.get("/accounts/{account_id}/snapshots", response_model=AccountSnapshotPage)
async def list_account_snapshots(
    account_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 50,
) -> AccountSnapshotPage:
    return await MonitoringService(db).account_snapshots(
        workspace.workspace_id, account_id, page=page, page_size=page_size
    )


@router.get(
    "/accounts/{account_id}/metrics/history",
    response_model=AccountMetricsHistory,
)
async def account_metrics_history(
    account_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> AccountMetricsHistory:
    """Compact account metric time series for charts (fan-out/followers/views)."""
    return await MonitoringService(db).account_metrics_history(
        workspace.workspace_id, account_id, days=days
    )


@router.get("/accounts/{account_id}/contents", response_model=ContentPage)
async def list_account_contents(
    account_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    sort: ContentSort = "published_at",
    order: SortOrder = "desc",
    page: Page = 1,
    page_size: PageSize = 20,
    platform: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    min_views: Annotated[int | None, Query(ge=0)] = None,
    max_views: Annotated[int | None, Query(ge=0)] = None,
    query: str | None = None,
) -> ContentPage:
    service = MonitoringService(db)
    await service.get_account(workspace.workspace_id, account_id)
    return await service.list_contents(
        workspace.workspace_id,
        filters=ContentFilters(
            platform=platform,
            account=account_id,
            published_from=published_from,
            published_to=published_to,
            min_views=min_views,
            max_views=max_views,
            query=query,
        ),
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/accounts/{account_id}/content-summary",
    response_model=AccountContentSummary,
)
async def summarize_account_contents(
    account_id: UUID, workspace: CurrentWorkspace, db: DatabaseSession
) -> AccountContentSummary:
    """Aggregated content overview (completion, watch time, traffic split)."""
    return await MonitoringService(db).summarize_account_contents(
        workspace.workspace_id, account_id
    )


@router.get("/contents/export.csv")
async def export_contents(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    sort: ContentSort = "published_at",
    order: SortOrder = "desc",
    platform: str | None = None,
    account: UUID | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    min_views: Annotated[int | None, Query(ge=0)] = None,
    max_views: Annotated[int | None, Query(ge=0)] = None,
    query: str | None = None,
) -> Response:
    csv_text = await MonitoringService(db).export_contents_csv(
        workspace.workspace_id,
        ContentFilters(
            platform=platform,
            account=account,
            published_from=published_from,
            published_to=published_to,
            min_views=min_views,
            max_views=max_views,
            query=query,
        ),
        sort,
        order,
    )
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="contents.csv"'},
    )


@router.get("/contents/calendar", response_model=ContentCalendarResponse)
async def contents_calendar(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    year: int,
    month: Annotated[int, Query(ge=1, le=12)],
    platform: str | None = None,
    account: UUID | None = None,
    query: str | None = None,
) -> ContentCalendarResponse:
    """Per-day calendar aggregation of published works for a given month."""
    return await MonitoringService(db).contents_calendar(
        workspace.workspace_id,
        filters=ContentFilters(
            platform=platform, account=account, query=query
        ),
        year=year,
        month=month,
    )


@router.get("/contents", response_model=ContentPage)
async def list_contents(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    sort: ContentSort = "published_at",
    order: SortOrder = "desc",
    page: Page = 1,
    page_size: PageSize = 20,
    platform: str | None = None,
    account: UUID | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    min_views: Annotated[int | None, Query(ge=0)] = None,
    max_views: Annotated[int | None, Query(ge=0)] = None,
    query: str | None = None,
) -> ContentPage:
    return await MonitoringService(db).list_contents(
        workspace.workspace_id,
        filters=ContentFilters(
            platform=platform,
            account=account,
            published_from=published_from,
            published_to=published_to,
            min_views=min_views,
            max_views=max_views,
            query=query,
        ),
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )


@router.get("/contents/{content_id}", response_model=ContentRead)
async def get_content(
    content_id: UUID, workspace: CurrentWorkspace, db: DatabaseSession
) -> ContentRead:
    return await MonitoringService(db).get_content(workspace.workspace_id, content_id)


@router.get("/contents/{content_id}/snapshots", response_model=ContentSnapshotPage)
async def list_content_snapshots(
    content_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 50,
) -> ContentSnapshotPage:
    return await MonitoringService(db).content_snapshots(
        workspace.workspace_id, content_id, page=page, page_size=page_size
    )


@router.get("/contents/{content_id}/metrics", response_model=DerivedMetricPage)
async def list_content_metrics(
    content_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 50,
) -> DerivedMetricPage:
    return await MonitoringService(db).content_metrics(
        workspace.workspace_id, content_id, page=page, page_size=page_size
    )


# -- Content CRUD (manual) -------------------------------------------------


@router.post("/contents", response_model=ContentRead, status_code=201)
async def create_content(
    payload: ContentCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> ContentRead:
    """Manually create a content item under an existing account."""
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await MonitoringService(db).create_content(
        workspace.workspace_id, auth.user.id, payload
    )


@router.patch("/contents/{content_id}", response_model=ContentRead)
async def update_content(
    content_id: UUID,
    payload: ContentUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> ContentRead:
    """Update fields on an existing content item."""
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await MonitoringService(db).update_content(
        workspace.workspace_id, auth.user.id, content_id, payload
    )


@router.delete("/contents/{content_id}", status_code=204)
async def delete_content(
    content_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> Response:
    """Delete a content item."""
    require_workspace_role(workspace, {"owner", "admin"})
    await MonitoringService(db).delete_content(workspace.workspace_id, auth.user.id, content_id)
    return Response(status_code=204)
