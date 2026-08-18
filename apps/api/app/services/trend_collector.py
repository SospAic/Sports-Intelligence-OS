"""趋势数据采集服务：从各平台公开 API 采集实时热点数据。

所有采集数据标记 source_kind="live"，每个平台独立容错，
单平台失败不影响其他平台的采集。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.monitoring import (
    Account,
    ContentItem,
    ContentSnapshot,
    DerivedMetric,
    Platform,
)
from app.models.news import Source
from app.models.trends import TrendKeywordSnapshot, TrendTopic, TrendVideo
from app.providers.news.base import NewsArticleData, NewsCallContext
from app.providers.news.registry import build_news_provider_registry
from app.services.metric_calculations import (
    freshness_score,
    percentile_rank,
    safe_rate,
    sample_confidence,
    weighted_available_score,
)
from app.services.platform_credentials import PlatformCredentialService
from app.services.trend_categories import canonical_trend_category
from app.services.trend_categories import infer_sports_category as _infer_sports_category
from app.services.trend_categories import is_sports_related as _is_sports_related
from app.services.trend_categories import trend_terms as _trend_terms

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, str], None]

# Official API request headers.
_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": "Sports-Intelligence-OS/0.1",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

def _position_heat_score(rank: int, total: int) -> float:
    """基于排名位置计算热度分数（rank 1 = 100，递减）"""
    if total <= 1:
        return 50.0
    return round(max(0.0, 100.0 * (1 - (rank - 1) / (total - 1))), 2)


def _confidence_adjusted(score: float | None, confidence: float) -> float | None:
    """Shrink uncertain rankings towards neutral rather than claiming extremes."""
    if score is None:
        return None
    return round(50.0 + (score - 50.0) * min(1.0, max(0.0, confidence)), 2)


def _engagement_rate(snapshot: ContentSnapshot | None) -> float | None:
    if snapshot is None:
        return None
    observed = [
        value
        for value in (snapshot.like_count, snapshot.comment_count, snapshot.share_count)
        if value is not None
    ]
    return safe_rate(sum(observed) if observed else None, snapshot.view_count)


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _engagement_from_statistics(statistics: dict[str, Any]) -> float | None:
    views = _optional_int(statistics.get("viewCount"))
    interactions = [
        value
        for key in ("likeCount", "commentCount")
        if (value := _optional_int(statistics.get(key))) is not None
    ]
    return safe_rate(sum(interactions) if interactions else None, views)


def _live_metadata(provider: str) -> dict[str, Any]:
    """生成带有来源追踪的元数据"""
    return {
        "source_kind": "live",
        "provider": provider,
        "access_method": "official_api",
        "collected_at": datetime.now(UTC).isoformat(),
    }


class TrendCollectorService:
    """从各平台公开 API 采集趋势数据的服务"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def collect_all(
        self,
        workspace_id: UUID,
        *,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """采集所有平台的趋势数据，返回各平台采集结果统计"""
        if progress:
            progress("开始读取已监控账号的近 72 小时实时样本", "monitored_samples")
        results: dict[str, Any] = await self._collect_monitored_samples(
            workspace_id, window_hours=72
        )
        if progress:
            sample_videos = sum(int(item.get("videos", 0)) for item in results.values())
            progress(f"监控样本处理完成：{sample_videos} 条作品", "monitored_samples")
            progress("正在检查 YouTube 官方 API 配置并采集公开趋势", "youtube")
        youtube = await self.collect_youtube_trends(workspace_id)
        youtube_result = results.setdefault(
            "youtube",
            {"topics": 0, "videos": 0, "keywords": 0, "status": "no_authorized_samples"},
        )
        for key in ("topics", "videos", "keywords"):
            youtube_result[key] += youtube[key]
        if any(youtube.values()):
            youtube_result["status"] = "collected"
        if progress:
            progress("正在独立采集已启用的公开 RSS/Atom 热点源（最近 72 小时）", "public_sources")
        public_sources = await self.collect_public_source_trends(
            workspace_id, progress=progress, window_hours=72
        )
        results["web"] = public_sources
        for platform in ("tiktok", "douyin", "bilibili"):
            results.setdefault(
                platform,
                {
                    "topics": 0,
                    "videos": 0,
                    "keywords": 0,
                    "status": "no_authorized_samples",
                },
            )
        if progress:
            for platform, summary in results.items():
                progress(
                    f"{platform}：作品 {int(summary.get('videos', 0))} 条，"
                    f"话题 {int(summary.get('topics', 0))} 个，"
                    f"状态 {summary.get('status', 'unknown')}",
                    "platform_summary",
                )
            progress("正在提交趋势榜单、话题和关键词快照", "persist")
        await self.session.commit()
        if progress:
            total_videos = sum(int(item.get("videos", 0)) for item in results.values())
            total_topics = sum(int(item.get("topics", 0)) for item in results.values())
            progress(
                f"采集完成：新增/更新作品 {total_videos} 条，话题 {total_topics} 个",
                "completed",
            )
        return results

    async def collect_public_source_trends(
        self,
        workspace_id: UUID,
        *,
        progress: ProgressCallback | None = None,
        window_hours: int = 72,
    ) -> dict[str, Any]:
        """Collect fresh public RSS/Atom entries independently of monitored accounts.

        The trend page must not depend on the account inventory being populated.
        Only sources explicitly enabled in ``news_sources`` are read here; this
        preserves source terms/attribution and makes the public-web boundary
        auditable.  Feed metrics are intentionally left ``None`` because a feed
        does not prove views or interactions.
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=max(24, min(int(window_hours), 72)))
        sources = list(
            (
                await self.session.scalars(
                    select(Source)
                    .where(
                        Source.workspace_id == workspace_id,
                        Source.enabled.is_(True),
                        Source.source_type.in_(("rss", "atom")),
                        Source.url.is_not(None),
                    )
                    .order_by(Source.priority.desc(), Source.reliability_score.desc())
                    .limit(self._settings.hotspot_feed_max_sources)
                )
            ).all()
        )
        summary: dict[str, Any] = {
            "topics": 0,
            "videos": 0,
            "keywords": 0,
            "sources": 0,
            "failed_sources": 0,
            "status": "no_enabled_public_sources" if not sources else "running",
        }
        if not sources:
            if progress:
                progress("没有启用的公开 RSS/Atom 源，热点中心保留明确空状态", "public_sources")
            return summary

        registry = build_news_provider_registry(self._settings)
        semaphore = asyncio.Semaphore(self._settings.hotspot_feed_concurrency)

        async def fetch_source(
            source: Source,
        ) -> tuple[Source, list[NewsArticleData], str | None]:
            provider_key = source.source_type
            try:
                provider = registry.get(provider_key)
                config = dict(source.config_json or {})
                config["url"] = source.url
                context = NewsCallContext(
                    config=config,
                    fetched_at=now,
                    request_id=f"hotspot:{workspace_id}:{source.id}",
                )
                async with semaphore:
                    page = await provider.fetch_latest(
                        context,
                        cursor=None,
                        limit=self._settings.hotspot_feed_items_per_source,
                    )
                fresh = [
                    item
                    for item in page.items
                    if item.published_at is not None and item.published_at >= cutoff
                ]
                return source, fresh, None
            except Exception as exc:  # noqa: BLE001 - isolate one public source
                return source, [], f"{type(exc).__name__}: {str(exc)[:240]}"

        fetched = await asyncio.gather(*(fetch_source(source) for source in sources))
        for provider in registry.values():
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()

        topic_aggregates: dict[str, dict[str, Any]] = {}
        collected_at = now.isoformat()
        for source, items, error in fetched:
            if error is not None:
                summary["failed_sources"] += 1
                if progress:
                    progress(f"公开源 {source.name} 失败：{error}", "public_source_failed")
                continue
            summary["sources"] += 1
            if progress:
                progress(f"公开源 {source.name} 获取 {len(items)} 条最近文章", "public_source")
            for rank, item in enumerate(items, start=1):
                text = f"{item.title}\n{item.summary or ''}"
                age_hours = max(
                    0.0,
                    (now - item.published_at.astimezone(UTC)).total_seconds() / 3600
                    if item.published_at is not None
                    else 72.0,
                )
                position_score = _position_heat_score(rank, len(items))
                raw_heat, applied_weights = weighted_available_score(
                    {
                        "freshness": (freshness_score(age_hours, half_life_hours=24), 0.65),
                        "feed_position": (position_score, 0.25),
                        "source_reliability": (float(source.reliability_score), 0.10),
                    },
                    minimum_components=2,
                )
                confidence = sample_confidence(len(items), target_size=10)
                score = _confidence_adjusted(raw_heat, confidence)
                external_id = f"{source.id}:{item.external_id}"[:255]
                self.session.add(
                    TrendVideo(
                        workspace_id=workspace_id,
                        platform="web",
                        external_id=external_id,
                        title=item.title,
                        author_name=item.author,
                        author_url=None,
                        cover_url=None,
                        video_url=item.canonical_url,
                        view_count=None,
                        like_count=None,
                        comment_count=None,
                        share_count=None,
                        breakout_score=score,
                        category=canonical_trend_category(item.sport or source.category),
                        metadata_json={
                            "source_kind": "live",
                            "provider": item.provider,
                            "access_method": "public_rss",
                            "metric_kind": "derived",
                            "metric_available": False,
                            "heat_score_method": "freshness_feed_position_source_reliability",
                            "applied_weights": applied_weights,
                            "confidence_score": round(confidence, 4),
                            "source_id": str(source.id),
                            "source_name": source.name,
                            "source_url": source.url,
                            "source_article_id": item.external_id,
                            "source_published_at": (
                                item.published_at.isoformat() if item.published_at else None
                            ),
                            "collected_at": collected_at,
                        },
                        observed_at=now,
                    )
                )
                summary["videos"] += 1
                for term in _trend_terms(text):
                    aggregate = topic_aggregates.setdefault(
                        term.casefold(),
                        {
                            "title": term,
                            "count": 0,
                            "sources": set(),
                            "latest": item.published_at,
                            "article_refs": [],
                        },
                    )
                    aggregate["count"] += 1
                    aggregate["sources"].add(str(source.id))
                    if len(aggregate["article_refs"]) < 10:
                        article_ref = {
                            "external_id": item.external_id,
                            "url": item.canonical_url,
                            "title": item.title,
                            "summary": item.summary,
                            "source_id": str(source.id),
                            "source_name": source.name,
                            "published_at": (
                                item.published_at.isoformat() if item.published_at else None
                            ),
                        }
                        if not any(
                            ref.get("external_id") == article_ref["external_id"]
                            for ref in aggregate["article_refs"]
                        ):
                            aggregate["article_refs"].append(article_ref)
                    if item.published_at and (
                        aggregate["latest"] is None or item.published_at > aggregate["latest"]
                    ):
                        aggregate["latest"] = item.published_at

        ranked_topics = sorted(
            topic_aggregates.values(),
            key=lambda item: (int(item["count"]), len(item["sources"])),
            reverse=True,
        )[:50]
        population = [int(item["count"]) for item in ranked_topics]
        for rank, aggregate in enumerate(ranked_topics, start=1):
            count = int(aggregate["count"])
            source_breadth = min(100.0, 100.0 * len(aggregate["sources"]) / 3)
            raw_heat, weights = weighted_available_score(
                {
                    "source_volume": (percentile_rank(count, population), 0.65),
                    "source_breadth": (source_breadth, 0.35),
                },
                minimum_components=2,
            )
            confidence = sample_confidence(count, target_size=8)
            metadata = {
                "source_kind": "live",
                "provider": "public_rss_aggregate",
                "access_method": "public_rss",
                "metric_kind": "derived",
                "metric_available": False,
                "heat_score_method": "source_volume_and_breadth",
                "applied_weights": weights,
                "confidence_score": confidence,
                "source_count": len(aggregate["sources"]),
                "source_article_refs": aggregate["article_refs"],
                "evidence_version": "trend-topic-evidence-v1",
                "source_published_at": (
                    aggregate["latest"].isoformat() if aggregate["latest"] is not None else None
                ),
                "collected_at": collected_at,
            }
            self.session.add(
                TrendTopic(
                    workspace_id=workspace_id,
                    platform="web",
                    title=str(aggregate["title"]),
                    category=_infer_sports_category(str(aggregate["title"])),
                    heat_score=_confidence_adjusted(raw_heat, confidence) or 50.0,
                    growth_rate=None,
                    rank=rank,
                    sample_size=count,
                    metadata_json=metadata,
                    observed_at=now,
                )
            )
            self.session.add(
                TrendKeywordSnapshot(
                    workspace_id=workspace_id,
                    keyword=str(aggregate["title"]),
                    platform="web",
                    observed_at=now,
                    video_count=count,
                    total_views=None,
                    avg_views=None,
                    heat_index=_confidence_adjusted(raw_heat, confidence),
                    metadata_json=metadata,
                )
            )
            summary["topics"] += 1
            summary["keywords"] += 1
        if summary["failed_sources"] and summary["sources"]:
            summary["status"] = "partial"
        elif summary["failed_sources"]:
            summary["status"] = "failed"
        else:
            summary["status"] = "collected"
        return summary

    async def _collect_monitored_samples(
        self, workspace_id: UUID, *, window_hours: int = 72
    ) -> dict[str, Any]:
        """Build trends from real content acquired by configured account adapters."""
        now = datetime.now(UTC)
        latest = (
            select(
                ContentSnapshot.content_item_id,
                func.max(ContentSnapshot.captured_at).label("captured_at"),
            )
            .group_by(ContentSnapshot.content_item_id)
            .subquery()
        )
        rows = (
            await self.session.execute(
                select(ContentItem, ContentSnapshot, Platform, Account)
                .join(Platform, Platform.id == ContentItem.platform_id)
                .join(Account, Account.id == ContentItem.account_id)
                .outerjoin(latest, latest.c.content_item_id == ContentItem.id)
                .outerjoin(
                    ContentSnapshot,
                    and_(
                        ContentSnapshot.content_item_id == ContentItem.id,
                        ContentSnapshot.captured_at == latest.c.captured_at,
                    ),
                )
                .where(
                    ContentItem.workspace_id == workspace_id,
                    ContentItem.source_kind == "live",
                    ContentItem.status.notin_(("archived", "deleted")),
                    ContentItem.published_at.is_not(None),
                    ContentItem.published_at >= now - timedelta(hours=window_hours),
                )
                .order_by(ContentItem.last_seen_at.desc())
                .limit(500)
            )
        ).all()
        velocity_latest = (
            select(
                DerivedMetric.entity_id,
                func.max(DerivedMetric.calculated_at).label("calculated_at"),
            )
            .where(
                DerivedMetric.workspace_id == workspace_id,
                DerivedMetric.entity_type == "content_item",
                DerivedMetric.metric_key == "view_velocity",
            )
            .group_by(DerivedMetric.entity_id)
            .subquery()
        )
        velocity_rows = (
            await self.session.scalars(
                select(DerivedMetric).join(
                    velocity_latest,
                    and_(
                        velocity_latest.c.entity_id == DerivedMetric.entity_id,
                        velocity_latest.c.calculated_at == DerivedMetric.calculated_at,
                    ),
                )
            )
        ).all()
        velocity_by_content = {row.entity_id: float(row.value) for row in velocity_rows}
        counts: dict[str, Any] = {}
        platform_signals: dict[str, dict[str, list[float]]] = {}
        row_signals: dict[UUID, dict[str, float | None]] = {}
        term_aggregates: dict[str, dict[str, dict[str, Any]]] = {}
        for item, snapshot, platform, _account in rows:
            views = (
                float(snapshot.view_count) if snapshot and snapshot.view_count is not None else None
            )
            age_hours = (
                max(1.0, (now - item.published_at.astimezone(UTC)).total_seconds() / 3600)
                if item.published_at is not None
                else None
            )
            velocity = velocity_by_content.get(item.id)
            engagement = _engagement_rate(snapshot)
            row_signals[item.id] = {
                "views": views,
                "velocity": velocity,
                "engagement": engagement,
                "age_hours": age_hours,
            }
            platform_signal_lists = platform_signals.setdefault(
                platform.key, {"views": [], "velocity": [], "engagement": []}
            )
            for key, value in (
                ("views", views),
                ("velocity", velocity),
                ("engagement", engagement),
            ):
                if value is not None:
                    platform_signal_lists[key].append(value)
        for item, snapshot, platform, account in rows:
            views = (
                int(snapshot.view_count) if snapshot and snapshot.view_count is not None else None
            )
            row_signal = row_signals[item.id]
            population = platform_signals[platform.key]
            component_scores = {
                "views": (
                    percentile_rank(row_signal["views"], population["views"]),
                    0.30,
                ),
                "view_velocity": (
                    percentile_rank(row_signal["velocity"], population["velocity"]),
                    0.35,
                ),
                "engagement": (
                    percentile_rank(row_signal["engagement"], population["engagement"]),
                    0.20,
                ),
                "freshness": (
                    freshness_score(row_signal["age_hours"], half_life_hours=72),
                    0.15,
                ),
            }
            raw_breakout, applied_weights = weighted_available_score(
                component_scores, minimum_components=2
            )
            available_count = sum(value is not None for value, _weight in component_scores.values())
            confidence = sample_confidence(len(population["views"])) * (available_count / 4)
            breakout_score = _confidence_adjusted(raw_breakout, confidence)
            content_text = f"{item.title}\n{item.description or ''}"
            configured_category = str(item.metadata_json.get("category") or "").strip()
            category = (
                configured_category
                if configured_category.casefold() not in {"", "general", "sports"}
                else _infer_sports_category(content_text)
            )
            self.session.add(
                TrendVideo(
                    workspace_id=workspace_id,
                    platform=platform.key,
                    external_id=item.external_id,
                    title=item.title,
                    author_name=account.display_name,
                    author_url=account.profile_url,
                    cover_url=item.cover_url,
                    video_url=item.canonical_url,
                    view_count=views,
                    like_count=(
                        int(snapshot.like_count)
                        if snapshot and snapshot.like_count is not None
                        else None
                    ),
                    comment_count=(
                        int(snapshot.comment_count)
                        if snapshot and snapshot.comment_count is not None
                        else None
                    ),
                    share_count=(
                        int(snapshot.share_count)
                        if snapshot and snapshot.share_count is not None
                        else None
                    ),
                    breakout_score=breakout_score,
                    category=category,
                    metadata_json={
                        "source_kind": "live",
                        "provider": item.source_provider,
                        "access_method": "monitored_account",
                        "metric_kind": "derived",
                        "formula_version": "trend-opportunity-v2",
                        "breakout_score_method": "confidence_adjusted_multisignal_score",
                        "component_scores": {
                            key: value for key, (value, _weight) in component_scores.items()
                        },
                        "applied_weights": applied_weights,
                        "confidence_score": round(confidence, 4),
                        "sample_size": len(population["views"]),
                        "velocity_basis": (
                            "observed_snapshot_delta_per_hour"
                            if row_signal["velocity"] is not None
                            else "unavailable"
                        ),
                        "source_url": item.canonical_url,
                        "source_entity_id": str(item.id),
                        "content_published_at": (
                            item.published_at.isoformat() if item.published_at else None
                        ),
                        "collected_at": now.isoformat(),
                    },
                    observed_at=now,
                )
            )
            summary = counts.setdefault(
                platform.key,
                {"topics": 0, "videos": 0, "keywords": 0, "status": "collected"},
            )
            summary["videos"] += 1
            platform_terms = term_aggregates.setdefault(platform.key, {})
            for term in _trend_terms(content_text):
                aggregate = platform_terms.setdefault(
                    term.casefold(),
                    {
                        "title": term,
                        "video_count": 0,
                        "total_views": 0,
                        "view_sample_count": 0,
                        "providers": set(),
                        "source_entity_ids": [],
                        "latest_published_at": None,
                    },
                )
                aggregate["video_count"] += 1
                if views is not None:
                    aggregate["total_views"] += int(views)
                    aggregate["view_sample_count"] += 1
                aggregate["providers"].add(item.source_provider)
                if item.published_at is not None and (
                    aggregate["latest_published_at"] is None
                    or item.published_at > aggregate["latest_published_at"]
                ):
                    aggregate["latest_published_at"] = item.published_at
                if len(aggregate["source_entity_ids"]) < 5:
                    aggregate["source_entity_ids"].append(str(item.id))

        for platform_key, aggregates in term_aggregates.items():
            ranked = sorted(
                aggregates.values(),
                key=lambda item: (item["total_views"], item["video_count"]),
                reverse=True,
            )[:50]
            summary = counts[platform_key]
            volume_population = [int(item["video_count"]) for item in ranked]
            view_population = [
                int(item["total_views"]) for item in ranked if int(item["view_sample_count"]) > 0
            ]
            average_view_population = [
                float(item["total_views"]) / int(item["view_sample_count"])
                for item in ranked
                if int(item["view_sample_count"]) > 0
            ]
            previous_rows = (
                await self.session.scalars(
                    select(TrendKeywordSnapshot)
                    .where(
                        TrendKeywordSnapshot.workspace_id == workspace_id,
                        TrendKeywordSnapshot.platform == platform_key,
                        TrendKeywordSnapshot.observed_at < now,
                    )
                    .order_by(TrendKeywordSnapshot.observed_at.desc())
                    .limit(500)
                )
            ).all()
            previous_by_keyword: dict[str, TrendKeywordSnapshot] = {}
            for previous_row in previous_rows:
                previous_by_keyword.setdefault(previous_row.keyword.casefold(), previous_row)
            for rank, aggregate in enumerate(ranked, start=1):
                video_count = int(aggregate["video_count"])
                view_sample_count = int(aggregate["view_sample_count"])
                total_views = int(aggregate["total_views"]) if view_sample_count > 0 else None
                average_views = (
                    total_views / view_sample_count
                    if total_views is not None and view_sample_count
                    else None
                )
                raw_heat, applied_weights = weighted_available_score(
                    {
                        "sample_volume": (percentile_rank(video_count, volume_population), 0.15),
                        "sample_views": (percentile_rank(total_views, view_population), 0.45),
                        "average_views": (
                            percentile_rank(average_views, average_view_population),
                            0.30,
                        ),
                        "source_breadth": (
                            min(100.0, 100.0 * len(aggregate["providers"]) / 3),
                            0.10,
                        ),
                    },
                    minimum_components=2,
                )
                confidence = sample_confidence(video_count, target_size=8)
                heat_score = _confidence_adjusted(raw_heat, confidence) or 50.0
                previous_snapshot = previous_by_keyword.get(str(aggregate["title"]).casefold())
                growth_rate = (
                    (total_views - previous_snapshot.total_views) / previous_snapshot.total_views
                    if previous_snapshot is not None
                    and total_views is not None
                    and previous_snapshot.total_views is not None
                    and previous_snapshot.total_views > 0
                    else None
                )
                metadata = {
                    "source_kind": "live",
                    "provider": "derived_from_monitored_content",
                    "source_providers": sorted(aggregate["providers"]),
                    "access_method": "monitored_account",
                    "metric_kind": "derived",
                    "derivation_method": "ranked_topics_events_entities_v2",
                    "formula_version": "trend-topic-heat-v2",
                    "heat_score_method": (
                        "confidence_adjusted_volume_total_views_average_views_breadth"
                    ),
                    "applied_weights": applied_weights,
                    "confidence_score": confidence,
                    "view_sample_size": view_sample_count,
                    "growth_rate_basis": (
                        "change_in_sample_total_views" if growth_rate is not None else None
                    ),
                    "source_entity_ids": aggregate["source_entity_ids"],
                    "source_published_at": (
                        aggregate["latest_published_at"].isoformat()
                        if aggregate["latest_published_at"] is not None
                        else None
                    ),
                    "collected_at": now.isoformat(),
                }
                self.session.add(
                    TrendTopic(
                        workspace_id=workspace_id,
                        platform=platform_key,
                        title=str(aggregate["title"]),
                        category=_infer_sports_category(str(aggregate["title"])),
                        heat_score=heat_score,
                        growth_rate=growth_rate,
                        rank=rank,
                        sample_size=video_count,
                        metadata_json=metadata,
                        observed_at=now,
                    )
                )
                self.session.add(
                    TrendKeywordSnapshot(
                        workspace_id=workspace_id,
                        keyword=str(aggregate["title"]),
                        platform=platform_key,
                        observed_at=now,
                        video_count=video_count,
                        total_views=total_views,
                        avg_views=average_views,
                        heat_index=heat_score,
                        metadata_json=metadata,
                    )
                )
                summary["topics"] += 1
                summary["keywords"] += 1
        return counts

    # ------------------------------------------------------------------
    # YouTube 采集（需要 API Key，无 Key 时跳过）
    # ------------------------------------------------------------------

    async def collect_youtube_trends(self, workspace_id: UUID) -> dict[str, int]:
        """采集 YouTube 趋势视频（需要配置 youtube_api_key）"""
        counts = {"topics": 0, "videos": 0, "keywords": 0}

        # 检查 API Key 是否可用
        mode, credential = await PlatformCredentialService(self.session, self._settings).resolve(
            workspace_id, "youtube"
        )
        api_key = credential.get("api_key") if mode == "api" else None
        if not isinstance(api_key, str) or not api_key:
            logger.info("youtube_api_key_not_configured, skipping youtube collection")
            return counts
        key = api_key

        # YouTube categoryId 到分类名称的映射
        category_map = {
            "1": "Film & Animation",
            "2": "Autos & Vehicles",
            "10": "Music",
            "15": "Pets & Animals",
            "17": "Sports",
            "19": "Travel & Events",
            "20": "Gaming",
            "22": "People & Blogs",
            "23": "Comedy",
            "24": "Entertainment",
            "25": "News & Politics",
            "26": "Howto & Style",
            "27": "Education",
            "28": "Science & Technology",
        }

        try:
            async with httpx.AsyncClient(
                timeout=15, follow_redirects=False, headers=_DEFAULT_HEADERS
            ) as client:
                # 1. 热门趋势视频
                try:
                    resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={
                            "part": "snippet,statistics",
                            "chart": "mostPopular",
                            "regionCode": "US",
                            "maxResults": 20,
                            "key": key,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    items = data.get("items", [])
                    if items:
                        self._save_youtube_videos(workspace_id, items, category_map, "trending")
                        counts["videos"] += len(items)
                except Exception as exc:
                    logger.warning("youtube_trending_failed: %s", exc)

                # 2. 体育类搜索趋势
                try:
                    resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/search",
                        params={
                            "part": "snippet",
                            "q": "sports",
                            "type": "video",
                            "order": "viewCount",
                            "maxResults": 10,
                            "key": key,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    items = data.get("items", [])
                    if items:
                        now = datetime.now(UTC)
                        aggregates: dict[str, dict[str, Any]] = {}
                        for idx, item in enumerate(items, start=1):
                            snippet = item.get("snippet", {})
                            title = str(snippet.get("title", ""))
                            video_id = item.get("id", {}).get("videoId", "")
                            for term in _trend_terms(title):
                                aggregate = aggregates.setdefault(
                                    term.casefold(),
                                    {
                                        "title": term,
                                        "count": 0,
                                        "rank_weight": 0.0,
                                        "video_ids": [],
                                    },
                                )
                                aggregate["count"] += 1
                                aggregate["rank_weight"] += 1 / idx
                                if video_id and len(aggregate["video_ids"]) < 5:
                                    aggregate["video_ids"].append(video_id)
                        ranked_terms = sorted(
                            aggregates.values(),
                            key=lambda value: (value["count"], value["rank_weight"]),
                            reverse=True,
                        )
                        count_population = [value["count"] for value in ranked_terms]
                        rank_population = [value["rank_weight"] for value in ranked_terms]
                        for idx, aggregate in enumerate(ranked_terms, start=1):
                            raw_heat, weights = weighted_available_score(
                                {
                                    "result_frequency": (
                                        percentile_rank(aggregate["count"], count_population),
                                        0.6,
                                    ),
                                    "search_rank_weight": (
                                        percentile_rank(aggregate["rank_weight"], rank_population),
                                        0.4,
                                    ),
                                },
                                minimum_components=2,
                            )
                            confidence = sample_confidence(aggregate["count"], target_size=5)
                            heat_score = _confidence_adjusted(raw_heat, confidence) or 50.0
                            self.session.add(
                                TrendTopic(
                                    workspace_id=workspace_id,
                                    platform="youtube",
                                    title=aggregate["title"],
                                    category=_infer_sports_category(aggregate["title"]),
                                    heat_score=heat_score,
                                    rank=idx,
                                    sample_size=aggregate["count"],
                                    metadata_json={
                                        **_live_metadata("youtube_data_api_v3"),
                                        "metric_kind": "derived",
                                        "formula_version": "youtube-search-topic-v2",
                                        "heat_score_method": (
                                            "controlled_term_frequency_and_search_rank"
                                        ),
                                        "applied_weights": weights,
                                        "confidence_score": confidence,
                                        "source_video_ids": aggregate["video_ids"],
                                        "is_sports": True,
                                    },
                                    observed_at=now,
                                )
                            )
                            counts["topics"] += 1
                except Exception as exc:
                    logger.warning("youtube_sports_search_failed: %s", exc)

        except Exception as exc:
            logger.error("youtube_collection_failed: %s", exc, exc_info=True)

        return counts

    def _save_youtube_videos(
        self,
        workspace_id: UUID,
        items: list[dict[str, Any]],
        category_map: dict[str, str],
        source: str,
    ) -> None:
        """将 YouTube 视频数据映射为 TrendVideo 并写入会话"""
        now = datetime.now(UTC)
        view_counts = [
            value
            for item in items
            if (value := _optional_int(item.get("statistics", {}).get("viewCount"))) is not None
        ]
        engagement_rates = [
            _engagement_from_statistics(item.get("statistics", {})) for item in items
        ]

        for rank, item in enumerate(items, start=1):
            video_id = item.get("id", "")
            if not video_id:
                continue
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            title = snippet.get("title", "")
            category_id = snippet.get("categoryId", "")
            category = canonical_trend_category(category_map.get(category_id, "general"))
            views = _optional_int(statistics.get("viewCount"))
            engagement = _engagement_from_statistics(statistics)
            published_at = snippet.get("publishedAt")
            age_hours: float | None = None
            if isinstance(published_at, str):
                try:
                    published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                    age_hours = max(0.0, (now - published.astimezone(UTC)).total_seconds() / 3600)
                except ValueError:
                    pass
            raw_score, applied_weights = weighted_available_score(
                {
                    "platform_chart_rank": (_position_heat_score(rank, len(items)), 0.55),
                    "views": (percentile_rank(views, view_counts), 0.20),
                    "engagement": (percentile_rank(engagement, engagement_rates), 0.15),
                    "freshness": (freshness_score(age_hours, half_life_hours=72), 0.10),
                },
                minimum_components=2,
            )
            confidence = sample_confidence(len(items)) * (
                sum(
                    component is not None
                    for component in (
                        _position_heat_score(rank, len(items)),
                        percentile_rank(views, view_counts),
                        percentile_rank(engagement, engagement_rates),
                        freshness_score(age_hours, half_life_hours=72),
                    )
                )
                / 4
            )

            # 缩略图取最高分辨率
            thumbnails = snippet.get("thumbnails", {})
            cover_url = (
                thumbnails.get("maxres", {}).get("url")
                or thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
            )

            video = TrendVideo(
                workspace_id=workspace_id,
                platform="youtube",
                external_id=video_id,
                title=title,
                author_name=snippet.get("channelTitle"),
                author_url=None,
                cover_url=cover_url,
                video_url=f"https://www.youtube.com/watch?v={video_id}",
                view_count=views,
                like_count=_optional_int(statistics.get("likeCount")),
                comment_count=_optional_int(statistics.get("commentCount")),
                share_count=None,
                breakout_score=_confidence_adjusted(raw_score, confidence),
                category=category,
                metadata_json={
                    **_live_metadata("youtube_data_api_v3"),
                    "metric_kind": "derived",
                    "formula_version": "youtube-chart-opportunity-v2",
                    "breakout_score_method": "chart_rank_views_engagement_freshness",
                    "applied_weights": applied_weights,
                    "confidence_score": round(confidence, 4),
                    "sample_size": len(items),
                    "source": source,
                    "published_at": snippet.get("publishedAt"),
                    "source_url": f"https://www.youtube.com/watch?v={video_id}",
                    "is_sports": _is_sports_related(f"{title} {category}"),
                },
                observed_at=now,
            )
            self.session.add(video)

    # ------------------------------------------------------------------
