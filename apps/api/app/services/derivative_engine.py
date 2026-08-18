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
from app.models.trends import DerivativeRun, DerivativeTopic, TrendTopic
from app.providers.llm.base import LLMProvider
from app.providers.registry import ProviderRegistry
from app.providers.translation.http import HttpTranslationProvider, TranslationUnavailable
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


def _normalise_search_result(item: dict[str, Any]) -> dict[str, Any]:
    """Keep raw platform metrics and expose a clearly derived heat proxy."""

    result = dict(item)
    views = _safe_int(result.get("view_count"))
    result["heat_score"] = _heat_from_views(views)
    result["metric_source"] = "platform_fields_and_log_view_proxy"
    return result


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

    async def list_runs(
        self, workspace_id: UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[DerivativeRun], int]:
        stmt = select(DerivativeRun).where(DerivativeRun.workspace_id == workspace_id)
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = await self.session.scalars(
            stmt.order_by(DerivativeRun.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.all()), int(total or 0)

    async def latest_run_for_topic(
        self, workspace_id: UUID, topic_id: UUID
    ) -> DerivativeRun | None:
        rows = await self.session.scalars(
            select(DerivativeRun)
            .where(
                DerivativeRun.workspace_id == workspace_id,
                DerivativeRun.source_topic_id == topic_id,
            )
            .order_by(DerivativeRun.created_at.desc())
            .limit(1)
        )
        return rows.first()

    async def _run_items(self, workspace_id: UUID, run_id: UUID) -> list[DerivativeTopic]:
        return list(
            (
                await self.session.scalars(
                    select(DerivativeTopic)
                    .where(
                        DerivativeTopic.workspace_id == workspace_id,
                        DerivativeTopic.derivative_run_id == run_id,
                    )
                    .order_by(DerivativeTopic.kind, DerivativeTopic.confidence.desc())
                )
            ).all()
        )

    async def get_run_detail(self, workspace_id: UUID, run_id: UUID) -> dict[str, Any]:
        run = await self.session.get(DerivativeRun, run_id)
        if run is None or run.workspace_id != workspace_id:
            raise ValueError("衍生生成记录不存在或不属于当前工作区")
        items = await self._run_items(workspace_id, run_id)
        return {
            "run": run,
            "items": items,
            "source_results": run.source_results_json,
            "process_log": run.process_log_json,
            "language": "en",
        }

    async def _translate_texts(
        self, texts: list[str], *, target_language: str, source_language: str = "auto"
    ) -> list[str]:
        if not texts:
            return []
        if (
            self.settings is None
            or self.settings.subtitle_translation_backend != "http"
            or not self.settings.subtitle_translation_base_url
        ):
            raise TranslationUnavailable("local translation backend is not configured")
        provider = HttpTranslationProvider(
            base_url=self.settings.subtitle_translation_base_url,
            api_key=(
                self.settings.subtitle_translation_api_key.get_secret_value()
                if self.settings.subtitle_translation_api_key
                else None
            ),
            timeout_seconds=self.settings.subtitle_translation_timeout_seconds,
        )
        return await provider.translate_segments(
            texts, source_language=source_language, target_language=target_language
        )

    async def translate_run(
        self, workspace_id: UUID, run_id: UUID, target_language: str
    ) -> dict[str, Any]:
        detail = await self.get_run_detail(workspace_id, run_id)
        run = detail["run"]
        if target_language.casefold() in {"en", "en-us", "en-gb"}:
            return detail
        cached = (run.translations_json or {}).get(target_language)
        if isinstance(cached, dict):
            return {
                "run": run,
                "items": cached.get("items", []),
                "source_results": cached.get("source_results", []),
                "process_log": cached.get("process_log", []),
                "language": target_language,
            }

        items = detail["items"]
        item_fields: list[tuple[DerivativeTopic, str, str]] = []
        texts: list[str] = []
        for item in items:
            for field, value in (
                ("title_en", item.title_en or item.title),
                ("description_en", item.description_en or item.description),
                ("ai_rationale_en", item.ai_rationale_en or item.ai_rationale),
                ("angle_en", item.angle_en or item.angle),
            ):
                if value:
                    item_fields.append((item, field, value))
                    texts.append(value)
        process = detail["process_log"]
        process_texts = [str(step.get("message")) for step in process if step.get("message")]
        result_rows = [dict(value) for value in detail["source_results"]]
        result_texts = [
            str(row.get("title_en") or row.get("title"))
            for row in result_rows
            if row.get("title_en") or row.get("title")
        ]
        translated = await self._translate_texts(
            texts + process_texts + result_texts,
            target_language=target_language,
            source_language="en",
        )
        cursor = 0
        item_translations: dict[str, dict[str, str]] = {}
        for item, field, _ in item_fields:
            item_translations.setdefault(str(item.id), {})[field] = translated[cursor]
            cursor += 1
        localized_items: list[dict[str, Any]] = []
        for item in items:
            payload = {
                "id": item.id,
                "workspace_id": item.workspace_id,
                "source_topic_id": item.source_topic_id,
                "derivative_run_id": item.derivative_run_id,
                "platform": item.platform,
                "kind": item.kind,
                "angle": item.angle,
                "title": item.title,
                "description": item.description,
                "predicted_heat_score": item.predicted_heat_score,
                "evidence_json": item.evidence_json,
                "ai_rationale": item.ai_rationale,
                "status": item.status,
                "confidence": item.confidence,
                "adopted_generation_id": item.adopted_generation_id,
                "observed_at": item.observed_at,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            payload.update(item_translations.get(str(item.id), {}))
            localized_items.append(payload)
        localized_process: list[dict[str, Any]] = []
        for step in process:
            copy = dict(step)
            if step.get("message"):
                copy["message"] = translated[cursor]
                cursor += 1
            localized_process.append(copy)
        for row in result_rows:
            if row.get("title_en") or row.get("title"):
                row["title_en"] = translated[cursor]
                cursor += 1
        cached_payload = {
            "items": localized_items,
            "source_results": result_rows,
            "process_log": localized_process,
        }
        translations = dict(run.translations_json or {})
        translations[target_language] = cached_payload
        run.translations_json = translations
        await self.session.commit()
        await self.session.refresh(run)
        return {
            "run": run,
            "items": localized_items,
            "source_results": result_rows,
            "process_log": localized_process,
            "language": target_language,
        }

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

        run = DerivativeRun(
            workspace_id=workspace_id,
            source_topic_id=topic.id,
            requested_by=actor_id,
            status="running",
            source_query=topic.title,
            platform=topic.platform,
            process_log_json=[],
            source_results_json=[],
            translations_json={},
        )
        self.session.add(run)
        await self.session.flush()
        process: list[dict[str, Any]] = [
            {
                "stage": "topic_context",
                "status": "completed",
                "message": "Loaded the selected hotspot topic and platform scope.",
            }
        ]
        notice_parts: list[str] = []
        try:
            try:
                run.source_query_en = (
                    await self._translate_texts([topic.title], target_language="en")
                )[0]
            except TranslationUnavailable as exc:
                run.source_query_en = None
                notice_parts.append(f"English translation unavailable: {exc}")
                process.append(
                    {
                        "stage": "english_translation",
                        "status": "degraded",
                        "message": str(exc),
                    }
                )
            results, note = await yt_search(topic.platform, topic.title, limit=20)
            if note:
                notice_parts.append(note)
            normalised_results = [_normalise_search_result(item) for item in results]
            run.source_results_json = normalised_results
            process.append(
                {
                    "stage": "platform_search",
                    "status": "completed" if not note else "degraded",
                    "message": f"Platform search completed with {len(results)} raw results.",
                    "query": run.source_query_en or topic.title,
                    "result_count": len(results),
                }
            )
            existing = self._cluster_existing(topic, normalised_results, run.id)
            for row in existing:
                self.session.add(row)

            predicted: list[DerivativeTopic] = []
            try:
                predicted = await self._predict(topic, existing, normalised_results, run.id)
                for row in predicted:
                    self.session.add(row)
            except LLMUnavailableError as exc:
                notice_parts.append(f"AI prediction unavailable: {exc}")
                process.append(
                    {"stage": "ai_prediction", "status": "degraded", "message": str(exc)}
                )

            all_rows = existing + predicted
            try:
                await self._populate_english_fields(all_rows, normalised_results)
                process.append(
                    {
                        "stage": "english_projection",
                        "status": "completed",
                        "message": (
                            "Generated English titles, descriptions, metrics, and "
                            "evidence projections."
                        ),
                    }
                )
            except TranslationUnavailable as exc:
                notice_parts.append(f"English result translation unavailable: {exc}")
                process.append(
                    {
                        "stage": "english_projection",
                        "status": "degraded",
                        "message": str(exc),
                    }
                )
            process.append(
                {
                    "stage": "angle_generation",
                    "status": "completed",
                    "message": f"Persisted {len(all_rows)} derivative angle results for this run.",
                    "result_count": len(all_rows),
                }
            )
            run.status = "degraded" if notice_parts else "completed"
            run.notice = " ".join(notice_parts) or None
            run.result_count = len(all_rows)
            run.process_log_json = process
            run.completed_at = datetime.now(UTC)
            await self.session.commit()
            all_rows = await self._run_items(workspace_id, run.id)
            return all_rows, run.notice
        except Exception as exc:
            run.status = "failed"
            run.notice = str(exc)[:2000]
            run.process_log_json = process + [
                {"stage": "run", "status": "failed", "message": "Derivative run failed."}
            ]
            run.completed_at = datetime.now(UTC)
            await self.session.commit()
            raise

    def _cluster_existing(
        self, topic: TrendTopic, results: list[dict[str, Any]], run_id: UUID | None = None
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
                    derivative_run_id=run_id,
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
                        "sample_results": items[:5],
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
        run_id: UUID | None = None,
    ) -> list[DerivativeTopic]:
        existing_angles = [str(r.angle) for r in existing if r.angle]
        sample_titles = [str(i["title"]) for i in results[:12] if i.get("title") is not None]
        system_prompt = (
            "You are a sports short-video derivative-angle strategist. Given one "
            "platform hotspot, existing angles, and sample titles, predict high-potential "
            "derivative angles that are not saturated. Return JSON only, in English."
        )
        user_prompt = (
            f"Hotspot: {topic.title}\n"
            f"Platform: {topic.platform}\n"
            f"Current heat score: {topic.heat_score}\n"
            f"Existing angles: {', '.join(existing_angles) if existing_angles else 'none'}\n"
            f"Sample titles:\n- " + "\n- ".join(sample_titles) + "\n\n"
            'Return JSON: {"derivatives": [{"title": str, "angle": str, '
            '"description": str, "predicted_heat_score": int(0-100), '
            '"rationale": str}]}. Provide 5-8 specific, unsaturated angles in English.'
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
                    derivative_run_id=run_id,
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

    async def _populate_english_fields(
        self, rows: list[DerivativeTopic], source_results: list[dict[str, Any]]
    ) -> None:
        texts: list[str] = []
        slots: list[tuple[DerivativeTopic, str]] = []
        for row in rows:
            for field, value in (
                ("title_en", row.title),
                ("description_en", row.description),
                ("ai_rationale_en", row.ai_rationale),
                ("angle_en", row.angle),
            ):
                if value:
                    texts.append(value)
                    slots.append((row, field))
        result_slots: list[dict[str, Any]] = []
        for item in source_results:
            if item.get("title"):
                result_slots.append(item)
                texts.append(str(item["title"]))
        translated = await self._translate_texts(texts, target_language="en")
        cursor = 0
        for row, field in slots:
            setattr(row, field, translated[cursor])
            cursor += 1
        for item in result_slots:
            item["title_en"] = translated[cursor]
            cursor += 1

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
