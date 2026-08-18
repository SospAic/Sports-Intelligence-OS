"""Run and persist a single platform adapter health probe.

The probe is intentionally small: it validates the adapter's own health
contract, records a safe external-call attempt, and never writes account or
content data. A successful probe is evidence about connectivity/configuration,
not proof of private Analytics or publishing permission.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.platforms.base import AdapterCallContext, PlatformAdapterError
from app.core.config import Settings
from app.models.monitoring import Platform
from app.providers.registry import ProviderRegistry
from app.schemas.readiness import CanaryStatus, PlatformCanaryRead
from app.services.audit import build_audit_entry, build_external_call_attempt
from app.services.platform_credentials import (
    PlatformCredentialError,
    PlatformCredentialService,
)


def _safe_exception_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    return str(code) if isinstance(code, str) and code else "platform_canary_failed"


def _safe_exception_detail(exc: Exception) -> str:
    code = _safe_exception_code(exc)
    if isinstance(exc, PlatformAdapterError):
        return f"{code}: {str(exc)[:500]}"
    if isinstance(exc, asyncio.TimeoutError):
        return "platform_canary_timeout: 平台探针超时"
    return f"{code}: 平台探针执行失败（{type(exc).__name__}）"


def _safe_text(value: str) -> str:
    return re.sub(
        r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|authorization)\s*[:=]\s*[^\s,;]+",
        r"\1=***",
        value[:500],
    )


def _safe_response_summary(
    summary: dict[str, Any],
) -> dict[str, str | int | float | bool | None]:
    sensitive_terms = ("secret", "token", "password", "authorization", "api_key")
    safe: dict[str, str | int | float | bool | None] = {}
    for key, value in summary.items():
        if any(term in key.casefold() for term in sensitive_terms):
            continue
        if isinstance(value, str):
            safe[key] = _safe_text(value)
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key] = value
    return safe


def classify_health_status(
    health_status: str, detail: str | None
) -> tuple[CanaryStatus, str, str | None]:
    """Map adapter health semantics to the persisted canary contract."""

    if health_status == "ok":
        status: CanaryStatus = "passed"
    elif health_status == "degraded":
        status = "degraded"
    else:
        status = "failed"
    default_detail = {
        "passed": "平台适配器探针通过。",
        "degraded": "平台适配器部分可用。",
        "failed": "平台适配器不可用。",
        "blocked": "平台探针未执行。",
    }[status]
    error_code = None if status in {"passed", "degraded"} else "platform_canary_unavailable"
    return status, detail or default_detail, error_code


async def _persist_result(
    *,
    session: AsyncSession,
    platform: Platform,
    workspace_id: UUID,
    actor_id: UUID | None,
    platform_key: str,
    adapter_key: str,
    mode: str,
    credential_source: str,
    status: str,
    checked_at: datetime,
    duration_ms: int,
    detail: str,
    error_code: str | None,
    response_summary: dict[str, Any],
) -> PlatformCanaryRead:
    external_status = "success" if status in {"passed", "degraded"} else "failed"
    safe_response_summary = _safe_response_summary(response_summary)
    attempt = build_external_call_attempt(
        id=uuid4(),
        workspace_id=workspace_id,
        call_type="platform_api",
        provider_key=adapter_key,
        entity_type="platform_canary",
        entity_id=platform.id,
        attempt_number=1,
        status=external_status,
        target_url=None,
        started_at=checked_at,
        finished_at=datetime.now(UTC),
        duration_ms=duration_ms,
        http_status=None,
        error_code=error_code,
        error_detail_safe=detail[:500] if error_code else None,
        retryable=False if error_code else None,
        request_summary={
            "platform_key": platform_key,
            "mode": mode,
            "trigger": "manual" if actor_id is not None else "scheduled",
            "probe_scope": "official_api" if mode == "api" else "adapter_runtime",
            "credential_source": credential_source,
        },
        response_summary=safe_response_summary,
    )
    session.add(attempt)
    session.add(
        build_audit_entry(
            id=uuid4(),
            workspace_id=workspace_id,
            actor_type="user" if actor_id is not None else "system",
            actor_id=actor_id,
            action="platform.canary",
            resource_type="platform",
            resource_id=platform.id,
            change_summary_json={
                "platform_key": platform_key,
                "adapter_key": adapter_key,
                "mode": mode,
                "status": status,
            },
            reason=(
                "manual platform readiness probe"
                if actor_id is not None
                else "scheduled platform API canary"
            ),
            trace_id=uuid4(),
            created_at=datetime.now(UTC),
            status="success" if external_status == "success" else "failed",
            error_code=error_code,
            error_detail=detail[:500] if error_code else None,
        )
    )
    await session.commit()
    return PlatformCanaryRead(
        platform_key=platform_key,
        adapter_key=adapter_key,
        trigger="manual" if actor_id is not None else "scheduled",
        mode=mode,  # type: ignore[arg-type]
        credential_source=credential_source,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        checked_at=checked_at,
        detail=detail,
        error_code=error_code,
        duration_ms=duration_ms,
        response_summary={
            key: value
            for key, value in safe_response_summary.items()
        },
    )


async def run_platform_canary(
    *,
    session: AsyncSession,
    settings: Settings,
    registry: ProviderRegistry[Any],
    workspace_id: UUID,
    actor_id: UUID | None,
    platform_key: str,
) -> PlatformCanaryRead:
    key = platform_key.strip().casefold().removesuffix("_browser")
    platform = await session.scalar(
        select(Platform).where(Platform.key == key, Platform.enabled.is_(True))
    )
    if platform is None:
        raise PlatformCredentialError(
            "platform was not found", code="platform_not_found", status_code=404
        )

    credential_service = PlatformCredentialService(session, settings)
    credential = await credential_service.get(workspace_id, key)
    mode, config = await credential_service.resolve(workspace_id, key)
    checked_at = datetime.now(UTC)

    if mode == "unconfigured":
        return await _persist_result(
            session=session,
            platform=platform,
            workspace_id=workspace_id,
            actor_id=actor_id,
            platform_key=key,
            adapter_key=platform.adapter_key,
            mode=credential.mode,
            credential_source=credential.source,
            status="blocked",
            checked_at=checked_at,
            duration_ms=0,
            detail="平台采集条件未满足，未发起外部探针。",
            error_code="platform_credentials_not_configured",
            response_summary={"probe_started": False},
        )

    probe_key = key if mode == "api" else platform.adapter_key
    try:
        adapter = registry.get(probe_key)
    except LookupError:
        try:
            adapter = registry.get(platform.adapter_key)
            probe_key = platform.adapter_key
        except LookupError:
            return await _persist_result(
                session=session,
                platform=platform,
                workspace_id=workspace_id,
                actor_id=actor_id,
                platform_key=key,
                adapter_key=probe_key,
                mode=mode,
                credential_source=credential.source,
                status="blocked",
                checked_at=checked_at,
                duration_ms=0,
                detail="平台适配器未注册，未发起外部探针。",
                error_code="platform_adapter_not_registered",
                response_summary={"probe_started": False},
            )

    started = datetime.now(UTC)
    ctx = AdapterCallContext(
        config=config,
        observed_at=started,
        request_id=str(uuid4()),
        timeout_seconds=settings.platform_request_timeout_seconds,
    )
    try:
        health = await adapter.health_check(ctx)
        duration_ms = max(0, int((datetime.now(UTC) - started).total_seconds() * 1000))
        status, detail, error_code = classify_health_status(health.status, health.detail)
        return await _persist_result(
            session=session,
            platform=platform,
            workspace_id=workspace_id,
            actor_id=actor_id,
            platform_key=key,
            adapter_key=probe_key,
            mode=mode,
            credential_source=credential.source,
            status=status,
            checked_at=started,
            duration_ms=duration_ms,
            detail=detail,
            error_code=error_code,
            response_summary={
                "probe_started": True,
                "health_status": health.status,
                "detail": detail,
                "probe_scope": "official_api" if mode == "api" else "adapter_runtime",
            },
        )
    except Exception as exc:  # noqa: BLE001 - probe must persist a safe failure
        duration_ms = max(0, int((datetime.now(UTC) - started).total_seconds() * 1000))
        error_code = _safe_exception_code(exc)
        return await _persist_result(
            session=session,
            platform=platform,
            workspace_id=workspace_id,
            actor_id=actor_id,
            platform_key=key,
            adapter_key=probe_key,
            mode=mode,
            credential_source=credential.source,
            status="failed",
            checked_at=started,
            duration_ms=duration_ms,
            detail=_safe_exception_detail(exc),
            error_code=error_code,
            response_summary={"probe_started": True},
        )
