from fastapi import APIRouter, Request, Response

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.core.problems import problem_response
from app.schemas.adapters import (
    AdapterDescriptorRead,
    build_adapter_descriptor_read,
)
from app.schemas.settings import (
    LLMProviderSettingRead,
    LLMProviderSettingUpdate,
    LLMProviderTestRead,
    PlatformCredentialRead,
    PlatformCredentialUpdate,
    RuntimeSettingsRead,
)
from app.services.platform_credentials import (
    PlatformCredentialError,
    PlatformCredentialService,
)
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
    return service(request, db).runtime_settings()


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
) -> LLMProviderTestRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await service(request, db).test_llm_setting(workspace.workspace_id, auth.user.id)


@router.get("/platform-credentials", response_model=list[PlatformCredentialRead])
async def list_platform_credentials(
    request: Request, workspace: CurrentWorkspace, db: DatabaseSession
) -> list[PlatformCredentialRead]:
    return await PlatformCredentialService(
        db, request.app.state.settings
    ).list(workspace.workspace_id)


@router.get(
    "/platform-credentials/{platform_key}", response_model=PlatformCredentialRead
)
async def get_platform_credentials(
    platform_key: str,
    request: Request,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> PlatformCredentialRead:
    return await PlatformCredentialService(db, request.app.state.settings).get(
        workspace.workspace_id, platform_key
    )


@router.put(
    "/platform-credentials/{platform_key}", response_model=PlatformCredentialRead
)
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
    return await PlatformCredentialService(
        db, request.app.state.settings
    ).revoke_login_access(workspace.workspace_id, auth.user.id, platform_key)


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
    return [
        build_adapter_descriptor_read(adapter.descriptor)
        for adapter in registry.values()
    ]
