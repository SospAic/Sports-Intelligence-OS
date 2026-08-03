# ruff: noqa: E501, I001, S110
"""Douyin (抖音) browser-simulation adapter.

Scrapes public Douyin profile pages using a headless browser. No API key
required — works by rendering the page and extracting data from embedded
JSON or the DOM.

Supports:
- No credentials: scrapes public profile info and video lists.
- Optional login for authenticated content.

Registered as 'douyin_browser', coexists with the API-based 'douyin' adapter.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime
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

DOUYIN_PROFILE_URL = "https://www.douyin.com/user/{sec_uid}"
DOUYIN_VIDEO_URL = "https://www.douyin.com/video/{aweme_id}"


class DouyinBrowserAdapter(BrowserPlatformAdapter):
    """Scrapes Douyin public pages via headless Chromium."""

    descriptor = AdapterDescriptor(
        key="douyin_browser",
        name="抖音（合规公开页）",
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
    default_viewport_width = 1920
    default_viewport_height = 1080

    async def _login_if_configured(
        self, page: Page, ctx: AdapterCallContext
    ) -> bool:
        await page.goto(
            "https://www.douyin.com/",
            wait_until="domcontentloaded",
            timeout=self.page_load_timeout_ms,
        )
        login_button = page.get_by_text("登录", exact=True).first
        if await login_button.is_visible(timeout=1000):
            await login_button.click()
        await page.locator(
            "input[placeholder*='手机号'], input[name='username']"
        ).first.fill(str(ctx.config.get("username", "")))
        password_input = page.locator("input[type='password']").first
        if not await password_input.is_visible(timeout=1000):
            raise LoginRequiredError("抖音", "当前登录页不提供密码登录")
        await password_input.fill(str(ctx.config.get("password", "")))
        await page.locator("button[type='submit']").first.click()
        await page.wait_for_timeout(3000)
        challenge = page.locator(
            "iframe[src*='captcha'], [class*='captcha'], [id*='captcha']"
        ).first
        if await challenge.is_visible(timeout=500):
            raise LoginRequiredError("抖音", "登录需要验证码、2FA 或其他人工验证")
        return True

    async def resolve_account(
        self, ctx: AdapterCallContext, locator: str
    ) -> PlatformAccountData:
        """Navigate to the user's profile page and extract info."""
        sec_uid = locator.strip()
        if not sec_uid:
            raise AdapterContractError(f"cannot extract sec_uid from locator: {locator}")

        context, page = await self._new_page(ctx)
        try:
            # Intercept the user profile API.
            user_data: dict[str, Any] | None = None

            async def _capture(response: Any) -> None:
                nonlocal user_data
                if user_data is not None:
                    return
                url = response.url
                if "/aweme/v1/web/user/profile" in url or "/aweme/v1/web/im/user" in url:
                    try:
                        data = await response.json()
                        if data.get("status_code") == 0 and data.get("user"):
                            user_data = data["user"]
                    except Exception:
                        pass

            page.on("response", _capture)

            # Construct URL: if locator looks like a sec_uid, use it directly.
            if sec_uid.startswith("MS4wLjABAAAA") or len(sec_uid) > 50:
                url = DOUYIN_PROFILE_URL.format(sec_uid=sec_uid)
            else:
                # Might be a short ID or custom URL.
                url = f"https://www.douyin.com/user/{sec_uid}"

            await page.goto(url, wait_until="domcontentloaded", timeout=self.page_load_timeout_ms)
            await self._polite_delay(2.0)

            display_name = ""
            avatar_url = None
            description = None
            unique_id = None

            if user_data:
                display_name = user_data.get("nickname", "")
                # ``avatar_larger`` may be null (not just missing) on some
                # profiles; coalesce to {} before indexing to avoid a crash.
                avatar_larger = user_data.get("avatar_larger") or {}
                avatar_url = (avatar_larger.get("url_list") or [None])[0]
                description = user_data.get("signature") or None
                unique_id = user_data.get("unique_id") or user_data.get("short_id")

            # Fallback: try embedded RENDER_DATA.
            if not display_name:
                try:
                    render_data = await page.evaluate("""() => {
                        const el = document.getElementById('RENDER_DATA');
                        if (el) return JSON.parse(decodeURIComponent(el.textContent));
                        return null;
                    }""")
                    if render_data:
                        # Navigate the nested structure to find user info.
                        for _key, val in render_data.items():
                            if isinstance(val, dict):
                                user_info = val.get("user", {}).get("user", {})
                                if user_info.get("nickname"):
                                    display_name = user_info["nickname"]
                                    avatar_larger = user_info.get("avatar_larger") or {}
                                    avatar_url = avatar_url or (
                                        (avatar_larger.get("url_list") or [None])[0]
                                    )
                                    description = description or user_info.get("signature") or None
                                    unique_id = unique_id or user_info.get("unique_id")
                                    break
                except Exception:
                    pass

            # Fallback: DOM.
            if not display_name:
                try:
                    name_el = page.locator("[class*='user-name'], .kOLiJM, span[data-e2e='user-info'] .name").first
                    display_name = (await name_el.inner_text()).strip()
                except Exception:
                    pass
            if not display_name:
                raw_title = await page.title()
                display_name = raw_title.replace(" - 抖音", "").strip()
            if not display_name:
                display_name = f"用户 {sec_uid[:12]}"

            if not avatar_url:
                try:
                    img_el = page.locator("[class*='avatar'] img, .user-avatar img").first
                    avatar_url = await img_el.get_attribute("src")
                except Exception:
                    pass

            return PlatformAccountData(
                external_id=unique_id or sec_uid,
                username=unique_id,
                display_name=display_name,
                profile_url=url,
                avatar_url=avatar_url,
                description=description,
                country="CN",
                language="zh",
                is_verified=None,
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                metadata={"method": "browser_scrape", "locator": locator},
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
        context, page = await self._new_page(ctx)
        try:
            url = f"https://www.douyin.com/user/{external_id}"
            await page.goto(url, wait_until="domcontentloaded", timeout=self.page_load_timeout_ms)
            await self._polite_delay(2.0)

            follower_count = None
            like_count = None
            video_count = None

            # Try RENDER_DATA.
            try:
                render_data = await page.evaluate("""() => {
                    const el = document.getElementById('RENDER_DATA');
                    if (el) return JSON.parse(decodeURIComponent(el.textContent));
                    return null;
                }""")
                if render_data:
                    for _key, val in render_data.items():
                        if isinstance(val, dict):
                            user_info = (val.get("user") or {}).get("user", {})
                            if user_info:
                                follower_count = user_info.get("follower_count")
                                like_count = user_info.get("total_favorited")
                                video_count = user_info.get("aweme_count")
                                break
            except Exception:
                pass

            # Fallback: DOM.
            if follower_count is None:
                try:
                    el = page.locator("[data-e2e='user-fans'], [class*='fans'] span").first
                    follower_count = self._parse_count(await el.inner_text())
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
                    "douyin_browser: all metrics extraction failed for %s — "
                    "anti-bot wall or page structure changed",
                    external_id,
                )
            return PlatformMetricsData(
                external_id=external_id,
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
        """Scrape the video list from the user's profile page."""
        context, page = await self._new_page(ctx)
        try:
            # Intercept the post list API.
            post_data: list[dict[str, Any]] = []

            async def _capture(response: Any) -> None:
                url = response.url
                if "/aweme/v1/web/aweme/post" in url:
                    try:
                        data = await response.json()
                        if data.get("status_code") == 0:
                            aweme_list = data.get("aweme_list", [])
                            post_data.extend(aweme_list)
                    except Exception:
                        pass

            page.on("response", _capture)

            url = f"https://www.douyin.com/user/{external_account_id}"
            await page.goto(url, wait_until="domcontentloaded", timeout=self.page_load_timeout_ms)
            await self._polite_delay(2.0)
            await self._scroll_page(page, times=2)

            # If API interception got data, use it.
            if post_data:
                items: list[PlatformContentData] = []
                for aweme in post_data[:page_size]:
                    aweme_id = aweme.get("aweme_id", "")
                    desc = aweme.get("desc", "").strip() or f"视频 {len(items) + 1}"
                    cover = None
                    video_info = aweme.get("video") or {}
                    cover_obj = video_info.get("cover") or {}
                    cover_urls = cover_obj.get("url_list", [])
                    if cover_urls:
                        cover = cover_urls[0]
                    stats = aweme.get("statistics", {})
                    create_time = aweme.get("create_time")
                    pub_dt = datetime.fromtimestamp(create_time, tz=UTC) if create_time else None

                    items.append(
                        PlatformContentData(
                            external_id=aweme_id,
                            account_external_id=external_account_id,
                            content_type="video",
                            title=desc,
                            description=None,
                            published_at=pub_dt,
                            duration_seconds=video_info.get("duration"),
                            canonical_url=DOUYIN_VIDEO_URL.format(aweme_id=aweme_id),
                            cover_url=cover,
                            language="zh",
                            status="public",
                            source_kind="live",
                            provider=self.key,
                            fetched_at=ctx.observed_at,
                            metadata={
                                "method": "browser_api_intercept",
                                "digg_count": stats.get("digg_count"),
                                "comment_count": stats.get("comment_count"),
                                "share_count": stats.get("share_count"),
                                "play_count": stats.get("play_count"),
                            },
                        )
                    )
                has_more = len(post_data) >= page_size
                return AdapterPage(
                    items=tuple(items),
                    next_cursor=str(int(cursor or "0") + page_size) if has_more else None,
                )

            # Fallback: DOM scraping via the video-grid anchors. The video grid
            # renders as anchors whose href contains "/video/"; legacy selectors
            # ([data-e2e='user-post-item']) are no longer reliable and this works
            # on the current DOM and on a real local browser driven over CDP.
            try:
                await page.wait_for_selector("a[href*='/video/']", timeout=12_000)
            except Exception:
                return AdapterPage(items=(), next_cursor=None)

            items_dom: list[PlatformContentData] = []
            anchors = page.locator("a[href*='/video/']")
            count = await anchors.count()

            for i in range(min(count, page_size)):
                try:
                    anchor = anchors.nth(i)
                    href = await anchor.get_attribute("href") or ""
                    vid_match = re.search(r"/video/(\d+)", href)
                    if not vid_match:
                        continue
                    aweme_id = vid_match.group(1)

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
                        title = f"视频 {i + 1}"

                    cover_url = None
                    try:
                        cover_url = await anchor.locator("img").first.get_attribute("src")
                    except Exception:
                        pass

                    # Best-effort play count from the card text (e.g. "1.2万次播放").
                    play_count = None
                    try:
                        card_text = await anchor.inner_text()
                        pm = re.search(
                            r"([\d.,]+\s*[万亿]?\s*[Ww]?)\s*(播放|次播放|plays?)",
                            card_text,
                        )
                        if pm:
                            play_count = self._parse_count(pm.group(1))
                    except Exception:
                        pass

                    items_dom.append(
                        PlatformContentData(
                            external_id=aweme_id or f"{external_account_id}_v{i}",
                            account_external_id=external_account_id,
                            content_type="video",
                            title=title,
                            description=None,
                            published_at=None,
                            duration_seconds=None,
                            canonical_url=DOUYIN_VIDEO_URL.format(aweme_id=aweme_id) if aweme_id else url,
                            cover_url=cover_url,
                            language="zh",
                            status="public",
                            source_kind="live",
                            provider=self.key,
                            fetched_at=ctx.observed_at,
                            metadata={"method": "browser_dom_scrape", "play_count": play_count},
                        )
                    )
                except Exception as exc:
                    logger.debug("skip card %d: %s", i, exc)
                    continue

            return AdapterPage(items=tuple(items_dom), next_cursor=None)
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
            url = DOUYIN_VIDEO_URL.format(aweme_id=external_id)
            await page.goto(url, wait_until="domcontentloaded")
            await self._polite_delay(1.5)

            title = await page.title()
            title = title.replace(" - 抖音", "").strip()

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
                language="zh",
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
        """Parse '12.3万', '1.2亿', '456' into integer."""
        text = text.strip().replace(",", "")
        m = re.match(r"([\d.]+)\s*万", text)
        if m:
            return int(float(m.group(1)) * 10_000)
        m = re.match(r"([\d.]+)\s*亿", text)
        if m:
            return int(float(m.group(1)) * 100_000_000)
        m = re.match(r"(\d+)", text)
        if m:
            return int(m.group(1))
        return None
