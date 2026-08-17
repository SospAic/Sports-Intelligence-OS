"""Publication lifecycle and evidence-backed performance attribution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.editorial import EditorialItem
from app.models.generation import GenerationRun
from app.models.monitoring import Account, ContentItem, ContentSnapshot
from app.models.publication import PerformanceAttribution, Publication
from app.schemas.publication import (
    AttributionRefreshResponse,
    PerformanceAttributionRead,
    PublicationCreate,
    PublicationDetail,
    PublicationPage,
    PublicationRead,
    PublicationUpdate,
)
from app.services.audit import build_audit_entry

WINDOWS: tuple[tuple[str, int], ...] = (
    ("1h", 60 * 60),
    ("3h", 3 * 60 * 60),
    ("6h", 6 * 60 * 60),
    ("24h", 24 * 60 * 60),
    ("72h", 72 * 60 * 60),
    ("7d", 7 * 24 * 60 * 60),
    ("30d", 30 * 24 * 60 * 60),
)
WINDOW_SECONDS = dict(WINDOWS)
_MAX_SNAPSHOT_GRACE = timedelta(hours=24)


class PublicationError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class PublicationNotFound(PublicationError):
    def __init__(self, message: str = "发布记录不存在") -> None:
        super().__init__(message, code="publication_not_found", status_code=404)


class PublicationConflict(PublicationError):
    def __init__(self, message: str, code: str = "publication_conflict") -> None:
        super().__init__(message, code=code, status_code=409)


_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"planned", "scheduled", "cancelled", "failed"},
    "scheduled": {"scheduled", "published", "unverified", "cancelled", "failed"},
    "published": {"published", "unverified"},
    "unverified": {"unverified", "published", "failed"},
    "failed": {"failed", "planned", "scheduled"},
    "cancelled": {"cancelled", "planned"},
}


class PublicationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_publications(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        content_item_id: UUID | None = None,
        account_ids: set[UUID] | None = None,
    ) -> PublicationPage:
        conditions = [Publication.workspace_id == workspace_id]
        if status:
            conditions.append(Publication.status == status)
        if content_item_id:
            conditions.append(Publication.content_item_id == content_item_id)
        if account_ids is not None:
            conditions.append(
                (Publication.account_id.is_(None))
                | Publication.account_id.in_(account_ids)
            )
        rows = list(
            (
                await self.session.scalars(
                    select(Publication)
                    .where(*conditions)
                    .order_by(Publication.updated_at.desc(), Publication.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(Publication).where(*conditions)
            )
            or 0
        )
        return PublicationPage(
            items=[PublicationRead.model_validate(item) for item in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_detail(self, workspace_id: UUID, publication_id: UUID) -> PublicationDetail:
        publication = await self._get(workspace_id, publication_id)
        attributions = await self._list_attributions(publication)
        return PublicationDetail(
            **PublicationRead.model_validate(publication).model_dump(),
            attributions=[self._attribution_read(item, publication) for item in attributions],
        )

    async def create(
        self, workspace_id: UUID, actor_id: UUID, payload: PublicationCreate
    ) -> PublicationDetail:
        generation_run = await self._get_generation(workspace_id, payload.generation_run_id)
        editorial_item = await self._get_editorial(workspace_id, payload.editorial_item_id)
        content_item = await self._get_content(workspace_id, payload.content_item_id)
        account = await self._get_account(workspace_id, payload.account_id)
        if editorial_item is not None:
            if generation_run is not None and editorial_item.generation_run_id != generation_run.id:
                raise PublicationConflict("审核条目与生成运行不匹配", "publication_source_mismatch")
            if generation_run is None:
                generation_run = await self._get_generation(
                    workspace_id, editorial_item.generation_run_id
                )
        if content_item is not None:
            if payload.platform_id is not None and payload.platform_id != content_item.platform_id:
                raise PublicationConflict("作品与平台不匹配", "publication_platform_mismatch")
            if payload.account_id is not None and payload.account_id != content_item.account_id:
                raise PublicationConflict("作品与账号不匹配", "publication_account_mismatch")
            platform_id: UUID | None = content_item.platform_id
            account_id: UUID | None = content_item.account_id
        else:
            platform_id = payload.platform_id
            account_id = account.id if account is not None else None

        self._validate_status_fields(
            payload.status, payload.published_at, payload.external_id, payload.canonical_url
        )
        publication = Publication(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=actor_id,
            generation_run_id=generation_run.id if generation_run else None,
            editorial_item_id=editorial_item.id if editorial_item else None,
            content_item_id=content_item.id if content_item else None,
            account_id=account_id,
            platform_id=platform_id,
            title=payload.title.strip(),
            canonical_url=str(payload.canonical_url) if payload.canonical_url else None,
            external_id=payload.external_id,
            status=payload.status,
            scheduled_at=payload.scheduled_at,
            published_at=payload.published_at,
            source_kind=payload.source_kind,
            source_provider=payload.source_provider,
            source_url=str(payload.source_url) if payload.source_url else None,
            verification_note=payload.verification_note,
            metadata_json=payload.metadata,
        )
        self.session.add(publication)
        self._audit(
            workspace_id,
            actor_id,
            "publication.created",
            publication.id,
            {
                "status": publication.status,
                "source_kind": publication.source_kind,
                "content_item_id": str(publication.content_item_id)
                if publication.content_item_id
                else None,
                "generation_run_id": str(publication.generation_run_id)
                if publication.generation_run_id
                else None,
            },
        )
        await self.session.commit()
        await self.session.refresh(publication)
        return await self.get_detail(workspace_id, publication.id)

    async def update(
        self,
        workspace_id: UUID,
        publication_id: UUID,
        actor_id: UUID,
        payload: PublicationUpdate,
    ) -> PublicationDetail:
        publication = await self._get(workspace_id, publication_id)
        changes = payload.model_dump(exclude_unset=True)
        target_status = changes.get("status")
        if target_status is not None and target_status not in _TRANSITIONS.get(
            publication.status, set()
        ):
            raise PublicationConflict(
                f"发布状态不能从 {publication.status} 变更为 {target_status}",
                "publication_invalid_transition",
            )
        target_published_at = changes.get("published_at", publication.published_at)
        target_external_id = changes.get("external_id", publication.external_id)
        target_url = changes.get("canonical_url", publication.canonical_url)
        self._validate_status_fields(
            target_status or publication.status,
            target_published_at,
            target_external_id,
            target_url,
        )
        if "content_item_id" in changes:
            raise PublicationConflict(
                "发布关联作品创建后不可更换，请新建发布记录", "publication_content_immutable"
            )
        if "account_id" in changes or "platform_id" in changes:
            account = await self._get_account(workspace_id, changes.get("account_id"))
            content = await self._get_content(workspace_id, publication.content_item_id)
            if content is not None:
                account_id = changes.get("account_id", publication.account_id)
                platform_id = changes.get("platform_id", publication.platform_id)
                if account_id != content.account_id or platform_id != content.platform_id:
                    raise PublicationConflict(
                        "已关联作品的账号和平台不能改为不匹配的对象", "publication_source_mismatch"
                    )
            elif "account_id" in changes:
                publication.account_id = account.id if account is not None else None
        for field, value in changes.items():
            if field == "metadata":
                publication.metadata_json = value
            elif field == "canonical_url" and value is not None:
                setattr(publication, field, str(value))
            else:
                setattr(publication, field, value)
        self._audit(
            workspace_id, actor_id, "publication.updated", publication.id, _serializable(changes)
        )
        await self.session.commit()
        await self.session.refresh(publication)
        return await self.get_detail(workspace_id, publication.id)

    async def refresh_attribution(
        self, workspace_id: UUID, publication_id: UUID, actor_id: UUID
    ) -> AttributionRefreshResponse:
        publication = await self._get(workspace_id, publication_id)
        if publication.published_at is None:
            raise PublicationConflict(
                "发布记录没有 published_at，无法计算固定窗口归因",
                "attribution_publish_time_missing",
            )
        content = await self._get_content(workspace_id, publication.content_item_id)
        if content is None:
            raise PublicationConflict(
                "发布记录未关联已监控作品，无法读取真实表现快照",
                "attribution_content_missing",
            )
        existing = {row.window_key: row for row in await self._list_attributions(publication)}
        now = datetime.now(UTC)
        snapshots = list(
            (
                await self.session.scalars(
                    select(ContentSnapshot)
                    .where(ContentSnapshot.content_item_id == content.id)
                    .order_by(ContentSnapshot.captured_at.asc())
                )
            ).all()
        )
        for window_key, seconds in WINDOWS:
            target_at = publication.published_at + timedelta(seconds=seconds)
            row = existing.get(window_key)
            if row is None:
                row = PerformanceAttribution(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    publication_id=publication.id,
                    window_key=window_key,
                    window_seconds=seconds,
                    target_at=target_at,
                    measurement_status="not_due",
                    evidence_json={},
                )
                self.session.add(row)
                existing[window_key] = row
            row.target_at = target_at
            candidate = next(
                (
                    snapshot
                    for snapshot in snapshots
                    if snapshot.captured_at >= target_at
                    and snapshot.captured_at <= target_at + _MAX_SNAPSHOT_GRACE
                ),
                None,
            )
            if now < target_at:
                self._mark_unavailable(
                    row, status="not_due", note="固定窗口尚未到达", target_at=target_at
                )
            elif candidate is None:
                self._mark_unavailable(
                    row,
                    status="unavailable",
                    note="窗口已到达，但当前没有落在目标窗口及 24 小时宽限期内的真实内容快照",
                    target_at=target_at,
                )
            else:
                self._copy_snapshot(row, candidate, content, target_at)
        self._audit(
            workspace_id,
            actor_id,
            "publication.attribution_refreshed",
            publication.id,
            {"content_item_id": str(content.id), "window_count": len(WINDOWS)},
        )
        await self.session.commit()
        await self.session.refresh(publication)
        attributions = await self._list_attributions(publication)
        reads = [self._attribution_read(item, publication) for item in attributions]
        return AttributionRefreshResponse(
            publication=PublicationRead.model_validate(publication),
            attributions=reads,
            measured_count=sum(item.measurement_status == "measured" for item in reads),
            unavailable_count=sum(item.measurement_status == "unavailable" for item in reads),
            not_due_count=sum(item.measurement_status == "not_due" for item in reads),
        )

    async def _get(self, workspace_id: UUID, publication_id: UUID) -> Publication:
        item = await self.session.scalar(
            select(Publication).where(
                Publication.workspace_id == workspace_id,
                Publication.id == publication_id,
            )
        )
        if item is None:
            raise PublicationNotFound()
        return item

    async def _get_generation(
        self, workspace_id: UUID, run_id: UUID | None
    ) -> GenerationRun | None:
        if run_id is None:
            return None
        item = await self.session.scalar(
            select(GenerationRun).where(
                GenerationRun.workspace_id == workspace_id,
                GenerationRun.id == run_id,
            )
        )
        if item is None:
            raise PublicationNotFound("生成运行不存在或不属于当前工作区")
        return item

    async def _get_editorial(
        self, workspace_id: UUID, item_id: UUID | None
    ) -> EditorialItem | None:
        if item_id is None:
            return None
        item = await self.session.scalar(
            select(EditorialItem).where(
                EditorialItem.workspace_id == workspace_id,
                EditorialItem.id == item_id,
            )
        )
        if item is None:
            raise PublicationNotFound("审核条目不存在或不属于当前工作区")
        return item

    async def _get_content(self, workspace_id: UUID, content_id: UUID | None) -> ContentItem | None:
        if content_id is None:
            return None
        item = await self.session.scalar(
            select(ContentItem).where(
                ContentItem.workspace_id == workspace_id,
                ContentItem.id == content_id,
            )
        )
        if item is None:
            raise PublicationNotFound("监控作品不存在或不属于当前工作区")
        return item

    async def _get_account(self, workspace_id: UUID, account_id: UUID | None) -> Account | None:
        if account_id is None:
            return None
        item = await self.session.scalar(
            select(Account).where(
                Account.workspace_id == workspace_id,
                Account.id == account_id,
            )
        )
        if item is None:
            raise PublicationNotFound("账号不存在或不属于当前工作区")
        return item

    async def _list_attributions(self, publication: Publication) -> list[PerformanceAttribution]:
        return list(
            (
                await self.session.scalars(
                    select(PerformanceAttribution)
                    .where(PerformanceAttribution.publication_id == publication.id)
                    .order_by(PerformanceAttribution.window_seconds.asc())
                )
            ).all()
        )

    @staticmethod
    def _validate_status_fields(
        status: str,
        published_at: datetime | None,
        external_id: str | None,
        canonical_url: Any,
    ) -> None:
        if status in {"published", "unverified"} and published_at is None:
            raise PublicationConflict(
                "已发布或待核实记录必须提供 published_at", "publication_time_missing"
            )
        if status == "published" and not (external_id or canonical_url):
            raise PublicationConflict(
                "只有提供平台作品 ID 或链接后才能标记为已发布",
                "publication_evidence_missing",
            )

    @staticmethod
    def _mark_unavailable(
        row: PerformanceAttribution,
        *,
        status: str,
        note: str,
        target_at: datetime,
    ) -> None:
        row.measurement_status = status
        row.target_at = target_at
        row.captured_at = None
        row.view_count = None
        row.like_count = None
        row.comment_count = None
        row.share_count = None
        row.favorite_count = None
        row.follower_gain = None
        row.average_watch_time = None
        row.completion_rate = None
        row.source_kind = None
        row.source_provider = None
        row.source_url = None
        row.note = note
        row.evidence_json = {
            "target_at": target_at.isoformat(),
            "selection_policy": "first_snapshot_after_target_with_24h_grace",
        }

    @staticmethod
    def _copy_snapshot(
        row: PerformanceAttribution,
        snapshot: ContentSnapshot,
        content: ContentItem,
        target_at: datetime,
    ) -> None:
        row.measurement_status = "measured"
        row.target_at = target_at
        row.captured_at = snapshot.captured_at
        row.view_count = snapshot.view_count
        row.like_count = snapshot.like_count
        row.comment_count = snapshot.comment_count
        row.share_count = snapshot.share_count
        row.favorite_count = snapshot.favorite_count
        row.follower_gain = snapshot.follower_gain
        row.average_watch_time = snapshot.average_watch_time
        row.completion_rate = snapshot.completion_rate
        row.source_kind = snapshot.source_kind
        row.source_provider = snapshot.source_provider
        row.source_url = content.source_url or content.canonical_url
        row.note = "来自真实内容快照；未进行指标估算"
        row.evidence_json = {
            "content_snapshot_id": str(snapshot.id),
            "content_item_id": str(content.id),
            "target_at": target_at.isoformat(),
            "captured_at": snapshot.captured_at.isoformat(),
            "captured_offset_seconds": int((snapshot.captured_at - target_at).total_seconds()),
            "selection_policy": "first_snapshot_after_target_with_24h_grace",
        }

    @staticmethod
    def _attribution_read(
        row: PerformanceAttribution, publication: Publication
    ) -> PerformanceAttributionRead:
        value = PerformanceAttributionRead.model_validate(row)
        offset = row.evidence_json.get("captured_offset_seconds")
        if offset is None and row.captured_at is not None:
            offset = (
                int((row.captured_at - publication.published_at).total_seconds())
                if publication.published_at
                else None
            )
        return value.model_copy(update={"captured_offset_seconds": offset})

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_id: UUID,
        changes: dict[str, Any],
    ) -> None:
        self.session.add(
            build_audit_entry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type="publication",
                resource_id=resource_id,
                change_summary_json=changes,
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )


def _serializable(changes: dict[str, Any]) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, (UUID, datetime)) else value
        for key, value in changes.items()
    }
