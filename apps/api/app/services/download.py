"""Service layer for on-demand downloads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.download import Download
from app.schemas.download import DownloadCreate, DownloadPage, DownloadRead


class DownloadService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, workspace_id: UUID, payload: DownloadCreate
    ) -> DownloadRead:
        now = datetime.now(UTC)
        download = Download(
            workspace_id=workspace_id,
            url=payload.url.strip(),
            status="pending",
            options={
                "download_video": payload.download_video,
                "video_format": payload.video_format,
                "write_subtitles": payload.write_subtitles,
                "write_auto_subtitles": payload.write_auto_subtitles,
                "subtitle_langs": payload.subtitle_langs,
                "write_thumbnail": payload.write_thumbnail,
                "write_info_json": payload.write_info_json,
            },
            created_at=now,
            updated_at=now,
        )
        self._session.add(download)
        await self._session.commit()
        await self._session.refresh(download)
        return DownloadRead.model_validate(download)

    async def list(
        self, workspace_id: UUID, *, page: int = 1, page_size: int = 20
    ) -> DownloadPage:
        conditions = [Download.workspace_id == workspace_id]
        total = int(
            (
                await self._session.scalar(
                    select(func.count())
                    .select_from(Download)
                    .where(*conditions)
                )
            )
            or 0
        )
        rows = (
            await self._session.scalars(
                select(Download)
                .where(*conditions)
                .order_by(Download.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return DownloadPage(
            items=[DownloadRead.model_validate(r) for r in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get(self, download_id: UUID) -> Download | None:
        return await self._session.get(Download, download_id)

    async def mark_running(self, download_id: UUID) -> None:
        download = await self._session.get(Download, download_id)
        if download is None:
            return
        download.status = "running"
        download.updated_at = datetime.now(UTC)
        await self._session.commit()

    async def mark_done(
        self,
        download_id: UUID,
        media: dict[str, Any] | None,
        platform: str | None,
    ) -> None:
        download = await self._session.get(Download, download_id)
        if download is None:
            return
        download.status = "done" if media else "empty"
        download.media = media
        download.platform = platform
        download.error = None
        download.updated_at = datetime.now(UTC)
        await self._session.commit()

    async def mark_failed(self, download_id: UUID, error: str) -> None:
        download = await self._session.get(Download, download_id)
        if download is None:
            return
        download.status = "failed"
        download.error = error[:2000]
        download.updated_at = datetime.now(UTC)
        await self._session.commit()
