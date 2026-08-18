from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.video_search import VideoSearchCandidate, VideoSearchPlan, VideoSearchRun
from app.schemas.topics import TopicCreate, TopicRead
from app.schemas.video_search import (
    PLATFORMS,
    VideoSearchPlanCreate,
    VideoSearchPlanUpdate,
    VideoSearchTopicCreate,
)
from app.services.platform_search import yt_search
from app.services.topics import TopicService
from app.services.video_content_analyzer import (
    VideoAnalysisResult,
    VideoAnalyzerUnavailableError,
    build_video_content_analyzer,
)

logger = logging.getLogger(__name__)


class VideoSearchCandidateError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def strict_content_match(result: VideoAnalysisResult, minimum_score: float) -> bool:
    """Return True only when a model supplied content evidence, not metadata."""
    has_timestamped_evidence = any(
        isinstance(segment, dict)
        and segment.get("evidence")
        and isinstance(segment.get("start_seconds"), (int, float))
        and isinstance(segment.get("end_seconds"), (int, float))
        and segment["start_seconds"] >= 0
        and segment["end_seconds"] >= segment["start_seconds"]
        for segment in result.segments
    )
    return bool(
        result.matches_query
        and result.match_score >= minimum_score
        and has_timestamped_evidence
        and result.match_basis
    )


def _canonical_url(platform: str, item: dict[str, Any]) -> str | None:
    raw_url = str(item.get("url") or item.get("webpage_url") or "").strip()
    if raw_url.startswith(("http://", "https://")):
        return raw_url
    external_id = str(item.get("external_id") or item.get("id") or raw_url).strip()
    if not external_id:
        return None
    if platform == "youtube":
        return f"https://www.youtube.com/watch?v={external_id}"
    if platform == "bilibili":
        return f"https://www.bilibili.com/video/{external_id}"
    return None


def _external_id(platform: str, url: str | None, item: dict[str, Any]) -> str | None:
    value = item.get("external_id") or item.get("id")
    if value:
        return str(value)
    if not url:
        return None
    if platform == "youtube" and "v=" in url:
        return url.split("v=", 1)[1].split("&", 1)[0]
    if platform == "bilibili" and "/video/" in url:
        return url.split("/video/", 1)[1].split("/", 1)[0].split("?", 1)[0]
    return None


def _published_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and len(value) == 8 and value.isdigit():
        try:
            return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _content_text(evidence: dict[str, Any]) -> str:
    pieces = [evidence.get("summary"), evidence.get("transcript_summary")]
    for key in ("visual_tags", "actions", "objects", "ocr_text", "audio_events", "match_basis"):
        values = evidence.get(key)
        if isinstance(values, list):
            pieces.extend(str(value) for value in values)
    for segment in evidence.get("segments", []):
        if isinstance(segment, dict) and segment.get("evidence"):
            pieces.append(str(segment["evidence"]))
    return " ".join(str(piece).strip() for piece in pieces if piece).strip()[:50_000]


def _result_evidence(result: VideoAnalysisResult) -> dict[str, Any]:
    return {
        "summary": result.summary,
        "segments": result.segments,
        "visual_tags": result.visual_tags,
        "actions": result.actions,
        "objects": result.objects,
        "ocr_text": result.ocr_text,
        "transcript_summary": result.transcript_summary,
        "audio_events": result.audio_events,
        "match_basis": result.match_basis,
    }


