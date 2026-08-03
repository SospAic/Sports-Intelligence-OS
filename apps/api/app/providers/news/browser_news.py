"""Browser-based news provider using Playwright for sports news scraping.

This provider navigates to sports news websites using a headless browser and
extracts article listings via configurable CSS selectors. It is designed for
sites that do not offer RSS/Atom/JSON feeds or whose feeds are incomplete.

Architecture constraints (from AGENTS.md):
- Only publicly accessible pages are scraped.
- Rate limiting and polite delays are mandatory (min 2s between page loads).
- All articles are marked source_kind="live", provider="browser_news".
- Anti-detection: random viewport, realistic UA, random delays.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urljoin

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from app.providers.news.base import (
    NewsArticleData,
    NewsCallContext,
    NewsPage,
    NewsProvider,
    NewsProviderConfigurationError,
    NewsProviderContractError,
    NewsProviderHealth,
    NewsProviderTransientError,
)
from app.providers.news.utils import canonicalize_url, clean_text, parse_iso_datetime

logger = logging.getLogger(__name__)

# Realistic desktop user agents for anti-detection rotation.
_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) "
    "Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
)

# Viewport sizes for randomization.
_VIEWPORTS = (
    (1920, 1080),
    (1536, 864),
    (1440, 900),
    (1366, 768),
    (1680, 1050),
)


class SitePreset:
    """CSS selector preset for a known sports news site."""

    def __init__(
        self,
        *,
        domain: str,
        article_container: str,
        title: str,
        link: str,
        summary: str | None = None,
        timestamp: str | None = None,
        image: str | None = None,
    ) -> None:
        self.domain = domain
        self.article_container = article_container
        self.title = title
        self.link = link
        self.summary = summary
        self.timestamp = timestamp
        self.image = image


# Built-in presets for common sports news sites.
SITE_PRESETS: dict[str, SitePreset] = {
    "espn.com": SitePreset(
        domain="espn.com",
        article_container=".contentItem, .article, [data-id]",
        title="h1, h2, h3, .contentItem__title, .article__title",
        link="a[href]",
        summary=".contentItem__description, .article__summary, p",
        timestamp="time[datetime], .timestamp, [data-date]",
        image="img[src]",
    ),
    "bbc.co.uk": SitePreset(
        domain="bbc.co.uk",
        article_container="[data-testid='card'], .gs-c-promo, article",
        title="h3, h2, .gs-c-promo-heading__title",
        link="a[href]",
        summary=".gs-c-promo-summary, p",
        timestamp="time[datetime], [data-testid='card-metadata-lastupdated']",
        image="img[src]",
    ),
    "bbc.com": SitePreset(
        domain="bbc.com",
        article_container="[data-testid='card'], .gs-c-promo, article",
        title="h3, h2, .gs-c-promo-heading__title",
        link="a[href]",
        summary=".gs-c-promo-summary, p",
        timestamp="time[datetime], [data-testid='card-metadata-lastupdated']",
        image="img[src]",
    ),
    "theguardian.com": SitePreset(
        domain="theguardian.com",
        article_container="[data-component='card'], .fc-item, article",
        title="h3, h2, .fc-item__title, span[data-link-name]",
        link="a[data-link-name], a.fc-item__link, a[href]",
        summary=".fc-item__standfirst, .fc-item__trail",
        timestamp="time[datetime]",
        image="img[src]",
    ),
    "cbssports.com": SitePreset(
        domain="cbssports.com",
        article_container=".article-list-item, .list-article, article",
        title="h3, h2, .article-list-item__title",
        link="a[href]",
        summary=".article-list-item__description, p",
        timestamp="time[datetime], .article-list-item__time",
        image="img[src]",
    ),
    # Free crawlable sports-data sites (the "通用网页连接器" path).
    "fbref.com": SitePreset(
        domain="fbref.com",
        article_container=".news-item, .article, article, [data-article]",
        title="h2, h3, .news-item__title, .article__title, a",
        link="a[href]",
        summary=".news-item__summary, p",
        timestamp="time[datetime], .news-item__date",
        image="img[src]",
    ),
    "transfermarkt.com": SitePreset(
        domain="transfermarkt.com",
        article_container=".news-item, .box > .table > tbody > tr, article",
        title=".news-item__title, .text > a, h2, h3",
        link="a[href]",
        summary=".news-item__content, .text, p",
        timestamp=".news-item__date, time[datetime]",
        image="img[src]",
    ),
}


def _resolve_preset(url: str, config: Mapping[str, Any] | None = None) -> SitePreset | None:
    """Match a URL to a built-in site preset by domain or explicit config key."""
    from urllib.parse import urlsplit

    hostname = (urlsplit(url).hostname or "").casefold()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    for domain, preset in SITE_PRESETS.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return preset
    # Allow an explicit preset name from the source config (e.g. "fbref").
    if config:
        named = config.get("preset")
        if named and named in SITE_PRESETS:
            return SITE_PRESETS[named]
    return None


class BrowserNewsProvider(NewsProvider):
    """News provider that scrapes article listings via a headless browser.

    Supports configurable CSS selectors per source, with built-in presets for
    ESPN, BBC Sport, The Guardian, and CBS Sports. Custom selectors can be
    provided in the source config to support any publicly accessible site.

    Rate limiting: minimum 2 seconds between page loads.
    Timeout: 30 seconds per page navigation.
    """

    key = "browser_news"

    def __init__(
        self,
        *,
        headless: bool = True,
        page_timeout_ms: int = 30_000,
        min_page_delay_seconds: float = 2.0,
        max_page_delay_seconds: float = 5.0,
    ) -> None:
        self._headless = headless
        self._page_timeout_ms = page_timeout_ms
        self._min_delay = min_page_delay_seconds
        self._max_delay = max_page_delay_seconds
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._last_request_at: float = 0.0

    # ─── Browser lifecycle ────────────────────────────────────────────────

    async def _ensure_browser(self) -> Browser:
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        return self._browser

    async def _new_context(self) -> BrowserContext:
        browser = await self._ensure_browser()
        viewport = random.choice(_VIEWPORTS)  # noqa: S311
        user_agent = random.choice(_USER_AGENTS)  # noqa: S311
        return await browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            user_agent=user_agent,
            locale="en-US",
            timezone_id="America/New_York",
        )

    async def _rate_limit(self) -> None:
        """Enforce minimum delay between page loads."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_at
        if elapsed < self._min_delay:
            wait = self._min_delay - elapsed + random.uniform(0, 0.5)  # noqa: S311
            await asyncio.sleep(wait)
        self._last_request_at = asyncio.get_event_loop().time()

    async def _polite_delay(self) -> None:
        """Random delay between actions to appear human-like."""
        delay = random.uniform(self._min_delay, self._max_delay)  # noqa: S311
        await asyncio.sleep(delay)

    # ─── Selector resolution ──────────────────────────────────────────────

    @staticmethod
    def _selectors_from_config(
        config: Mapping[str, Any], url: str
    ) -> dict[str, str | None]:
        """Resolve CSS selectors from config or built-in presets."""
        preset = _resolve_preset(url, config)
        return {
            "article_container": str(
                config.get("selector_article_container")
                or (preset.article_container if preset else "article")
            ),
            "title": str(
                config.get("selector_title")
                or (preset.title if preset else "h1, h2, h3")
            ),
            "link": str(
                config.get("selector_link")
                or (preset.link if preset else "a[href]")
            ),
            "summary": (
                str(config["selector_summary"])
                if config.get("selector_summary")
                else (preset.summary if preset else None)
            ),
            "timestamp": (
                str(config["selector_timestamp"])
                if config.get("selector_timestamp")
                else (preset.timestamp if preset else None)
            ),
            "image": (
                str(config["selector_image"])
                if config.get("selector_image")
                else (preset.image if preset else None)
            ),
        }

    # ─── NewsProvider interface ───────────────────────────────────────────

    async def validate_source(self, config: Mapping[str, Any]) -> None:
        url = config.get("url")
        if not isinstance(url, str) or not url.strip():
            raise NewsProviderConfigurationError(
                "browser_news source requires a 'url' config field"
            )
        if not url.lower().startswith(("https://", "http://")):
            raise NewsProviderConfigurationError(
                "browser_news source URL must be absolute HTTP(S)"
            )

    async def fetch_latest(
        self,
        ctx: NewsCallContext,
        *,
        cursor: str | None,
        limit: int,
    ) -> NewsPage:
        url = cast(str, ctx.config["url"])
        selectors = self._selectors_from_config(ctx.config, url)
        articles = await self._scrape_articles(url, selectors, limit)
        return NewsPage(items=tuple(articles), next_cursor=None)

    async def fetch_range(
        self,
        ctx: NewsCallContext,
        *,
        start: datetime,
        end: datetime,
        cursor: str | None,
        limit: int,
    ) -> NewsPage:
        # Browser scraping fetches the current page listing; time filtering
        # is applied post-hoc on extracted timestamps where available.
        url = cast(str, ctx.config["url"])
        selectors = self._selectors_from_config(ctx.config, url)
        articles = await self._scrape_articles(url, selectors, limit * 2)
        filtered = [
            article
            for article in articles
            if article.published_at is None
            or (start <= article.published_at <= end)
        ]
        return NewsPage(items=tuple(filtered[:limit]), next_cursor=None)

    async def normalize_article(
        self, raw: Mapping[str, Any], ctx: NewsCallContext
    ) -> NewsArticleData:
        title = str(raw.get("title", "")).strip()
        link = str(raw.get("link", "")).strip()
        if not title or not link:
            raise NewsProviderContractError(
                "browser_news article requires both title and link"
            )
        try:
            canonical = canonicalize_url(link)
        except ValueError:
            canonical = link
        published_at = parse_iso_datetime(raw.get("timestamp"))
        external_id = hashlib.sha256(
            f"browser_news:{canonical}:{title}".encode()
        ).hexdigest()[:32]
        return NewsArticleData(
            external_id=external_id,
            canonical_url=canonical,
            title=title,
            summary=clean_text(raw.get("summary")),
            content=None,
            author=None,
            published_at=published_at,
            event_time=None,
            language=str(raw.get("language") or "en"),
            sport=str(raw.get("sport") or "general"),
            league=raw.get("league") if isinstance(raw.get("league"), str) else None,
            country=raw.get("country") if isinstance(raw.get("country"), str) else None,
            source_kind="live",
            provider="browser_news",
            fetched_at=ctx.fetched_at,
            metadata={
                "scrape_method": "playwright_browser",
                "image_url": raw.get("image"),
            },
        )

    async def health_check(self, ctx: NewsCallContext) -> NewsProviderHealth:
        try:
            browser = await self._ensure_browser()
            if browser.is_connected():
                return NewsProviderHealth(
                    status="ok",
                    checked_at=ctx.fetched_at,
                    detail="browser ready",
                )
            return NewsProviderHealth(
                status="unavailable",
                checked_at=ctx.fetched_at,
                detail="browser disconnected",
            )
        except Exception as exc:
            return NewsProviderHealth(
                status="unavailable",
                checked_at=ctx.fetched_at,
                detail=f"{type(exc).__name__}: {exc}",
            )

    # ─── Internal scraping logic ──────────────────────────────────────────

    async def _scrape_articles(
        self,
        url: str,
        selectors: dict[str, str | None],
        limit: int,
    ) -> list[NewsArticleData]:
        """Navigate to the URL and extract article data from the DOM."""
        await self._rate_limit()
        context: BrowserContext | None = None
        try:
            context = await self._new_context()
            page: Page = await context.new_page()
            page.set_default_timeout(self._page_timeout_ms)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self._page_timeout_ms)
            except Exception as exc:
                raise NewsProviderTransientError(
                    f"Failed to load page: {type(exc).__name__}: {exc}"
                ) from exc
            # Allow dynamic content to settle.
            await self._polite_delay()
            # Scroll to trigger lazy-loaded content.
            for _ in range(3):
                await page.mouse.wheel(0, 400)
                await asyncio.sleep(0.4)

            container_selector = selectors["article_container"] or "article"
            title_selector = selectors["title"] or "h1, h2, h3"
            link_selector = selectors["link"] or "a[href]"
            summary_selector = selectors.get("summary")
            timestamp_selector = selectors.get("timestamp")
            image_selector = selectors.get("image")

            articles: list[NewsArticleData] = []
            fetched_at = datetime.now(UTC)

            # Try to find article containers.
            containers = page.locator(container_selector)
            count = await containers.count()
            if count == 0:
                # Fallback: try extracting links directly from the page.
                return await self._extract_from_links(
                    page, url, link_selector, title_selector, fetched_at, limit
                )

            for index in range(min(count, limit)):
                try:
                    container = containers.nth(index)
                    raw = await self._extract_article_data(
                        container,
                        page,
                        url,
                        title_selector=title_selector,
                        link_selector=link_selector,
                        summary_selector=summary_selector,
                        timestamp_selector=timestamp_selector,
                        image_selector=image_selector,
                    )
                    if raw is None:
                        continue
                    article = await self.normalize_article(
                        raw,
                        NewsCallContext(
                            config={},
                            fetched_at=fetched_at,
                            request_id=f"browser_news_{index}",
                        ),
                    )
                    articles.append(article)
                except Exception:
                    logger.debug(
                        "browser_news: skipping article at index %d",
                        index,
                        exc_info=True,
                    )
                    continue
            return articles
        finally:
            if context is not None:
                await context.close()

    async def _extract_article_data(
        self,
        container: Any,
        page: Page,
        base_url: str,
        *,
        title_selector: str,
        link_selector: str,
        summary_selector: str | None,
        timestamp_selector: str | None,
        image_selector: str | None,
    ) -> dict[str, Any] | None:
        """Extract raw article fields from a single container element."""
        # Title
        title_el = container.locator(title_selector).first
        title = (await title_el.inner_text(timeout=2000)).strip() if await title_el.count() else ""
        if not title:
            return None

        # Link
        link_el = container.locator(link_selector).first
        href = ""
        if await link_el.count():
            href = await link_el.get_attribute("href") or ""
        if not href:
            # Try the container itself if it's a link.
            href = await container.get_attribute("href") or ""
        if href and not href.startswith(("http://", "https://")):
            href = urljoin(base_url, href)
        if not href:
            return None

        # Summary
        summary: str | None = None
        if summary_selector:
            summary_el = container.locator(summary_selector).first
            if await summary_el.count():
                summary = (await summary_el.inner_text(timeout=1000)).strip() or None

        # Timestamp
        timestamp: str | None = None
        if timestamp_selector:
            ts_el = container.locator(timestamp_selector).first
            if await ts_el.count():
                timestamp = (
                    await ts_el.get_attribute("datetime")
                    or (await ts_el.inner_text(timeout=1000)).strip()
                    or None
                )

        # Image
        image: str | None = None
        if image_selector:
            img_el = container.locator(image_selector).first
            if await img_el.count():
                image = (
                    await img_el.get_attribute("src")
                    or await img_el.get_attribute("data-src")
                    or None
                )
                if image and not image.startswith(("http://", "https://", "data:")):
                    image = urljoin(base_url, image)

        return {
            "title": title,
            "link": href,
            "summary": summary,
            "timestamp": timestamp,
            "image": image,
        }

    async def _extract_from_links(
        self,
        page: Page,
        base_url: str,
        link_selector: str,
        title_selector: str,
        fetched_at: datetime,
        limit: int,
    ) -> list[NewsArticleData]:
        """Fallback extraction when no article containers are found."""
        articles: list[NewsArticleData] = []
        links = page.locator(link_selector)
        count = await links.count()
        seen_urls: set[str] = set()
        for index in range(min(count, limit * 3)):
            if len(articles) >= limit:
                break
            try:
                link_el = links.nth(index)
                href = await link_el.get_attribute("href") or ""
                if not href or href.startswith(("javascript:", "#", "mailto:")):
                    continue
                if not href.startswith(("http://", "https://")):
                    href = urljoin(base_url, href)
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                title = (await link_el.inner_text(timeout=1000)).strip()
                if not title or len(title) < 10:
                    continue
                article = await self.normalize_article(
                    {"title": title, "link": href},
                    NewsCallContext(
                        config={},
                        fetched_at=fetched_at,
                        request_id=f"browser_news_fallback_{index}",
                    ),
                )
                articles.append(article)
            except Exception as exc:  # noqa: BLE001
                logger.warning("browser_news fallback item %d skipped: %s", index, exc)
                continue
        return articles

    # ─── Cleanup ──────────────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Shut down browser and Playwright."""
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
