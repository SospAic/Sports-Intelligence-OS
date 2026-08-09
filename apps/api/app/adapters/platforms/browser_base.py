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
import ipaddress
import json
import logging
import os
import random
import socket
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlparse, urlunparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    ProxySettings,
    StorageState,
    async_playwright,
)

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterHealth,
    LoginRequiredError,
    PlatformAdapter,
    PlatformAdapterError,
)

# ``LoginRequiredError`` used to be defined here. It moved to ``base`` so that
# non-browser adapters (yt-dlp) can raise it without importing Playwright.
# Re-exported so existing ``from .browser_base import LoginRequiredError``
# imports keep working.
__all__ = ["LoginRequiredError"]

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


def _normalize_cdp_endpoint(endpoint: str) -> str:
    """Resolve a CDP endpoint hostname to an IP address.

    Chrome/Edge DevTools only accept ``/json`` requests whose ``Host`` header is
    ``localhost`` or a bare IP address — a hostname such as
    ``host.docker.internal`` is rejected with HTTP 500. Resolving the name to its
    IP (e.g. the Docker bridge gateway) lets Docker users simply paste
    ``http://host.docker.internal:9222``.
    """
    try:
        parsed = urlparse(endpoint)
        host = parsed.hostname or ""
        if host and host.lower() not in ("localhost", "127.0.0.1", "::1"):
            try:
                ipaddress.ip_address(host)
                return endpoint  # already an IP
            except ValueError:
                resolved = socket.gethostbyname(host)
                return urlunparse(parsed._replace(netloc=f"{resolved}:{parsed.port}"))
    except Exception:  # noqa: BLE001 - never block browser startup on this
        return endpoint
    return endpoint


