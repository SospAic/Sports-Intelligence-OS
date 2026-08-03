# ruff: noqa: E501, I001, S110
"""TikTok browser-simulation adapter.

Scrapes public TikTok profile pages using a headless browser. No API key
required — works by rendering the page and extracting data from the DOM
or intercepting XHR responses.

Supports:
- No credentials: scrapes public profile info and video lists.
- Optional login for authenticated content.

Registered as 'tiktok_browser', coexists with the API-based 'tiktok' adapter.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from playwright.async_api import Page

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterCapability,
    AdapterContractError,
    AdapterDescriptor,
    AdapterNotFoundError,
    AdapterPage,
    PlatformAccountData,
    PlatformContentData,
    PlatformMetricsData,
    TransientAdapterError,
)
from app.adapters.platforms.browser_base import BrowserPlatformAdapter, LoginRequiredError

logger = logging.getLogger(__name__)

TIKTOK_PROFILE_URL = "https://www.tiktok.com/@{username}"
TIKTOK_VIDEO_URL = "https://www.tiktok.com/@{username}/video/{video_id}"


class TikTokBrowserAdapter(BrowserPlatformAdapter):
    """Scrapes TikTok public pages via headless Chromium."""

    descriptor = AdapterDescriptor(
        key="tiktok_browser",
        name="TikTok（合规公开页）",
        implementation_status="implemented",
        capabilities={
            AdapterCapability.PUBLIC_PROFILE: True,
            AdapterCapability.ACCOUNT_ANALYTICS: True,
            AdapterCapability.CONTENT_LIST: True,
            AdapterCapability.CONTENT_ANALYTICS: False,
            AdapterCapability.TRAFFIC_SOURCES: False,
            AdapterCapability.RETENTION: False,
            AdapterCapability.REVENUE: False,
            AdapterCapability.COMMENTS: False,
            AdapterCapability.SEARCH_TERMS: False,
        },
        config_fields=(),
        source_kinds=frozenset({"live"}),
    )

    min_action_delay = 1.5
    max_action_delay = 4.0

    async def _login_if_configured(
        self, page: Page, ctx: AdapterCallContext
    ) -> bool:
        await page.goto(
            "https://www.tiktok.com/login/phone-or-email/email",
            wait_until="domcontentloaded",
            timeout=self.page_load_timeout_ms,
        )
        await page.locator(
            "input[name='username'], input[autocomplete='username']"
        ).first.fill(str(ctx.config.get("username", "")))
        await page.locator("input[type='password']").first.fill(
            str(ctx.config.get("password", ""))
        )
        await page.locator(
            "button[type='submit'], button[data-e2e='login-button']"
        ).first.click()
        await page.wait_for_timeout(3000)
        challenge = page.locator(
            "iframe[src*='captcha'], [class*='captcha'], [id*='captcha']"
        ).first
        if "login" in page.url.lower() or await challenge.is_visible(timeout=500):
            raise LoginRequiredError(
                "TikTok", "登录需要验证码、2FA 或其他人工验证"
            )
        return True

    async def resolve_account(
        self, ctx: AdapterCallContext, locator: str
    ) -> PlatformAccountData:
        """Navigate to the profile page and extract account info."""
        username = locator.lstrip("@")
        if not username:
            raise AdapterContractError(f"cannot extract username from locator: {locator}")

        context, page = await self._new_page(ctx)
        try:
            # Intercept SIGI_STATE or __UNIVERSAL_DATA_FOR_REHYDRATION__
            profile_data: dict[str, Any] | None = None

            async def _capture(response: Any) -> None:
                nonlocal profile_data
                if profile_data is not None:
                    return
                url = response.url
                if "/api/user/detail" in url or "/api/post/item_list" in url:
                    try:
                        data = await response.json()
                        if "userInfo" in data:
                            profile_data = data["userInfo"]
                    except Exception:
                        pass

            page.on("response", _capture)

            url = TIKTOK_PROFILE_URL.format(username=username)
            await page.goto(url, wait_until="domcontentloaded", timeout=self.page_load_timeout_ms)
            await self._polite_delay(2.0)

            # Try to extract from embedded JSON (SIGI_STATE).
            display_name = ""
            avatar_url = None
            description = None
            follower_count = None

            if profile_data:
                user = profile_data.get("user", {})
                display_name = user.get("nickname", "")
                avatar_url = user.get("avatarLarger") or user.get("avatarMedium")
                description = user.get("signature") or None
                stats = profile_data.get("stats", {})
                follower_count = stats.get("followerCount")

            # Fallback: DOM extraction.
            if not display_name:
                try:
                    name_el = page.locator("[data-e2e='user-title'], .tiktok-j2a19r-Span, h1[data-e2e='browse-user-nickname']").first
                    display_name = (await name_el.inner_text()).strip()
                except Exception:
                    pass
            if not display_name:
                try:
                    # Try embedded script data
                    script_data = await page.evaluate("""() => {
                        const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
                        if (el) return JSON.parse(el.textContent);
                        const sigi = document.getElementById('SIGI_STATE');
                        if (sigi) return JSON.parse(sigi.textContent);
                        return null;
                    }""")
                    if script_data:
                        user_module = script_data.get("__DEFAULT_SCOPE__", {}).get("webapp.user-detail", {})
                        user_info = user_module.get("userInfo", {})
                        user = user_info.get("user", {})
                        display_name = user.get("nickname", "")
                        avatar_url = avatar_url or user.get("avatarLarger")
                        description = description or user.get("signature") or None
                        stats = user_info.get("stats", {})
                        follower_count = follower_count or stats.get("followerCount")
                except Exception:
                    pass
            if not display_name:
                display_name = f"@{username}"

            if not avatar_url:
                try:
                    img_el = page.locator("[data-e2e='browse-user-avatar'] img, .tiktok-1zpj2q-ImgAvatar img").first
                    avatar_url = await img_el.get_attribute("src")
                except Exception:
                    pass

            return PlatformAccountData(
                external_id=username,
                username=username,
                display_name=display_name,
                profile_url=url,
                avatar_url=avatar_url,
                description=description,
                country=None,
                language="en",
                is_verified=None,
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                metadata={
                    "method": "browser_scrape",
                    "locator": locator,
                    "follower_count": follower_count,
                },
            )
        except Exception as exc:
            if isinstance(exc, (AdapterContractError, AdapterNotFoundError)):
                raise
            raise TransientAdapterError(
                f"browser scrape failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            await context.close()

    async def fetch_account(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformAccountData:
        return await self.resolve_account(ctx, external_id)

    async def fetch_account_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformMetricsData:
        """Extract follower/like counts from the profile page."""
        username = external_id.lstrip("@")
        context, page = await self._new_page(ctx)
        try:
            url = TIKTOK_PROFILE_URL.format(username=username)
            await page.goto(url, wait_until="domcontentloaded", timeout=self.page_load_timeout_ms)
            await self._polite_delay(2.0)

            follower_count = None
            like_count = None
            video_count = None

            # Try embedded JSON data.
            try:
                script_data = await page.evaluate("""() => {
                    const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
                    if (el) return JSON.parse(el.textContent);
                    const sigi = document.getElementById('SIGI_STATE');
                    if (sigi) return JSON.parse(sigi.textContent);
                    return null;
                }""")
                if script_data:
                    user_module = script_data.get("__DEFAULT_SCOPE__", {}).get("webapp.user-detail", {})
                    stats = user_module.get("userInfo", {}).get("stats", {})
                    follower_count = stats.get("followerCount")
                    like_count = stats.get("heartCount")
                    video_count = stats.get("videoCount")
            except Exception:
                pass

            # Fallback: DOM.
            if follower_count is None:
                try:
                    el = page.locator("[data-e2e='followers-count']").first
                    follower_count = self._parse_count(await el.inner_text())
                except Exception:
                    pass
            if like_count is None:
                try:
                    el = page.locator("[data-e2e='likes-count']").first
                    like_count = self._parse_count(await el.inner_text())
                except Exception:
                    pass

            metrics: dict[str, int | float | None] = {
                "follower_count": follower_count,
                "total_like_count": like_count,
                "video_count": video_count,
            }
            unavailable = tuple(k for k, v in metrics.items() if v is None)
            extraction_failed = (
                follower_count is None and like_count is None and video_count is None
            )
            if extraction_failed:
                logger.warning(
                    "tiktok_browser: all metrics extraction failed for %s — "
                    "anti-bot wall or page structure changed",
                    username,
                )
            return PlatformMetricsData(
                external_id=username,
                captured_at=ctx.observed_at,
                metrics=metrics,
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                unavailable_metrics=unavailable,
                metadata={"method": "browser_scrape", "extraction_failure": extraction_failed},
            )
        finally:
            await context.close()

    async def list_contents(
        self,
        ctx: AdapterCallContext,
        external_account_id: str,
        *,
        published_after: datetime | None,
        cursor: str | None,
        page_size: int,
    ) -> AdapterPage:
        """Scrape the video list from the profile page."""
        username = external_account_id.lstrip("@")
        context, page = await self._new_page(ctx)
        try:
            url = TIKTOK_PROFILE_URL.format(username=username)
            await page.goto(url, wait_until="domcontentloaded", timeout=self.page_load_timeout_ms)
            await self._polite_delay(2.0)
            # Scroll further than the default (10×) so TikTok lazily renders more
            # of the video grid before we scrape the anchors.
            await self._scroll_page(page, times=10)

            # The video grid renders as anchors whose href contains "/video/".
            # (Legacy selectors such as [data-e2e='user-post-item'] are no longer
            # reliable; the href-based approach works on the current DOM and on a
            # real local browser driven over CDP.)
            try:
                await page.wait_for_selector("a[href*='/video/']", timeout=12_000)
            except Exception:
                return AdapterPage(items=(), next_cursor=None)

            items: list[PlatformContentData] = []
            anchors = page.locator("a[href*='/video/']")
            count = await anchors.count()

            for i in range(min(count, page_size)):
                try:
                    anchor = anchors.nth(i)
                    href = await anchor.get_attribute("href") or ""
                    vid_match = re.search(r"/video/(\d+)", href)
                    if not vid_match:
                        continue
                    video_id = vid_match.group(1)

                    title = ""
                    try:
                        title = (await anchor.get_attribute("aria-label") or "").strip()
                    except Exception:
                        pass
                    if not title:
                        try:
                            title = (await anchor.inner_text()).strip()
                        except Exception:
                            pass
                    if not title:
                        title = f"Video {i + 1}"

                    cover_url = None
                    try:
                        img_el = anchor.locator("img").first
                        cover_url = await img_el.get_attribute("src")
                    except Exception:
                        pass

                    # Best-effort view count from the card text (e.g. "1.2M views").
                    view_count = None
                    try:
                        card_text = await anchor.inner_text()
                        vm = re.search(r"([\d.,]+\s*[KMB]?)\s*views?", card_text, re.I)
                        if vm:
                            view_count = self._parse_count(vm.group(1))
                    except Exception:
                        pass

                    canonical = TIKTOK_VIDEO_URL.format(username=username, video_id=video_id)
                    items.append(
                        PlatformContentData(
                            external_id=video_id or f"{username}_v{i}",
                            account_external_id=username,
                            content_type="video",
                            title=title,
                            description=None,
                            published_at=None,
                            duration_seconds=None,
                            canonical_url=canonical,
                            cover_url=cover_url,
                            language="en",
                            status="public",
                            source_kind="live",
                            provider=self.key,
                            fetched_at=ctx.observed_at,
                            metadata={
                                "method": "browser_scrape",
                                "view_count": view_count,
                            },
                        )
                    )
                except Exception as exc:
                    logger.debug("skip card %d: %s", i, exc)
                    continue

            return AdapterPage(items=tuple(items), next_cursor=None)
        except Exception as exc:
            if isinstance(exc, (AdapterContractError, AdapterNotFoundError)):
                raise
            raise TransientAdapterError(
                f"browser list_contents failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            await context.close()

    async def fetch_content(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformContentData:
        """Fetch a single video page."""
        context, page = await self._new_page(ctx)
        try:
            # external_id might be just the video ID; construct a generic URL.
            url = f"https://www.tiktok.com/video/{external_id}"
            await page.goto(url, wait_until="domcontentloaded")
            await self._polite_delay(1.5)

            title = await page.title()
            title = title.replace(" | TikTok", "").strip()

            cover_url = None
            try:
                og_img = page.locator("meta[property='og:image']")
                cover_url = await og_img.get_attribute("content")
            except Exception:
                pass

            return PlatformContentData(
                external_id=external_id,
                account_external_id="",
                content_type="video",
                title=title or external_id,
                description=None,
                published_at=None,
                duration_seconds=None,
                canonical_url=url,
                cover_url=cover_url,
                language="en",
                status="public",
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                metadata={"method": "browser_scrape"},
            )
        finally:
            await context.close()

    async def fetch_content_analytics(
        self, ctx: AdapterCallContext, external_ids: Sequence[str]
    ) -> tuple[PlatformMetricsData, ...]:
        return tuple(
            PlatformMetricsData(
                external_id=eid,
                captured_at=ctx.observed_at,
                metrics={},
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                unavailable_metrics=("view_count", "like_count", "comment_count", "share_count"),
                metadata={"method": "browser_scrape", "note": "analytics not available via browser"},
            )
            for eid in external_ids
        )

    @staticmethod
    def _parse_count(text: str) -> int | None:
        """Parse '1.2M', '456K', '789' into integer."""
        text = text.strip().upper().replace(",", "")
        m = re.match(r"([\d.]+)\s*([KM]?)", text)
        if not m:
            return None
        num = float(m.group(1))
        suffix = m.group(2)
        if suffix == "K":
            return int(num * 1_000)
        if suffix == "M":
            return int(num * 1_000_000)
        return int(num)
