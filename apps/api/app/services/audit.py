"""Convenience builders for the operation-trail audit entries.

Every audited operation should surface, when it fails, both a *code-level*
detail (exception class + message, ids) and a *business-layer* explanation +
remediation. This module centralises the ``AuditEntry`` construction so the
``error_hint`` is always derived from ``error_code`` (via
:func:`app.services.error_detail.business_hint_for`) whenever a failure is
recorded — there is a single place to keep that behaviour consistent.
"""

from __future__ import annotations

from uuid import UUID

from app.models.operations import AuditEntry, ExternalCallAttempt
from app.services.error_detail import business_hint_for


def build_audit_entry(
    *,
    id: UUID,
    workspace_id: UUID | None,
    actor_type: str,
    actor_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: UUID | None,
    before_hash: str | None = None,
    after_hash: str | None = None,
    change_summary_json: dict | None = None,
    reason: str | None = None,
    ip_hash: str | None = None,
    trace_id: UUID,
    created_at,
    status: str = "success",
    error_code: str | None = None,
    error_detail: str | None = None,
    error_hint: str | None = None,
) -> AuditEntry:
    """Construct an :class:`AuditEntry`, deriving ``error_hint`` on failures.

    When ``status == "failed"`` and no explicit ``error_hint`` is supplied, the
    business-layer explanation is computed from ``error_code`` so a failed
    operation in the audit trail is never left without guidance for the
    operator.
    """

    if error_hint is None and status == "failed" and error_code is not None:
        error_hint = business_hint_for(error_code)

    return AuditEntry(
        id=id,
        workspace_id=workspace_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before_hash=before_hash,
        after_hash=after_hash,
        change_summary_json=change_summary_json if change_summary_json is not None else {},
        reason=reason,
        ip_hash=ip_hash,
        trace_id=trace_id,
        created_at=created_at,
        status=status,
        error_code=error_code,
        error_detail=error_detail,
        error_hint=error_hint,
    )


def build_external_call_attempt(**kwargs) -> ExternalCallAttempt:
    """Construct an :class:`ExternalCallAttempt`, deriving ``error_hint``.

    When an ``error_code`` is present (i.e. the call failed), the
    business-layer explanation is computed via
    :func:`app.services.error_detail.business_hint_for` unless an explicit
    ``error_hint`` is supplied. All other keyword arguments are forwarded to
    the :class:`ExternalCallAttempt` constructor unchanged.
    """

    error_code = kwargs.get("error_code")
    if kwargs.get("error_hint") is None and error_code is not None:
        kwargs["error_hint"] = business_hint_for(error_code, category="external_call")
    return ExternalCallAttempt(**kwargs)
