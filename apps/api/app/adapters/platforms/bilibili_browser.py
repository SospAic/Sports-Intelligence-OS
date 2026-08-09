# ruff: noqa: E501, I001, S110
"""Bilibili Playwright adapter.

Reads Bilibili space pages through an isolated browser context. It supports
policy-approved anonymous sampling, encrypted user-authorized credentials, or
an encrypted imported storage state. It does not bypass CAPTCHA or other
interactive security checks.
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
    AdapterPage,
    PlatformAccountData,
    PlatformContentData,
    PlatformMetricsData,
    TransientAdapterError,
)
from app.adapters.platforms.browser_base import (
    BrowserPlatformAdapter,
    LoginRequiredError,
    reraise_if_terminal,
)

logger = logging.getLogger(__name__)

BILIBILI_SPACE_URL = "https://space.bilibili.com/{mid}"
BILIBILI_VIDEO_URL = "https://www.bilibili.com/video/{bvid}"


def _parse_play_count(text: str) -> int | None:
    """Parse Bilibili play count text like '12.3万' or '1.2亿' into an integer."""
    text = text.strip().replace(",", "")
    match = re.match(r"([\d.]+)\s*万", text)
    if match:
        return int(float(match.group(1)) * 10_000)
    match = re.match(r"([\d.]+)\s*亿", text)
    if match:
        return int(float(match.group(1)) * 100_000_000)
    match = re.match(r"(\d+)", text)
    if match:
        return int(match.group(1))
    return None


class BilibiliBrowserAdapter(BrowserPlatformAdapter):
    """Scrapes Bilibili public pages via headless Chromium."""

    descriptor = AdapterDescriptor(
        key="bilibili_browser",
        name="Bilibili（合规公开页）",
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

    min_action_delay = 1.0
    max_action_delay = 3.0

    async def _login_if_configured(self, page: Page, ctx: AdapterCallContext) -> bool:
        await page.goto(
            "https://passport.bilibili.com/login",
            wait_until="domcontentloaded",
            timeout=self.page_load_timeout_ms,
        )
        await page.locator("input[placeholder*='账号'], input[name='username']").first.fill(
            str(ctx.config.get("username", ""))
        )
        await page.locator("input[type='password']").first.fill(str(ctx.config.get("password", "")))
        await page.locator("button[type='submit'], .btn_primary").first.click()
        await page.wait_for_timeout(3000)
        challenge = page.locator(
            "iframe[src*='captcha'], [class*='captcha'], [id*='captcha']"
        ).first
        if "passport.bilibili.com/login" in page.url or await challenge.is_visible(timeout=500):
            raise LoginRequiredError("Bilibili", "登录需要验证码、2FA 或其他人工验证")
        return True

    async def resolve_account(self, ctx: AdapterCallContext, locator: str) -> PlatformAccountData:
        """Navigate to the user's space page and extract profile info.

        Intercepts the /x/space/wbi/acc/info API response for reliable data,
        falling back to DOM extraction if the API call is missed.
        """
        mid = re.sub(r"[^\d]", "", locator)
        if not mid:
            raise AdapterContractError(f"cannot extract mid from locator: {locator}")

        context, page = await self._new_page(ctx)
        try:
            # Intercept the acc/info API for reliable profile data.
            acc_info: dict[str, Any] | None = None

            async def _capture_acc(response: Any) -> None:
                nonlocal acc_info
                if acc_info is not None:
                    return
                if "acc/info" in response.url and f"mid={mid}" in response.url:
                    try:
                        data = await response.json()
                        if data.get("code") == 0:
                            acc_info = data.get("data")
                    except Exception as exc:
                        logger.debug("bilibili profile response parse failed: %s", exc)

            page.on("response", _capture_acc)

            url = BILIBILI_SPACE_URL.format(mid=mid)
            await page.goto(url, wait_until="domcontentloaded", timeout=self.page_load_timeout_ms)
            await self._polite_delay(1.5)

            # Anonymous-first: check if platform demands login.
            await self._check_login_required(page, "Bilibili")
            # Primary: use intercepted API data.
            if acc_info:
                display_name = acc_info.get("name", "").strip() or f"UID {mid}"
                avatar_url = acc_info.get("face") or None
                description = acc_info.get("sign") or None
                official = acc_info.get("official", {})
                is_verified = bool(official.get("title"))
                return PlatformAccountData(
                    external_id=mid,
                    username=None,
                    display_name=display_name,
                    profile_url=url,
                    avatar_url=avatar_url,
                    description=description,
                    country="CN",
                    language="zh",
                    is_verified=is_verified,
                    source_kind="live",
                    provider=self.key,
                    fetched_at=ctx.observed_at,
                    metadata={
                        "method": "browser_api_intercept",
                        "locator": locator,
                        "official_title": official.get("title") or None,
                    },
                )

            # Fallback: DOM extraction.
            display_name = ""
            try:
                name_el = page.locator(
                    ".h-name, .nickname, [class*='nickname'], [class*='user-name'], #h-name"
                ).first
                display_name = (await name_el.inner_text()).strip()
            except Exception as exc:
                logger.debug("bilibili display name extraction failed: %s", exc)
            if not display_name:
                raw_title = await page.title()
                m = re.match(r"^(.+?)的个人(?:空间|主页)", raw_title)
                if m:
                    display_name = m.group(1).strip()
                else:
                    display_name = raw_title.split("-")[0].strip()
            if not display_name:
                display_name = f"UID {mid}"

            # B: this branch only runs when the authoritative acc/info XHR was
            # missed. On a genuinely walled page display_name collapses to the
            # synthetic "UID {mid}" fallback, so we skip the DOM avatar grab and
            # return None rather than caching the platform's default face. If the
            # page did render a real identity, a precise selector (C) is used.
            avatar_url = None
            if display_name != f"UID {mid}":
                try:
                    avatar_el = page.locator(
                        ".h-avatar img, .bili-avatar img, .b-avatar img"
                    ).first
                    avatar_url = await avatar_el.get_attribute("src")
                    if avatar_url and avatar_url.startswith("//"):
                        avatar_url = "https:" + avatar_url
                except Exception as exc:
                    logger.debug("bilibili avatar extraction failed: %s", exc)

            description = None
            try:
                desc_el = page.locator(
                    ".h-signature, .bili-account__signature, .sign .pure-text"
                ).first
                description = await desc_el.inner_text()
            except Exception as exc:
                logger.debug("bilibili description extraction failed: %s", exc)

            return PlatformAccountData(
                external_id=mid,
                username=None,
                display_name=display_name or f"UID {mid}",
                profile_url=url,
                avatar_url=avatar_url,
                description=description,
                country="CN",
                language="zh",
                is_verified=None,
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                metadata={"method": "browser_dom_scrape", "locator": locator},
            )
        except Exception as exc:
            reraise_if_terminal(exc)
            raise TransientAdapterError(
                f"browser scrape failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            await context.close()

    async def fetch_account(self, ctx: AdapterCallContext, external_id: str) -> PlatformAccountData:
        return await self.resolve_account(ctx, external_id)

    async def fetch_account_analytics(
        self, ctx: AdapterCallContext, external_id: str
    ) -> PlatformMetricsData:
        """Extract follower count from the space page."""
        mid = re.sub(r"[^\d]", "", external_id)
        context, page = await self._new_page(ctx)
        try:
            url = BILIBILI_SPACE_URL.format(mid=mid)
            await page.goto(url, wait_until="domcontentloaded")
            await self._polite_delay(1.5)
            # Anonymous-first: stop immediately if the platform demands login.
            await self._check_login_required(page, "Bilibili")

            follower_count = None
            try:
                fans_el = page.locator("[class*='fans'] .n, .n[data-v-type='fans']").first
                fans_text = await fans_el.inner_text()
                follower_count = _parse_play_count(fans_text)
            except Exception as exc:
                logger.debug("bilibili follower extraction failed: %s", exc)

            video_count = None
            try:
                # Try to get video count from tab or header
                tabs = page.locator(".n[data-v-type='video'], [class*='video'] .n")
                if await tabs.count() > 0:
                    video_text = await tabs.first.inner_text()
                    video_count = _parse_play_count(video_text)
            except Exception as exc:
                logger.debug("bilibili video count extraction failed: %s", exc)

            metrics: dict[str, int | float | None] = {
                "follower_count": follower_count,
                "video_count": video_count,
                "total_view_count": None,
                "total_like_count": None,
            }
            unavailable = tuple(k for k, v in metrics.items() if v is None)
            extraction_failed = follower_count is None and video_count is None
            if extraction_failed:
                logger.warning(
                    "bilibili_browser: all metrics extraction failed for %s — "
                    "login wall or page structure changed",
                    mid,
                )
            return PlatformMetricsData(
                external_id=mid,
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
        """Fetch the video list by intercepting the space page's API response.

        Bilibili's space page is a Vue SPA that loads video data via
        /x/space/wbi/arc/search. We intercept that JSON response directly,
        which is far more reliable than scraping rendered DOM elements.
        """
        mid = re.sub(r"[^\d]", "", external_account_id)
        page_num = int(cursor) if cursor else 1
        context, page = await self._new_page(ctx)
        try:
            # Set up API response interception before navigation.
            api_data: dict[str, Any] | None = None

            async def _capture_response(response: Any) -> None:
                nonlocal api_data
                if api_data is not None:
                    return
                req_url = response.url
                if "arc/search" in req_url and f"mid={mid}" in req_url:
                    try:
                        api_data = await response.json()
                    except Exception as exc:
                        logger.debug("bilibili content response parse failed: %s", exc)

            page.on("response", _capture_response)

            url = (
                f"{BILIBILI_SPACE_URL.format(mid=mid)}/video"
                f"?tid=0&pn={page_num}&keyword=&order=pubdate"
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=self.page_load_timeout_ms)
            # Give the SPA time to fire its XHR calls.
            await self._polite_delay(2.0)
            # Anonymous-first: stop immediately if the platform demands login.
            await self._check_login_required(page, "Bilibili")

            # If interception missed it, wait a bit more.
            if api_data is None:
                try:
                    await page.wait_for_timeout(5000)
                except Exception as exc:
                    logger.debug("bilibili content wait failed: %s", exc)

            if api_data is None or api_data.get("code") != 0:
                # Fallback: try DOM scraping for older page layouts.
                return await self._list_contents_from_dom(page, mid, page_num, page_size, ctx, url)

            vlist: list[dict[str, Any]] = api_data.get("data", {}).get("list", {}).get("vlist", [])
            total = api_data.get("data", {}).get("page", {}).get("count", 0)

            items: list[PlatformContentData] = []
            for v in vlist[:page_size]:
                bvid = v.get("bvid", "")
                title = v.get("title", "").strip() or bvid or "未命名视频"
                cover = v.get("pic", "")
                if cover and cover.startswith("//"):
                    cover = "https:" + cover
                play_count = v.get("play")
                created = v.get("created")
                pub_dt = datetime.fromtimestamp(created, tz=UTC) if created else None
                canonical = BILIBILI_VIDEO_URL.format(bvid=bvid) if bvid else url
                items.append(
                    PlatformContentData(
                        external_id=bvid or f"{mid}_p{page_num}_{len(items)}",
                        account_external_id=mid,
                        content_type="video",
                        title=title,
                        description=v.get("description") or None,
                        published_at=pub_dt,
                        duration_seconds=None,
                        canonical_url=canonical,
                        cover_url=cover or None,
                        language="zh",
                        status="public",
                        source_kind="live",
                        provider=self.key,
                        fetched_at=ctx.observed_at,
                        metadata={
                            "method": "browser_api_intercept",
                            "view_count": play_count,
                            "comment_count": v.get("comment"),
                            "page": page_num,
                        },
                    )
                )

            next_cursor = str(page_num + 1) if page_num * page_size < total else None
            return AdapterPage(items=tuple(items), next_cursor=next_cursor)
        except Exception as exc:
            reraise_if_terminal(exc)
            raise TransientAdapterError(
                f"browser list_contents failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            await context.close()

    async def _list_contents_from_dom(
        self,
        page: Page,
        mid: str,
        page_num: int,
        page_size: int,
        ctx: AdapterCallContext,
        fallback_url: str,
    ) -> AdapterPage:
        """Fallback: scrape video cards from the rendered DOM."""
        await self._scroll_page(page, times=2, ctx=ctx)
        try:
            await page.wait_for_selector(
                ".small-item, .video-card, [class*='video-card']",
                timeout=8_000,
            )
        except Exception:
            return AdapterPage(items=(), next_cursor=None)

        items: list[PlatformContentData] = []
        cards = page.locator(".small-item, .video-card-wrap, [class*='video-card']")
        count = await cards.count()

        for i in range(min(count, page_size)):
            try:
                card = cards.nth(i)
                title = ""
                try:
                    title_el = card.locator(".title, [class*='title']").first
                    title = (await title_el.inner_text()).strip()
                except Exception as exc:
                    logger.debug("bilibili card title extraction failed: %s", exc)
                if not title:
                    title = await card.get_attribute("title") or f"视频 {i + 1}"

                bvid = ""
                try:
                    link_el = card.locator("a[href*='bilibili.com/video'], a[href*='BV']").first
                    href = await link_el.get_attribute("href") or ""
                    bvid_match = re.search(r"(BV[\w]+)", href)
                    if bvid_match:
                        bvid = bvid_match.group(1)
                except Exception as exc:
                    logger.debug("bilibili card URL extraction failed: %s", exc)

                cover_url = None
                try:
                    img_el = card.locator("img").first
                    cover_url = await img_el.get_attribute("src")
                    if cover_url and cover_url.startswith("//"):
                        cover_url = "https:" + cover_url
                except Exception as exc:
                    logger.debug("bilibili cover extraction failed: %s", exc)

                canonical = BILIBILI_VIDEO_URL.format(bvid=bvid) if bvid else fallback_url
                items.append(
                    PlatformContentData(
                        external_id=bvid or f"{mid}_p{page_num}_{i}",
                        account_external_id=mid,
                        content_type="video",
                        title=title,
                        description=None,
                        published_at=None,
                        duration_seconds=None,
                        canonical_url=canonical,
                        cover_url=cover_url,
                        language="zh",
                        status="public",
                        source_kind="live",
                        provider=self.key,
                        fetched_at=ctx.observed_at,
                        metadata={"method": "browser_dom_scrape", "page": page_num},
                    )
                )
            except Exception as exc:
                logger.debug("skip card %d: %s", i, exc)
                continue

        next_cursor = str(page_num + 1) if count >= page_size else None
        return AdapterPage(items=tuple(items), next_cursor=next_cursor)

    async def fetch_content(self, ctx: AdapterCallContext, external_id: str) -> PlatformContentData:
        """Fetch a single video page for details."""
        context, page = await self._new_page(ctx)
        try:
            url = BILIBILI_VIDEO_URL.format(bvid=external_id)
            await page.goto(url, wait_until="domcontentloaded")
            await self._polite_delay(1.5)
            # Anonymous-first: stop immediately if the platform demands login.
            await self._check_login_required(page, "Bilibili")

            title = await page.title()
            title = title.replace("_哔哩哔哩_bilibili", "").strip()

            cover_url = None
            try:
                og_img = page.locator("meta[property='og:image']")
                cover_url = await og_img.get_attribute("content")
            except Exception as exc:
                logger.debug("bilibili detail cover extraction failed: %s", exc)

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
        """Browser scraping does not provide per-content analytics."""
        return tuple(
            PlatformMetricsData(
                external_id=eid,
                captured_at=ctx.observed_at,
                metrics={},
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                unavailable_metrics=("view_count", "like_count", "comment_count", "share_count"),
                metadata={
                    "method": "browser_scrape",
                    "note": "analytics not available via browser",
                },
            )
            for eid in external_ids
        )
