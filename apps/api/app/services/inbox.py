"""Durable read receipts for the unified operations inbox."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inbox import InboxReadState
from app.schemas.inbox import InboxReadStateRead


class InboxKeyError(ValueError):
    """Raised when a client sends an unknown or malformed inbox key."""


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
        from sqlalchemy import or_

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
            await self._upsert(workspace_id, user_id, kind, item_id)
            for kind, item_id in parsed
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
