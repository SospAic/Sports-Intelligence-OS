"""Base class for Playwright-based platform adapters.

The adapter supports either policy-approved public-page sampling, an encrypted
user-authorized login, or an encrypted imported Playwright storage state. Each
run uses an isolated browser context and never persists plaintext credentials.

Architecture constraints (from AGENTS.md):
- Browser access is limited to approved public pages or accounts owned/authorized
  by the user.
- No CAPTCHA bypass, no login security circumvention.
- Rate limiting and polite delays are mandatory.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from typing import Any, cast

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    StorageState,
    async_playwright,
)

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterHealth,
    PlatformAdapter,
    PlatformAdapterError,
)

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Common URL patterns that indicate a platform login redirect.
LOGIN_URL_PATTERNS = (
    "passport.bilibili.com/login",
    "accounts.google.com",
    "login.tiktok.com",
    "sso.douyin.com",
    "login.taobao.com",
    "/login",
    "/signin",
)

# DOM selectors that commonly indicate a login wall overlay.
LOGIN_WALL_SELECTORS = (
    ".login-panel-popover",
    ".bili-mini-mask",
    "[class*='login-guide']",
    "[class*='login-modal']",
    ".dy-account-close",
    "#login-container",
)


class LoginRequiredError(PlatformAdapterError):
    """Raised when login, CAPTCHA, or an interactive security step blocks access."""

    code = "login_required"
    retryable = False

    def __init__(self, platform: str, detail: str = ""):
        msg = f"平台 {platform} 要求登录后才能访问该数据；公开页采集已停止，请改用官方 API/OAuth。"
        if detail:
            msg += f"（{detail}）"
        super().__init__(msg)
        self.platform = platform


class BrowserPlatformAdapter(PlatformAdapter):
    """Base adapter that drives a headless Chromium browser via Playwright.

    Subclasses implement page navigation and DOM extraction logic. The base class
    manages the browser lifecycle and conservative request pacing.

    Collection strategy is selected explicitly through the workspace acquisition
    policy: public sampling, authorized credentials, or imported storage state.
    Interactive CAPTCHA and account-security challenges are never bypassed.
    """

    # Subclasses can override these defaults.
    default_viewport_width: int = 1920
    default_viewport_height: int = 1080
    min_action_delay: float = 0.5
    max_action_delay: float = 2.0
    page_load_timeout_ms: int = 30_000

    def __init__(
        self,
        *,
        headless: bool = True,
        min_action_delay: float | None = None,
        max_action_delay: float | None = None,
    ) -> None:
        self._headless = headless
        self._min_delay = min_action_delay or self.min_action_delay
        self._max_delay = max_action_delay or self.max_action_delay
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._session_states: dict[str, StorageState] = {}

    def _credential_cache_key(self, ctx: AdapterCallContext) -> str | None:
        username = ctx.config.get("username")
        password = ctx.config.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        return hashlib.sha256(
            f"{self.key}\0{username}\0{password}".encode()
        ).hexdigest()

    async def _ensure_browser(self) -> Browser:
        """Lazily launch the browser instance."""
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=["--disable-dev-shm-usage"],
        )
        return self._browser

    async def _new_context(self, ctx: AdapterCallContext) -> BrowserContext:
        """Create an isolated browser context for public-page sampling."""
        browser = await self._ensure_browser()
        cache_key = self._credential_cache_key(ctx)
        storage_state: StorageState | None = self._session_states.get(cache_key or "")
        raw_storage_state = ctx.config.get("storage_state_json")
        if isinstance(raw_storage_state, str) and raw_storage_state:
            try:
                parsed_state = json.loads(raw_storage_state)
            except json.JSONDecodeError as exc:
                raise LoginRequiredError(
                    self.descriptor.name, "加密会话状态不是有效 JSON"
                ) from exc
            if not isinstance(parsed_state, dict):
                raise LoginRequiredError(
                    self.descriptor.name, "加密会话状态格式无效"
                )
            storage_state = cast(StorageState, parsed_state)
        context = await browser.new_context(
            viewport={
                "width": self.default_viewport_width,
                "height": self.default_viewport_height,
            },
            user_agent=DEFAULT_USER_AGENT,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            storage_state=storage_state,
        )
        return context

    async def _new_page(self, ctx: AdapterCallContext) -> tuple[BrowserContext, Page]:
        """Create a context and page ready for navigation."""
        context = await self._new_context(ctx)
        page = await context.new_page()
        page.set_default_timeout(self.page_load_timeout_ms)
        cache_key = self._credential_cache_key(ctx)
        if cache_key and cache_key not in self._session_states:
            try:
                logged_in = await self._login_if_configured(page, ctx)
                if not logged_in:
                    raise LoginRequiredError(
                        self.descriptor.name,
                        "该平台的自动登录流程不可用",
                    )
                self._session_states[cache_key] = await context.storage_state()
            except LoginRequiredError:
                await context.close()
                raise
            except Exception as exc:
                await context.close()
                raise LoginRequiredError(
                    self.descriptor.name,
                    f"自动登录失败或页面结构已变化: {type(exc).__name__}",
                ) from exc
        return context, page

    async def _polite_delay(self, multiplier: float = 1.0) -> None:
        """Wait between interactions to respect the target site's capacity."""
        delay = ((self._min_delay + self._max_delay) / 2) * multiplier
        await asyncio.sleep(delay)

    async def _scroll_page(self, page: Page, times: int = 3) -> None:
        """Scroll the page incrementally to trigger lazy-loaded content."""
        for _ in range(times):
            await page.mouse.wheel(0, 450)
            await self._polite_delay(0.5)

    async def _check_login_required(self, page: Page, platform_name: str) -> None:
        """Detect if the platform is showing a login wall.

        Checks current URL for login redirects and DOM for login overlays.
        Raises LoginRequiredError if a login wall is detected and no
        credentials are available to retry.
        """
        current_url = page.url.lower()
        for pattern in LOGIN_URL_PATTERNS:
            if pattern in current_url:
                raise LoginRequiredError(
                    platform_name, f"被重定向到登录页: {page.url[:80]}"
                )
        # Check for login wall overlays in DOM.
        for selector in LOGIN_WALL_SELECTORS:
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=500):
                    raise LoginRequiredError(
                        platform_name, f"检测到登录弹窗 ({selector})"
                    )
            except LoginRequiredError:
                raise
            except Exception as exc:
                logger.debug(
                    "login wall selector check failed",
                    extra={"selector": selector, "error_type": type(exc).__name__},
                )
                continue

    async def _login_if_configured(
        self, page: Page, ctx: AdapterCallContext
    ) -> bool:
        """Platform adapters override this for permitted credential login flows."""
        del page, ctx
        return False

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        """Accept anonymous public mode or a complete encrypted credential pair."""
        username = config.get("username")
        password = config.get("password")
        if bool(username) != bool(password):
            raise LoginRequiredError(self.descriptor.name, "账号与密码必须同时配置")

    async def health_check(self, ctx: AdapterCallContext) -> AdapterHealth:
        """Verify Playwright browser can launch."""
        try:
            browser = await self._ensure_browser()
            if browser.is_connected():
                return AdapterHealth(
                    status="ok", checked_at=ctx.observed_at, detail="browser ready"
                )
            return AdapterHealth(
                status="unavailable",
                checked_at=ctx.observed_at,
                detail="browser disconnected",
            )
        except Exception as exc:
            return AdapterHealth(
                status="unavailable",
                checked_at=ctx.observed_at,
                detail=f"{type(exc).__name__}: {exc}",
            )

    async def aclose(self) -> None:
        """Shut down browser and Playwright."""
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._session_states.clear()
