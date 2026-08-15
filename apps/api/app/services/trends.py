from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trends import TrendKeywordSnapshot, TrendTopic, TrendVideo
from app.schemas.trends import (
    PlatformSummary,
    ScoreComponent,
    ScoreExplanation,
    TrendAggregateItem,
    TrendDashboard,
    TrendKeywordSnapshotRead,
    TrendTopicPage,
    TrendTopicRead,
    TrendVideoPage,
    TrendVideoRead,
)

# 支持的平台列表
PLATFORMS = ("youtube", "tiktok", "douyin", "bilibili", "web")


class TrendService:
    """趋势分析服务层"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @staticmethod
    def _cutoff(window_hours: int = 24) -> datetime:
        """Return a bounded freshness cutoff for the hotspot dashboard."""
        safe_hours = max(24, min(int(window_hours), 72))
        return datetime.now(UTC) - timedelta(hours=safe_hours)

    @staticmethod
    def _row_is_in_window(row: Any, cutoff: datetime, *, topic: bool = False) -> bool:
        """Use publication evidence when available, not collection time alone.

        Older rows created before the publication metadata was introduced fall
        back to ``observed_at`` so the migration remains backward compatible.
        """
        metadata = row.metadata_json or {}
        key = "source_published_at" if topic else "content_published_at"
        raw = metadata.get(key)
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")) >= cutoff
            except ValueError:
                pass
        return bool(row.observed_at >= cutoff)

    @staticmethod
    def _topic_identity(row: TrendTopic) -> tuple[str, str]:
        """Return the stable identity used by all topic projections.

        Trend topics are append-only observations.  ``id`` is therefore a
        snapshot id, not an entity id; using it in analytics would render the
        same topic once per collection run.  Titles are the current canonical
        key because the collector stores normalized terms rather than a
        separate topic entity table.
        """
        return row.platform, row.title.strip().casefold()

    @staticmethod
    def _video_identity(row: TrendVideo) -> tuple[str, str]:
        """Return the stable identity for a video or public article row.

        Platform videos are keyed by their provider id.  RSS-backed web rows
        include the same article in multiple feeds, so their provider-scoped
        ``external_id`` is not an entity id; ``source_article_id`` is the
        canonical article identity and must take precedence when present.
        """
        if row.platform == "web":
            source_article_id = str(
                (row.metadata_json or {}).get("source_article_id") or ""
            ).strip()
            if source_article_id:
                return row.platform, source_article_id.casefold()
        return row.platform, row.external_id.strip()

    @staticmethod
    def _latest_unique[T: Any](
        rows: list[T], identity: Any,
    ) -> list[T]:
        """Keep the newest observation for each logical entity.

        The trend tables intentionally retain history for audit and trend
        analysis.  Read models must project that history into one current row
        per entity before ranking or summing metrics.  ``id`` is only a
        deterministic tie-breaker when two observations share a timestamp.
        """
        ordered = sorted(
            rows,
            key=lambda row: (row.observed_at, str(row.id)),
            reverse=True,
        )
        seen: set[Any] = set()
        result: list[T] = []
        for row in ordered:
            key = identity(row)
            if key in seen:
                continue
            seen.add(key)
            result.append(row)
        return result

    async def _latest_topics(
        self,
        workspace_id: UUID,
        platform: str | None = None,
        *,
        window_hours: int = 24,
    ) -> list[TrendTopic]:
        stmt = select(TrendTopic).where(
            TrendTopic.workspace_id == workspace_id,
            TrendTopic.observed_at >= self._cutoff(window_hours),
        )
        if platform:
            stmt = stmt.where(TrendTopic.platform == platform)
        rows = (
            await self.session.scalars(stmt.order_by(TrendTopic.observed_at.desc()).limit(5_000))
        ).all()
        cutoff = self._cutoff(window_hours)
        live_rows = [
            row
            for row in rows
            if (row.metadata_json or {}).get("source_kind") == "live"
            and self._row_is_in_window(row, cutoff, topic=True)
        ]
        return self._latest_unique(live_rows, self._topic_identity)

    async def _latest_videos(
        self,
        workspace_id: UUID,
        platform: str | None = None,
        *,
        window_hours: int = 24,
    ) -> list[TrendVideo]:
        stmt = select(TrendVideo).where(
            TrendVideo.workspace_id == workspace_id,
            TrendVideo.observed_at >= self._cutoff(window_hours),
        )
        if platform:
            stmt = stmt.where(TrendVideo.platform == platform)
        rows = (
            await self.session.scalars(stmt.order_by(TrendVideo.observed_at.desc()).limit(5_000))
        ).all()
        cutoff = self._cutoff(window_hours)
        live_rows = [
            row
            for row in rows
            if (row.metadata_json or {}).get("source_kind") == "live"
            and self._row_is_in_window(row, cutoff)
        ]
        return self._latest_unique(live_rows, self._video_identity)

    async def get_dashboard(
        self, workspace_id: UUID, *, window_hours: int = 24
    ) -> TrendDashboard:
        """Return de-duplicated live observations inside a 24–72h window."""
        safe_hours = max(24, min(int(window_hours), 72))
        topics = await self._latest_topics(workspace_id, window_hours=safe_hours)
        videos = await self._latest_videos(workspace_id, window_hours=safe_hours)
        top_topics = sorted(topics, key=lambda item: item.heat_score, reverse=True)[:15]
        breakout_videos = sorted(
            (item for item in videos if item.breakout_score is not None),
            key=lambda item: item.breakout_score or 0,
            reverse=True,
        )[:12]

        platform_summary: list[PlatformSummary] = []
        for platform in PLATFORMS:
            platform_topics = [item for item in topics if item.platform == platform]
            platform_videos = [item for item in videos if item.platform == platform]
            if not platform_topics and not platform_videos:
                continue
            heat_values = [item.heat_score for item in platform_topics]
            breakout_values = [
                item.breakout_score for item in platform_videos if item.breakout_score is not None
            ]
            view_values = [
                item.view_count for item in platform_videos if item.view_count is not None
            ]
            platform_summary.append(
                PlatformSummary(
                    platform=platform,
                    topic_count=len(platform_topics),
                    video_count=len(platform_videos),
                    avg_heat_score=(
                        round(sum(heat_values) / len(heat_values), 2) if heat_values else 0.0
                    ),
                    max_breakout_score=(
                        round(max(breakout_values), 2) if breakout_values else None
                    ),
                    total_views=sum(view_values) if view_values else None,
                )
            )

        return TrendDashboard(
            top_topics=[TrendTopicRead.model_validate(item) for item in top_topics],
            breakout_videos=[TrendVideoRead.model_validate(item) for item in breakout_videos],
            platform_summary=platform_summary,
            window_hours=safe_hours,
            generated_at=datetime.now(UTC),
        )

    async def list_topics(
        self,
        workspace_id: UUID,
        *,
        platform: str | None = None,
        window_hours: int = 24,
        page: int = 1,
        page_size: int = 20,
    ) -> TrendTopicPage:
        rows = await self._latest_topics(workspace_id, platform, window_hours=window_hours)
        rows.sort(key=lambda item: item.heat_score, reverse=True)
        start = (page - 1) * page_size
        items = rows[start : start + page_size]
        return TrendTopicPage(
            items=[TrendTopicRead.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=len(rows),
        )

    async def list_videos(
        self,
        workspace_id: UUID,
        *,
        platform: str | None = None,
        sort_by: str = "breakout_score",
        window_hours: int = 24,
        page: int = 1,
        page_size: int = 20,
    ) -> TrendVideoPage:
        rows = await self._latest_videos(workspace_id, platform, window_hours=window_hours)
        allowed_sort_fields = {
            "breakout_score",
            "view_count",
            "like_count",
            "comment_count",
            "share_count",
            "observed_at",
        }
        field = sort_by if sort_by in allowed_sort_fields else "breakout_score"
        rows.sort(
            key=lambda item: (getattr(item, field) is not None, getattr(item, field)),
            reverse=True,
        )
        start = (page - 1) * page_size
        items = rows[start : start + page_size]
        return TrendVideoPage(
            items=[TrendVideoRead.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=len(rows),
        )

    async def list_keywords(
        self,
        workspace_id: UUID,
        *,
        keyword: str | None = None,
        platform: str | None = None,
        window_hours: int = 24,
    ) -> list[TrendKeywordSnapshotRead]:
        stmt = select(TrendKeywordSnapshot).where(
            TrendKeywordSnapshot.workspace_id == workspace_id,
            TrendKeywordSnapshot.observed_at >= self._cutoff(window_hours),
        )
        if keyword:
            stmt = stmt.where(TrendKeywordSnapshot.keyword.ilike(f"%{keyword}%"))
        if platform:
            stmt = stmt.where(TrendKeywordSnapshot.platform == platform)
        rows = (
            await self.session.scalars(
                stmt.order_by(TrendKeywordSnapshot.observed_at.desc()).limit(5_000)
            )
        ).all()
        latest: list[TrendKeywordSnapshotRead] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            if row.metadata_json.get("source_kind") != "live":
                continue
            identity = (row.platform, row.keyword.casefold())
            if identity not in seen:
                seen.add(identity)
                latest.append(TrendKeywordSnapshotRead.model_validate(row))
            if len(latest) == 200:
                break
        return latest

    # ------------------------------------------------------------------
    # Aggregation (single/multi-platform + category)
    # ------------------------------------------------------------------

    async def aggregate(
        self,
        workspace_id: UUID,
        *,
        platforms: list[str] | None = None,
        category: str | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        """Aggregate trend topics/videos over a window for the analytics view.

        Produces four representations consumed by the four display modes:
        timeline (每天每平台累计热度), ranking (热点/视频按热度), index
        (各平台归一化热度 0-100), matrix (平台 × 分类 热度合计).
        """
        safe_days = max(1, min(int(days), 90))
        cutoff = datetime.now(UTC) - timedelta(days=safe_days)

        tstmt = select(TrendTopic).where(
            TrendTopic.workspace_id == workspace_id,
            TrendTopic.observed_at >= cutoff,
        )
        if platforms:
            tstmt = tstmt.where(TrendTopic.platform.in_(platforms))
        if category:
            tstmt = tstmt.where(TrendTopic.category == category)
        topic_rows = (
            await self.session.scalars(tstmt.order_by(TrendTopic.observed_at.desc()).limit(20_000))
        ).all()

        vstmt = select(TrendVideo).where(
            TrendVideo.workspace_id == workspace_id,
            TrendVideo.observed_at >= cutoff,
        )
        if platforms:
            vstmt = vstmt.where(TrendVideo.platform.in_(platforms))
        if category:
            vstmt = vstmt.where(TrendVideo.category == category)
        video_rows = (
            await self.session.scalars(vstmt.order_by(TrendVideo.observed_at.desc()).limit(20_000))
        ).all()

        # The tables are append-only snapshots.  Only live, publication-valid
        # observations belong in the default hotspot analytics, and each
        # logical entity must contribute once to ranking/index/matrix metrics.
        topics = [
            row
            for row in topic_rows
            if (row.metadata_json or {}).get("source_kind") == "live"
            and self._row_is_in_window(row, cutoff, topic=True)
        ]
        videos = [
            row
            for row in video_rows
            if (row.metadata_json or {}).get("source_kind") == "live"
            and self._row_is_in_window(row, cutoff)
        ]
        latest_topics = self._latest_unique(topics, self._topic_identity)
        latest_videos = self._latest_unique(videos, self._video_identity)

        # Preserve a useful daily timeline without summing repeated snapshots
        # of one entity collected multiple times on the same day.
        daily_topics = self._latest_unique(
            topics,
            lambda row: (row.observed_at.date().isoformat(), *self._topic_identity(row)),
        )
        daily_videos = self._latest_unique(
            videos,
            lambda row: (row.observed_at.date().isoformat(), *self._video_identity(row)),
        )

        plat_set: set[str] = set()
        cat_set: set[str] = set()
        for t in topics:
            plat_set.add(t.platform)
            cat_set.add(t.category)
        for v in videos:
            plat_set.add(v.platform)
            if v.category:
                cat_set.add(v.category)

        # 趋势时间线: 每天 × 平台 的累计热度
        day_plat_heat: dict[tuple[str, str], float] = {}
        for t in daily_topics:
            key = (t.observed_at.date().isoformat(), t.platform)
            day_plat_heat[key] = day_plat_heat.get(key, 0.0) + float(t.heat_score)
        for v in daily_videos:
            if v.breakout_score is not None:
                key = (v.observed_at.date().isoformat(), v.platform)
                day_plat_heat[key] = day_plat_heat.get(key, 0.0) + float(v.breakout_score)
        timeline = [
            {"date": d, "platform": p, "heat": h} for (d, p), h in sorted(day_plat_heat.items())
        ]

        # 排行榜单: 热点按热度 + 视频按爆发分
        top_topics = sorted(
            latest_topics,
            key=lambda x: (x.heat_score, x.observed_at),
            reverse=True,
        )[:25]
        top_videos = sorted(
            [v for v in latest_videos if v.breakout_score is not None],
            key=lambda x: (x.breakout_score or 0, x.observed_at),
            reverse=True,
        )[:25]
        ranking: list[TrendAggregateItem] = []
        for t in top_topics:
            ranking.append(
                TrendAggregateItem(
                    platform=t.platform,
                    category=t.category,
                    title=t.title,
                    kind="topic",
                    metric=float(t.heat_score),
                    metric_label="热度",
                    observed_at=t.observed_at,
                )
            )
        for v in top_videos:
            ranking.append(
                TrendAggregateItem(
                    platform=v.platform,
                    category=v.category or "general",
                    title=v.title,
                    kind="video",
                    metric=float(v.breakout_score or 0),
                    metric_label="爆发分",
                    observed_at=v.observed_at,
                )
            )

        # Ranking mixes two 0-100 derived scores, so sort the merged result by
        # score instead of placing every topic ahead of every video.
        ranking.sort(key=lambda item: item.metric, reverse=True)

        # 指数对比: 各平台当前实体热度归一化到 0-100
        plat_heat: dict[str, float] = {}
        for t in latest_topics:
            plat_heat[t.platform] = plat_heat.get(t.platform, 0.0) + float(t.heat_score)
        for v in latest_videos:
            if v.breakout_score is not None:
                plat_heat[v.platform] = plat_heat.get(v.platform, 0.0) + float(v.breakout_score)
        max_heat = max(plat_heat.values()) if plat_heat else 0.0
        index = [
            {
                "platform": p,
                "value": round((h / max_heat) * 100, 2) if max_heat else 0.0,
            }
            for p, h in sorted(plat_heat.items(), key=lambda kv: kv[1], reverse=True)
        ]

        # 热度矩阵: 平台 × 分类 热度合计
        pc: dict[tuple[str, str], float] = {}
        for t in latest_topics:
            k = (t.platform, t.category)
            pc[k] = pc.get(k, 0.0) + float(t.heat_score)
        for v in latest_videos:
            if v.breakout_score is not None and v.category:
                k = (v.platform, v.category)
                pc[k] = pc.get(k, 0.0) + float(v.breakout_score)
        matrix = [
            {"platform": p, "category": c, "heat": h}
            for (p, c), h in sorted(pc.items(), key=lambda kv: kv[1], reverse=True)
        ]

        return {
            "generated_at": datetime.now(UTC),
            "window_days": safe_days,
            "source_scope": "live",
            "raw_topic_observations": len(topics),
            "unique_topics": len(latest_topics),
            "raw_video_observations": len(videos),
            "unique_videos": len(latest_videos),
            "platforms": sorted(plat_set),
            "categories": sorted(cat_set),
            "timeline": timeline,
            "ranking": ranking,
            "index": index,
            "matrix": matrix,
        }

    # ------------------------------------------------------------------
    # Explainability
    # ------------------------------------------------------------------

    async def explain_video(self, workspace_id: UUID, video_id: UUID) -> ScoreExplanation:
        """Return a breakdown of how the breakout_score was calculated."""
        video = await self.session.get(TrendVideo, video_id)
        if video is None or video.workspace_id != workspace_id:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="趋势视频未找到")

        meta = video.metadata_json or {}
        algorithm = meta.get(
            "algorithm_version",
            meta.get("score_algorithm", "trend-opportunity-v2"),
        )
        components_raw = meta.get("components", meta.get("score_components", {}))
        actual_weights = meta.get("actual_weights", {})
        confidence = meta.get("confidence_score", meta.get("confidence"))
        sample_count = meta.get("sample_count", meta.get("platform_sample_size"))
        observed_start = meta.get("sample_window_start", meta.get("observed_from"))
        observed_end = meta.get("sample_window_end", meta.get("observed_to"))

        # Determine missing fields
        missing_fields: list[str] = []
        field_map = {
            "view_count": video.view_count,
            "like_count": video.like_count,
            "comment_count": video.comment_count,
            "share_count": video.share_count,
        }
        for field_name, value in field_map.items():
            if value is None:
                missing_fields.append(field_name)

        # Build component explanations
        components: list[ScoreComponent] = []
        component_defs = [
            ("view_percentile", "播放百分位", 0.30),
            ("playback_speed_percentile", "播放速度百分位", 0.35),
            ("engagement_rate_percentile", "互动率百分位", 0.20),
            ("freshness", "新鲜度(72h半衰期)", 0.15),
        ]
        for key, label, default_weight in component_defs:
            raw = components_raw.get(key)
            weight = actual_weights.get(key, default_weight)
            is_missing = raw is None
            contribution = None
            if raw is not None and weight > 0:
                contribution = round(float(raw) * float(weight), 4)
            note = None
            if is_missing:
                note = "字段缺失，未参与计算；权重已重归一化至其他分量"
            components.append(
                ScoreComponent(
                    name=label,
                    raw_value=float(raw) if raw is not None else None,
                    percentile=float(raw) if raw is not None else None,
                    weight=float(weight),
                    weighted_contribution=contribution,
                    missing=is_missing,
                    note=note,
                )
            )

        # Confidence reason
        confidence_reason = None
        if confidence is not None:
            reasons = []
            if sample_count is not None and int(sample_count) < 20:
                reasons.append(f"平台样本量较小({sample_count})，分数向50收缩")
            if missing_fields:
                reasons.append(f"缺失字段: {', '.join(missing_fields)}")
            if not reasons:
                reasons.append("样本量充足且字段完整")
            confidence_reason = "；".join(reasons)

        return ScoreExplanation(
            entity_id=video.id,
            entity_type="trend_video",
            score_field="breakout_score",
            score_value=video.breakout_score,
            algorithm_version=str(algorithm),
            components=components,
            missing_fields=missing_fields,
            sample_window={
                "start": str(observed_start) if observed_start else None,
                "end": str(observed_end) if observed_end else None,
                "observed_at": video.observed_at.isoformat() if video.observed_at else None,
            },
            confidence=float(confidence) if confidence is not None else None,
            confidence_reason=confidence_reason,
            metadata={
                "platform": video.platform,
                "external_id": video.external_id,
                "source_kind": meta.get("source_kind"),
                "provider": meta.get("provider"),
            },
        )

    async def explain_topic(self, workspace_id: UUID, topic_id: UUID) -> ScoreExplanation:
        """Return a breakdown of how the heat_score was calculated for a topic."""
        topic = await self.session.get(TrendTopic, topic_id)
        if topic is None or topic.workspace_id != workspace_id:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="趋势话题未找到")

        meta = topic.metadata_json or {}
        algorithm = meta.get(
            "algorithm_version",
            meta.get("score_algorithm", "trend-topic-heat-v2"),
        )
        components_raw = meta.get("components", meta.get("score_components", {}))
        actual_weights = meta.get("actual_weights", {})
        confidence = meta.get("confidence_score", meta.get("confidence"))
        sample_count = meta.get("sample_count", topic.sample_size)

        missing_fields: list[str] = []
        component_defs = [
            ("sample_size_percentile", "样本量百分位", 0.15),
            ("total_views_percentile", "样本总播放百分位", 0.45),
            ("avg_views_percentile", "样本平均播放百分位", 0.30),
            ("source_breadth", "来源广度", 0.10),
        ]

        components: list[ScoreComponent] = []
        for key, label, default_weight in component_defs:
            raw = components_raw.get(key)
            weight = actual_weights.get(key, default_weight)
            is_missing = raw is None
            contribution = None
            if raw is not None and weight > 0:
                contribution = round(float(raw) * float(weight), 4)
            note = None
            if is_missing:
                note = "分量不可用（播放字段缺失或样本不足），未按零分处理"
                missing_fields.append(key)
            components.append(
                ScoreComponent(
                    name=label,
                    raw_value=float(raw) if raw is not None else None,
                    percentile=float(raw) if raw is not None else None,
                    weight=float(weight),
                    weighted_contribution=contribution,
                    missing=is_missing,
                    note=note,
                )
            )

        confidence_reason = None
        if confidence is not None:
            reasons = []
            if sample_count is not None and int(sample_count) < 20:
                reasons.append(f"样本量({sample_count})不足20，分数向50收缩")
            if missing_fields:
                reasons.append(f"缺失分量: {', '.join(missing_fields)}")
            if not reasons:
                reasons.append("样本量充足且分量完整")
            confidence_reason = "；".join(reasons)

        return ScoreExplanation(
            entity_id=topic.id,
            entity_type="trend_topic",
            score_field="heat_score",
            score_value=topic.heat_score,
            algorithm_version=str(algorithm),
            components=components,
            missing_fields=missing_fields,
            sample_window={
                "observed_at": topic.observed_at.isoformat() if topic.observed_at else None,
                "sample_size": str(sample_count) if sample_count else None,
            },
            confidence=float(confidence) if confidence is not None else None,
            confidence_reason=confidence_reason,
            metadata={
                "platform": topic.platform,
                "source_kind": meta.get("source_kind"),
                "provider": meta.get("provider"),
            },
        )

    # ------------------------------------------------------------------
