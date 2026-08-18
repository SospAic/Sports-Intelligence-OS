from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.core.problems import problem_response
from app.models.monitoring import Platform
from app.models.operations import ExternalCallAttempt
from app.schemas.adapters import (
    AdapterDescriptorRead,
    build_adapter_descriptor_read,
)
from app.schemas.readiness import PlatformCanaryRead, ReadinessReportRead
from app.schemas.settings import (
    LLMModelsRead,
    LLMProviderSettingRead,
    LLMProviderSettingUpdate,
    LLMProviderTestRead,
    PlatformCredentialRead,
    PlatformCredentialUpdate,
    PlatformSessionCaptureOpenRead,
    PlatformSessionCaptureRequest,
    RuntimeSettingsRead,
    SyncSettingsRead,
    SyncSettingsUpdate,
)
from app.services.platform_canary import run_platform_canary
from app.services.platform_credentials import (
    PlatformCredentialError,
    PlatformCredentialService,
)
from app.services.platform_session_capture import (
    PLATFORM_LOGIN_URLS,
    BrowserSessionCaptureError,
    open_login_page,
)
from app.services.readiness import build_readiness_report
from app.services.settings import SettingsError, SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


async def settings_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, (SettingsError, PlatformCredentialError)):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title="设置请求失败",
        detail=str(exc),
    )


def service(request: Request, db: DatabaseSession) -> SettingsService:
    return SettingsService(
        db,
        request.app.state.settings,
        request.app.state.llm_providers,
    )


@router.get("/runtime", response_model=RuntimeSettingsRead)
async def runtime_settings(
    request: Request, workspace: CurrentWorkspace, db: DatabaseSession
) -> RuntimeSettingsRead:
    del workspace
    return await service(request, db).runtime_settings()


@router.get("/llm/openai-compatible", response_model=LLMProviderSettingRead)
async def get_llm_setting(
    request: Request, workspace: CurrentWorkspace, db: DatabaseSession
) -> LLMProviderSettingRead:
    return await service(request, db).llm_setting(workspace.workspace_id)


