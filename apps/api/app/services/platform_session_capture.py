"""Capture an already-authorized browser session through a local CDP endpoint.

The user completes the platform login in a normal browser. This module only
reads the resulting cookies from that browser and never automates passwords,
CAPTCHA, MFA, or other security challenges.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

from playwright.async_api import async_playwright


class BrowserSessionCaptureError(RuntimeError):
    """A safe, user-actionable error while attaching to the local browser."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


PLATFORM_LOGIN_URLS: dict[str, str] = {
    "youtube": "https://accounts.google.com/ServiceLogin?service=youtube",
    "tiktok": "https://www.tiktok.com/login/phone-or-email/email",
    # The public home page only shows a login modal after navigation. Use the
    # official SSO entry so the Docker browser visibly opens the Douyin login
    # flow just like the other platforms.
    "douyin": "https://sso.douyin.com/?service=www.douyin.com%2Flogin",
    "bilibili": "https://passport.bilibili.com/login",
}

PLATFORM_COOKIE_DOMAINS: dict[str, tuple[str, ...]] = {
    "youtube": ("youtube.com", "google.com"),
    "tiktok": ("tiktok.com",),
    "douyin": ("douyin.com",),
    "bilibili": ("bilibili.com",),
}

AUTH_COOKIE_HINTS: dict[str, frozenset[str]] = {
    "youtube": frozenset({"login_info", "sapisid", "__secure-3papisid", "sid"}),
    "tiktok": frozenset({"sessionid", "sid_tt", "uid_tt", "uid_tt_ss"}),
    "douyin": frozenset({"sessionid", "sid_guard", "passport_csrf_token", "uid_tt", "uid_tt_ss"}),
    "bilibili": frozenset({"sessdata", "bili_jct", "dedeuserid", "sid"}),
}

# Only local browser debugging endpoints are accepted. This prevents the
# endpoint field from becoming a general SSRF primitive.
ALLOWED_CDP_HOSTS = frozenset(
    {
        "browser",
        "localhost",
        "127.0.0.1",
        "::1",
        "host.docker.internal",
        "gateway.docker.internal",
    }
)


@dataclass(frozen=True)
class CapturedBrowserSession:
    storage_state_json: str
    cookies_netscape: str
    session_expires_at: str
    page_url: str
    cookie_count: int


def validate_cdp_endpoint(raw_endpoint: str) -> str:
    endpoint = raw_endpoint.strip().rstrip("/")
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise BrowserSessionCaptureError(
            "CDP 地址必须是 http(s) URL，且不能包含账号密码",
            code="cdp_endpoint_invalid",
        )
    if host not in ALLOWED_CDP_HOSTS:
        raise BrowserSessionCaptureError(
            "为安全起见，CDP 地址仅允许本机或 Docker 主机网关",
            code="cdp_endpoint_not_local",
        )
    return endpoint


def _domain_matches(cookie_domain: str, allowed_domains: tuple[str, ...]) -> bool:
    domain = cookie_domain.lstrip(".").lower().rstrip(".")
    return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in allowed_domains)


def _looks_authenticated(platform_key: str, cookies: list[dict[str, object]]) -> bool:
    hints = AUTH_COOKIE_HINTS.get(platform_key, frozenset())
    for cookie in cookies:
        name = str(cookie.get("name") or "").casefold()
        if name in hints or any(
            token in name for token in ("session", "login", "sapisid", "sessdata")
        ):
            return True
    return False


