"""Smart-search analysis for the 热点情报中心 module.

Given a free-text description and an optional platform scope, this runs real
platform searches (via :mod:`app.services.platform_search`), aggregates basic
signals (volume, per-platform distribution, date timeline, a view-based heat
proxy), then asks the workspace LLM to produce a structured analysis:
related hotness, sentiment, timeline phases, related derivative topics, a
summary and source references. The LLM step degrades gracefully when the
provider is unconfigured.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.trends import SearchAnalysis, SearchQuery
from app.providers.registry import ProviderRegistry
from app.services.llm_client import LLMUnavailableError, call_json_llm
from app.services.platform_search import PLATFORM_LABELS, SEARCHABLE_PLATFORMS, yt_search


def _views(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _heat_from_views(views: int) -> float:
    if views <= 0:
        return 0.0
    return round(min(100.0, 12.0 * math.log10(views + 1)), 1)


def _bucket_date(published: Any) -> str | None:
    if published is None:
        return None
    text = str(published)
    # yt-dlp upload_date is YYYYMMDD; timestamps are unix seconds.
    if text.isdigit() and len(text) >= 8:
        if len(text) >= 12:  # unix timestamp
            try:
                return datetime.fromtimestamp(int(text), UTC).strftime("%Y-%m")
            except (OverflowError, OSError, ValueError):
                return None
        return f"{text[:4]}-{text[4:6]}"
    return None


class SearchAnalysisService:
    def __init__(
        self,
        session: AsyncSession,
        llm_providers: ProviderRegistry,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.llm_providers = llm_providers
        self.settings = settings

    async def list_queries(
        self, workspace_id: UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[SearchQuery], int]:
        stmt = select(SearchQuery).where(SearchQuery.workspace_id == workspace_id)
        total = await self.session.scalar(
            select(func.count()).select_from(stmt.subquery())
        )
        rows = await self.session.scalars(
            stmt.order_by(SearchQuery.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.all()), int(total or 0)

    async def get_analysis(
        self, workspace_id: UUID, query_id: UUID
    ) -> tuple[SearchQuery, SearchAnalysis]:
        query = await self.session.get(SearchQuery, query_id)
        if query is None or query.workspace_id != workspace_id:
            raise ValueError("搜索记录不存在或不属于当前工作区")
        analysis = await self.session.scalar(
            select(SearchAnalysis).where(SearchAnalysis.search_query_id == query_id)
        )
        if analysis is None:
            raise ValueError("该搜索尚未生成分析结果")
        return query, analysis

    async def analyze(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        query_text: str,
        platform: str = "all",
        limit: int = 10,
    ) -> tuple[SearchQuery, SearchAnalysis, list[dict[str, Any]], str | None]:
        platforms = SEARCHABLE_PLATFORMS if platform in ("all", "", None) else [platform]

        all_results: list[dict[str, Any]] = []
        notes: list[str] = []
        for pf in platforms:
            results, note = await yt_search(pf, query_text, limit=limit)
            if note:
                notes.append(note)
            all_results.extend(results)

        # ---- aggregate basic signals -------------------------------------
        total_views = sum(_views(r.get("view_count")) for r in all_results)
        per_platform = Counter(r.get("platform") for r in all_results)
        platform_distribution = {
            PLATFORM_LABELS.get(p, p): c for p, c in per_platform.items()
        }
        date_buckets: Counter[str] = Counter()
        for r in all_results:
            bucket = _bucket_date(r.get("published"))
            if bucket:
                date_buckets[bucket] += 1
        timeline = [
            {"month": m, "count": c}
            for m, c in sorted(date_buckets.items())
        ]
        computed_heat = _heat_from_views(total_views) if all_results else 0.0
        volume_estimate = {
            "total_hits": len(all_results),
            "total_views": total_views,
            "platforms_searched": [PLATFORM_LABELS.get(p, p) for p in platforms],
        }

        # ---- LLM structured analysis (degrades gracefully) ---------------
        notice: str | None = None
        analysis_fields: dict[str, Any] = {
            "related_hotness": computed_heat,
            "volume_estimate": volume_estimate,
            "sentiment": None,
            "timeline_phases": timeline,
            "platform_distribution": platform_distribution,
            "related_derivative_topics": None,
            "summary": None,
            "sources": all_results[:8],
            "model_used": None,
            "raw_llm": None,
        }
        try:
            llm_out = await self._call_analysis_llm(
                workspace_id, query_text, platform, all_results, volume_estimate, timeline
            )
            analysis_fields.update(
                {
                    "related_hotness": llm_out.get("related_hotness", computed_heat),
                    "sentiment": llm_out.get("sentiment"),
                    "related_derivative_topics": llm_out.get("related_derivative_topics"),
                    "summary": llm_out.get("summary"),
                    "model_used": llm_out.get("model_used"),
                    "raw_llm": llm_out,
                }
            )
        except LLMUnavailableError as exc:
            notice = (
                "AI 深度分析未生成："
                f"{exc}. 已返回基于检索结果的统计量（热度/声量/平台分布/时间线）。"
            )
            analysis_fields["summary"] = (
                f"检索到 {len(all_results)} 条相关内容，合计播放约 {total_views:,}。"
                + (f" 提示：{'; '.join(notes)}" if notes else "")
            )

        if notes:
            notice = (notice + " " if notice else "") + "；".join(notes)

        # ---- persist -----------------------------------------------------
        query = SearchQuery(
            workspace_id=workspace_id,
            query_text=query_text,
            platform_scope=platform,
            status="completed",
            requested_by=actor_id,
            result_count=len(all_results),
        )
        self.session.add(query)
        await self.session.flush()

        analysis = SearchAnalysis(
            workspace_id=workspace_id,
            search_query_id=query.id,
            related_hotness=analysis_fields["related_hotness"],
            volume_estimate=analysis_fields["volume_estimate"],
            sentiment=analysis_fields["sentiment"],
            timeline_phases=analysis_fields["timeline_phases"],
            platform_distribution=analysis_fields["platform_distribution"],
            related_derivative_topics=analysis_fields["related_derivative_topics"],
            summary=analysis_fields["summary"],
            sources=analysis_fields["sources"],
            model_used=analysis_fields["model_used"],
            raw_llm=analysis_fields["raw_llm"],
            results_json=all_results,
        )
        self.session.add(analysis)
        await self.session.commit()
        await self.session.refresh(query)
        await self.session.refresh(analysis)
        return query, analysis, all_results, notice

    async def _call_analysis_llm(
        self,
        workspace_id: UUID,
        query_text: str,
        platform: str,
        results: list[dict[str, Any]],
        volume: dict[str, Any],
        timeline: list[dict[str, Any]],
    ) -> dict[str, Any]:
        scope_label = "全网" if platform in ("all", "", None) else PLATFORM_LABELS.get(
            platform, platform
        )
        sample_titles = [r.get("title") for r in results[:15] if r.get("title")]
        system_prompt = (
            "你是热点情报分析师。给定一段用户检索描述、检索范围与真实检索结果样本，"
            "请输出该检索条件相关的热度、声量、情绪、时间线、平台分布、相关衍生话题与"
            "一句摘要。只输出 JSON，不要额外解释。"
        )
        user_prompt = (
            f"检索描述：{query_text}\n"
            f"检索范围：{scope_label}\n"
            f"检索统计：命中 {volume.get('total_hits')} 条，"
            f"合计播放约 {volume.get('total_views'):,}\n"
            f"时间线（按月计数）：{timeline}\n"
            f"样本标题：\n- " + "\n- ".join(sample_titles) + "\n\n"
            "请输出 JSON：{\"related_hotness\": int(0-100), \"sentiment\": str("
            "'positive'|'neutral'|'negative'|'mixed'), \"timeline_phases\": "
            "[{\"phase\": str, \"note\": str}], \"related_derivative_topics\": "
            "[{\"title\": str, \"angle\": str, \"predicted_heat_score\": int}], "
            "\"summary\": str(中文一句摘要), \"model_used\": str}。"
        )
        return await call_json_llm(
            self.session,
            self.llm_providers,
            self.settings,
            workspace_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout_seconds=60.0,
            max_tokens=1500,
        )