class VideoContentSearchService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def create_plan(
        self, workspace_id: UUID, actor_id: UUID, payload: VideoSearchPlanCreate
    ) -> VideoSearchPlan:
        interval = min(payload.interval_seconds, 2_592_000)
        plan = VideoSearchPlan(
            workspace_id=workspace_id,
            name=(payload.name or payload.query_text[:80]).strip(),
            query_text=payload.query_text,
            platforms_json=payload.platforms,
            interval_seconds=interval,
            max_candidates=min(
                payload.max_candidates, self.settings.video_search_max_candidates_per_run
            ),
            min_match_score=payload.min_match_score,
            content_mode=payload.content_mode,
            analyzer_key=payload.analyzer_key,
            created_by=actor_id,
            next_run_at=datetime.now(UTC),
        )
        self.db.add(plan)
        await self.db.flush()
        return plan

    async def get_plan(self, workspace_id: UUID, plan_id: UUID) -> VideoSearchPlan | None:
        return cast(
            VideoSearchPlan | None,
            await self.db.scalar(
                select(VideoSearchPlan).where(
                    VideoSearchPlan.id == plan_id,
                    VideoSearchPlan.workspace_id == workspace_id,
                )
            ),
        )

    async def list_plans(
        self, workspace_id: UUID, *, page: int, page_size: int
    ) -> tuple[list[VideoSearchPlan], int]:
        base = select(VideoSearchPlan).where(VideoSearchPlan.workspace_id == workspace_id)
        total = await self.db.scalar(select(func.count()).select_from(base.subquery())) or 0
        items = list(
            (
                await self.db.scalars(
                    base.order_by(VideoSearchPlan.updated_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return items, int(total)

    async def update_plan(
        self, workspace_id: UUID, plan_id: UUID, payload: VideoSearchPlanUpdate
    ) -> VideoSearchPlan | None:
        plan = await self.get_plan(workspace_id, plan_id)
        if plan is None:
            return None
        for field, value in payload.model_dump(exclude_unset=True).items():
            if field == "platforms":
                field = "platforms_json"
            if field == "query_text" and value is not None:
                value = " ".join(value.split())
            setattr(plan, field, value)
        if plan.status == "active" and plan.next_run_at < datetime.now(UTC):
            plan.next_run_at = datetime.now(UTC)
        await self.db.flush()
        return plan

    async def create_run(
        self, workspace_id: UUID, plan_id: UUID, task_id: str | None = None
    ) -> VideoSearchRun | None:
        plan = await self.get_plan(workspace_id, plan_id)
        if plan is None:
            return None
        active_run = await self.db.scalar(
            select(VideoSearchRun).where(
                VideoSearchRun.plan_id == plan_id,
                VideoSearchRun.status.in_(["queued", "running", "stopping"]),
            )
        )
        if active_run is not None:
            return active_run
        now = datetime.now(UTC)
        run = VideoSearchRun(
            plan_id=plan.id,
            workspace_id=workspace_id,
            task_id=task_id,
            status="queued",
            # Populate both timestamp fields in memory before dispatching the
            # Celery task.  Relying only on server defaults leaves ``updated_at``
            # expired on the async ORM instance; serializing it in the same
            # request can then trigger MissingGreenlet instead of returning the
            # accepted run response.
            created_at=now,
            updated_at=now,
        )
        self.db.add(run)
        await self.db.flush()
        return run

    async def list_runs(
        self, workspace_id: UUID, *, page: int, page_size: int, plan_id: UUID | None = None
    ) -> tuple[list[VideoSearchRun], int]:
        base = select(VideoSearchRun).where(VideoSearchRun.workspace_id == workspace_id)
        if plan_id:
            base = base.where(VideoSearchRun.plan_id == plan_id)
        total = await self.db.scalar(select(func.count()).select_from(base.subquery())) or 0
        items = list(
            (
                await self.db.scalars(
                    base.order_by(VideoSearchRun.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return items, int(total)

    async def stop_latest_run(self, workspace_id: UUID, plan_id: UUID) -> VideoSearchRun | None:
        run = await self.db.scalar(
            select(VideoSearchRun)
            .where(
                VideoSearchRun.workspace_id == workspace_id,
                VideoSearchRun.plan_id == plan_id,
                VideoSearchRun.status.in_(["queued", "running"]),
            )
            .order_by(VideoSearchRun.created_at.desc())
        )
        if run:
            run.stop_requested = True
            if run.status == "running":
                run.status = "stopping"
            await self.db.flush()
        return run

    async def list_candidates(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        plan_id: UUID | None = None,
        status: str = "matched",
        platform: str | None = None,
    ) -> tuple[list[VideoSearchCandidate], int]:
        base = select(VideoSearchCandidate).where(
            VideoSearchCandidate.workspace_id == workspace_id,
            VideoSearchCandidate.content_match_status == status,
        )
        if plan_id:
            base = base.where(VideoSearchCandidate.plan_id == plan_id)
        if platform:
            base = base.where(VideoSearchCandidate.platform == platform)
        total = await self.db.scalar(select(func.count()).select_from(base.subquery())) or 0
        items = list(
            (
                await self.db.scalars(
                    base.order_by(
                        VideoSearchCandidate.match_score.desc().nullslast(),
                        VideoSearchCandidate.updated_at.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return items, int(total)

    async def create_topic_from_candidate(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        candidate_id: UUID,
        payload: VideoSearchTopicCreate,
    ) -> TopicRead:
        """Promote one evidence-backed video result into an auditable topic.

        The candidate UUID is stored as the manual topic's ``source_id``.  It
        is intentionally not presented as a monitored platform content ID;
        the metadata keeps the original URL, provider, fetch time and
        analysis evidence so the topic can be traced back to the search run.
        """

        candidate = await self.db.scalar(
            select(VideoSearchCandidate).where(
                VideoSearchCandidate.workspace_id == workspace_id,
                VideoSearchCandidate.id == candidate_id,
            )
        )
        if candidate is None:
            raise VideoSearchCandidateError(
                "视频搜索候选不存在或不属于当前工作区",
                code="video_search_candidate_not_found",
                status_code=404,
            )
        if candidate.content_match_status != "matched":
            raise VideoSearchCandidateError(
                "只有已通过内容证据核验的候选才能进入选题库",
                code="video_search_candidate_not_matched",
                status_code=409,
            )

        evidence = dict(candidate.evidence_json or {})
        title = payload.title or candidate.title or f"{candidate.platform} 视频选题"
        summary = payload.summary or candidate.content_text or evidence.get("summary")
        metadata = {
            "source_kind": candidate.source_kind,
            "provider": candidate.source_provider,
            "external_id": candidate.external_id,
            "source_url": candidate.source_url or candidate.canonical_url,
            "fetched_at": candidate.fetched_at.isoformat(),
            "analyzed_at": candidate.analyzed_at.isoformat() if candidate.analyzed_at else None,
            "match_score": candidate.match_score,
            "video_search_candidate_id": str(candidate.id),
            "video_search_plan_id": str(candidate.plan_id),
            "evidence": evidence,
        }
        return await TopicService(self.db).create(
            workspace_id,
            actor_id,
            TopicCreate(
                title=title,
                summary=summary,
                source_type="manual",
                source_id=candidate.id,
                priority=payload.priority,
                notes=payload.notes,
                metadata=metadata,
            ),
        )

    async def capabilities(self) -> dict[str, Any]:
        analyzer = build_video_content_analyzer(self.settings)
        configured = analyzer is not None
        supported = analyzer.supported_platforms if analyzer else frozenset()
        platforms = {
            platform: {
                "discovery": platform in {"youtube", "bilibili"},
                "content_analysis": platform in supported,
                "status": "available" if platform in supported else "not_configured",
            }
            for platform in PLATFORMS
        }
        notice = (
            None
            if configured
            else "未配置真实视频分析器；系统会记录候选，但不会将其标记为内容命中。"
        )
        return {
            "analyzer_key": analyzer.key if analyzer else self.settings.video_search_analyzer,
            "configured": configured,
            "model": analyzer.model if analyzer else None,
            "platforms": platforms,
            "notice": notice,
        }

    async def execute_run(self, run_id: UUID) -> dict[str, Any]:
        run = await self.db.scalar(select(VideoSearchRun).where(VideoSearchRun.id == run_id))
        if run is None:
            return {"status": "missing", "run_id": str(run_id)}
        plan = await self.db.scalar(
            select(VideoSearchPlan).where(VideoSearchPlan.id == run.plan_id)
        )
        if plan is None:
            run.status = "failed"
            run.error_detail = "搜索计划不存在"
            await self.db.commit()
            return {"status": "failed", "run_id": str(run_id)}
        run.status = "running"
        run.started_at = datetime.now(UTC)
        await self.db.commit()

        analyzer = (
            build_video_content_analyzer(self.settings, requested_key=plan.analyzer_key)
            if plan.analyzer_key
            else None
        )
        discovery_errors: dict[str, str] = {}
        candidates: list[VideoSearchCandidate] = []
        seen_urls: set[str] = set()
        analysis_degraded = False
        per_platform = max(
            1, (plan.max_candidates + len(plan.platforms_json) - 1) // len(plan.platforms_json)
        )
        for platform in plan.platforms_json:
            try:
                items, error = await yt_search(platform, plan.query_text, limit=per_platform)
            except Exception as exc:  # noqa: BLE001 - isolate one source from the run
                items, error = [], str(exc)
            if error:
                discovery_errors[platform] = error
            for item in items:
                url = _canonical_url(platform, item)
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                existing = await self.db.scalar(
                    select(VideoSearchCandidate).where(
                        VideoSearchCandidate.plan_id == plan.id,
                        VideoSearchCandidate.canonical_url == url,
                    )
                )
                candidate = existing or VideoSearchCandidate(
                    plan_id=plan.id,
                    workspace_id=plan.workspace_id,
                    canonical_url=url,
                    source_kind="live",
                    source_provider="platform_search",
                    source_url=url,
                )
                candidate.last_run_id = run.id
                candidate.platform = platform
                candidate.external_id = _external_id(platform, url, item)
                candidate.title = item.get("title")
                candidate.author_name = item.get("author")
                candidate.cover_url = item.get("cover_url")
                candidate.published_at = _published_at(item.get("published"))
                candidate.content_match_status = "discovered"
                candidate.match_score = None
                candidate.error_detail = None
                candidate.fetched_at = datetime.now(UTC)
                if existing is None:
                    self.db.add(candidate)
                candidates.append(candidate)
                if len(candidates) >= plan.max_candidates:
                    break
            if len(candidates) >= plan.max_candidates:
                break
        await self.db.flush()
        run.candidate_count = len(candidates)
        await self.db.commit()

        for candidate in candidates:
            current = await self.db.scalar(
                select(VideoSearchRun).where(VideoSearchRun.id == run.id)
            )
            if current is None or current.stop_requested:
                run.status = "stopped"
                run.finished_at = datetime.now(UTC)
                break
            candidate.content_match_status = "analyzing"
            await self.db.commit()
            if analyzer is None or candidate.platform not in analyzer.supported_platforms:
                analysis_degraded = True
                candidate.content_match_status = "unavailable"
                candidate.error_detail = (
                    "未配置可读取该平台视频内容的分析器；候选发现不等于内容命中。"
                )
                run.analyzed_count += 1
                await self.db.commit()
                continue
            try:
                result = await analyzer.analyze(
                    video_url=candidate.canonical_url,
                    platform=candidate.platform,
                    query=plan.query_text,
                    metadata={"title": candidate.title, "author": candidate.author_name},
                )
                evidence = _result_evidence(result)
                candidate.evidence_json = evidence
                candidate.content_text = _content_text(evidence)
                candidate.match_score = result.match_score
                candidate.analysis_provider = result.provider
                candidate.analysis_model = result.model
                candidate.source_kind = result.source_kind
                candidate.analyzed_at = datetime.now(UTC)
                if strict_content_match(result, plan.min_match_score):
                    candidate.content_match_status = "matched"
                    run.matched_count += 1
                else:
                    candidate.content_match_status = "rejected"
                    run.rejected_count += 1
                run.analyzed_count += 1
                candidate.error_detail = None
            except VideoAnalyzerUnavailableError as exc:
                analysis_degraded = True
                candidate.content_match_status = "unavailable"
                candidate.error_detail = str(exc)
                run.analyzed_count += 1
            except Exception as exc:  # noqa: BLE001 - keep other candidates running
                analysis_degraded = True
                logger.exception(
                    "video_content_candidate_failed", extra={"candidate_id": str(candidate.id)}
                )
                candidate.content_match_status = "failed"
                candidate.error_detail = str(exc)[:4000]
                run.analyzed_count += 1
            await self.db.commit()

        if run.status != "stopped":
            run.status = "partial" if discovery_errors or analysis_degraded else "completed"
            run.finished_at = datetime.now(UTC)
            if discovery_errors:
                run.error_detail = json.dumps(discovery_errors, ensure_ascii=False)
        plan.last_run_at = datetime.now(UTC)
        plan.next_run_at = datetime.now(UTC) + timedelta(seconds=plan.interval_seconds)
        plan.last_error = (
            json.dumps(discovery_errors, ensure_ascii=False) if discovery_errors else None
        )
        if discovery_errors and not candidates:
            plan.status = "error"
        await self.db.commit()
        return {
            "status": run.status,
            "run_id": str(run.id),
            "candidate_count": run.candidate_count,
            "analyzed_count": run.analyzed_count,
            "matched_count": run.matched_count,
            "errors": discovery_errors,
        }