def reraise_if_terminal(exc: BaseException) -> None:
    """Let already-classified *permanent* adapter errors escape untouched.

    Every browser adapter ends its scrape in a broad ``except Exception`` that
    re-wraps the failure into :class:`TransientAdapterError` so the scheduler can
    retry flaky pages. That wrapper is correct for genuine transient faults, but
    it also used to swallow errors the adapter had *already* classified as
    permanent — a login wall, a deleted account, a broken contract. Re-wrapping
    them flips ``retryable`` from ``False`` to ``True``, so the scheduler burns
    the full retry budget on a failure that can never succeed (Bilibili's login
    wall alone cost ~26s x N retries per account, every hour, forever) and the
    operator sees a useless "retry_exhausted" instead of "configure a cookie".

    Calling this first preserves each error's own ``retryable`` verdict. It is a
    pure function: no IO, no logging, safe to call from any adapter.
    """
    if isinstance(exc, PlatformAdapterError) and not exc.retryable:
        raise exc


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
        self._browsers: dict[str, Browser] = {}
        self._cdp_browsers: set[str] = set()
        self._session_states: dict[str, StorageState] = {}

    def _credential_cache_key(self, ctx: AdapterCallContext) -> str | None:
        username = ctx.config.get("username")
        password = ctx.config.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        return hashlib.sha256(f"{self.key}\0{username}\0{password}".encode()).hexdigest()

    def _proxy_from_config(self, ctx: AdapterCallContext) -> ProxySettings | None:
        """Build a Playwright proxy dict from the workspace credential config.

        Residential/rotating proxies are the practical way to avoid datacenter-IP
        anti-bot walls on TikTok/Douyin when an authorized session is supplied.
        """
        server = ctx.config.get("proxy_server")
        if not isinstance(server, str) or not server.strip():
            return None
        server = server.strip()
        if not server.startswith(("http://", "https://", "socks5://", "socks4://")):
            server = f"http://{server}"
        proxy: ProxySettings = {"server": server}
        username = ctx.config.get("proxy_username")
        password = ctx.config.get("proxy_password")
        if isinstance(username, str) and username:
            proxy["username"] = username
        if isinstance(password, str) and password:
            proxy["password"] = password
        return proxy

    async def _ensure_browser(self, ctx: AdapterCallContext | None = None) -> Browser:
        """Lazily acquire a browser instance.

        Selection order (lets the project reuse the operator's *real* browser to
        bypass datacenter-headless anti-bot walls on TikTok/Douyin):

        1. CDP endpoint (``cdp_endpoint`` config or ``SIO_BROWSER_CDP_ENDPOINT`` env):
           connect to an already-running local Chrome/Edge launched by the user
           (same fingerprint, same residential IP, same login cookies). This is the
           recommended mode for TikTok/Douyin.
        2. Local real-browser launch (``launch_mode=='local'``): spawn the host's
           ownChrome/Edge binary headful (real fingerprint) instead of the bundled
           headless Chromium.
        3. Default: the bundled headless Chromium, optionally behind a proxy.
        """
        # 1) Connect to the operator's real local browser over CDP.
        cdp = (ctx.config.get("cdp_endpoint") if ctx is not None else None) or os.environ.get(
            "SIO_BROWSER_CDP_ENDPOINT"
        )
        if cdp and cdp.strip():
            cdp = _normalize_cdp_endpoint(cdp.strip())
            existing = self._browsers.get(cdp)
            if existing is not None and existing.is_connected():
                return existing
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            logger.info("Connecting to local browser over CDP: %s", cdp)
            browser = await self._playwright.chromium.connect_over_cdp(cdp)
            self._cdp_browsers.add(cdp)
            self._browsers[cdp] = browser
            return browser

        # 2) Launch the host's real browser binary headful (real fingerprint).
        launch_mode = (
            ctx.config.get("launch_mode") if ctx is not None else None
        ) or os.environ.get("SIO_BROWSER_LAUNCH_MODE")
        if launch_mode == "local":
            existing = self._browsers.get("local")
            if existing is not None and existing.is_connected():
                return existing
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            launch_kwargs: dict[str, Any] = {
                "headless": False,
                "args": [
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            }
            exe = ctx.config.get("browser_executable_path") if ctx is not None else None
            channel = ctx.config.get("browser_channel") if ctx is not None else None
            if exe:
                launch_kwargs["executable_path"] = exe
            elif channel:
                launch_kwargs["channel"] = channel
            ud = ctx.config.get("user_data_dir") if ctx is not None else None
            if ud:
                launch_kwargs["user_data_dir"] = ud
            logger.info("Launching local real browser (headful)")
            self._browsers["local"] = await self._playwright.chromium.launch(**launch_kwargs)
            return self._browsers["local"]

        # 3) Default: bundled headless Chromium (optionally behind a proxy).
        proxy = self._proxy_from_config(ctx) if ctx is not None else None
        cache_key = proxy["server"] if proxy else "direct"
        existing = self._browsers.get(cache_key)
        if existing is not None and existing.is_connected():
            return existing
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        # --disable-blink-features=AutomationControlled hides the WebDriver flag
        # that many anti-bot systems use to fingerprint headless Chromium.
        self._browsers[cache_key] = await self._playwright.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
            proxy=proxy,
        )
        return self._browsers[cache_key]

    async def _new_context(self, ctx: AdapterCallContext) -> BrowserContext:
        """Create an isolated browser context for public-page sampling."""
        browser = await self._ensure_browser(ctx)
        cache_key = self._credential_cache_key(ctx)
        storage_state: StorageState | None = self._session_states.get(cache_key or "")
        raw_storage_state = ctx.config.get("storage_state_json")
        if isinstance(raw_storage_state, str) and raw_storage_state:
            try:
                parsed_state = json.loads(raw_storage_state)
            except json.JSONDecodeError as exc:
                raise LoginRequiredError(self.descriptor.name, "加密会话状态不是有效 JSON") from exc
            if not isinstance(parsed_state, dict):
                raise LoginRequiredError(self.descriptor.name, "加密会话状态格式无效")
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

    async def _navigate(
        self,
        ctx: AdapterCallContext,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout: int | None = None,
        max_attempts: int = 3,
        response_handler: Any | None = None,
    ) -> tuple[BrowserContext, Page]:
        """Open a fresh context and navigate to ``url`` with bounded retry.

        Anti-bot platforms (notably TikTok) frequently reset the TCP connection
        mid-navigation (``net::ERR_CONNECTION_CLOSED``). A brand-new context/page
        usually recovers, so each attempt recreates the context; a single
        transient drop should not fail the whole scrape.

        ``response_handler`` (if given) is registered on the page *before* each
        navigation attempt, so callers that intercept XHR responses (e.g. TikTok's
        embedded user-detail JSON) still capture them across retries.
        """
        timeout = timeout or self.page_load_timeout_ms
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            context: BrowserContext | None = None
            try:
                self._progress(
                    ctx,
                    f"[{self.key}] 打开页面 {url}"
                    + (f"（第 {attempt}/{max_attempts} 次尝试）" if attempt > 1 else ""),
                )
                context, page = await self._new_page(ctx)
                if response_handler is not None:
                    page.on("response", response_handler)
                await page.goto(url, wait_until=wait_until, timeout=timeout)
                self._progress(ctx, f"[{self.key}] 页面已加载，开始解析")
                return context, page
            except Exception as exc:  # noqa: BLE001 - transient network resets
                last_exc = exc
                logger.warning(
                    "navigate attempt %d/%d to %s failed: %s: %s",
                    attempt, max_attempts, url, type(exc).__name__, exc,
                )
                self._progress(
                    ctx,
                    f"[{self.key}] 打开失败（{type(exc).__name__}），"
                    + ("准备重试…" if attempt < max_attempts else "已达最大重试次数"),
                )
                if context is not None:
                    try:
                        await context.close()
                    except Exception:
                        pass
                if attempt < max_attempts:
                    await asyncio.sleep(min(2.0 * attempt, 8.0) + random.uniform(0, 1.5))
        assert last_exc is not None
        raise last_exc

    def _progress(self, ctx: AdapterCallContext | None, text: str) -> None:
        """Emit one live log line for the sync run, if a sink is attached.

        Shared by all four browser platforms so the account page shows a
        scrolling log for TikTok/Douyin/Bilibili/YouTube, not just for the
        yt-dlp path.

        This is observability only: a broken or missing sink must never abort a
        sync. (A previous revision passed a non-callable sink and took every
        sync run down with ``TypeError``, so the guard here is deliberate.)
        """
        sink = getattr(ctx, "progress_sink", None)
        if sink is None:
            return
        try:
            sink(text)
        except Exception:  # noqa: BLE001 - never let logging break a sync
            logger.debug("progress sink rejected a line", exc_info=True)

    async def _polite_delay(self, multiplier: float = 1.0) -> None:
        """Wait between interactions to respect the target site's capacity."""
        delay = ((self._min_delay + self._max_delay) / 2) * multiplier
        await asyncio.sleep(delay)

    async def _scroll_page(
        self, page: Page, times: int = 3, *, ctx: AdapterCallContext | None = None
    ) -> None:
        """Scroll the page incrementally to trigger lazy-loaded content."""
        for index in range(times):
            await page.mouse.wheel(0, 450)
            await self._polite_delay(0.5)
            self._progress(ctx, f"[{self.key}] 滚动加载 {index + 1}/{times}")

    async def _check_login_required(self, page: Page, platform_name: str) -> None:
        """Detect if the platform is showing a login wall.

        Checks current URL for login redirects and DOM for login overlays.
        Raises LoginRequiredError if a login wall is detected and no
        credentials are available to retry.
        """
        current_url = page.url.lower()
        for pattern in LOGIN_URL_PATTERNS:
            if pattern in current_url:
                raise LoginRequiredError(platform_name, f"被重定向到登录页: {page.url[:80]}")
        # Check for login wall overlays in DOM.
        for selector in LOGIN_WALL_SELECTORS:
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=500):
                    raise LoginRequiredError(platform_name, f"检测到登录弹窗 ({selector})")
            except LoginRequiredError:
                raise
            except Exception as exc:
                logger.debug(
                    "login wall selector check failed",
                    extra={"selector": selector, "error_type": type(exc).__name__},
                )
                continue

    async def _login_if_configured(self, page: Page, ctx: AdapterCallContext) -> bool:
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
        """Shut down browser and Playwright.

        CDP-connected browsers belong to the operator's real local browser, so we
        must NOT close them (that would terminate the user's Edge/Chrome). We only
        drop the reference. Locally-launched and bundled browsers are closed.
        """
        for key, browser in list(self._browsers.items()):
            if key in self._cdp_browsers:
                continue
            try:
                await browser.close()
            except Exception:  # noqa: S110
                pass
        self._browsers.clear()
        self._cdp_browsers.clear()
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._session_states.clear()