@router.put("/llm/openai-compatible", response_model=LLMProviderSettingRead)
async def update_llm_setting(
    payload: LLMProviderSettingUpdate,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> LLMProviderSettingRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await service(request, db).update_llm_setting(
        workspace.workspace_id, auth.user.id, payload
    )


@router.post("/llm/openai-compatible/test", response_model=LLMProviderTestRead)
async def test_llm_setting(
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
    payload: LLMProviderSettingUpdate | None = None,
) -> LLMProviderTestRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await service(request, db).test_llm_setting(
        workspace.workspace_id,
        auth.user.id,
        payload,
    )


@router.get("/llm/models", response_model=LLMModelsRead)
async def list_llm_models(
    request: Request,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> LLMModelsRead:
    return await service(request, db).llm_models(workspace.workspace_id)


@router.get("/platform-credentials", response_model=list[PlatformCredentialRead])
async def list_platform_credentials(
    request: Request, workspace: CurrentWorkspace, db: DatabaseSession
) -> list[PlatformCredentialRead]:
    return await PlatformCredentialService(db, request.app.state.settings).list(
        workspace.workspace_id
    )


@router.get("/platform-credentials/{platform_key}", response_model=PlatformCredentialRead)
async def get_platform_credentials(
    platform_key: str,
    request: Request,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> PlatformCredentialRead:
    return await PlatformCredentialService(db, request.app.state.settings).get(
        workspace.workspace_id, platform_key
    )


@router.put("/platform-credentials/{platform_key}", response_model=PlatformCredentialRead)
async def update_platform_credentials(
    platform_key: str,
    payload: PlatformCredentialUpdate,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> PlatformCredentialRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await PlatformCredentialService(db, request.app.state.settings).update(
        workspace.workspace_id, auth.user.id, platform_key, payload
    )


@router.post(
    "/platform-credentials/{platform_key}/revoke-login",
    response_model=PlatformCredentialRead,
)
async def revoke_platform_login_access(
    platform_key: str,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> PlatformCredentialRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await PlatformCredentialService(db, request.app.state.settings).revoke_login_access(
        workspace.workspace_id, auth.user.id, platform_key
    )


@router.post(
    "/platform-credentials/{platform_key}/session-capture/open",
    response_model=PlatformSessionCaptureOpenRead,
)
async def open_platform_session_capture(
    platform_key: str,
    payload: PlatformSessionCaptureRequest,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> PlatformSessionCaptureOpenRead:
    """Open a platform login page in the Docker or user-provided browser."""

    require_workspace_role(workspace, {"owner", "admin"})
    key = platform_key.strip().casefold().removesuffix("_browser")
    if key not in PLATFORM_LOGIN_URLS:
        raise PlatformCredentialError(
            "该平台暂不支持人工浏览器授权",
            code="platform_not_supported",
            status_code=422,
        )
    cdp_endpoint = payload.cdp_endpoint or request.app.state.settings.browser_cdp_endpoint
    try:
        login_url = await open_login_page(cdp_endpoint, key)
    except BrowserSessionCaptureError as exc:
        raise PlatformCredentialError(str(exc), code=exc.code, status_code=422) from exc
    browser_view_url = (
        request.app.state.settings.browser_vnc_url
        if urlsplit(cdp_endpoint).hostname == "browser"
        else None
    )
    del auth, db
    return PlatformSessionCaptureOpenRead(
        status="awaiting_manual_login",
        platform_key=key,
        login_url=login_url,
        detail=(
            "Docker 内置浏览器登录页已打开，请在浏览器窗口中完成人工登录、验证码或二次验证，"
            "然后返回系统点击保存会话。"
            if browser_view_url
            else "登录页已在浏览器打开；请完成人工登录、验证码或二次验证后返回系统点击保存会话。"
        ),
        browser_view_url=browser_view_url,
    )


@router.post(
    "/platform-credentials/{platform_key}/session-capture/save",
    response_model=PlatformCredentialRead,
)
async def save_platform_session_capture(
    platform_key: str,
    payload: PlatformSessionCaptureRequest,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> PlatformCredentialRead:
    """Capture and encrypt cookies after the user completes browser login."""

    require_workspace_role(workspace, {"owner", "admin"})
    cdp_endpoint = payload.cdp_endpoint or request.app.state.settings.browser_cdp_endpoint
    return await PlatformCredentialService(db, request.app.state.settings).capture_browser_session(
        workspace.workspace_id,
        auth.user.id,
        platform_key,
        cdp_endpoint=cdp_endpoint,
        account_authorization_confirmed=payload.account_authorization_confirmed,
        platform_session_allowed=payload.platform_session_allowed,
        oauth_unavailable_or_insufficient=payload.oauth_unavailable_or_insufficient,
    )


@router.get("/sync", response_model=SyncSettingsRead)
async def get_sync_settings(
    request: Request, workspace: CurrentWorkspace, db: DatabaseSession
) -> SyncSettingsRead:
    """Return the workspace's global fetch policy (yt-dlp / scrape tuning)."""

    return await service(request, db).sync_settings(workspace.workspace_id)


@router.put("/sync", response_model=SyncSettingsRead)
async def update_sync_settings(
    payload: SyncSettingsUpdate,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> SyncSettingsRead:
    """Persist the workspace's global fetch policy.

    Centralises the yt-dlp / scrape tuning that used to live per-account so
    every account in the workspace shares one fetch policy.
    """

    require_workspace_role(workspace, {"owner", "admin"})
    return await service(request, db).update_sync_settings(
        workspace.workspace_id, auth.user.id, payload
    )


@router.get("/platform-adapters", response_model=list[AdapterDescriptorRead])
async def list_platform_adapters(
    request: Request, workspace: CurrentWorkspace, db: DatabaseSession
) -> list[AdapterDescriptorRead]:
    """List every registered platform adapter with its declared capabilities.

    Surfaces the adapter-level differentiation (which metrics/fields each
    platform supports, required config and supported source kinds) so the
    platform-management UI can render a capability matrix instead of hiding
    platform differences in the adapter code.
    """
    del workspace, db
    registry = request.app.state.platform_adapters
    return [build_adapter_descriptor_read(adapter.descriptor) for adapter in registry.values()]


@router.get("/readiness", response_model=ReadinessReportRead)
async def readiness_report(
    request: Request, workspace: CurrentWorkspace, db: DatabaseSession
) -> ReadinessReportRead:
    """Return actionable configuration and capability readiness diagnostics.

    This endpoint intentionally performs no provider calls. A configured item
    is reported as ``unverified`` until an explicit live canary is recorded.
    """

    platforms = list(
        (
            await db.scalars(
                select(Platform).where(Platform.enabled.is_(True)).order_by(Platform.name)
            )
        ).all()
    )
    credentials = await PlatformCredentialService(db, request.app.state.settings).list(
        workspace.workspace_id
    )
    attempts = list(
        (
            await db.scalars(
                select(ExternalCallAttempt)
                .where(
                    ExternalCallAttempt.workspace_id == workspace.workspace_id,
                    ExternalCallAttempt.call_type == "platform_api",
                    ExternalCallAttempt.entity_type == "platform_canary",
                )
                .order_by(ExternalCallAttempt.started_at.desc())
                .limit(1000)
            )
        ).all()
    )
    last_probes: dict[str, PlatformCanaryRead] = {}
    for attempt in attempts:
        request_summary = attempt.request_summary or {}
        platform_key = request_summary.get("platform_key")
        if not isinstance(platform_key, str) or platform_key in last_probes:
            continue
        response_summary = attempt.response_summary or {}
        health_status = response_summary.get("health_status")
        if attempt.error_code == "platform_credentials_not_configured":
            canary_status = "blocked"
        elif attempt.status != "success":
            canary_status = "failed"
        elif health_status == "degraded":
            canary_status = "degraded"
        else:
            canary_status = "passed"
        last_probes[platform_key] = PlatformCanaryRead.model_validate(
            {
                "platform_key": platform_key,
                "adapter_key": attempt.provider_key,
                "trigger": request_summary.get("trigger", "manual"),
                "mode": request_summary.get("mode", "public_page"),
                "credential_source": request_summary.get("credential_source", "default"),
                "status": canary_status,
                "checked_at": attempt.started_at,
                "detail": (
                    attempt.error_detail_safe
                    or response_summary.get("detail")
                    or ("平台探针通过。" if canary_status == "passed" else "平台探针未通过。")
                ),
                "error_code": attempt.error_code,
                "duration_ms": attempt.duration_ms,
                "response_summary": response_summary,
            }
        )
    return build_readiness_report(
        settings=request.app.state.settings,
        platforms=platforms,
        credentials=credentials,
        registry=request.app.state.platform_adapters,
        last_probes=last_probes,
    )


@router.post("/readiness/{platform_key}/probe", response_model=PlatformCanaryRead)
async def probe_platform_readiness(
    platform_key: str,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> PlatformCanaryRead:
    """Run one safe adapter health probe and persist its redacted result."""

    require_workspace_role(workspace, {"owner", "admin"})
    return await run_platform_canary(
        session=db,
        settings=request.app.state.settings,
        registry=request.app.state.platform_adapters,
        workspace_id=workspace.workspace_id,
        actor_id=auth.user.id,
        platform_key=platform_key,
    )
