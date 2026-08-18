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
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.trends import SearchAnalysis, SearchQuery
from app.providers.llm.base import LLMProvider
from app.providers.registry import ProviderRegistry
from app.providers.translation.http import HttpTranslationProvider, TranslationUnavailable
from app.services.audit import build_audit_entry
from app.services.llm_client import LLMUnavailableError, call_json_llm
from app.services.platform_search import PLATFORM_LABELS, SEARCHABLE_PLATFORMS, yt_search
from app.services.query_language import contains_cjk, detect_language, filter_english_results


def _views(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _heat_from_views(views: int) -> float:
    if views <= 0:
        return 0.0
    return round(min(100.0, 12.0 * math.log10(views + 1)), 1)


def _detect_language(text: str) -> str:
    return detect_language(text)


def _result_heat(result: dict[str, Any]) -> float:
    """Expose a derived per-result heat proxy without claiming platform data."""

    views = _views(result.get("view_count"))
    likes = _views(result.get("like_count"))
    comments = _views(result.get("comment_count"))
    return round(min(100.0, _heat_from_views(views) + math.log10(likes + comments + 1)), 1)


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
        llm_providers: ProviderRegistry[LLMProvider],
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.llm_providers = llm_providers
        self.settings = settings

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

    async def translate_analysis(
        self, workspace_id: UUID, query_id: UUID, target_language: str
    ) -> dict[str, Any]:
        query, analysis = await self.get_analysis(workspace_id, query_id)
        if target_language.casefold() in {"en", "en-us", "en-gb"}:
            return {
                "query": query,
                "analysis": analysis,
                "results": analysis.results_json or [],
                "language": "en",
            }
        cached = (analysis.translations_json or {}).get(target_language)
        if isinstance(cached, dict):
            return {"query": query, "analysis": analysis, **cached, "language": target_language}

        results = [dict(result) for result in analysis.results_json or []]
        process = [dict(step) for step in analysis.process_log_json or []]
        texts: list[str] = [query.query_text_en or query.query_text]
        for result in results:
            for key in ("title_en", "author_en"):
                if result.get(key):
                    texts.append(str(result[key]))
        if analysis.summary:
            texts.append(analysis.summary)
        for step in process:
            if step.get("message"):
                texts.append(str(step["message"]))
        translated = await self._translate_texts(
            texts, target_language=target_language, source_language="en"
        )
        cursor = 0
        localized_query = translated[cursor]
        cursor += 1
        localized_results: list[dict[str, Any]] = []
        for result in results:
            localized = dict(result)
            if result.get("title_en"):
                localized["title"] = translated[cursor]
                cursor += 1
            if result.get("author_en"):
                localized["author"] = translated[cursor]
                cursor += 1
            localized_results.append(localized)
        localized_summary = analysis.summary
        if analysis.summary:
            localized_summary = translated[cursor]
            cursor += 1
        for step in process:
            if step.get("message"):
                step["message"] = translated[cursor]
                cursor += 1
        localized_analysis = {
            "query_text": localized_query,
            "summary": localized_summary,
            "results": localized_results,
            "process_log": process,
        }
        translations = dict(analysis.translations_json or {})
        translations[target_language] = localized_analysis
        analysis.translations_json = translations
        await self.session.commit()
        await self.session.refresh(analysis)
        return {
            "query": query,
            "analysis": analysis,
            "results": localized_results,
            "process_log": process,
            "language": target_language,
            "translated_query_text": localized_query,
            "translated_summary": localized_summary,
        }

    async def list_queries(
        self,
        workspace_id: UUID,
        page: int = 1,
        page_size: int = 20,
        saved_only: bool = False,
    ) -> tuple[list[SearchQuery], int]:
        stmt = select(SearchQuery).where(SearchQuery.workspace_id == workspace_id)
        if saved_only:
            stmt = stmt.where(SearchQuery.is_saved.is_(True))
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = await self.session.scalars(
            stmt.order_by(SearchQuery.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.all()), int(total or 0)

    async def save_query(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        query_id: UUID,
        *,
        is_saved: bool,
        saved_name: str | None,
    ) -> SearchQuery:
        query = await self.session.scalar(
            select(SearchQuery).where(
                SearchQuery.workspace_id == workspace_id,
                SearchQuery.id == query_id,
            )
        )
        if query is None:
            raise ValueError("搜索记录不存在或不属于当前工作区")
        query.is_saved = is_saved
        query.saved_name = saved_name if is_saved else None
        self.session.add(
            build_audit_entry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action="search_query.saved" if is_saved else "search_query.unsaved",
                resource_type="search_query",
                resource_id=query.id,
                change_summary_json={
                    "is_saved": is_saved,
                    "saved_name": query.saved_name,
                },
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )
        await self.session.commit()
        await self.session.refresh(query)
        return query

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
        source_language = _detect_language(query_text)
        english_query = query_text.strip()
        process_log: list[dict[str, Any]] = [
            {
                "stage": "query_normalized",
                "status": "completed",
                "message": (
                    "Normalized the search scope and prepared an English platform query."
                ),
                "source_language": source_language,
            }
        ]

        all_results: list[dict[str, Any]] = []
        notes: list[str] = []
        if source_language != "en":
            try:
                translated_query = await self._translate_texts(
                    [query_text], target_language="en", source_language=source_language
                )
                english_query = translated_query[0].strip()
                if not english_query or contains_cjk(english_query):
                    raise TranslationUnavailable(
                        "translation backend returned a non-English search query"
                    )
                process_log.append(
                    {
                        "stage": "english_query_prepared",
                        "status": "completed",
                        "message": (
                            "Translated the input into an English search query; "
                            "platform search will not use the original non-English text."
                        ),
                        "query": english_query,
                    }
                )
            except TranslationUnavailable as exc:
                english_query = ""
                note = f"English platform search skipped: {exc}"
                notes.append(note)
                process_log.append(
                    {
                        "stage": "english_query_prepared",
                        "status": "degraded",
                        "message": note,
                    }
                )
        else:
            process_log.append(
                {
                    "stage": "english_query_prepared",
                    "status": "completed",
                    "message": (
                        "The input is already English and will be used as the platform query."
                    ),
                    "query": english_query,
                }
            )

        if english_query:
            for pf in platforms:
                results, search_note = await yt_search(
                    pf,
                    english_query,
                    limit=limit,
                    query_language="en",
                    region="US",
                )
                if search_note:
                    notes.append(search_note)
                all_results.extend(results)
        raw_result_count = len(all_results)
        all_results = filter_english_results(all_results)
        if raw_result_count != len(all_results):
            notes.append(
                f"Excluded {raw_result_count - len(all_results)} non-English platform results."
            )
        process_log.append(
            {
                "stage": "platform_search",
                "status": "completed" if all_results else "degraded",
                "message": (
                    f"Completed the English platform search with {len(all_results)} "
                    "English-source results."
                    if english_query
                    else "Skipped platform search because an English query was unavailable."
                ),
                "platforms": [PLATFORM_LABELS.get(p, p) for p in platforms],
                "result_count": len(all_results),
                "query": english_query or None,
                "region": "US",
            }
        )

        english_results = [dict(result) for result in all_results]
        for result in english_results:
            if result.get("title"):
                result["title_en"] = result["title"]
            if result.get("author"):
                result["author_en"] = result["author"]

        for result in english_results:
            result["heat_score"] = _result_heat(result)
            result["metric_source"] = "platform_fields_and_log_view_engagement_proxy"
        all_results = english_results

        # ---- aggregate basic signals -------------------------------------
        total_views = sum(_views(r.get("view_count")) for r in all_results)
        total_likes = sum(_views(r.get("like_count")) for r in all_results)
        total_comments = sum(_views(r.get("comment_count")) for r in all_results)
        raw_platforms = [r.get("platform") for r in all_results]
        per_platform = Counter(value for value in raw_platforms if isinstance(value, str) and value)
        platform_distribution = {PLATFORM_LABELS.get(p, p): c for p, c in per_platform.items()}
        date_buckets: Counter[str] = Counter()
        for r in all_results:
            bucket = _bucket_date(r.get("published"))
            if bucket:
                date_buckets[bucket] += 1
        timeline = [{"month": m, "count": c} for m, c in sorted(date_buckets.items())]
        computed_heat = _heat_from_views(total_views) if all_results else 0.0
        volume_estimate = {
            "total_hits": len(all_results),
            "total_views": total_views,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "average_views": round(total_views / len(all_results)) if all_results else 0,
            "top_view_count": max((_views(r.get("view_count")) for r in all_results), default=0),
            "metric_note": (
                "Views, likes, and comments are platform fields when returned; "
                "heat is a derived proxy."
            ),
            "platforms_searched": [PLATFORM_LABELS.get(p, p) for p in platforms],
        }
        process_log.append(
            {
                "stage": "metrics_aggregated",
                "status": "completed",
                "message": (
                    "Aggregated views, likes, comments, platform distribution, "
                    "and derived heat."
                ),
                "total_views": total_views,
                "total_likes": total_likes,
                "total_comments": total_comments,
            }
        )

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
                workspace_id, english_query, platform, all_results, volume_estimate, timeline
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
                "AI deep analysis unavailable: "
                f"{exc}. Returned measured search metrics and platform distribution."
            )
            analysis_fields["summary"] = (
                f"Search returned {len(all_results)} related results with "
                f"{total_views:,} total views."
                + (f" Note: {'; '.join(notes)}" if notes else "")
            )

        if notes:
            notice = (notice + " " if notice else "") + "；".join(notes)
        process_log.append(
            {
                "stage": "analysis_completed",
                "status": "completed" if not notice else "degraded",
                "message": "Persisted the English analysis snapshot and raw metric evidence.",
                "model_used": analysis_fields["model_used"],
            }
        )

        # ---- persist -----------------------------------------------------
        query = SearchQuery(
            workspace_id=workspace_id,
            query_text=query_text,
            query_text_en=english_query,
            source_language=source_language,
            platform_scope=platform,
            saved_name=None,
            is_saved=False,
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
            process_log_json=process_log,
            translations_json={},
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
        scope_label = (
            "all platforms"
            if platform in ("all", "", None)
            else PLATFORM_LABELS.get(platform, platform)
        )
        sample_titles = [str(r["title"]) for r in results[:15] if r.get("title") is not None]
        system_prompt = (
            "You are a sports intelligence analyst. Given a search description, scope, "
            "measured result metrics, and real result samples, return related heat, volume, "
            "sentiment, timeline, platform distribution, derivative angles, and one summary. "
            "Return JSON only, and write every text field in English."
        )
        user_prompt = (
            f"Search description: {query_text}\n"
            f"Search scope: {scope_label}\n"
            f"Measured metrics: {volume.get('total_hits')} results, "
            f"{volume.get('total_views'):,} total views, {volume.get('total_likes'):,} likes, "
            f"{volume.get('total_comments'):,} comments\n"
            f"Monthly timeline: {timeline}\n"
            f"Sample titles:\n- " + "\n- ".join(sample_titles) + "\n\n"
            'Return JSON: {"related_hotness": int(0-100), "sentiment": str('
            "'positive'|'neutral'|'negative'|'mixed'), \"timeline_phases\": "
            '[{"phase": str, "note": str}], "related_derivative_topics": '
            '[{"title": str, "angle": str, "predicted_heat_score": int}], '
            '"summary": str, "model_used": str}. All text must be English.'
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
