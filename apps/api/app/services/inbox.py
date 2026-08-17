"""Durable read receipts for the unified operations inbox."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inbox import InboxReadState
from app.models.inbox_queue import InboxQueueState, InboxSavedView
from app.models.workspace import WorkspaceMembership
from app.schemas.inbox import InboxReadStateRead
from app.schemas.inbox_queue import (
    InboxQueueStateBulkPatch,
    InboxQueueStatePatch,
    InboxQueueStateRead,
    InboxSavedViewCreate,
    InboxSavedViewRead,
    InboxSavedViewUpdate,
)
from app.services.audit import build_audit_entry


class InboxKeyError(ValueError):
    """Raised when a client sends an unknown or malformed inbox key."""


class InboxServiceError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class InboxService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_read_states(
        self,
        workspace_id: UUID,
        user_id: UUID,
        item_keys: list[str],
    ) -> list[InboxReadStateRead]:
        parsed = [_parse_item_key(key) for key in item_keys]
        if not parsed:
            return []
        conditions = [
            InboxReadState.workspace_id == workspace_id,
            InboxReadState.user_id == user_id,
        ]
        state_filters = [
            (InboxReadState.item_kind == kind) & (InboxReadState.item_id == item_id)
            for kind, item_id in parsed
        ]
        states = list(
            (
                await self.session.scalars(
                    select(InboxReadState)
                    .where(*conditions, or_(*state_filters))
                    .order_by(InboxReadState.read_at.desc())
                )
            ).all()
        )
        return [_read_state(state) for state in states]

    async def list_queue_states(
        self,
        workspace_id: UUID,
        item_keys: list[str],
    ) -> list[InboxQueueStateRead]:
        parsed = [_parse_item_key(key) for key in item_keys]
        filters = [InboxQueueState.workspace_id == workspace_id]
        if parsed:
            filters.append(
                or_(
                    *[
                        (InboxQueueState.item_kind == kind) & (InboxQueueState.item_id == item_id)
                        for kind, item_id in parsed
                    ]
                )
            )
        states = list(
            (
                await self.session.scalars(
                    select(InboxQueueState)
                    .where(*filters)
                    .order_by(InboxQueueState.updated_at.desc())
                    .limit(500)
                )
            ).all()
        )
        return [_queue_state(state) for state in states]

    async def update_queue_state(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        item_key: str,
        payload: InboxQueueStatePatch,
    ) -> InboxQueueStateRead:
        kind, item_id = _parse_item_key(item_key)
        state = await self.session.scalar(
            select(InboxQueueState).where(
                InboxQueueState.workspace_id == workspace_id,
                InboxQueueState.item_kind == kind,
                InboxQueueState.item_id == item_id,
            )
        )
        if payload.assignee_id is not None:
            await self._validate_assignee(workspace_id, payload.assignee_id)
        changes = payload.model_dump(exclude_unset=True)
        if state is None:
            state = InboxQueueState(
                workspace_id=workspace_id,
                item_kind=kind,
                item_id=item_id,
                state="open",
                labels=[],
            )
            self.session.add(state)
        for field, value in changes.items():
            setattr(state, field, value)
        state.updated_by = actor_id
        self.session.add(
            build_audit_entry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action="inbox_queue.state_updated",
                resource_type="inbox_queue_item",
                resource_id=item_id,
                change_summary_json={"item_key": item_key, **changes},
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )
        await self.session.commit()
        await self.session.refresh(state)
        return _queue_state(state)

    async def update_queue_states_bulk(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: InboxQueueStateBulkPatch,
    ) -> list[InboxQueueStateRead]:
        changes = payload.model_dump(exclude={"item_keys"}, exclude_unset=True)
        if not changes:
            raise InboxServiceError(
                "批量更新至少需要提供状态、标签、负责人或截止时间",
                code="inbox_queue_change_required",
            )
        results = []
        for item_key in dict.fromkeys(payload.item_keys):
            results.append(
                await self.update_queue_state(
                    workspace_id,
                    actor_id,
                    item_key,
                    InboxQueueStatePatch.model_validate(changes),
                )
            )
        return results

    async def list_views(self, workspace_id: UUID) -> list[InboxSavedViewRead]:
        views = list(
            (
                await self.session.scalars(
                    select(InboxSavedView)
                    .where(InboxSavedView.workspace_id == workspace_id)
                    .order_by(InboxSavedView.name.asc())
                )
            ).all()
        )
        return [_saved_view(view) for view in views]

    async def create_view(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: InboxSavedViewCreate,
    ) -> InboxSavedViewRead:
        name = payload.name.strip()
        await self._ensure_view_name_available(workspace_id, name)
        if payload.is_default:
            await self._clear_default_views(workspace_id)
        view = InboxSavedView(
            workspace_id=workspace_id,
            created_by=actor_id,
            name=name,
            filters_json=_normalise_view_filters(payload.filters),
            is_default=payload.is_default,
        )
        self.session.add(view)
        self._audit_view(workspace_id, actor_id, "inbox_view.created", view.id)
        await self.session.commit()
        await self.session.refresh(view)
        return _saved_view(view)

    async def get_view(self, workspace_id: UUID, view_id: UUID) -> InboxSavedView:
        view = await self.session.scalar(
            select(InboxSavedView).where(
                InboxSavedView.workspace_id == workspace_id,
                InboxSavedView.id == view_id,
            )
        )
        if view is None:
            raise InboxServiceError("保存视图不存在", code="inbox_view_not_found", status_code=404)
        return view

    async def update_view(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        view_id: UUID,
        payload: InboxSavedViewUpdate,
    ) -> InboxSavedViewRead:
        view = await self.get_view(workspace_id, view_id)
        changes = payload.model_dump(exclude_unset=True)
        if "name" in changes:
            changes["name"] = str(changes["name"]).strip()
            await self._ensure_view_name_available(workspace_id, changes["name"], view_id)
        if "filters" in changes:
            changes["filters_json"] = _normalise_view_filters(changes.pop("filters"))
        if changes.get("is_default"):
            await self._clear_default_views(workspace_id, excluding_id=view.id)
        for field, value in changes.items():
            setattr(view, field, value)
        self._audit_view(workspace_id, actor_id, "inbox_view.updated", view.id, changes)
        await self.session.commit()
        await self.session.refresh(view)
        return _saved_view(view)

    async def delete_view(self, workspace_id: UUID, actor_id: UUID, view_id: UUID) -> None:
        view = await self.get_view(workspace_id, view_id)
        self.session.add(
            build_audit_entry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action="inbox_view.deleted",
                resource_type="inbox_saved_view",
                resource_id=view.id,
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )
        await self.session.delete(view)
        await self.session.commit()

    async def mark_read(
        self,
        workspace_id: UUID,
        user_id: UUID,
        item_key: str,
    ) -> InboxReadStateRead:
        kind, item_id = _parse_item_key(item_key)
        return await self._upsert(workspace_id, user_id, kind, item_id)

    async def mark_many_read(
        self,
        workspace_id: UUID,
        user_id: UUID,
        item_keys: list[str],
    ) -> list[InboxReadStateRead]:
        parsed = [_parse_item_key(key) for key in dict.fromkeys(item_keys)]
        states = [
            await self._upsert(workspace_id, user_id, kind, item_id) for kind, item_id in parsed
        ]
        return states

    async def _upsert(
        self,
        workspace_id: UUID,
        user_id: UUID,
        kind: str,
        item_id: UUID,
    ) -> InboxReadStateRead:
        state = await self.session.scalar(
            select(InboxReadState).where(
                InboxReadState.workspace_id == workspace_id,
                InboxReadState.user_id == user_id,
                InboxReadState.item_kind == kind,
                InboxReadState.item_id == item_id,
            )
        )
        now = datetime.now(UTC)
        if state is None:
            state = InboxReadState(
                id=uuid4(),
                workspace_id=workspace_id,
                user_id=user_id,
                item_kind=kind,
                item_id=item_id,
                read_at=now,
            )
            self.session.add(state)
        else:
            state.read_at = now
        await self.session.flush()
        return _read_state(state)

    async def _validate_assignee(self, workspace_id: UUID, assignee_id: UUID) -> None:
        member = await self.session.scalar(
            select(WorkspaceMembership.id).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == assignee_id,
                WorkspaceMembership.status == "active",
            )
        )
        if member is None:
            raise InboxServiceError(
                "负责人不是当前工作区的活跃成员",
                code="inbox_assignee_invalid",
            )

    async def _ensure_view_name_available(
        self, workspace_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> None:
        filters = [InboxSavedView.workspace_id == workspace_id, InboxSavedView.name == name]
        if excluding_id is not None:
            filters.append(InboxSavedView.id != excluding_id)
        if await self.session.scalar(select(InboxSavedView.id).where(*filters)) is not None:
            raise InboxServiceError("当前工作区已存在同名保存视图", code="inbox_view_name_exists")

    async def _clear_default_views(
        self, workspace_id: UUID, excluding_id: UUID | None = None
    ) -> None:
        filters = [
            InboxSavedView.workspace_id == workspace_id,
            InboxSavedView.is_default.is_(True),
        ]
        if excluding_id is not None:
            filters.append(InboxSavedView.id != excluding_id)
        for view in (await self.session.scalars(select(InboxSavedView).where(*filters))).all():
            view.is_default = False

    def _audit_view(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_id: UUID,
        changes: dict[str, object] | None = None,
    ) -> None:
        self.session.add(
            build_audit_entry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type="inbox_saved_view",
                resource_id=resource_id,
                change_summary_json=changes or {},
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )


def _parse_item_key(value: str) -> tuple[str, UUID]:
    prefix, separator, raw_id = value.partition(":")
    if not separator or prefix not in {"task", "notification"}:
        raise InboxKeyError("inbox item key must use task:<uuid> or notification:<uuid>")
    try:
        return prefix, UUID(raw_id)
    except ValueError as exc:
        raise InboxKeyError("inbox item key contains an invalid UUID") from exc


def _read_state(state: InboxReadState) -> InboxReadStateRead:
    return InboxReadStateRead(
        item_key=f"{state.item_kind}:{state.item_id}",
        item_kind=state.item_kind,  # type: ignore[arg-type]
        item_id=state.item_id,
        read_at=state.read_at,
    )


def _queue_state(state: InboxQueueState) -> InboxQueueStateRead:
    return InboxQueueStateRead(
        item_key=f"{state.item_kind}:{state.item_id}",
        item_kind=state.item_kind,  # type: ignore[arg-type]
        item_id=state.item_id,
        state=state.state,  # type: ignore[arg-type]
        labels=list(state.labels or []),
        assignee_id=state.assignee_id,
        due_at=state.due_at,
        updated_by=state.updated_by,
        updated_at=state.updated_at,
    )


def _saved_view(view: InboxSavedView) -> InboxSavedViewRead:
    return InboxSavedViewRead(
        id=view.id,
        workspace_id=view.workspace_id,
        created_by=view.created_by,
        name=view.name,
        filters=dict(view.filters_json or {}),
        is_default=view.is_default,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _normalise_view_filters(filters: dict[str, object]) -> dict[str, object]:
    allowed = {"kind", "status", "queue_state", "label", "unread"}
    unknown = sorted(set(filters) - allowed)
    if unknown:
        raise InboxServiceError(
            f"保存视图包含不支持的筛选字段: {', '.join(unknown)}",
            code="inbox_view_filter_invalid",
        )
    return filters
