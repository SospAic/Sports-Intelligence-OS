"""Workspace-scoped media rights review service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import MediaArtifact
from app.models.media_rights import MediaArtifactRights
from app.schemas.media_rights import (
    MediaRightsPage,
    MediaRightsRead,
    MediaRightsUpdate,
    RightsSourceKind,
    RightsStatus,
)
from app.services.audit import build_audit_entry


class MediaRightsError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class MediaRightsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        rights_status: str | None = None,
    ) -> MediaRightsPage:
        filters = [MediaArtifact.workspace_id == workspace_id]
        if rights_status:
            filters.append(MediaArtifactRights.rights_status == rights_status)
        statement = (
            select(MediaArtifact, MediaArtifactRights)
            .outerjoin(MediaArtifactRights, MediaArtifactRights.artifact_id == MediaArtifact.id)
            .where(*filters)
            .order_by(MediaArtifact.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list((await self.session.execute(statement)).all())
        total = int(
            await self.session.scalar(
                select(func.count(MediaArtifact.id))
                .select_from(MediaArtifact)
                .outerjoin(MediaArtifactRights, MediaArtifactRights.artifact_id == MediaArtifact.id)
                .where(*filters)
            )
            or 0
        )
        return MediaRightsPage(
            items=[_read(artifact, rights) for artifact, rights in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def update(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        actor_id: UUID,
        payload: MediaRightsUpdate,
    ) -> MediaRightsRead:
        artifact = await self.session.scalar(
            select(MediaArtifact).where(
                MediaArtifact.id == artifact_id,
                MediaArtifact.workspace_id == workspace_id,
            )
        )
        if artifact is None:
            raise MediaRightsError("素材不存在", code="media_artifact_not_found", status_code=404)
        rights = await self.session.scalar(
            select(MediaArtifactRights).where(
                MediaArtifactRights.workspace_id == workspace_id,
                MediaArtifactRights.artifact_id == artifact_id,
            )
        )
        before = _audit_snapshot(rights)
        if rights is None:
            rights = MediaArtifactRights(
                id=uuid4(),
                workspace_id=workspace_id,
                artifact_id=artifact_id,
                territories=[],
                metadata_json={},
            )
            self.session.add(rights)
        rights.rights_status = payload.rights_status
        rights.license_type = payload.license_type
        rights.rights_holder = payload.rights_holder
        rights.territories = list(
            dict.fromkeys(item.strip() for item in payload.territories if item.strip())
        )
        rights.valid_from = payload.valid_from
        rights.valid_until = payload.valid_until
        rights.evidence_url = str(payload.evidence_url) if payload.evidence_url else None
        rights.evidence_note = payload.evidence_note
        rights.source_kind = payload.source_kind
        rights.metadata_json = payload.metadata
        rights.verified_at = (
            datetime.now(UTC)
            if payload.rights_status in {"approved", "restricted"}
            else None
        )
        rights.verified_by = actor_id if rights.verified_at else None
        self.session.add(
            build_audit_entry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action="media_artifact.rights.updated",
                resource_type="media_artifact",
                resource_id=artifact_id,
                change_summary_json={
                    "before": before,
                    "after": _audit_snapshot(rights),
                    "source_kind": payload.source_kind,
                },
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )
        await self.session.commit()
        await self.session.refresh(rights)
        return _read(artifact, rights)


def _audit_snapshot(rights: MediaArtifactRights | None) -> dict[str, object] | None:
    if rights is None:
        return None
    return {
        "rights_status": rights.rights_status,
        "license_type": rights.license_type,
        "rights_holder": rights.rights_holder,
        "territories": list(rights.territories or []),
        "valid_from": rights.valid_from.isoformat() if rights.valid_from else None,
        "valid_until": rights.valid_until.isoformat() if rights.valid_until else None,
        "evidence_url": rights.evidence_url,
        "source_kind": rights.source_kind,
    }


def _read(artifact: MediaArtifact, rights: MediaArtifactRights | None) -> MediaRightsRead:
    return MediaRightsRead(
        id=rights.id if rights else None,
        workspace_id=artifact.workspace_id,
        artifact_id=artifact.id,
        artifact_kind=artifact.artifact_kind,
        file_name=artifact.file_name,
        artifact_status=artifact.status,
        rights_status=cast(RightsStatus, rights.rights_status if rights else "unknown"),
        license_type=rights.license_type if rights else None,
        rights_holder=rights.rights_holder if rights else None,
        territories=list(rights.territories or []) if rights else [],
        valid_from=rights.valid_from if rights else None,
        valid_until=rights.valid_until if rights else None,
        evidence_url=rights.evidence_url if rights else None,
        evidence_note=rights.evidence_note if rights else None,
        source_kind=cast(RightsSourceKind, rights.source_kind if rights else "imported"),
        verified_at=rights.verified_at if rights else None,
        verified_by=rights.verified_by if rights else None,
        metadata=rights.metadata_json if rights else {},
        created_at=rights.created_at if rights else artifact.created_at,
        updated_at=rights.updated_at if rights else artifact.updated_at,
    )
