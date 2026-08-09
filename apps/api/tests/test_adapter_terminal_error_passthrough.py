"""Permanent adapter failures must not be re-wrapped as retryable.

Every browser adapter closes its scrape with a broad ``except Exception`` that
converts the failure into ``TransientAdapterError`` so the scheduler retries
flaky pages. Before ``reraise_if_terminal`` that wrapper also caught errors the
adapter had *already* classified as permanent, flipping ``retryable`` from
``False`` to ``True``. The visible damage: Bilibili's login wall produced
``retry_exhausted`` after burning the whole retry budget (~26s x N, hourly, per
account) instead of telling the operator to configure a cookie.

These tests pin the contract on all four platforms so the regression cannot
silently come back in one adapter while the others stay correct.
"""

from __future__ import annotations

import inspect

import pytest

from app.adapters.platforms.base import (
    AdapterConfigurationError,
    AdapterContractError,
    AdapterNotFoundError,
    AuthenticationError,
    PermissionDeniedError,
    PlatformAdapterError,
    RateLimitError,
    TransientAdapterError,
)
from app.adapters.platforms.browser_base import LoginRequiredError, reraise_if_terminal

BROWSER_ADAPTER_MODULES = (
    "app.adapters.platforms.youtube_browser",
    "app.adapters.platforms.tiktok_browser",
    "app.adapters.platforms.douyin_browser",
    "app.adapters.platforms.bilibili_browser",
)

TERMINAL_ERRORS = (
    LoginRequiredError("Bilibili", "检测到登录弹窗"),
    AdapterContractError("bad payload"),
    AdapterNotFoundError("gone"),
    AuthenticationError("bad token"),
    PermissionDeniedError("no access"),
    AdapterConfigurationError("missing cookie"),
)

RETRYABLE_ERRORS = (
    TransientAdapterError("page timed out"),
    RateLimitError("slow down"),
)


@pytest.mark.parametrize("exc", TERMINAL_ERRORS, ids=lambda e: type(e).__name__)
def test_terminal_errors_are_reraised(exc: PlatformAdapterError) -> None:
    """A permanent error escapes untouched, keeping retryable=False."""
    assert exc.retryable is False
    with pytest.raises(type(exc)) as caught:
        reraise_if_terminal(exc)
    assert caught.value is exc


@pytest.mark.parametrize("exc", RETRYABLE_ERRORS, ids=lambda e: type(e).__name__)
def test_retryable_errors_pass_through_silently(exc: PlatformAdapterError) -> None:
    """Transient errors fall through so the caller can wrap and retry them."""
    assert exc.retryable is True
    assert reraise_if_terminal(exc) is None


def test_unknown_exceptions_pass_through_silently() -> None:
    """Non-adapter exceptions stay wrappable — they are genuinely unclassified."""
    assert reraise_if_terminal(RuntimeError("playwright exploded")) is None
    assert reraise_if_terminal(TimeoutError()) is None


def test_login_required_is_not_retryable() -> None:
    """Guards the flag the whole fix depends on."""
    assert LoginRequiredError("Bilibili").retryable is False
    assert LoginRequiredError("Bilibili").code == "login_required"


@pytest.mark.parametrize("module_name", BROWSER_ADAPTER_MODULES)
def test_no_adapter_still_uses_the_old_whitelist(module_name: str) -> None:
    """Cross-platform consistency: all four adapters use the shared guard.

    The old form only let ``AdapterContractError``/``AdapterNotFoundError``
    through, so login walls were mislabelled as transient.
    """
    module = __import__(module_name, fromlist=["_"])
    source = inspect.getsource(module)
    assert "isinstance(exc, (AdapterContractError, AdapterNotFoundError))" not in source, (
        f"{module_name} still uses the old whitelist; permanent errors will be "
        "re-wrapped as retryable"
    )
    assert "reraise_if_terminal(exc)" in source, (
        f"{module_name} does not call the shared terminal-error guard"
    )


@pytest.mark.parametrize("module_name", BROWSER_ADAPTER_MODULES)
def test_every_broad_handler_is_guarded(module_name: str) -> None:
    """Each ``except Exception`` that wraps into Transient must guard first."""
    module = __import__(module_name, fromlist=["_"])
    source = inspect.getsource(module)
    wrap_sites = source.count("raise TransientAdapterError(")
    guard_sites = source.count("reraise_if_terminal(exc)")
    assert guard_sites >= 2, f"{module_name}: expected >=2 guarded handlers, got {guard_sites}"
    assert wrap_sites >= guard_sites, (
        f"{module_name}: {guard_sites} guards but only {wrap_sites} wrap sites"
    )