def _netscape_cookie_line(cookie: dict[str, object]) -> str:
    domain = str(cookie.get("domain") or "")
    include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
    path = str(cookie.get("path") or "/")
    secure = "TRUE" if cookie.get("secure") else "FALSE"
    raw_expiry = cookie.get("expires")
    try:
        expiry = int(float(str(raw_expiry))) if raw_expiry and float(str(raw_expiry)) > 0 else 0
    except (TypeError, ValueError):
        expiry = 0
    name = str(cookie.get("name") or "").replace("\t", " ").replace("\n", " ")
    value = str(cookie.get("value") or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return "\t".join((domain, include_subdomains, path, secure, str(expiry), name, value))


def _to_netscape(cookies: list[dict[str, object]]) -> str:
    lines = [
        "# Netscape HTTP Cookie File",
        "# Generated from a user-authorized browser session; do not share.",
    ]
    lines.extend(_netscape_cookie_line(cookie) for cookie in cookies)
    return "\n".join(lines) + "\n"


def _session_expiry(cookies: list[dict[str, object]]) -> datetime:
    now = datetime.now(UTC)
    expiries: list[datetime] = []
    for cookie in cookies:
        raw = cookie.get("expires")
        try:
            timestamp = float(str(raw)) if raw is not None else 0
        except (TypeError, ValueError):
            timestamp = 0
        if timestamp > now.timestamp():
            expiries.append(datetime.fromtimestamp(timestamp, tz=UTC))
    # Session cookies have no platform-provided expiry. Use a conservative
    # seven-day reauthorization window rather than pretending they are eternal.
    return min(expiries) if expiries else now + timedelta(days=7)


def _storage_state_for_platform(
    state: dict[str, object], cookies: list[dict[str, object]], allowed_domains: tuple[str, ...]
) -> dict[str, object]:
    origins: list[dict[str, object]] = []
    raw_origins = state.get("origins")
    if not isinstance(raw_origins, list):
        raw_origins = []
    for origin in raw_origins:
        if not isinstance(origin, dict):
            continue
        host = urlsplit(str(origin.get("origin") or "")).hostname or ""
        if _domain_matches(host, allowed_domains):
            origins.append(origin)
    return {"cookies": cookies, "origins": origins}


def _pick_page(contexts: list[object], allowed_domains: tuple[str, ...]) -> tuple[Any, Any]:
    for context in contexts:
        for page in getattr(context, "pages", []):
            host = urlsplit(page.url).hostname or ""
            if _domain_matches(host, allowed_domains):
                return context, page
    return None, None


def _resolve_cdp_websocket_endpoint(endpoint: str) -> str:
    """Resolve and normalize Chromium's websocket URL before Playwright connects.

    Chromium reports a loopback websocket URL even when its HTTP CDP endpoint is
    reached through a Docker service or a host gateway. Playwright's HTTP
    convenience path can then try that loopback address from the API container.
    Resolving the URL explicitly keeps the browser host/port used by the
    caller while still supporting ordinary local Chrome endpoints.
    """
    parsed_endpoint = urlsplit(endpoint)
    if parsed_endpoint.scheme not in {"http", "https"}:
        return endpoint
    version_url = f"{endpoint}/json/version"
    with urlopen(version_url, timeout=10) as response:  # noqa: S310 - endpoint validated above
        payload = json.load(response)
    websocket_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
    parsed_websocket = urlsplit(websocket_url)
    if parsed_websocket.scheme not in {"ws", "wss"} or not parsed_websocket.hostname:
        raise BrowserSessionCaptureError(
            "CDP 未返回可用的 WebSocket 地址",
            code="cdp_websocket_unavailable",
        )
    if parsed_websocket.hostname.lower().rstrip(".") not in {"127.0.0.1", "localhost", "::1"}:
        return websocket_url
    host = parsed_endpoint.hostname or parsed_websocket.hostname
    port = parsed_endpoint.port or (443 if parsed_endpoint.scheme == "https" else 80)
    netloc = f"[{host}]:{port}" if ":" in host and not host.startswith("[") else f"{host}:{port}"
    return urlunsplit(
        (
            "wss" if parsed_endpoint.scheme == "https" else "ws",
            netloc,
            parsed_websocket.path,
            parsed_websocket.query,
            parsed_websocket.fragment,
        )
    )


async def _connect_browser(playwright: Any, endpoint: str) -> Any:
    websocket_endpoint = await asyncio.to_thread(_resolve_cdp_websocket_endpoint, endpoint)
    return await playwright.chromium.connect_over_cdp(websocket_endpoint, timeout=15_000)


async def open_login_page(cdp_endpoint: str, platform_key: str) -> str:
    """Open the platform login page in the user's already-running browser."""

    endpoint = validate_cdp_endpoint(cdp_endpoint)
    login_url = PLATFORM_LOGIN_URLS.get(platform_key)
    if not login_url:
        raise BrowserSessionCaptureError(
            "该平台暂不支持人工浏览器授权", code="platform_not_supported"
        )
    playwright = await async_playwright().start()
    try:
        try:
            browser = await _connect_browser(playwright, endpoint)
        except Exception as exc:  # noqa: BLE001 - hide endpoint internals
            raise BrowserSessionCaptureError(
                "无法连接本机浏览器，请确认已用 remote-debugging-port 启动",
                code="cdp_connect_failed",
            ) from exc
        contexts = list(browser.contexts)
        if not contexts:
            raise BrowserSessionCaptureError(
                "CDP 浏览器没有可用的浏览器上下文",
                code="cdp_context_unavailable",
            )
        context = contexts[0]
        page = await context.new_page()
        await page.goto(login_url, wait_until="domcontentloaded", timeout=30_000)
        # A remote CDP browser may keep the previously selected tab visible in
        # noVNC unless the newly opened platform page is explicitly foregrounded.
        await page.bring_to_front()
        return login_url
    except BrowserSessionCaptureError:
        raise
    except Exception as exc:  # noqa: BLE001 - convert browser errors
        raise BrowserSessionCaptureError(
            "打开平台登录页失败，请检查浏览器连接和网络",
            code="login_page_open_failed",
        ) from exc
    finally:
        # Stop the Playwright client without taking ownership of the user's
        # Chrome/Edge process. The page remains open in that browser.
        await playwright.stop()


async def capture_session(cdp_endpoint: str, platform_key: str) -> CapturedBrowserSession:
    """Read and serialize cookies after the user has completed login."""

    endpoint = validate_cdp_endpoint(cdp_endpoint)
    allowed_domains = PLATFORM_COOKIE_DOMAINS.get(platform_key)
    if not allowed_domains:
        raise BrowserSessionCaptureError(
            "该平台暂不支持人工浏览器授权", code="platform_not_supported"
        )
    playwright = await async_playwright().start()
    try:
        try:
            browser = await _connect_browser(playwright, endpoint)
        except Exception as exc:  # noqa: BLE001 - hide endpoint internals
            raise BrowserSessionCaptureError(
                "无法连接本机浏览器，请确认登录浏览器仍在运行",
                code="cdp_connect_failed",
            ) from exc
        context, page = _pick_page(list(browser.contexts), allowed_domains)
        if context is None or page is None:
            raise BrowserSessionCaptureError(
                "未找到该平台的浏览器页面，请先点击打开登录页并完成人工登录",
                code="platform_page_not_found",
            )
        all_cookies = await context.cookies()
        cookies = [
            dict(cookie)
            for cookie in all_cookies
            if _domain_matches(str(cookie.get("domain") or ""), allowed_domains)
        ]
        if not cookies or not _looks_authenticated(platform_key, cookies):
            raise BrowserSessionCaptureError(
                "未检测到已登录会话，请在浏览器中完成登录后再保存",
                code="browser_session_not_authenticated",
            )
        raw_state = await context.storage_state()
        state = _storage_state_for_platform(raw_state, cookies, allowed_domains)
        storage_state_json = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        cookies_netscape = _to_netscape(cookies)
        if len(storage_state_json) > 262_144 or len(cookies_netscape) > 262_144:
            raise BrowserSessionCaptureError(
                "登录会话过大，未保存；请关闭无关标签页后重试",
                code="browser_session_too_large",
            )
        return CapturedBrowserSession(
            storage_state_json=storage_state_json,
            cookies_netscape=cookies_netscape,
            session_expires_at=_session_expiry(cookies).isoformat(),
            page_url=page.url,
            cookie_count=len(cookies),
        )
    except BrowserSessionCaptureError:
        raise
    except Exception as exc:  # noqa: BLE001 - convert browser errors
        raise BrowserSessionCaptureError(
            "读取浏览器登录会话失败，请保持浏览器运行后重试",
            code="browser_session_capture_failed",
        ) from exc
    finally:
        await playwright.stop()
