"""Workspace member administration and one-time invitation acceptance."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.monitoring import Account
from app.models.operations import AuditEntry
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.models.workspace_account_grant import WorkspaceAccountGrant
from app.models.workspace_invitation import WorkspaceInvitation
from app.schemas.auth import (
    WorkspaceAccountGrantCreate,
    WorkspaceAccountGrantRead,
    WorkspaceInvitationAccept,
    WorkspaceInvitationCreate,
    WorkspaceInvitationCreateResponse,
    WorkspaceInvitationRead,
    WorkspaceMemberRead,
    WorkspaceMemberUpdate,
)


class WorkspaceAccessError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class WorkspaceAccessService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_invitations(self, workspace_id: UUID) -> list[WorkspaceInvitationRead]:
        rows = list(
            (
                await self.session.scalars(
                    select(WorkspaceInvitation)
                    .where(WorkspaceInvitation.workspace_id == workspace_id)
                    .order_by(WorkspaceInvitation.created_at.desc())
                )
            ).all()
        )
        await self._expire_pending(rows)
        return [self._read(item) for item in rows]

    async def create_invitation(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: WorkspaceInvitationCreate,
    ) -> WorkspaceInvitationCreateResponse:
        email = str(payload.email)
        normalized = email.casefold()
        existing_member = await self.session.scalar(
            select(WorkspaceMembership)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                User.email_normalized == normalized,
                WorkspaceMembership.status == "active",
            )
        )
        if existing_member is not None:
            raise WorkspaceAccessError(
                "该用户已经是工作区成员",
                code="workspace_member_exists",
                status_code=409,
            )
        pending = await self.session.scalar(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.email_normalized == normalized,
                WorkspaceInvitation.status == "pending",
            )
        )
        if pending is not None and pending.expires_at > datetime.now(UTC):
            raise WorkspaceAccessError(
                "该邮箱已有待处理邀请", code="invitation_exists", status_code=409
            )
        if pending is not None:
            pending.status = "expired"

        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        invitation = WorkspaceInvitation(
            id=uuid4(),
            workspace_id=workspace_id,
            email_normalized=normalized,
            email_display=email,
            role=payload.role,
            status="pending",
            token_hash=_hash_token(token),
            invited_by=actor_id,
            accepted_by=None,
            expires_at=now + timedelta(hours=payload.expires_in_hours),
            accepted_at=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(invitation)
        self._audit(
            workspace_id,
            actor_id,
            "workspace_invitation.created",
            invitation.id,
            {
                "email": normalized,
                "role": payload.role,
                "expires_at": invitation.expires_at.isoformat(),
            },
        )
        await self.session.commit()
        await self.session.refresh(invitation)
        return WorkspaceInvitationCreateResponse(**self._read(invitation).model_dump(), token=token)

    async def revoke_invitation(
        self, workspace_id: UUID, invitation_id: UUID, actor_id: UUID
    ) -> None:
        invitation = await self._invitation(workspace_id, invitation_id)
        if invitation.status != "pending":
            raise WorkspaceAccessError(
                "只有待处理邀请可以撤销", code="invitation_not_pending", status_code=409
            )
        invitation.status = "revoked"
        invitation.updated_at = datetime.now(UTC)
        self._audit(workspace_id, actor_id, "workspace_invitation.revoked", invitation.id)
        await self.session.commit()

    async def accept_invitation(
        self, actor_id: UUID, payload: WorkspaceInvitationAccept
    ) -> WorkspaceMemberRead:
        invitation = await self.session.scalar(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.token_hash == _hash_token(payload.token)
            )
        )
        if invitation is None:
            raise WorkspaceAccessError(
                "邀请令牌无效", code="invalid_invitation_token", status_code=404
            )
        now = datetime.now(UTC)
        if invitation.status != "pending":
            raise WorkspaceAccessError(
                "邀请已处理，不能重复接受", code="invitation_not_pending", status_code=409
            )
        if invitation.expires_at <= now:
            invitation.status = "expired"
            await self.session.commit()
            raise WorkspaceAccessError("邀请已过期", code="invitation_expired", status_code=410)
        user = await self.session.get(User, actor_id)
        if user is None or user.email_normalized != invitation.email_normalized:
            raise WorkspaceAccessError(
                "当前登录邮箱与邀请邮箱不匹配",
                code="invitation_email_mismatch",
                status_code=403,
            )

        membership = await self.session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == invitation.workspace_id,
                WorkspaceMembership.user_id == actor_id,
            )
        )
        if membership is None:
            membership = WorkspaceMembership(
                id=uuid4(),
                workspace_id=invitation.workspace_id,
                user_id=actor_id,
                role=invitation.role,
                status="active",
                invited_by=invitation.invited_by,
                joined_at=now,
            )
            self.session.add(membership)
        else:
            membership.role = invitation.role
            membership.status = "active"
            membership.invited_by = invitation.invited_by
            membership.joined_at = now
        invitation.status = "accepted"
        invitation.accepted_by = actor_id
        invitation.accepted_at = now
        invitation.updated_at = now
        self._audit(
            invitation.workspace_id,
            actor_id,
            "workspace_invitation.accepted",
            invitation.id,
            {"role": invitation.role},
        )
        await self.session.commit()
        return await self._member_read(invitation.workspace_id, actor_id)

    async def update_member(
        self,
        workspace_id: UUID,
        member_id: UUID,
        actor_id: UUID,
        payload: WorkspaceMemberUpdate,
    ) -> WorkspaceMemberRead:
        membership = await self.session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == member_id,
            )
        )
        if membership is None:
            raise WorkspaceAccessError(
                "工作区成员不存在", code="workspace_member_not_found", status_code=404
            )
        if membership.role == "owner" and payload.role is not None:
            raise WorkspaceAccessError(
                "工作区所有者不能通过成员接口改角色",
                code="owner_role_immutable",
                status_code=409,
            )
        if member_id == actor_id and payload.status == "disabled":
            raise WorkspaceAccessError(
                "不能停用当前登录成员", code="cannot_disable_self", status_code=409
            )
        if payload.role is not None:
            membership.role = payload.role
        if payload.status is not None:
            membership.status = payload.status
        self._audit(
            workspace_id,
            actor_id,
            "workspace_membership.updated",
            membership.id,
            {"member_id": str(member_id), "role": payload.role, "status": payload.status},
        )
        await self.session.commit()
        return await self._member_read(workspace_id, member_id)

    async def list_account_grants(
        self, workspace_id: UUID, account_id: UUID | None = None
    ) -> list[WorkspaceAccountGrantRead]:
        statement = select(WorkspaceAccountGrant).where(
            WorkspaceAccountGrant.workspace_id == workspace_id
        )
        if account_id is not None:
            statement = statement.where(WorkspaceAccountGrant.account_id == account_id)
        rows = list(
            (
                await self.session.scalars(
                    statement.order_by(WorkspaceAccountGrant.created_at)
                )
            ).all()
        )
        return [self._grant_read(item) for item in rows]

    async def create_account_grant(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        payload: WorkspaceAccountGrantCreate,
    ) -> WorkspaceAccountGrantRead:
        account = await self.session.scalar(
            select(Account).where(
                Account.id == payload.account_id,
                Account.workspace_id == workspace_id,
            )
        )
        if account is None:
            raise WorkspaceAccessError(
                "账号不存在或不属于当前工作区",
                code="account_not_found",
                status_code=404,
            )
        membership = await self.session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == payload.user_id,
                WorkspaceMembership.status == "active",
            )
        )
        if membership is None:
            raise WorkspaceAccessError(
                "目标用户不是当前工作区的活跃成员",
                code="workspace_member_not_found",
                status_code=404,
            )
        if membership.role in {"owner", "admin"}:
            raise WorkspaceAccessError(
                "所有者和管理员不需要账号级授权",
                code="account_grant_not_required",
                status_code=409,
            )
        existing = await self.session.scalar(
            select(WorkspaceAccountGrant).where(
                WorkspaceAccountGrant.workspace_id == workspace_id,
                WorkspaceAccountGrant.account_id == payload.account_id,
                WorkspaceAccountGrant.user_id == payload.user_id,
            )
        )
        if existing is not None:
            existing.permission = payload.permission
            existing.updated_at = datetime.now(UTC)
            self._audit(
                workspace_id,
                actor_id,
                "workspace_account_grant.updated",
                existing.id,
                {
                    "account_id": str(payload.account_id),
                    "user_id": str(payload.user_id),
                    "permission": payload.permission,
                },
            )
            await self.session.commit()
            return self._grant_read(existing)
        now = datetime.now(UTC)
        grant = WorkspaceAccountGrant(
            id=uuid4(),
            workspace_id=workspace_id,
            account_id=payload.account_id,
            user_id=payload.user_id,
            permission=payload.permission,
            created_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(grant)
        self._audit(
            workspace_id,
            actor_id,
            "workspace_account_grant.created",
            grant.id,
            {
                "account_id": str(payload.account_id),
                "user_id": str(payload.user_id),
                "permission": payload.permission,
            },
        )
        await self.session.commit()
        return self._grant_read(grant)

    async def revoke_account_grant(
        self, workspace_id: UUID, grant_id: UUID, actor_id: UUID
    ) -> None:
        grant = await self.session.scalar(
            select(WorkspaceAccountGrant).where(
                WorkspaceAccountGrant.workspace_id == workspace_id,
                WorkspaceAccountGrant.id == grant_id,
            )
        )
        if grant is None:
            raise WorkspaceAccessError(
                "账号级授权不存在", code="account_grant_not_found", status_code=404
            )
        await self.session.delete(grant)
        self._audit(workspace_id, actor_id, "workspace_account_grant.revoked", grant.id)
        await self.session.commit()

    async def _member_read(self, workspace_id: UUID, user_id: UUID) -> WorkspaceMemberRead:
        row = await self.session.execute(
            select(WorkspaceMembership, User)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        )
        item = row.one_or_none()
        if item is None:
            raise WorkspaceAccessError(
                "工作区成员不存在", code="workspace_member_not_found", status_code=404
            )
        membership, user = item
        return WorkspaceMemberRead(
            id=user.id,
            display_name=user.display_name or user.email_display,
            email=user.email_display,
            role=membership.role,
        )

    async def _invitation(self, workspace_id: UUID, invitation_id: UUID) -> WorkspaceInvitation:
        invitation = await self.session.scalar(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.id == invitation_id,
            )
        )
        if invitation is None:
            raise WorkspaceAccessError("邀请不存在", code="invitation_not_found", status_code=404)
        return invitation

    async def _expire_pending(self, invitations: list[WorkspaceInvitation]) -> None:
        now = datetime.now(UTC)
        changed = False
        for invitation in invitations:
            if invitation.status == "pending" and invitation.expires_at <= now:
                invitation.status = "expired"
                changed = True
        if changed:
            await self.session.commit()

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_id: UUID,
        changes: dict[str, object] | None = None,
    ) -> None:
        self.session.add(
            AuditEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type="workspace_access",
                resource_id=resource_id,
                before_hash=None,
                after_hash=None,
                change_summary_json=changes or {},
                reason=None,
                ip_hash=None,
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )

    @staticmethod
    def _read(invitation: WorkspaceInvitation) -> WorkspaceInvitationRead:
        return WorkspaceInvitationRead(
            id=invitation.id,
            workspace_id=invitation.workspace_id,
            email=invitation.email_display,
            role=cast(Literal["admin", "editor", "analyst", "viewer"], invitation.role),
            status=cast(
                Literal["pending", "accepted", "revoked", "expired"], invitation.status
            ),
            invited_by=invitation.invited_by,
            accepted_by=invitation.accepted_by,
            expires_at=invitation.expires_at,
            accepted_at=invitation.accepted_at,
            created_at=invitation.created_at,
            updated_at=invitation.updated_at,
        )

    @staticmethod
    def _grant_read(grant: WorkspaceAccountGrant) -> WorkspaceAccountGrantRead:
        return WorkspaceAccountGrantRead(
            id=grant.id,
            workspace_id=grant.workspace_id,
            account_id=grant.account_id,
            user_id=grant.user_id,
            permission=cast(Literal["viewer", "editor"], grant.permission),
            created_by=grant.created_by,
            created_at=grant.created_at,
            updated_at=grant.updated_at,
        )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def account_scope(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    role: str,
) -> set[UUID] | None:
    """Return explicit account scope, or ``None`` for unrestricted access.

    Owners/admins bypass account grants. For backwards compatibility, a
    non-admin with no grants keeps the existing workspace-wide role access;
    adding the first grant for a user opts that user into explicit scoping.
    """

    if role in {"owner", "admin"}:
        return None
    ids = list(
        (
            await session.scalars(
                select(WorkspaceAccountGrant.account_id).where(
                    WorkspaceAccountGrant.workspace_id == workspace_id,
                    WorkspaceAccountGrant.user_id == user_id,
                )
            )
        ).all()
    )
    return set(ids) if ids else None


async def require_account_access(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    role: str,
    account_id: UUID,
    *,
    require_editor: bool = False,
) -> None:
    if role in {"owner", "admin"}:
        return
    grants = list(
        (
            await session.scalars(
                select(WorkspaceAccountGrant).where(
                    WorkspaceAccountGrant.workspace_id == workspace_id,
                    WorkspaceAccountGrant.user_id == user_id,
                )
            )
        ).all()
    )
    if not grants:
        return
    grant = next((item for item in grants if item.account_id == account_id), None)
    if grant is None:
        raise WorkspaceAccessError(
            "当前成员没有该账号的访问权限",
            code="account_access_denied",
            status_code=403,
        )
    if require_editor and grant.permission != "editor":
        raise WorkspaceAccessError(
            "当前成员只有该账号的只读权限",
            code="account_write_denied",
            status_code=403,
        )
