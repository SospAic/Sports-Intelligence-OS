# ruff: noqa: E501, I001, S110
"""YouTube browser-simulation adapter.

Scrapes public YouTube channel pages using a headless browser. No API key
required — works by rendering the page and intercepting XHR responses.

Supports:
- No credentials: scrapes public channel info and video lists.
- Optional Google account login for authenticated content.

Registered as 'youtube_browser', coexists with the API-based 'youtube' adapter.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
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

YT_CHANNEL_URL = "https://www.youtube.com/@{handle}"
YT_VIDEO_URL = "https://www.youtube.com/watch?v={video_id}"


def _parse_relative_date(text: str | None, observed_at: datetime) -> datetime | None:
    """Parse YouTube's relative/absolute publish timestamps into a datetime.

    Handles English ('3 days ago') and Chinese ('17小时前', '1天前') relative
    forms, plus absolute formats like 'Jun 3, 2024'. Returns ``None`` if
    unparseable.
    """
    if not text:
        return None
    t = text.strip().lower()
    m = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s+ago", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        deltas = {
            "second": timedelta(seconds=n),
            "minute": timedelta(minutes=n),
            "hour": timedelta(hours=n),
            "day": timedelta(days=n),
            "week": timedelta(weeks=n),
            "month": timedelta(days=30 * n),
            "year": timedelta(days=365 * n),
        }
        return observed_at - deltas[unit]
    # Chinese relative: 30秒前 / 5分钟前 / 17小时前 / 3天前 / 2周前 / 1个月前 / 半年前(ignore) / 1年前
    m = re.search(r"(\d+)\s*(秒|分钟|小时|天|周|个月|年)前", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        deltas = {
            "秒": timedelta(seconds=n),
            "分钟": timedelta(minutes=n),
            "小时": timedelta(hours=n),
            "天": timedelta(days=n),
            "周": timedelta(weeks=n),
            "个月": timedelta(days=30 * n),
            "年": timedelta(days=365 * n),
        }
        return observed_at - deltas[unit]
    for fmt in ("%b %d, %Y", "%b %d %Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(t, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_views_from_text(text: str | None) -> int | None:
    """Extract a video view count from the renderer's combined text line.

    YouTube renders this in the adapter's zh-CN locale as e.g. '8225次观看',
    '1.2万次观看', or in English as '1.2M views'. The combined text also
    contains the duration ('20:52'), so we must match the views token
    specifically rather than the first number.
    """
    if not text:
        return None
    m = re.search(r"([\d.,]+)\s*万?\s*次观看", text)
    if m:
        num = float(m.group(1).replace(",", ""))
        mult = 10_000 if "万" in m.group(0) else 1
        return int(num * mult)
    m = re.search(r"([\d.,]+)\s*([KMB]?)\s*views", text, re.IGNORECASE)
    if m:
        num = float(m.group(1).replace(",", ""))
        mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(m.group(2).upper(), 1)
        return int(num * mult)
    return None


class YouTubeBrowserAdapter(BrowserPlatformAdapter):
    """Scrapes YouTube public pages via headless Chromium."""

    descriptor = AdapterDescriptor(
        key="youtube_browser",
        name="YouTube（合规公开页）",
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
        username = str(ctx.config.get("username", ""))
        password = str(ctx.config.get("password", ""))
        await page.goto(
            "https://accounts.google.com/signin/v2/identifier?service=youtube",
            wait_until="domcontentloaded",
            timeout=self.page_load_timeout_ms,
        )
        await page.locator("input[type='email']").fill(username)
        await page.locator("#identifierNext button, #identifierNext").click()
        await page.locator("input[type='password']").wait_for(state="visible")
        await page.locator("input[type='password']").fill(password)
        await page.locator("#passwordNext button, #passwordNext").click()
        await page.wait_for_timeout(3000)
        if "challenge" in page.url or "accounts.google.com" in page.url:
            raise LoginRequiredError("YouTube", "登录需要验证码、2FA 或其他人工验证")
        return True

    async def resolve_account(self, ctx: AdapterCallContext, locator: str) -> PlatformAccountData:
        """Navigate to the channel page and extract profile info."""
        handle = locator.lstrip("@")
        if not handle:
            raise AdapterContractError(f"cannot extract handle from locator: {locator}")

        context, page = await self._new_page(ctx)
        try:
            # Intercept the channel about page data.
            channel_data: dict[str, Any] | None = None

            async def _capture(response: Any) -> None:
                nonlocal channel_data
                if channel_data is not None:
                    return
                if "youtubei/v1/browse" in response.url:
                    try:
                        data = await response.json()
                        # YouTube's internal API returns channel metadata
                        header = data.get("header", {}).get("c4TabbedHeaderRenderer", {})
                        if header:
                            channel_data = header
                    except Exception:
                        pass

            page.on("response", _capture)

            url = YT_CHANNEL_URL.format(handle=handle)
            await page.goto(url, wait_until="domcontentloaded", timeout=self.page_load_timeout_ms)
            await self._polite_delay(1.5)
            # Anonymous-first: stop immediately if the platform demands login.
            await self._check_login_required(page, "YouTube")

            # Try intercepted data first.
            display_name = ""
            avatar_url = None
            description = None
            subscriber_text = None

            if channel_data:
                display_name = channel_data.get("title", "")
                avatar_thumbs = channel_data.get("avatar", {}).get("thumbnails", [])
                if avatar_thumbs:
                    avatar_url = avatar_thumbs[-1].get("url")
                sub_text = channel_data.get("subscriberCountText", {}).get("simpleText", "")
                subscriber_text = sub_text

            # Fallback: DOM extraction.
            if not display_name:
                try:
                    name_el = page.locator(
                        "#channel-name yt-formatted-string, #text-container .yt-core-attributed-string"
                    ).first
                    display_name = (await name_el.inner_text()).strip()
                except Exception:
                    pass
            if not display_name:
                raw_title = await page.title()
                display_name = raw_title.replace(" - YouTube", "").strip()
            if not display_name:
                display_name = f"@{handle}"

            # B: only attempt a DOM avatar fallback when the authoritative
            # youtubei/browse XHR returned the channel header. On a walled page
            # (channel_data is None) we must NOT grab a default/generic image.
            # The selector below is already precise (no broad [class*='avatar']).
            if not avatar_url and channel_data is not None:
                try:
                    img_el = page.locator("#channel-header img, yt-img-shadow#avatar img").first
                    avatar_url = await img_el.get_attribute("src")
                except Exception:
                    pass

            if not description:
                try:
                    desc_el = page.locator(
                        "#description yt-formatted-string, .about-description"
                    ).first
                    description = (await desc_el.inner_text()).strip() or None
                except Exception:
                    pass

            return PlatformAccountData(
                external_id=handle,
                username=handle,
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
                    "subscriber_text": subscriber_text,
                },
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
        """Extract subscriber count from the channel page."""
        handle = external_id.lstrip("@")
        context, page = await self._new_page(ctx)
        try:
            url = YT_CHANNEL_URL.format(handle=handle)
            await page.goto(url, wait_until="domcontentloaded", timeout=self.page_load_timeout_ms)
            await self._polite_delay(1.5)
            # Anonymous-first: stop immediately if the platform demands login.
            await self._check_login_required(page, "YouTube")

            subscriber_count = None
            try:
                sub_el = page.locator("#subscriber-count, #channel-tagline #subscriber-count").first
                sub_text = await sub_el.inner_text()
                subscriber_count = self._parse_subscriber_count(sub_text)
            except Exception:
                pass

            video_count = None
            try:
                # Check the Videos tab count
                tab_el = page.locator(
                    "yt-tab[title*='Videos'] #tab-text, tp-yt-paper-tab:has-text('Videos')"
                ).first
                tab_text = await tab_el.inner_text()
                m = re.search(r"([\d,]+)", tab_text)
                if m:
                    video_count = int(m.group(1).replace(",", ""))
            except Exception:
                pass

            metrics: dict[str, int | float | None] = {
                "follower_count": subscriber_count,
                "video_count": video_count,
                "total_view_count": None,
            }

            extraction_failed = subscriber_count is None and video_count is None
            if extraction_failed:
                logger.warning(
                    "youtube_browser: all metrics extraction failed for %s — "
                    "page structure may have changed or channel is unavailable",
                    url,
                )

            unavailable = tuple(k for k, v in metrics.items() if v is None)
            return PlatformMetricsData(
                external_id=handle,
                captured_at=ctx.observed_at,
                metrics=metrics,
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                unavailable_metrics=unavailable,
                metadata={
                    "method": "browser_scrape",
                    "extraction_failure": extraction_failed,
                },
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
        """Scrape the video list from the channel's Videos tab."""
        handle = external_account_id.lstrip("@")
        context, page = await self._new_page(ctx)
        try:
            url = f"{YT_CHANNEL_URL.format(handle=handle)}/videos"
            await page.goto(url, wait_until="domcontentloaded", timeout=self.page_load_timeout_ms)
            await self._polite_delay(2.0)
            # Anonymous-first: stop before scrolling a page that will never load.
            await self._check_login_required(page, "YouTube")
            await self._scroll_page(page, times=3, ctx=ctx)

            # Wait for video renderers.
            try:
                await page.wait_for_selector(
                    "ytd-rich-item-renderer, ytd-grid-video-renderer",
                    timeout=10_000,
                )
            except Exception:
                return AdapterPage(items=(), next_cursor=None)

            items = await self._extract_video_renderers(page, ctx, handle, page_size)

            # YouTube uses infinite scroll; no simple cursor pagination.
            next_cursor = None
            return AdapterPage(items=tuple(items), next_cursor=next_cursor)
        except Exception as exc:
            reraise_if_terminal(exc)
            raise TransientAdapterError(
                f"browser list_contents failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            await context.close()

    async def _extract_video_renderers(
        self,
        page: Page,
        ctx: AdapterCallContext,
        handle: str,
        page_size: int,
    ) -> list[PlatformContentData]:
        """Extract video cards from the Videos tab in a single DOM read.

        YouTube's markup changes often; locating each field with individual
        Playwright locators is slow and brittle (stale selectors wait the full
        default timeout). Reading the whole grid once via ``page.evaluate`` is
        fast and resilient to layout changes.
        """
        raw = await page.evaluate(
            """(limit) => {
                const rs = Array.from(
                    document.querySelectorAll('ytd-rich-item-renderer, ytd-grid-video-renderer')
                );
                const out = [];
                for (const r of rs.slice(0, limit)) {
                    const a = r.querySelector('a[href*="/watch"]');
                    if (!a) continue;
                    const href = a.getAttribute('href') || '';
                    const m = href.match(/[?&]v=([\\w-]+)/);
                    const videoId = m ? m[1] : '';
                    const tEl = r.querySelector('a.ytLockupMetadataViewModelTitle') || a;
                    const title = (tEl ? tEl.textContent : '').trim();
                    const img = r.querySelector('img');
                    const cover = img ? (img.getAttribute('src') || '') : '';
                    const text = r.innerText ? r.innerText.replace(/\\n+/g, ' | ') : '';
                    out.push({videoId, title, cover, text});
                }
                return out;
            }""",
            page_size,
        )
        items: list[PlatformContentData] = []
        for i, d in enumerate(raw):
            video_id = (d.get("videoId") or "").strip()
            title = (d.get("title") or "").strip()
            if not title:
                title = f"Video {i + 1}"
            cover_url = d.get("cover") or None
            text = d.get("text") or ""
            view_count = _parse_views_from_text(text)
            published_at = _parse_relative_date(text, ctx.observed_at)
            canonical = (
                YT_VIDEO_URL.format(video_id=video_id)
                if video_id
                else f"https://www.youtube.com/@{handle}/videos"
            )
            items.append(
                PlatformContentData(
                    external_id=video_id or f"{handle}_v{i}",
                    account_external_id=handle,
                    content_type="video",
                    title=title,
                    description=None,
                    published_at=published_at,
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
                        "raw_text": text[:300],
                        "view_count": view_count,
                    },
                )
            )
        return items

    async def fetch_content(self, ctx: AdapterCallContext, external_id: str) -> PlatformContentData:
        """Fetch a single video page for details."""
        context, page = await self._new_page(ctx)
        try:
            url = YT_VIDEO_URL.format(video_id=external_id)
            await page.goto(url, wait_until="domcontentloaded")
            await self._polite_delay(1.5)
            # Anonymous-first: stop immediately if the platform demands login.
            await self._check_login_required(page, "YouTube")

            title = await page.title()
            title = title.replace(" - YouTube", "").strip()

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
        """Browser scraping does not provide per-content analytics."""
        return tuple(
            PlatformMetricsData(
                external_id=eid,
                captured_at=ctx.observed_at,
                metrics={},
                source_kind="live",
                provider=self.key,
                fetched_at=ctx.observed_at,
                unavailable_metrics=("view_count", "like_count", "comment_count"),
                metadata={
                    "method": "browser_scrape",
                    "note": "analytics not available via browser",
                },
            )
            for eid in external_ids
        )

    @staticmethod
    def _parse_subscriber_count(text: str) -> int | None:
        """Parse '1.23M subscribers' or '456K subscribers' into integer."""
        text = text.strip().lower()
        m = re.search(r"([\d.]+)\s*([km]?)", text)
        if not m:
            return None
        num = float(m.group(1))
        suffix = m.group(2)
        if suffix == "k":
            return int(num * 1_000)
        if suffix == "m":
            return int(num * 1_000_000)
        return int(num)
