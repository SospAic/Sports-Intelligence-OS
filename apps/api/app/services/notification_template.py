from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.notification_template import (
    NotificationTemplate,
    NotificationTemplateVersion,
)
from app.models.operations import AuditEntry

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

class NotificationTemplateError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class NotificationTemplateNotFound(NotificationTemplateError):
    def __init__(self, message: str = "Notification template not found") -> None:
        super().__init__(message, code="template_not_found", status_code=404)


class NotificationTemplateVersionNotFound(NotificationTemplateError):
    def __init__(self, message: str = "Template version not found") -> None:
        super().__init__(message, code="template_version_not_found", status_code=404)


class NotificationTemplateConflict(NotificationTemplateError):
    def __init__(self, message: str, code: str = "template_conflict") -> None:
        super().__init__(message, code=code, status_code=409)


class NotificationTemplateValidationError(NotificationTemplateError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="template_validation_error", status_code=422)


# --------------------------------------------------------------------------- #
# Pydantic schemas
# --------------------------------------------------------------------------- #

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TemplateCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    category: str = Field(default="general", min_length=1, max_length=64)
    subject_template: str = Field(min_length=1)
    body_template: str = Field(min_length=1)
    variables_schema: dict[str, Any] = Field(default_factory=dict)


class TemplateUpdate(StrictModel):
    subject_template: str | None = Field(default=None, min_length=1)
    body_template: str | None = Field(default=None, min_length=1)
    variables_schema: dict[str, Any] | None = None
    change_notes: str | None = Field(default=None, max_length=2000)


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    category: str
    created_at: datetime
    updated_at: datetime
    current_version: int | None = None
    published_version: int | None = None


class TemplateVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    status: str
    subject_template: str
    body_template: str
    variables_schema: dict[str, Any]
    created_at: datetime
    published_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #

