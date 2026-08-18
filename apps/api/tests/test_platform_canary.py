import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.adapters.platforms.base import AuthenticationError
from app.services.platform_canary import (
    _persist_result,
    _safe_exception_detail,
    classify_health_status,
)


def test_health_status_mapping_preserves_degraded_without_calling_it_success() -> None:
    assert classify_health_status("ok", None) == (
        "passed",
        "平台适配器探针通过。",
        None,
    )
    assert classify_health_status("degraded", "部分字段缺失") == (
        "degraded",
        "部分字段缺失",
        None,
    )
    assert classify_health_status("unavailable", "access_token_invalid") == (
        "failed",
        "access_token_invalid",
        "platform_canary_unavailable",
    )


def test_probe_exception_detail_keeps_error_code_and_does_not_require_secret_payload() -> None:
    detail = _safe_exception_detail(AuthenticationError("credential rejected"))

    assert detail.startswith("authentication_error:")
    assert "credential rejected" in detail


def test_persist_result_writes_external_call_and_audit_without_credentials() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.items: list[object] = []

        def add(self, item: object) -> None:
            self.items.append(item)

        async def commit(self) -> None:
            return None

    session = FakeSession()
    secret = "access-token-must-not-be-stored"  # noqa: S105
    result = asyncio.run(
        _persist_result(
            session=session,  # type: ignore[arg-type]
            platform=SimpleNamespace(id=uuid4()),
            workspace_id=uuid4(),
            actor_id=uuid4(),
            platform_key="youtube",
            adapter_key="youtube",
            mode="api",
            credential_source="environment",
            status="passed",
            checked_at=datetime.now(UTC),
            duration_ms=24,
            detail="平台探针通过",
            error_code=None,
            response_summary={"health_status": "ok", "secret": secret},
        )
    )

    assert result.status == "passed"
    assert result.trigger == "manual"
    assert len(session.items) == 2
    assert all(secret not in repr(item) for item in session.items)
