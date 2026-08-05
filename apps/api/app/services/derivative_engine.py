"""Derivative-topic engine for the 热点情报中心 module.

Given a trending topic, this produces two kinds of derivative angles:

* ``existing_on_platform`` — cluster the real videos yt-dlp finds for the topic
  keyword into a few "angles" (深度解析 / 二创混剪 / 盘点榜单 …), recording the
  sample heat as evidence.
* ``ai_predicted`` — ask the workspace LLM which derivative angles are *not*
  yet saturated, with a predicted heat score and rationale.

Both are persisted as :class:`DerivativeTopic` rows so the UI can list,
filter and "adopt" them.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.trends import DerivativeTopic, TrendTopic
from app.providers.llm.base import LLMProvider
from app.providers.registry import ProviderRegistry
from app.services.llm_client import LLMUnavailableError, call_json_llm
from app.services.platform_search import yt_search

# Angle dictionary: each angle maps to keyword/regex hints used to bucket
# existing videos. Order matters — first match wins.
ANGLE_KEYWORDS: dict[str, list[str]] = {
    "深度解析": ["解析", "深度", "复盘", "为什么", "背后", "分析", "讲透", "科普"],
    "教程教学": ["教程", "教学", "怎么", "如何", "入门", "攻略", "教你", "技巧"],
    "二创混剪": ["混剪", "二创", "cut", "剪辑", "remix", "合集", "名场面", "高光"],
    "盘点榜单": ["盘点", "榜单", "top", "排名", "十大", "一生", "全集", "合集"],
    "幕后花絮": ["幕后", "花絮", "采访", "纪录片", "训练", "日常", "vlog", "准备"],
    "reaction吐槽": ["reaction", "反应", "吐槽", "评价", "看完", "震惊", "聊", "闲聊"],
    "数据可视化": ["数据", "可视化", "统计", "图表", "对比", "趋势", "报告"],
    "争议讨论": ["争议", "吵架", "翻车", "口水", "风波", "质疑", "道歉", "回应"],
}


def _classify_angle(title: str | None) -> str:
    if not title:
        return "其他角度"
    low = title.lower()
    for angle, hints in ANGLE_KEYWORDS.items():
        for hint in hints:
            if hint.lower() in low:
                return angle
    return "其他角度"


def _safe_int(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _median(values: list[int]) -> int:
    """True median (average of the two middle elements for even lengths)."""
    if not values:
        return 0
    ordered = sorted(values)
    n = len(ordered)
    if n % 2 == 1:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) // 2


def _heat_from_views(views: int) -> float:
    """Map an absolute view count to a 0-100 heat proxy (log scale)."""
    if views <= 0:
        return 0.0
    return round(min(100.0, 12.0 * math.log10(views + 1)), 1)


class DerivativeService:
    def __init__(
        self,
        session: AsyncSession,
        llm_providers: ProviderRegistry[LLMProvider],
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.llm_providers = llm_providers
        self.settings = settings

    async def list_derivatives(
        self,
        workspace_id: UUID,
        topic_id: UUID | None = None,
        kind: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[DerivativeTopic], int]:
        stmt = select(DerivativeTopic).where(DerivativeTopic.workspace_id == workspace_id)
        if topic_id is not None:
            stmt = stmt.where(DerivativeTopic.source_topic_id == topic_id)
        if kind is not None:
            stmt = stmt.where(DerivativeTopic.kind == kind)
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = await self.session.scalars(
            stmt.order_by(DerivativeTopic.confidence.desc(), DerivativeTopic.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.all()), int(total or 0)

    async def generate_for_topic(
        self, workspace_id: UUID, topic_id: UUID, actor_id: UUID
    ) -> tuple[list[DerivativeTopic], str | None]:
        """Cluster existing derivatives + generate AI-predicted angles.

        Returns the persisted rows and an optional notice (e.g. when the LLM
        is unavailable so only the existing-on-platform angles were produced).
        """
        topic = await self.session.get(TrendTopic, topic_id)
        if topic is None or topic.workspace_id != workspace_id:
            raise ValueError("热点话题不存在或不属于当前工作区")

        results, note = await yt_search(topic.platform, topic.title, limit=20)
        existing = self._cluster_existing(topic, results)
        for row in existing:
            self.session.add(row)

        notice: str | None = None
        predicted: list[DerivativeTopic] = []
        try:
            predicted = await self._predict(topic, existing, results)
            for row in predicted:
                self.session.add(row)
        except LLMUnavailableError as exc:
            notice = f"AI 潜在衍生未生成：{exc}. 仅展示平台上已存在的衍生内容。"

        await self.session.commit()
        await self.session.refresh(topic)
        all_rows = existing + predicted
        for row in all_rows:
            await self.session.refresh(row)
        return all_rows, notice

    def _cluster_existing(
        self, topic: TrendTopic, results: list[dict[str, Any]]
    ) -> list[DerivativeTopic]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for item in results:
            angle = _classify_angle(item.get("title"))
            buckets.setdefault(angle, []).append(item)

        now = datetime.now(UTC)
        rows: list[DerivativeTopic] = []
        for angle, items in buckets.items():
            if not items:
                continue
            views = [_safe_int(i.get("view_count")) for i in items]
            median_views = _median(views)
            sample_titles = [i.get("title") for i in items[:5] if i.get("title")]
            rows.append(
                DerivativeTopic(
                    workspace_id=topic.workspace_id,
                    source_topic_id=topic.id,
                    platform=topic.platform,
                    kind="existing_on_platform",
                    angle=angle,
                    title=f"{topic.title} · {angle}",
                    description=f"平台上已有 {len(items)} 条「{angle}」角度内容",
                    predicted_heat_score=_heat_from_views(median_views),
                    evidence_json={
                        "sample_count": len(items),
                        "median_views": median_views,
                        "sample_titles": sample_titles,
                    },
                    status="suggested",
                    confidence=round(min(1.0, 0.4 + 0.05 * len(items)), 2),
                    observed_at=now,
                )
            )
        return rows

    async def _predict(
        self,
        topic: TrendTopic,
        existing: list[DerivativeTopic],
        results: list[dict[str, Any]],
    ) -> list[DerivativeTopic]:
        existing_angles = [str(r.angle) for r in existing if r.angle]
        sample_titles = [str(i["title"]) for i in results[:12] if i.get("title") is not None]
        system_prompt = (
            "你是体育/短视频热点衍生内容策划专家。给定一条平台热点话题、"
            "其已经在平台上存在的衍生角度，以及若干样本标题，请预测尚未被"
            "充分开发的「潜在热门衍生话题」。只输出 JSON，不要额外解释。"
        )
        user_prompt = (
            f"热点话题：{topic.title}\n"
            f"平台：{topic.platform}\n"
            f"当前热度分：{topic.heat_score}\n"
            f"已存在的衍生角度：{', '.join(existing_angles) if existing_angles else '（无）'}\n"
            f"样本标题：\n- " + "\n- ".join(sample_titles) + "\n\n"
            '请输出 JSON：{"derivatives": [{"title": str, "angle": str, '
            '"description": str, "predicted_heat_score": int(0-100), '
            '"rationale": str}]}，给出 5-8 个高潜力且尚未饱和的衍生角度。'
        )
        data = await call_json_llm(
            self.session,
            self.llm_providers,
            self.settings,
            topic.workspace_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=60.0,
            max_tokens=1500,
        )
        items = data.get("derivatives") or []
        now = datetime.now(UTC)
        rows: list[DerivativeTopic] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            try:
                heat = float(item.get("predicted_heat_score") or 0)
            except (TypeError, ValueError):
                heat = 0.0
            rows.append(
                DerivativeTopic(
                    workspace_id=topic.workspace_id,
                    source_topic_id=topic.id,
                    platform=topic.platform,
                    kind="ai_predicted",
                    angle=item.get("angle"),
                    title=str(item.get("title")),
                    description=item.get("description"),
                    predicted_heat_score=round(min(100.0, max(0.0, heat)), 1),
                    ai_rationale=item.get("rationale"),
                    status="suggested",
                    confidence=round(min(1.0, 0.3 + heat / 200.0), 2),
                    observed_at=now,
                )
            )
        return rows

    async def adopt(
        self, workspace_id: UUID, derivative_id: UUID, actor_id: UUID
    ) -> DerivativeTopic:
        row = await self.session.get(DerivativeTopic, derivative_id)
        if row is None or row.workspace_id != workspace_id:
            raise ValueError("衍生话题不存在或不属于当前工作区")
        row.status = "adopted"
        await self.session.commit()
        await self.session.refresh(row)
        return row