class NotificationTemplateService:
    """Manages notification templates and their versioned content."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    async def _get_template_or_raise(
        self, workspace_id: UUID, template_id: UUID
    ) -> NotificationTemplate:
        stmt = (
            select(NotificationTemplate)
            .where(
                NotificationTemplate.id == template_id,
                NotificationTemplate.workspace_id == workspace_id,
            )
            .options(selectinload(NotificationTemplate.versions))
        )
        result = await self.session.execute(stmt)
        template = result.scalar_one_or_none()
        if template is None:
            raise NotificationTemplateNotFound()
        return template

    def _latest_version(
        self, template: NotificationTemplate
    ) -> NotificationTemplateVersion | None:
        if not template.versions:
            return None
        return max(template.versions, key=lambda v: v.version)

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        changes: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            AuditEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                before_hash=None,
                after_hash=(
                    hashlib.sha256(
                        json.dumps(changes, default=str, sort_keys=True).encode()
                    ).hexdigest()
                    if changes
                    else None
                ),
                change_summary_json=changes or {},
                reason=None,
                ip_hash=None,
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )

    # ------------------------------------------------------------------ #
    # 1. list_templates
    # ------------------------------------------------------------------ #

    async def list_templates(
        self,
        workspace_id: UUID,
        page: int = 1,
        page_size: int = 20,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Return a paginated list of templates with optional category filter."""
        base = select(NotificationTemplate).where(
            NotificationTemplate.workspace_id == workspace_id
        )
        if category:
            base = base.where(NotificationTemplate.category == category)

        # Total count
        count_stmt = select(sa_func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Paginated rows
        offset = (page - 1) * page_size
        stmt = (
            base.options(selectinload(NotificationTemplate.versions))
            .order_by(NotificationTemplate.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        templates = result.scalars().all()

        items: list[dict[str, Any]] = []
        for t in templates:
            latest = self._latest_version(t)
            published = next((v for v in t.versions if v.status == "published"), None)
            items.append(
                TemplateRead(
                    id=t.id,
                    name=t.name,
                    description=t.description,
                    category=t.category,
                    created_at=t.created_at,
                    updated_at=t.updated_at,
                    current_version=latest.version if latest else None,
                    published_version=published.version if published else None,
                ).model_dump(mode="json")
            )

        return {"items": items, "total": total, "page": page, "page_size": page_size}

    # ------------------------------------------------------------------ #
    # 2. get_template
    # ------------------------------------------------------------------ #

    async def get_template(
        self, workspace_id: UUID, template_id: UUID
    ) -> dict[str, Any]:
        """Return a single template with all its versions."""
        template = await self._get_template_or_raise(workspace_id, template_id)
        latest = self._latest_version(template)
        published = next((v for v in template.versions if v.status == "published"), None)

        versions = sorted(template.versions, key=lambda v: v.version, reverse=True)
        version_reads = [
            TemplateVersionRead(
                id=v.id,
                version=v.version,
                status=v.status,
                subject_template=v.subject_template,
                body_template=v.body_template,
                variables_schema=v.variables_schema,
                created_at=v.created_at,
                published_at=v.published_at,
            ).model_dump(mode="json")
            for v in versions
        ]

        return {
            **TemplateRead(
                id=template.id,
                name=template.name,
                description=template.description,
                category=template.category,
                created_at=template.created_at,
                updated_at=template.updated_at,
                current_version=latest.version if latest else None,
                published_version=published.version if published else None,
            ).model_dump(mode="json"),
            "versions": version_reads,
        }

    # ------------------------------------------------------------------ #
    # 3. create_template
    # ------------------------------------------------------------------ #

    async def create_template(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        name: str,
        description: str | None,
        category: str,
        subject_template: str,
        body_template: str,
        variables_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new template with its initial draft version (version=1)."""
        # Check uniqueness
        existing = await self.session.execute(
            select(NotificationTemplate).where(
                NotificationTemplate.workspace_id == workspace_id,
                NotificationTemplate.name == name,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise NotificationTemplateConflict(
                f"A template named '{name}' already exists in this workspace",
                code="template_name_conflict",
            )

        now = datetime.now(UTC)
        template_id = uuid4()
        version_id = uuid4()

        template = NotificationTemplate(
            id=template_id,
            workspace_id=workspace_id,
            name=name,
            description=description,
            category=category,
            created_by=actor_id,
        )
        self.session.add(template)

        version = NotificationTemplateVersion(
            id=version_id,
            template_id=template_id,
            workspace_id=workspace_id,
            version=1,
            status="draft",
            subject_template=subject_template,
            body_template=body_template,
            variables_schema=variables_schema,
            change_notes="Initial version",
            created_by=actor_id,
            created_at=now,
        )
        self.session.add(version)

        self._audit(
            workspace_id=workspace_id,
            actor_id=actor_id,
            action="template_created",
            resource_type="notification_template",
            resource_id=template_id,
            changes={"name": name, "category": category, "version": 1},
        )

        await self.session.flush()

        return {
            **TemplateRead(
                id=template.id,
                name=template.name,
                description=template.description,
                category=template.category,
                created_at=template.created_at,
                updated_at=template.updated_at,
                current_version=1,
            ).model_dump(mode="json"),
            "versions": [
                TemplateVersionRead(
                    id=version.id,
                    version=version.version,
                    status=version.status,
                    subject_template=version.subject_template,
                    body_template=version.body_template,
                    variables_schema=version.variables_schema,
                    created_at=version.created_at,
                    published_at=version.published_at,
                ).model_dump(mode="json")
            ],
        }

    # ------------------------------------------------------------------ #
    # 4. update_draft
    # ------------------------------------------------------------------ #

    async def update_draft(
        self,
        workspace_id: UUID,
        template_id: UUID,
        actor_id: UUID,
        subject_template: str | None = None,
        body_template: str | None = None,
        variables_schema: dict[str, Any] | None = None,
        change_notes: str | None = None,
    ) -> dict[str, Any]:
        """Update the latest draft version, or create a new draft if latest is published."""
        template = await self._get_template_or_raise(workspace_id, template_id)
        latest = self._latest_version(template)

        if latest is None:
            raise NotificationTemplateValidationError(
                "Template has no versions to update"
            )

        now = datetime.now(UTC)

        if latest.status == "draft":
            # Update in-place
            if subject_template is not None:
                latest.subject_template = subject_template
            if body_template is not None:
                latest.body_template = body_template
            if variables_schema is not None:
                latest.variables_schema = variables_schema
            if change_notes is not None:
                latest.change_notes = change_notes

            version_read = TemplateVersionRead(
                id=latest.id,
                version=latest.version,
                status=latest.status,
                subject_template=latest.subject_template,
                body_template=latest.body_template,
                variables_schema=latest.variables_schema,
                created_at=latest.created_at,
                published_at=latest.published_at,
            ).model_dump(mode="json")

            self._audit(
                workspace_id=workspace_id,
                actor_id=actor_id,
                action="template_draft_updated",
                resource_type="notification_template",
                resource_id=template_id,
                changes={
                    "version": latest.version,
                    "fields_updated": [
                        k for k, v in [
                            ("subject_template", subject_template),
                            ("body_template", body_template),
                            ("variables_schema", variables_schema),
                            ("change_notes", change_notes),
                        ]
                        if v is not None
                    ],
                },
            )

            await self.session.flush()
            return version_read

        else:
            # Latest is published — create a new draft with version+1
            new_version_num = latest.version + 1
            version_id = uuid4()

            new_version = NotificationTemplateVersion(
                id=version_id,
                template_id=template_id,
                workspace_id=workspace_id,
                version=new_version_num,
                status="draft",
                subject_template=(
                    subject_template if subject_template is not None
                    else latest.subject_template
                ),
                body_template=(
                    body_template if body_template is not None
                    else latest.body_template
                ),
                variables_schema=(
                    variables_schema if variables_schema is not None
                    else latest.variables_schema
                ),
                change_notes=change_notes,
                created_by=actor_id,
                created_at=now,
            )
            self.session.add(new_version)

            self._audit(
                workspace_id=workspace_id,
                actor_id=actor_id,
                action="template_draft_created",
                resource_type="notification_template",
                resource_id=template_id,
                changes={
                    "version": new_version_num,
                    "based_on_version": latest.version,
                },
            )

            await self.session.flush()

            return TemplateVersionRead(
                id=new_version.id,
                version=new_version.version,
                status=new_version.status,
                subject_template=new_version.subject_template,
                body_template=new_version.body_template,
                variables_schema=new_version.variables_schema,
                created_at=new_version.created_at,
                published_at=new_version.published_at,
            ).model_dump(mode="json")

    # ------------------------------------------------------------------ #
    # 5. publish_version
    # ------------------------------------------------------------------ #

    async def publish_version(
        self,
        workspace_id: UUID,
        template_id: UUID,
        actor_id: UUID,
    ) -> dict[str, Any]:
        """Publish the current draft version and archive previously published versions."""
        template = await self._get_template_or_raise(workspace_id, template_id)

        # Find the draft version
        draft = None
        for v in template.versions:
            if v.status == "draft":
                if draft is None or v.version > draft.version:
                    draft = v

        if draft is None:
            raise NotificationTemplateValidationError(
                "No draft version available to publish"
            )

        now = datetime.now(UTC)

        # Archive any previously published versions
        archived_ids: list[str] = []
        for v in template.versions:
            if v.status == "published" and v.id != draft.id:
                v.status = "archived"
                archived_ids.append(str(v.id))

        # Publish the draft
        draft.status = "published"
        draft.published_at = now

        self._audit(
            workspace_id=workspace_id,
            actor_id=actor_id,
            action="template_version_published",
            resource_type="notification_template",
            resource_id=template_id,
            changes={
                "published_version": draft.version,
                "archived_version_ids": archived_ids,
            },
        )

        await self.session.flush()

        return TemplateVersionRead(
            id=draft.id,
            version=draft.version,
            status=draft.status,
            subject_template=draft.subject_template,
            body_template=draft.body_template,
            variables_schema=draft.variables_schema,
            created_at=draft.created_at,
            published_at=draft.published_at,
        ).model_dump(mode="json")

    # ------------------------------------------------------------------ #
    # 6. rollback_version
    # ------------------------------------------------------------------ #

    async def rollback_version(
        self,
        workspace_id: UUID,
        template_id: UUID,
        version_id: UUID,
        actor_id: UUID,
    ) -> dict[str, Any]:
        """Create a new draft that copies the content of the specified version."""
        template = await self._get_template_or_raise(workspace_id, template_id)

        # Find the source version
        source = None
        for v in template.versions:
            if v.id == version_id:
                source = v
                break

        if source is None:
            raise NotificationTemplateVersionNotFound(
                f"Version {version_id} not found for template {template_id}"
            )

        # Determine the next version number
        latest = self._latest_version(template)
        new_version_num = (latest.version if latest else 0) + 1

        now = datetime.now(UTC)
        new_id = uuid4()

        new_version = NotificationTemplateVersion(
            id=new_id,
            template_id=template_id,
            workspace_id=workspace_id,
            version=new_version_num,
            status="draft",
            subject_template=source.subject_template,
            body_template=source.body_template,
            variables_schema=source.variables_schema,
            change_notes=f"Rollback from version {source.version}",
            created_by=actor_id,
            created_at=now,
        )
        self.session.add(new_version)

        self._audit(
            workspace_id=workspace_id,
            actor_id=actor_id,
            action="template_version_rollback",
            resource_type="notification_template",
            resource_id=template_id,
            changes={
                "source_version": source.version,
                "source_version_id": str(source.id),
                "new_version": new_version_num,
            },
        )

        await self.session.flush()

        return TemplateVersionRead(
            id=new_version.id,
            version=new_version.version,
            status=new_version.status,
            subject_template=new_version.subject_template,
            body_template=new_version.body_template,
            variables_schema=new_version.variables_schema,
            created_at=new_version.created_at,
            published_at=new_version.published_at,
        ).model_dump(mode="json")

    # ------------------------------------------------------------------ #
    # 7. delete_template
    # ------------------------------------------------------------------ #

    async def delete_template(
        self, workspace_id: UUID, template_id: UUID, actor_id: UUID
    ) -> None:
        """Delete a template and all its versions."""
        template = await self._get_template_or_raise(workspace_id, template_id)
        self._audit(
            workspace_id=workspace_id,
            actor_id=actor_id,
            action="template_deleted",
            resource_type="notification_template",
            resource_id=template_id,
            changes={"name": template.name},
        )
        await self.session.delete(template)
        await self.session.flush()

    # ------------------------------------------------------------------ #
    # 8. render_template
    # ------------------------------------------------------------------ #

    @staticmethod
    def render_template(
        template_version: NotificationTemplateVersion | TemplateVersionRead | dict[str, Any],
        variables: dict[str, Any],
    ) -> dict[str, str]:
        """Render a template version with the given variables.

        Accepts either an ORM instance, a Pydantic read model, or a plain dict.
        Returns ``{"subject": ..., "body": ...}`` with variables substituted via
        ``str.format_map``.  Missing keys are left as-is (``{key}``) so that
        callers can detect unresolved placeholders.
        """
        if isinstance(template_version, dict):
            subject_tpl = template_version["subject_template"]
            body_tpl = template_version["body_template"]
        elif isinstance(template_version, TemplateVersionRead):
            subject_tpl = template_version.subject_template
            body_tpl = template_version.body_template
        else:
            subject_tpl = template_version.subject_template
            body_tpl = template_version.body_template

        safe = _SafeFormat(variables)
        return {
            "subject": subject_tpl.format_map(safe),
            "body": body_tpl.format_map(safe),
        }

    # ------------------------------------------------------------------ #
    # 9. list_versions
    # ------------------------------------------------------------------ #

    async def list_versions(
        self,
        workspace_id: UUID,
        template_id: UUID,
    ) -> list[dict[str, Any]]:
        """List all versions for a template, newest first."""
        template = await self._get_template_or_raise(workspace_id, template_id)
        versions = sorted(template.versions, key=lambda v: v.version, reverse=True)

        return [
            TemplateVersionRead(
                id=v.id,
                version=v.version,
                status=v.status,
                subject_template=v.subject_template,
                body_template=v.body_template,
                variables_schema=v.variables_schema,
                created_at=v.created_at,
                published_at=v.published_at,
            ).model_dump(mode="json")
            for v in versions
        ]


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

class _SafeFormat(dict[str, Any]):
    """Dict subclass that returns ``{key}`` for missing keys instead of raising."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
