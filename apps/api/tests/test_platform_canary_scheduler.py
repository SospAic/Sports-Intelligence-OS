from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.tasks.platform_canary import (
    canary_status_from_attempt,
    is_unhealthy_canary_status,
    should_run_canary,
)


def test_scheduler_respects_interval_and_future_clock_skew() -> None:
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)

    assert should_run_canary(None, now=now, interval_seconds=3600)
    assert not should_run_canary(
        now - timedelta(minutes=30), now=now, interval_seconds=3600
    )
    assert should_run_canary(
        now - timedelta(hours=1), now=now, interval_seconds=3600
    )
    assert not should_run_canary(
        now + timedelta(minutes=5), now=now, interval_seconds=3600
    )


def test_persisted_attempt_maps_to_readiness_status() -> None:
    assert canary_status_from_attempt(None) is None
    assert canary_status_from_attempt(
        SimpleNamespace(
            status="success", error_code=None, response_summary={"health_status": "ok"}
        )
    ) == "passed"
    assert canary_status_from_attempt(
        SimpleNamespace(
            status="success",
            error_code=None,
            response_summary={"health_status": "degraded"},
        )
    ) == "degraded"
    assert canary_status_from_attempt(
        SimpleNamespace(
            status="failed",
            error_code="platform_credentials_not_configured",
            response_summary={},
        )
    ) == "blocked"
    assert canary_status_from_attempt(
        SimpleNamespace(status="failed", error_code="authentication_error", response_summary={})
    ) == "failed"


def test_only_unhealthy_statuses_trigger_transition_handling() -> None:
    assert is_unhealthy_canary_status("failed")
    assert is_unhealthy_canary_status("degraded")
    assert is_unhealthy_canary_status("blocked")
    assert not is_unhealthy_canary_status("passed")
    assert not is_unhealthy_canary_status(None)
