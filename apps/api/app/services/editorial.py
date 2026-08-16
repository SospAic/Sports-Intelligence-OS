"""Editorial review queue orchestration and transition rules."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.editorial import EditorialItem
from app.models.editorial_comment import EditorialComment
from app.models.editorial_view import EditorialSavedView
from app.models.generation import GenerationRun
from app.models.workspace import WorkspaceMembership
from app.schemas.editorial import (
    EditorialBulkResult,
    EditorialBulkUpdate,
    EditorialCommentCreate,
    EditorialCommentRead,
    EditorialCommentUpdate,
    EditorialItemCreate,
    EditorialItemPage,
    EditorialItemRead,
    EditorialItemUpdate,
    EditorialSavedViewCreate,
    EditorialSavedViewRead,
    EditorialSavedViewUpdate,
)
from app.services.audit import build_audit_entry


class EditorialError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class EditorialNotFound(EditorialError):
    def __init__(self, message: str = "审核条目不存在") -> None:
        super().__init__(message, code="editorial_item_not_found", status_code=404)


class EditorialCommentNotFound(EditorialError):
    def __init__(self, message: str = "协作评论不存在") -> None:
        super().__init__(message, code="editorial_comment_not_found", status_code=404)


class EditorialConflict(EditorialError):
    def __init__(self, message: str, code: str = "editorial_item_conflict") -> None:
        super().__init__(message, code=code, status_code=409)


_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"draft", "in_review", "archived"},
    "in_review": {"in_review", "approved", "rejected", "draft", "archived"},
    "approved": {"approved", "archived"},
    "rejected": {"rejected", "draft", "in_review", "archived"},
    "archived": {"archived"},
}


def can_transition(current: str, target: str) -> bool:
    """Return whether a review state transition is intentionally supported."""

    return target in _TRANSITIONS.get(current, set())


class EditorialService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_items(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        status: str | None,
        assignee_id: UUID | None,
        overdue: bool,
        unassigned: bool = False,
        priority_min: int | None = None,
        priority_max: int | None = None,
    ) -> EditorialItemPage:
        if priority_min is not None and priority_max is not None and priority_min > priority_max:
            raise EditorialConflict("最低优先级不能高于最高优先级", "editorial_priority_range")
        conditions = [EditorialItem.workspace_id == workspace_id]
        if status is not None:
            conditions.append(EditorialItem.status == status)
        if assignee_id is not None:
            conditions.append(EditorialItem.assignee_id == assignee_id)
        if unassigned:
            conditions.append(EditorialItem.assignee_id.is_(None))
        if priority_min is not None:
            conditions.append(EditorialItem.priority >= priority_min)
        if priority_max is not None:
            conditions.append(EditorialItem.priority <= priority_max)
        if overdue:
            conditions.extend(
                (
                    EditorialItem.due_at.is_not(None),
                    EditorialItem.due_at < datetime.now(UTC),
                    EditorialItem.status.not_in(("approved", "archived")),
                )
            )
        items = list(
            (
                await self.session.scalars(
                    select(EditorialItem)
                    .where(*conditions)
                    .order_by(
                        EditorialItem.priority.desc(),
                        EditorialItem.due_at.asc().nulls_last(),
                        EditorialItem.updated_at.desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(EditorialItem).where(*conditions)
            )
            or 0
        )
        return EditorialItemPage(
            items=[EditorialItemRead.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_item(self, workspace_id: UUID, item_id: UUID) -> EditorialItemRead:
        return EditorialItemRead.model_validate(await self._item(workspace_id, item_id))

    async def list_comments(
        self, workspace_id: UUID, item_id: UUID
    ) -> list[EditorialCommentRead]:
        await self._item(workspace_id, item_id)
        comments = list(
            (
                await self.session.scalars(
                    select(EditorialComment)
                    .where(
                        EditorialComment.workspace_id == workspace_id,
                        EditorialComment.editorial_item_id == item_id,
                    )
                    .order_by(EditorialComment.created_at.asc(), EditorialComment.id.asc())
                )
            ).all()
        )
        return [EditorialCommentRead.model_validate(comment) for comment in comments]

    async def get_comment(
        self, workspace_id: UUID, comment_id: UUID
    ) -> EditorialCommentRead:
        return EditorialCommentRead.model_validate(await self._comment(workspace_id, comment_id))

    async def create_comment(
        self,
        workspace_id: UUID,
        item_id: UUID,
        actor_id: UUID,
        payload: EditorialCommentCreate,
    ) -> EditorialCommentRead:
        await self._item(workspace_id, item_id)
        comment = EditorialComment(
            id=uuid4(),
            workspace_id=workspace_id,
            editorial_item_id=item_id,
            author_id=actor_id,
            body=payload.body,
        )
        self.session.add(comment)
        self._audit(
            workspace_id,
            actor_id,
            "editorial_comment.created",
            comment.id,
            {"editorial_item_id": str(item_id), "body_length": len(payload.body)},
            resource_type="editorial_comment",
        )
        await self.session.commit()
        await self.session.refresh(comment)
        return EditorialCommentRead.model_validate(comment)

    async def update_comment(
        self,
        workspace_id: UUID,
        comment_id: UUID,
        actor_id: UUID,
        payload: EditorialCommentUpdate,
    ) -> EditorialCommentRead:
        comment = await self._comment(workspace_id, comment_id)
        if payload.resolved:
            comment.resolved_at = datetime.now(UTC)
            comment.resolved_by = actor_id
        else:
            comment.resolved_at = None
            comment.resolved_by = None
        self._audit(
            workspace_id,
            actor_id,
            "editorial_comment.resolution_changed",
            comment.id,
            {"resolved": payload.resolved, "editorial_item_id": str(comment.editorial_item_id)},
            resource_type="editorial_comment",
        )
        await self.session.commit()
        await self.session.refresh(comment)
        return EditorialCommentRead.model_validate(comment)

    async def create_item(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: EditorialItemCreate,
    ) -> EditorialItemRead:
        run = await self.session.scalar(
            select(GenerationRun).where(
                GenerationRun.workspace_id == workspace_id,
                GenerationRun.id == payload.generation_run_id,
            )
        )
        if run is None:
            raise EditorialNotFound("生成运行不存在或不属于当前工作区")
        if run.status != "completed" or not run.final_output:
            raise EditorialConflict(
                "只有已完成且存在最终输出的生成运行才能进入审核队列",
                "generation_output_not_ready",
            )
        duplicate = await self.session.scalar(
            select(EditorialItem).where(
                EditorialItem.workspace_id == workspace_id,
                EditorialItem.generation_run_id == run.id,
            )
        )
        if duplicate is not None:
            return EditorialItemRead.model_validate(duplicate)
        await self._validate_assignee(workspace_id, payload.assignee_id)
        final_output = dict(run.final_output)
        title = (payload.title or _output_title(final_output, run.input_payload))[:255]
        item = EditorialItem(
            id=uuid4(),
            workspace_id=workspace_id,
            generation_run_id=run.id,
            created_by=actor_id,
            assignee_id=payload.assignee_id,
            title=title,
            status="draft",
            priority=payload.priority,
            due_at=payload.due_at,
            content_snapshot=final_output,
            source_snapshot=_source_snapshot(run),
            requested_at=None,
            reviewed_at=None,
            reviewed_by=None,
            review_note=None,
        )
        self.session.add(item)
        self._audit(workspace_id, actor_id, "editorial_item.created", item.id)
        await self.session.commit()
        await self.session.refresh(item)
        return EditorialItemRead.model_validate(item)

    async def bulk_update(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: EditorialBulkUpdate,
    ) -> EditorialBulkResult:
        items = list(
            (
                await self.session.scalars(
                    select(EditorialItem).where(
                        EditorialItem.workspace_id == workspace_id,
                        EditorialItem.id.in_(payload.item_ids),
                    )
                )
            ).all()
        )
        if len(items) != len(set(payload.item_ids)):
            raise EditorialNotFound("批量更新中包含不存在或不属于当前工作区的条目")
        changes = payload.model_dump(exclude_unset=True, exclude={"item_ids"})
        target_status = changes.get("status")
        for item in items:
            if target_status is not None and not can_transition(item.status, target_status):
                raise EditorialConflict(
                    f"条目 {item.id} 不能从 {item.status} 批量变更为 {target_status}",
                    "editorial_invalid_transition",
                )
        if "assignee_id" in changes:
            await self._validate_assignee(workspace_id, changes["assignee_id"])
        now = datetime.now(UTC)
        for item in items:
            self._apply_changes(item, actor_id, changes, now)
            self._audit(
                workspace_id,
                actor_id,
                "editorial_item.bulk_updated",
                item.id,
                _serializable_changes(changes),
            )
        await self.session.commit()
        for item in items:
            await self.session.refresh(item)
        return EditorialBulkResult(
            updated_count=len(items),
            items=[EditorialItemRead.model_validate(item) for item in items],
        )

    async def list_views(self, workspace_id: UUID) -> list[EditorialSavedViewRead]:
        views = list(
            (
                await self.session.scalars(
                    select(EditorialSavedView)
                    .where(EditorialSavedView.workspace_id == workspace_id)
                    .order_by(EditorialSavedView.name.asc())
                )
            ).all()
        )
        return [EditorialSavedViewRead.model_validate(view) for view in views]

    async def get_view(self, workspace_id: UUID, view_id: UUID) -> EditorialSavedViewRead:
        return EditorialSavedViewRead.model_validate(await self._view(workspace_id, view_id))

    async def create_view(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: EditorialSavedViewCreate,
    ) -> EditorialSavedViewRead:
        await self._ensure_view_name_available(workspace_id, payload.name)
        await self._validate_assignee(workspace_id, payload.assignee_id)
        view = EditorialSavedView(
            workspace_id=workspace_id,
            created_by=actor_id,
            name=payload.name.strip(),
            status=payload.status,
            assignee_id=payload.assignee_id,
            overdue=payload.overdue,
            unassigned=payload.unassigned,
            priority_min=payload.priority_min,
            priority_max=payload.priority_max,
        )
        self.session.add(view)
        self._audit(workspace_id, actor_id, "editorial_view.created", view.id)
        await self.session.commit()
        await self.session.refresh(view)
        return EditorialSavedViewRead.model_validate(view)

    async def update_view(
        self,
        workspace_id: UUID,
        view_id: UUID,
        actor_id: UUID,
        payload: EditorialSavedViewUpdate,
    ) -> EditorialSavedViewRead:
        view = await self._view(workspace_id, view_id)
        changes = payload.model_dump(exclude_unset=True)
        if "name" in changes and changes["name"] != view.name:
            await self._ensure_view_name_available(workspace_id, changes["name"], view_id)
            changes["name"] = changes["name"].strip()
        if "assignee_id" in changes:
            await self._validate_assignee(workspace_id, changes["assignee_id"])
        candidate_min = changes.get("priority_min", view.priority_min)
        candidate_max = changes.get("priority_max", view.priority_max)
        if (
            candidate_min is not None
            and candidate_max is not None
            and candidate_min > candidate_max
        ):
            raise EditorialConflict("最低优先级不能高于最高优先级", "editorial_view_priority_range")
        for field, value in changes.items():
            setattr(view, field, value)
        self._audit(
            workspace_id,
            actor_id,
            "editorial_view.updated",
            view.id,
            _serializable_changes(changes),
        )
        await self.session.commit()
        await self.session.refresh(view)
        return EditorialSavedViewRead.model_validate(view)

    async def delete_view(
        self,
        workspace_id: UUID,
        view_id: UUID,
        actor_id: UUID,
        can_manage: bool = False,
    ) -> None:
        view = await self._view(workspace_id, view_id)
        if view.created_by != actor_id and not can_manage:
            raise EditorialConflict(
                "只有保存视图创建者或工作区管理员可以删除",
                "editorial_view_delete_forbidden",
            )
        self._audit(workspace_id, actor_id, "editorial_view.deleted", view.id)
        await self.session.delete(view)
        await self.session.commit()

    async def update_item(
        self,
        workspace_id: UUID,
        item_id: UUID,
        actor_id: UUID,
        payload: EditorialItemUpdate,
    ) -> EditorialItemRead:
        item = await self._item(workspace_id, item_id)
        changes = payload.model_dump(exclude_unset=True)
        target_status = changes.get("status")
        if target_status is not None and not can_transition(item.status, target_status):
            raise EditorialConflict(
                f"审核状态不能从 {item.status} 变更为 {target_status}",
                "editorial_invalid_transition",
            )
        if "assignee_id" in changes:
            await self._validate_assignee(workspace_id, changes["assignee_id"])
        self._apply_changes(item, actor_id, changes, datetime.now(UTC))
        self._audit(
            workspace_id,
            actor_id,
            "editorial_item.updated",
            item.id,
            _serializable_changes(changes),
        )
        await self.session.commit()
        await self.session.refresh(item)
        return EditorialItemRead.model_validate(item)

    async def _item(self, workspace_id: UUID, item_id: UUID) -> EditorialItem:
        item = await self.session.scalar(
            select(EditorialItem).where(
                EditorialItem.workspace_id == workspace_id,
                EditorialItem.id == item_id,
            )
        )
        if item is None:
            raise EditorialNotFound()
        return item

    async def _comment(self, workspace_id: UUID, comment_id: UUID) -> EditorialComment:
        comment = await self.session.scalar(
            select(EditorialComment).where(
                EditorialComment.workspace_id == workspace_id,
                EditorialComment.id == comment_id,
            )
        )
        if comment is None:
            raise EditorialCommentNotFound()
        return comment

    async def _view(self, workspace_id: UUID, view_id: UUID) -> EditorialSavedView:
        view = await self.session.scalar(
            select(EditorialSavedView).where(
                EditorialSavedView.workspace_id == workspace_id,
                EditorialSavedView.id == view_id,
            )
        )
        if view is None:
            raise EditorialNotFound("保存视图不存在")
        return view

    async def _ensure_view_name_available(
        self, workspace_id: UUID, name: str, excluding_id: UUID | None = None
    ) -> None:
        conditions = [
            EditorialSavedView.workspace_id == workspace_id,
            EditorialSavedView.name == name.strip(),
        ]
        if excluding_id is not None:
            conditions.append(EditorialSavedView.id != excluding_id)
        if await self.session.scalar(select(EditorialSavedView.id).where(*conditions)) is not None:
            raise EditorialConflict("当前工作区已存在同名保存视图", "editorial_view_name_exists")

    @staticmethod
    def _apply_changes(
        item: EditorialItem,
        actor_id: UUID,
        changes: dict[str, Any],
        now: datetime,
    ) -> None:
        target_status = changes.get("status")
        if target_status == "in_review" and item.requested_at is None:
            item.requested_at = now
        if target_status in {"approved", "rejected"}:
            item.reviewed_at = now
            item.reviewed_by = actor_id
        if target_status == "draft":
            item.reviewed_at = None
            item.reviewed_by = None
        for field, value in changes.items():
            setattr(item, field, value)

    async def _validate_assignee(self, workspace_id: UUID, assignee_id: UUID | None) -> None:
        if assignee_id is None:
            return
        membership = await self.session.scalar(
            select(WorkspaceMembership.id).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == assignee_id,
                WorkspaceMembership.status == "active",
            )
        )
        if membership is None:
            raise EditorialConflict("负责人不属于当前工作区或已停用", "editorial_assignee_invalid")

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_id: UUID,
        changes: dict[str, Any] | None = None,
        resource_type: str = "editorial_item",
    ) -> None:
        self.session.add(
            build_audit_entry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                change_summary_json=changes or {},
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )


def _output_title(final_output: dict[str, Any], input_payload: dict[str, Any]) -> str:
    for key in ("video_title_zh", "video_title_en", "title", "headline"):
        value = final_output.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(input_payload.get("title") or input_payload.get("headline") or "未命名内容")


def _source_snapshot(run: GenerationRun) -> dict[str, Any]:
    payload = run.input_payload
    return {
        "input_type": run.input_type,
        "input_id": str(run.input_id) if run.input_id else None,
        "source_kind": run.run_metadata.get("source_kind", "imported"),
        "provider_is_mock": bool(run.run_metadata.get("provider_is_mock", False)),
        "title": payload.get("title") or payload.get("headline"),
        "source_url": payload.get("source_url"),
    }


def _serializable_changes(changes: dict[str, Any]) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, (UUID, datetime)) else value
        for key, value in changes.items()
    }
