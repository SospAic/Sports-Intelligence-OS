from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.monitoring import Account, ContentItem, Platform
from app.models.settings import SyncSettings
from app.models.sync import SyncRun, SyncRunEvent
from app.schemas.settings import DEFAULT_SYNC_SETTINGS_CONFIG


class SyncRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_account(self, workspace_id: UUID, account_id: UUID) -> Account | None:
        statement = (
            select(Account)
            .options(joinedload(Account.platform))
            .where(Account.workspace_id == workspace_id, Account.id == account_id)
        )
        return cast(Account | None, await self.session.scalar(statement))

    async def get_account_unscoped(self, account_id: UUID) -> Account | None:
        return cast(
            Account | None,
            await self.session.scalar(
                select(Account)
                .options(joinedload(Account.platform))
                .where(Account.id == account_id)
            ),
        )

    async def get_run(self, run_id: UUID) -> SyncRun | None:
        return cast(SyncRun | None, await self.session.get(SyncRun, run_id))

    async def get_active_run(self, lock_key: str) -> SyncRun | None:
        return cast(
            SyncRun | None,
            await self.session.scalar(select(SyncRun).where(SyncRun.lock_key == lock_key)),
        )

    async def list_runs(
        self,
        workspace_id: UUID,
        target_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[SyncRun], int]:
        conditions = (
            SyncRun.workspace_id == workspace_id,
            SyncRun.target_id == target_id,
        )
        statement: Select[tuple[SyncRun]] = (
            select(SyncRun)
            .where(*conditions)
            .order_by(SyncRun.queued_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        runs = list((await self.session.scalars(statement)).all())
        total = int(
            (
                await self.session.scalar(
                    select(func.count()).select_from(SyncRun).where(*conditions)
                )
            )
            or 0
        )
        return runs, total

    async def due_accounts(self, due_at: datetime, limit: int = 500) -> list[Account]:
        statement = (
            select(Account)
            .options(joinedload(Account.platform))
            .join(Platform, Platform.id == Account.platform_id)
            .where(
                Account.is_active.is_(True),
                Account.sync_status != "disabled",
                Platform.enabled.is_(True),
                (Account.next_sync_at.is_(None) | (Account.next_sync_at <= due_at)),
            )
            .order_by(Account.next_sync_at.asc().nullsfirst(), Account.created_at.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).unique().all())

    async def contents_for_account(self, account_id: UUID) -> list[ContentItem]:
        return list(
            (
                await self.session.scalars(
                    select(ContentItem).where(ContentItem.account_id == account_id)
                )
            ).all()
        )

    async def add_sync_run_event(self, event: SyncRunEvent) -> None:
        """Persist a single append-only tracklog entry for a sync run."""

        self.session.add(event)

    async def list_sync_run_events(
        self, run_id: UUID, *, limit: int = 1000
    ) -> list[SyncRunEvent]:
        """Return a run's tracklog events ordered by sequence (creation order)."""

        statement = (
            select(SyncRunEvent)
            .where(SyncRunEvent.sync_run_id == run_id)
            .order_by(SyncRunEvent.sequence.asc(), SyncRunEvent.created_at.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    async def get_sync_settings_config(self, workspace_id: UUID) -> dict[str, Any]:
        """Return the workspace's merged fetch policy (defaults applied).

        Used by the sync executor so the global ``sync_settings`` policy — works
        cap, duplicate-skip behaviour and yt-dlp window params — is read once per
        run instead of being stashed on each account.
        """

        row = cast(
            SyncSettings | None,
            await self.session.scalar(
                select(SyncSettings).where(SyncSettings.workspace_id == workspace_id)
            ),
        )
        if row is None:
            return dict(DEFAULT_SYNC_SETTINGS_CONFIG)
        stored = dict(row.config or {})
        merged: dict[str, Any] = {**DEFAULT_SYNC_SETTINGS_CONFIG, **stored}
        merged["yt_dlp"] = {
            **DEFAULT_SYNC_SETTINGS_CONFIG["yt_dlp"],
            **(stored.get("yt_dlp") or {}),
        }
        merged["download"] = {
            **DEFAULT_SYNC_SETTINGS_CONFIG["download"],
            **(stored.get("download") or {}),
        }
        return merged
