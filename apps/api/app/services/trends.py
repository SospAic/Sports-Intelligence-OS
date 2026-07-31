from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trends import TrendKeywordSnapshot, TrendTopic, TrendVideo
from app.schemas.trends import (
    PlatformSummary,
    ScoreComponent,
    ScoreExplanation,
    TrendDashboard,
    TrendKeywordSnapshotRead,
    TrendTopicPage,
    TrendTopicRead,
    TrendVideoPage,
    TrendVideoRead,
)

# 支持的平台列表
PLATFORMS = ("youtube", "tiktok", "douyin", "bilibili")


class TrendService:
    """趋势分析服务层"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @staticmethod
    def _cutoff() -> datetime:
        return datetime.now(UTC) - timedelta(hours=24)

    async def _latest_topics(
        self, workspace_id: UUID, platform: str | None = None
    ) -> list[TrendTopic]:
        stmt = select(TrendTopic).where(
            TrendTopic.workspace_id == workspace_id,
            TrendTopic.observed_at >= self._cutoff(),
        )
        if platform:
            stmt = stmt.where(TrendTopic.platform == platform)
        rows = (
            await self.session.scalars(
                stmt.order_by(TrendTopic.observed_at.desc()).limit(5_000)
            )
        ).all()
        latest: list[TrendTopic] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            if row.metadata_json.get("source_kind") != "live":
                continue
            identity = (row.platform, row.title.casefold())
            if identity not in seen:
                seen.add(identity)
                latest.append(row)
        return latest

    async def _latest_videos(
        self, workspace_id: UUID, platform: str | None = None
    ) -> list[TrendVideo]:
        stmt = select(TrendVideo).where(
            TrendVideo.workspace_id == workspace_id,
            TrendVideo.observed_at >= self._cutoff(),
        )
        if platform:
            stmt = stmt.where(TrendVideo.platform == platform)
        rows = (
            await self.session.scalars(
                stmt.order_by(TrendVideo.observed_at.desc()).limit(5_000)
            )
        ).all()
        latest: list[TrendVideo] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            if row.metadata_json.get("source_kind") != "live":
                continue
            identity = (row.platform, row.external_id)
            if identity not in seen:
                seen.add(identity)
                latest.append(row)
        return latest

    async def get_dashboard(self, workspace_id: UUID) -> TrendDashboard:
        """Return de-duplicated latest observations from the last 24 hours."""
        topics = await self._latest_topics(workspace_id)
        videos = await self._latest_videos(workspace_id)
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
                item.breakout_score
                for item in platform_videos
                if item.breakout_score is not None
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
                        round(sum(heat_values) / len(heat_values), 2)
                        if heat_values
                        else 0.0
                    ),
                    max_breakout_score=(
                        round(max(breakout_values), 2) if breakout_values else None
                    ),
                    total_views=sum(view_values) if view_values else None,
                )
            )

        return TrendDashboard(
            top_topics=[TrendTopicRead.model_validate(item) for item in top_topics],
            breakout_videos=[
                TrendVideoRead.model_validate(item) for item in breakout_videos
            ],
            platform_summary=platform_summary,
        )

    async def list_topics(
        self,
        workspace_id: UUID,
        *,
        platform: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TrendTopicPage:
        rows = await self._latest_topics(workspace_id, platform)
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
        page: int = 1,
        page_size: int = 20,
    ) -> TrendVideoPage:
        rows = await self._latest_videos(workspace_id, platform)
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
    ) -> list[TrendKeywordSnapshotRead]:
        stmt = select(TrendKeywordSnapshot).where(
            TrendKeywordSnapshot.workspace_id == workspace_id,
            TrendKeywordSnapshot.observed_at >= self._cutoff(),
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
    # Explainability
    # ------------------------------------------------------------------

    async def explain_video(
        self, workspace_id: UUID, video_id: UUID
    ) -> ScoreExplanation:
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
            components.append(ScoreComponent(
                name=label,
                raw_value=float(raw) if raw is not None else None,
                percentile=float(raw) if raw is not None else None,
                weight=float(weight),
                weighted_contribution=contribution,
                missing=is_missing,
                note=note,
            ))

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

    async def explain_topic(
        self, workspace_id: UUID, topic_id: UUID
    ) -> ScoreExplanation:
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
            components.append(ScoreComponent(
                name=label,
                raw_value=float(raw) if raw is not None else None,
                percentile=float(raw) if raw is not None else None,
                weight=float(weight),
                weighted_contribution=contribution,
                missing=is_missing,
                note=note,
            ))

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
