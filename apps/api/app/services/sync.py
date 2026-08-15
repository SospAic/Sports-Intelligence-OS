import asyncio
import dataclasses
import logging
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any, TypeVar
from uuid import UUID, uuid4

import anyio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.platforms.avatar_helpers import should_update_avatar
from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterConfigurationError,
    AdapterContractError,
    PlatformAdapter,
    PlatformAdapterError,
    PlatformContentData,
    PlatformMetricsData,
    TransientAdapterError,
    parse_compact_count,
)
from app.adapters.platforms.profile_helpers import (
    is_invalid_display_name,
    should_update_display_name,
)
from app.adapters.platforms.yt_dlp import YtDlpAdapter
from app.api.routes.media import cache_avatar_for_account
from app.core.config import Settings
from app.models.monitoring import (
    Account,
    AccountSnapshot,
    Comment,
    ContentItem,
    ContentSnapshot,
    DerivedMetric,
)
from app.models.operations import SystemEvent
from app.models.sync import SyncRun, SyncRunEvent
from app.providers.registry import ProviderRegistry
from app.repositories.sync import SyncRepository
from app.schemas.monitoring import (
    SyncRunDetailRead,
    SyncRunEventRead,
    SyncRunPage,
    SyncRunRead,
)
from app.services.adaptive_sync import compute_adaptive_interval
from app.services.audit import build_external_call_attempt
from app.services.error_detail import business_hint_for, code_level_detail
from app.services.metric_calculations import (
    percentile_rank,
    ratio_score,
    safe_rate,
    sample_confidence,
    weighted_available_score,
)
from app.services.platform_credentials import (
    MANAGED_PLATFORM_KEYS,
    PlatformCredentialService,
)

logger = logging.getLogger(__name__)

SnapshotT = TypeVar("SnapshotT", AccountSnapshot, ContentSnapshot)

# Mirrors the ``ck_sync_run_events_sync_run_event_type`` CHECK constraint.
# The tracklog is *diagnostic* data: it must never be able to abort a sync.
# A value outside this set raises a CheckViolationError on flush, which poisons
# the whole session (PendingRollbackError) and leaves the run stuck in
# ``running`` with its account lock held — the exact stall this guard prevents.
# Unknown values are therefore normalized instead of persisted verbatim.
_SYNC_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "stage",
        "page",
        "item",
        "analytics",
        "external_call",
        "warning",
        "error",
        "info",
        "summary",
    }
)

# Levels the tracklog UI understands; same "diagnostics must not break the run"
# rule applies.
_SYNC_EVENT_LEVELS: frozenset[str] = frozenset({"debug", "info", "warn", "error"})


def _normalize_event_type(event_type: str, level: str) -> str:
    """Coerce ``event_type`` into the DB-allowed set.

    Falls back to the level-appropriate generic bucket so an unrecognized value
    still lands in the tracklog (never silently dropped) without violating the
    CHECK constraint.
    """

    if event_type in _SYNC_EVENT_TYPES:
        return event_type
    if level == "error":
        return "error"
    if level == "warn":
        return "warning"
    return "info"


class SyncError(Exception):
    code = "sync_error"
    status_code = 400


class SyncNotFoundError(SyncError):
    code = "sync_resource_not_found"
    status_code = 404


class SyncValidationError(SyncError):
    code = "sync_validation_error"
    status_code = 422


class SyncDispatchError(SyncError):
    code = "sync_queue_unavailable"
    status_code = 503


class RetryableSyncError(Exception):
    pass


# Smallest wall-clock budget worth starting an attempt with. A retry that is
# dispatched after the run's deadline (queue backlog, a crashed attempt, a
# stale sweep re-queue) would otherwise compute a *negative* budget, make every
# asyncio.wait_for fire instantly, re-raise a retryable error and loop —
# burning worker slots while the account stays locked. The run deadline is
# absolute: below this floor we close the run instead of pretending to work.
_MIN_ATTEMPT_BUDGET_SECONDS = 5.0

# Persist several item updates together. A commit for every work would make a
# detailed progress panel itself slow down the sync; batching keeps the UI
# granular while limiting database round-trips.
_SYNC_ITEM_PROGRESS_COMMIT_INTERVAL = 5
_SYNC_RECENT_ITEM_LIMIT = 8


def _as_int(value: int | float | None) -> int | None:
    return int(value) if value is not None else None


def _as_decimal(value: int | float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def merge_media_manifest(
    existing: Mapping[str, Any] | None,
    discovered: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge partial media observations without erasing archived artifacts.

    A catalogue pass may have no download artifacts, and a subtitle probe may
    return an empty list after a transient platform response. Treating those
    observations as a shallow replacement makes existing video, covers,
    info-json, or subtitle tracks disappear. Sync is additive by default;
    explicit deletion belongs to media-management APIs.
    """

    if not existing and not discovered:
        return None
    if not discovered:
        return dict(existing) if existing else None

    merged = dict(existing or {})
    list_keys = {"subtitles", "subtitle_exports"}
    for key, value in dict(discovered).items():
        if key == "base" and merged.get("base"):
            # Keep the directory containing older files. The on-demand download
            # path copies files before choosing a target base.
            continue
        if key in list_keys and isinstance(value, list):
            previous = merged.get(key)
            previous_items = list(previous) if isinstance(previous, list) else []
            by_file: dict[str, int] = {
                str(item["file"]): index
                for index, item in enumerate(previous_items)
                if isinstance(item, Mapping) and item.get("file")
            }
            for item in value:
                if not isinstance(item, Mapping) or not item.get("file"):
                    continue
                file_key = str(item["file"])
                index = by_file.get(file_key)
                if index is None:
                    by_file[file_key] = len(previous_items)
                    previous_items.append(dict(item))
                else:
                    previous_items[index] = {**dict(previous_items[index]), **dict(item)}
            if previous_items:
                merged[key] = previous_items
            continue
        # False is meaningful for preferences such as timestamp display; only
        # None/blank/empty containers represent no observation.
        if value is None or value == "" or value == [] or value == {}:
            continue
        merged[key] = value
    return merged or None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _run_last_active(run: "SyncRun") -> datetime:
    """Most recent signal that a sync run was still progressing.

    Falls back to ``started_at``/``queued_at`` when no heartbeat is recorded, so
    a run that never reported progress is still recoverable.
    """

    hb = (run.metadata_json or {}).get("heartbeat_at")
    if isinstance(hb, str):
        try:
            return _utc(datetime.fromisoformat(hb))
        except ValueError:
            pass
    return _utc(run.started_at or run.queued_at)


class SyncService:
    def __init__(
        self,
        session: AsyncSession,
        registry: ProviderRegistry[PlatformAdapter],
        settings: Settings,
    ) -> None:
        self.session = session
        self.repository = SyncRepository(session)
        self.registry = registry
        self.settings = settings

    @staticmethod
    def settings_now() -> datetime:
        return datetime.now(UTC)

    async def request_account_sync(
        self,
        workspace_id: UUID,
        account_id: UUID,
        request_id: str,
    ) -> tuple[SyncRunRead, bool]:
        account = await self.repository.get_account(workspace_id, account_id)
        if account is None:
            raise SyncNotFoundError("account was not found")
        if not account.is_active or account.sync_status == "disabled":
            raise SyncValidationError("disabled accounts cannot be synchronized")
        mode, _ = await PlatformCredentialService(self.session, self.settings).resolve(
            workspace_id, account.platform.key
        )
        if mode == "unconfigured" and account.platform.key in MANAGED_PLATFORM_KEYS:
            raise SyncValidationError(
                "platform acquisition is not configured: add official API credentials "
                "or approve every public-page collection condition"
            )
        base_adapter_key = account.platform.adapter_key
        if mode == "api" and not self.settings.browser_first_mode:
            # Standard API-first: use the non-browser adapter.
            resolved_key = base_adapter_key.replace("_browser", "")
        elif mode == "api" and self.settings.browser_first_mode:
            # Browser-first mode: prefer browser adapter even when API creds exist,
            # unless the platform has no browser adapter registered.
            browser_key = (
                base_adapter_key
                if base_adapter_key.endswith("_browser")
                else f"{base_adapter_key}_browser"
            )
            try:
                self.registry.get(browser_key)
                resolved_key = browser_key
            except LookupError:
                resolved_key = base_adapter_key.replace("_browser", "")
        else:
            resolved_key = (
                base_adapter_key
                if base_adapter_key.endswith("_browser")
                else f"{base_adapter_key}_browser"
            )
        try:
            adapter = self.registry.get(resolved_key)
        except LookupError:
            # Fallback to whatever the platform declares
            try:
                adapter = self.registry.get(base_adapter_key)
            except LookupError as exc:
                raise SyncValidationError("platform adapter is not registered") from exc
        if adapter.descriptor.implementation_status != "implemented":
            raise SyncValidationError("platform adapter is a skeleton and cannot synchronize")

        lock_key = f"account:{account.id}"
        active = await self.repository.get_active_run(lock_key)
        if active is not None:
            return SyncRunRead.model_validate(active), False

        now = datetime.now(UTC)
        run = SyncRun(
            id=uuid4(),
            workspace_id=workspace_id,
            target_type="account",
            target_id=account.id,
            adapter_key=adapter.key,
            request_id=request_id,
            queued_at=now,
            started_at=None,
            finished_at=None,
            status="queued",
            records_created=0,
            records_updated=0,
            progress_percent=0,
            progress_stage="queued",
            progress_message="等待后台任务开始",
            items_processed=0,
            items_total=None,
            error_code=None,
            error_message=None,
            error_detail=None,
            error_hint=None,
            metadata_json={"trigger": "manual", "retry_count": 0},
            lock_key=lock_key,
        )
        account.sync_status = "queued"
        account.last_sync_error_code = None
        account.last_sync_error_message = None
        self.session.add(run)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            active = await self.repository.get_active_run(lock_key)
            if active is None:
                raise
            return SyncRunRead.model_validate(active), False
        return SyncRunRead.model_validate(run), True

    async def mark_dispatch_failure(self, run_id: UUID) -> None:
        run = await self.repository.get_run(run_id)
        if run is None:
            return
        account = await self.repository.get_account_unscoped(run.target_id)
        now = datetime.now(UTC)
        run.status = "error"
        run.finished_at = now
        run.error_code = "queue_dispatch_failed"
        run.error_message = "Background task broker is unavailable"
        run.error_detail = code_level_detail(None, run=run, adapter_key=run.adapter_key)
        run.error_hint = business_hint_for("queue_dispatch_failed", adapter_key=run.adapter_key)
        run.progress_stage = "failed"
        run.progress_message = run.error_hint
        run.lock_key = None
        if account is not None:
            account.sync_status = "error"
            account.last_sync_error_code = run.error_code
            account.last_sync_error_message = run.error_message
        await self.session.commit()

    async def list_account_runs(
        self,
        workspace_id: UUID,
        account_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> SyncRunPage:
        account = await self.repository.get_account(workspace_id, account_id)
        if account is None:
            raise SyncNotFoundError("account was not found")
        runs, total = await self.repository.list_runs(
            workspace_id, account_id, page=page, page_size=page_size
        )
        return SyncRunPage(
            items=[SyncRunRead.model_validate(item) for item in runs],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def get_run_detail(
        self, workspace_id: UUID, account_id: UUID, run_id: UUID
    ) -> SyncRunDetailRead:
        """Return a single sync run with its full, ordered execution tracklog."""

        account = await self.repository.get_account(workspace_id, account_id)
        if account is None:
            raise SyncNotFoundError("account was not found")
        run = await self.repository.get_run(run_id)
        if run is None or run.workspace_id != workspace_id:
            raise SyncNotFoundError("sync run was not found")
        if run.target_id != account.id:
            raise SyncValidationError("sync run does not belong to this account")
        events = await self.repository.list_sync_run_events(run_id)
        return SyncRunDetailRead(
            run=SyncRunRead.model_validate(run),
            events=[SyncRunEventRead.model_validate(event) for event in events],
        )

    async def cancel_sync_run(
        self, workspace_id: UUID, account_id: UUID, run_id: UUID
    ) -> SyncRunRead:
        """Cancel a queued/running sync run for an account.

        Validates that the run belongs to the account and workspace, then delegates
        to the shared :func:`cancel_sync_run` helper which marks the run cancelled,
        releases the account lock, and best-effort revokes the Celery task.
        """
        account = await self.repository.get_account(workspace_id, account_id)
        if account is None:
            raise SyncNotFoundError("account was not found")
        run = await self.repository.get_run(run_id)
        if run is None or run.workspace_id != workspace_id:
            raise SyncNotFoundError("sync run was not found")
        if run.target_id != account.id:
            raise SyncValidationError("sync run does not belong to this account")
        return await cancel_sync_run(self.session, workspace_id, run_id)

    async def recover_stale_runs(
        self, stale_before: datetime, dispatch_stale_before: datetime | None = None
    ) -> int:
        """Release sync runs that are stuck and will never make progress.

        Two distinct failure modes are handled:

        * **Never dispatched** — ``status == 'queued'`` and no worker ever picked
          the task up (no heartbeat). Released fast via ``dispatch_stale_before``
          so a transient broker/worker outage does not permanently lock an account.
        * **Exceeded lease** — ``status == 'running'`` but silent longer than
          ``stale_before`` (no heartbeat). A worker may have died mid-run.

        The recovery is keyed on staleness (no recent heartbeat), NOT on whether a
        ``lock_key`` is present. Orphaned runs whose worker died *before* the lock
        was recorded (``lock_key IS NULL``) would otherwise sit in ``running``
        forever, making the account look permanently busy in the UI without ever
        blocking a new sync. Those are recovered here too — the lock release is a
        no-op when the key is already null, but the run is closed and the account
        status is reset so the user can re-trigger the sync.
        """

        runs = list(
            (
                await self.session.scalars(
                    select(SyncRun).where(SyncRun.status.in_(("queued", "running"))).limit(500)
                )
            ).all()
        )
        recovered = 0
        now = datetime.now(UTC)
        for run in runs:
            last_active = _run_last_active(run)
            if run.status == "queued" and dispatch_stale_before is not None:
                if _utc(last_active) >= _utc(dispatch_stale_before):
                    continue
                await self._release_stuck_run(
                    run,
                    now,
                    "dispatch_timeout",
                    "Sync task was queued but never picked up by a worker",
                )
            else:
                if _utc(last_active) >= _utc(stale_before):
                    continue
                await self._release_stuck_run(
                    run,
                    now,
                    "stale_task_recovered",
                    "Task exceeded its execution lease and was released",
                )
            recovered += 1
        if recovered:
            await self.session.commit()
        return recovered

    async def _release_stuck_run(
        self, run: "SyncRun", now: datetime, error_code: str, error_message: str
    ) -> None:
        run.status = "error"
        run.finished_at = now
        run.error_code = error_code
        run.error_message = error_message
        run.error_detail = code_level_detail(None, run=run, adapter_key=run.adapter_key)
        run.error_hint = business_hint_for(error_code, adapter_key=run.adapter_key)
        run.lock_key = None
        run.progress_stage = "failed"
        run.progress_message = run.error_hint
        account = await self.repository.get_account_unscoped(run.target_id)
        if account is not None:
            # Only reset the account's sync status if this orphaned run is still
            # the most recent one. A newer run may have already completed
            # (success/error) for the same account — we must not clobber that
            # settled state with a stale recovery of an older dead run.
            anchor = _utc(run.started_at or run.queued_at)
            newer = await self.session.scalar(
                select(SyncRun)
                .where(
                    SyncRun.workspace_id == run.workspace_id,
                    SyncRun.target_id == run.target_id,
                    SyncRun.id != run.id,
                    SyncRun.status.in_(("success", "degraded", "error", "cancelled", "skipped")),
                )
                .order_by(
                    SyncRun.started_at.desc().nullslast(),
                    SyncRun.queued_at.desc(),
                )
                .limit(1)
            )
            newer_anchor = _utc(newer.started_at or newer.queued_at) if newer is not None else None
            if newer is None or (
                anchor is not None and newer_anchor is not None and newer_anchor < anchor
            ):
                account.sync_status = "error"
                account.last_sync_error_code = run.error_code
                account.last_sync_error_message = run.error_message
                # Do not make the just-recovered account immediately due again.
                # The beat scheduler runs the stale sweep and the due-account
                # sweep independently; setting this to ``now`` lets the latter
                # redeliver the same stuck platform task in the same minute,
                # creating an endless recover -> retry -> recover loop.  Use the
                # account cadence as a cooldown, with a small lower bound for
                # legacy/test rows that may contain an unrealistically short
                # interval.  Manual sync remains available because this only
                # moves the next automatic due time.
                recovery_cooldown = max(300, int(account.sync_interval_seconds or 0))
                account.next_sync_at = now + timedelta(seconds=recovery_cooldown)


class PlatformSyncExecutor:
    def __init__(
        self,
        session: AsyncSession,
        registry: ProviderRegistry[PlatformAdapter],
        settings: Settings,
    ) -> None:
        self.session = session
        self.repository = SyncRepository(session)
        self.registry = registry
        self.settings = settings
        # Set when a run hits its wall-clock budget mid-pagination so the success
        # path can label the result as truncated rather than a full sync.
        self._budget_exceeded = False
        # Set when the configured per-run page budget ends while the adapter
        # still returns a continuation cursor. The cursor is persisted on the
        # account so the next scheduled/manual run resumes the backfill instead
        # of silently restarting at page one or declaring the catalogue complete.
        self._content_truncated = False
        # Live scrolling log for the run currently being executed (set in
        # execute_account_run). ``None`` for code paths that have no run yet.
        # The annotation is never evaluated at runtime (it sits in a function
        # body), so naming a class defined further down this module is fine.
        self._log_sink: _SyncLogSink | None = None
        # Monotonic counter for append-only tracklog events emitted during this
        # run's execution (reset per executor instance / per run).
        self._event_seq = 0
        # The freshly-built AccountSnapshot for this run. It is NOT added to the
        # session inside ``_sync_account`` because the account-level lifetime
        # view count (when the platform omits it, e.g. TikTok/Douyin) must be
        # derived from synced content views, which are only known after
        # ``_sync_contents``. We insert it once, after content sync, so the
        # derived value rides along on the new (append-only) row — never via an
        # UPDATE of an existing snapshot.
        self._pending_account_snapshot: AccountSnapshot | None = None
        # Content ids whose embeddable text changed during this run. Collected
        # while ingesting and flushed to the incremental index task after each
        # page commit (see ``_flush_pending_indexing``), so the dispatch always
        # happens against an already-committed row.
        self._pending_index_ids: list[UUID] = []
        # A provider can return the same work more than once in one catalogue
        # window, and a retry can reuse the same observed_at timestamp. Keep
        # snapshot writes idempotent within this executor.
        self._pending_content_snapshots: dict[tuple[UUID, datetime], ContentSnapshot] = {}
        # Set only when a backfill reaches the real end of an unfiltered
        # catalogue. This is a truthful public upload count and must not be
        # confused with the number of rows currently stored under a capped or
        # date-filtered sync.
        self._catalogue_total: int | None = None

    @staticmethod
    def _is_incrementally_complete_content_row(
        metadata: Any,
        published_at: datetime | None,
        duration_seconds: Any,
        cover_url: str | None,
    ) -> bool:
        """Return whether a stored row may safely skip full detail extraction.

        ``skip_existing`` is a performance policy, not permission to preserve a
        catalogue-only row forever.  Flat yt-dlp entries intentionally carry a
        real title/cover/view count but omit fields such as publish time,
        duration and description.  Those rows must re-enter the detail queue on
        the next run.  An empty description is valid platform data, so it is
        not used as a completeness gate.
        """
        payload = dict(metadata) if isinstance(metadata, dict) else {}
        detail_level = str(payload.get("detail_level") or "full")
        return (
            not bool(payload.get("partial"))
            and detail_level == "full"
            and published_at is not None
            and duration_seconds is not None
            and bool(cover_url)
        )

    def _remaining_budget_seconds(self, run: SyncRun) -> float:
        """Return the remaining wall-clock budget for an external call.

        The page-boundary check alone cannot protect a worker while a browser
        fallback or a provider call is in flight.  Callers use this value as
        the timeout for the individual awaitable and mark the run truncated
        when the budget is exhausted.
        """

        anchor = run.started_at or run.queued_at
        return float(self.settings.sync_run_timeout_seconds) - max(
            0.0, (datetime.now(UTC) - _utc(anchor)).total_seconds()
        )

    def _emit(
        self,
        run: "SyncRun",
        event_type: str,
        level: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Append a single tracklog event for ``run`` (persisted on next flush).

        Each event carries ``elapsed_ms`` (time since the run started) and
        ``step_ms`` (time since the previous event) so the detail page can
        surface exactly which step was slow during a sync.
        """

        self._event_seq += 1
        now = datetime.now(UTC)
        last = getattr(self, "_last_track_at", None)
        step_ms = int((now - last).total_seconds() * 1000) if last is not None else None
        anchor = run.started_at or run.queued_at
        elapsed_ms = (
            int((now - _utc(anchor)).total_seconds() * 1000) if anchor is not None else None
        )
        enriched: dict[str, Any] = {
            **(payload or {}),
            "step_ms": step_ms,
            "elapsed_ms": elapsed_ms,
        }
        self._last_track_at = now
        safe_level = level if level in _SYNC_EVENT_LEVELS else "info"
        safe_type = _normalize_event_type(event_type, safe_level)
        if safe_type != event_type:
            # Keep the caller's intent visible for debugging without letting it
            # reach the constrained column.
            enriched["requested_event_type"] = event_type
            logger.warning(
                "sync tracklog received unsupported event_type %r; stored as %r",
                event_type,
                safe_type,
            )
        self.session.add(
            SyncRunEvent(
                id=uuid4(),
                workspace_id=run.workspace_id,
                sync_run_id=run.id,
                sequence=self._event_seq,
                event_type=safe_type,
                level=safe_level,
                message=message,
                payload=enriched,
            )
        )

    async def _aborted(self, run: "SyncRun") -> bool:
        """Return True if the run was cancelled by a user while executing.

        Re-reads the persisted status because a concurrent cancel transaction
        may have changed it after this worker loaded the row.
        """
        await self.session.refresh(run)
        return run.status == "cancelled"

    async def _config_for(self, account: Account) -> dict[str, Any]:
        mode, config = await PlatformCredentialService(self.session, self.settings).resolve(
            account.workspace_id, account.platform.key
        )
        if mode == "unconfigured" and account.platform.key in MANAGED_PLATFORM_KEYS:
            raise AdapterConfigurationError("platform acquisition policy is no longer configured")
        # Merge the workspace's global fetch policy (yt-dlp window / passthrough
        # args, plus the works cap) on top of the platform-resolved credential
        # config. The global ``sync_settings`` wins on conflict so operators tune
        # behaviour once, centrally, instead of per account.
        sync_cfg = await self.repository.get_sync_settings_config(account.workspace_id)
        # A manually captured browser session is stored as a platform
        # credential, while the yt-dlp adapter reads its CLI inputs from the
        # nested ``yt_dlp`` block. Keep the secret in memory only and bridge
        # the Netscape cookie text into that block for the current run.
        yt_cfg = {key: config[key] for key in ("cookies_netscape",) if config.get(key)}
        yt_cfg.update(dict(sync_cfg.get("yt_dlp") or {}))
        if sync_cfg.get("max_contents") is not None:
            yt_cfg["max_items"] = sync_cfg["max_contents"]
        merged = dict(config)
        merged["yt_dlp"] = {**(merged.get("yt_dlp") or {}), **yt_cfg}
        # Download policy + the workspace media root so the adapter can archive
        # artifacts (thumbnail / subtitles / video) during the sync.
        if sync_cfg.get("download"):
            merged["download"] = sync_cfg["download"]
        # Per-account override: deep-merge the account's ``download`` on top of
        # the workspace policy so a single account can opt into e.g. video
        # downloads without changing the workspace-wide settings.
        override = account.sync_settings_override
        if isinstance(override, dict) and isinstance(override.get("download"), dict):
            base_dl = dict(merged.get("download") or {})
            merged["download"] = self._deep_merge_download(base_dl, override["download"])
        # TikTok / Douyin serve covers through short-lived signed CDN URLs that
        # expire within hours, so the platform-provided ``cover_url`` 404s by
        # the time the user opens the page (the "作品" tab then shows no cover).
        # Force local thumbnail archiving for those platforms so the detail UI
        # serves a permanent copy via the /media route. Honour an explicit
        # operator setting; only default it on when unset.
        if account.platform.key in ("tiktok", "douyin"):
            dl = dict(merged.get("download") or {})
            dl.setdefault("write_thumbnail", True)
            merged["download"] = dl
        # Per-account fetch window (count / date range / start). These override
        # the workspace-wide ``yt_dlp`` window and works cap for this account
        # only, so an operator can e.g. sync a smaller slice of one account
        # without touching the global policy.
        fetch = override.get("fetch") if isinstance(override, dict) else None
        if isinstance(fetch, dict):
            if fetch.get("max_contents") is not None:
                yt_cfg["max_items"] = int(fetch["max_contents"])
            if fetch.get("dateafter") is not None:
                yt_cfg["dateafter"] = fetch["dateafter"]
            if fetch.get("datebefore") is not None:
                yt_cfg["datebefore"] = fetch["datebefore"]
            if fetch.get("playlist_start") is not None:
                yt_cfg["playlist_start"] = int(fetch["playlist_start"])
            merged["yt_dlp"] = {**(merged.get("yt_dlp") or {}), **yt_cfg}
        media_root = os.environ.get("SIO_MEDIA_ROOT", "/workspace/media")
        merged["media_root"] = os.path.join(media_root, str(account.workspace_id))
        return merged

    @staticmethod
    def _deep_merge_download(
        base: Mapping[str, Any], override: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Recursively merge ``override`` onto ``base``.

        ``override`` values win on conflict; nested dicts are merged rather than
        replaced so a partial override does not wipe sibling keys.
        """

        result: dict[str, Any] = dict(base)
        for key, value in override.items():
            if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
                result[key] = PlatformSyncExecutor._deep_merge_download(
                    result[key],
                    value,
                )
            else:
                result[key] = value
        return result

    async def execute_account_run(self, run_id: UUID) -> None:
        run = await self.repository.get_run(run_id)
        if run is None:
            raise SyncNotFoundError("sync run was not found")
        if run.status == "cancelled":
            logger.info("sync run %s was cancelled before execution; skipping", run_id)
            return
        if run.status in ("success", "degraded"):
            return
        account = await self.repository.get_account(run.workspace_id, run.target_id)
        if account is None:
            await self._terminal_error(run, None, "account_not_found", "account was deleted")
            return
        adapter = self.registry.get(run.adapter_key)
        now = datetime.now(UTC)
        run.status = "running"
        run.started_at = run.started_at or now
        run.error_code = None
        run.error_message = None
        account.sync_status = "syncing"
        # Attach the live log before the first stage transition so the very first
        # line ("正在验证采集方式与凭证") already lands in the scrolling panel.
        sink = _SyncLogSink(run)
        self._log_sink = sink
        sink.push(f"▸ 开始同步 {account.display_name or account.external_id}（{run.adapter_key}）")
        self._set_progress(run, 5, "validating", "正在验证采集方式与凭证")
        await self.session.commit()
        if await self._aborted(run):
            return
        # The run deadline is absolute and spans every attempt: ``started_at`` is
        # kept across retries on purpose. A retry that reaches the worker after
        # the deadline (queue backlog, retry backoff, a re-queued stale run) has
        # nothing left to spend — starting it would drive every wait_for with a
        # negative timeout, fail instantly, and be re-queued again. Close it
        # cleanly so the lock is released and the UI shows a real reason.
        attempt_budget = self._remaining_budget_seconds(run)
        if attempt_budget < _MIN_ATTEMPT_BUDGET_SECONDS:
            await self._terminal_error(
                run,
                account,
                "sync_budget_exhausted",
                (
                    f"同步时间预算已耗尽（上限 {self.settings.sync_run_timeout_seconds}s，"
                    f"本次尝试开始时剩余 {attempt_budget:.0f}s），已终止并释放账号锁"
                ),
            )
            return
        attempt_started = datetime.now(UTC)
        attempt_number = int(run.metadata_json.get("retry_count", 0)) + 1

        try:
            ctx = AdapterCallContext(
                config=await self._config_for(account),
                observed_at=now,
                request_id=run.request_id,
                progress_sink=sink,
            )
            await adapter.validate_config(ctx.config)
            self._set_progress(run, 12, "account_profile", "正在同步账号资料与公开指标")
            await self.session.commit()
            if await self._aborted(run):
                return
            created, updated, metrics_degraded, profile_degraded = await self._sync_account(
                account, adapter, ctx, run
            )
            self._set_progress(run, 25, "content_list", "账号资料已完成，正在获取作品列表")
            await self.session.commit()
            (
                content_created,
                content_updated,
                items_failed,
                content_analytics_failed,
            ) = await self._sync_contents(account, adapter, ctx, run)
            created += content_created
            updated += content_updated
            # Some public channel extractors expose no lifetime ``video_count``
            # (YouTube Shorts-only channels are a common example). Once the
            # content paginator itself has reached the unfiltered catalogue
            # end, use that independently observed count for the pending
            # account snapshot instead of leaving the platform-total card blank.
            if self._pending_account_snapshot is not None:
                catalogue_total = self._catalogue_total
                if catalogue_total is None:
                    raw_catalogue_total = (account.metadata_json or {}).get(
                        "content_sync_catalogue_total"
                    )
                    try:
                        catalogue_total = (
                            max(0, int(raw_catalogue_total))
                            if raw_catalogue_total is not None
                            else None
                        )
                    except (TypeError, ValueError):
                        catalogue_total = None
                if (
                    catalogue_total is not None
                    and self._pending_account_snapshot.video_count is None
                ):
                    self._pending_account_snapshot.video_count = catalogue_total
                    self._pending_account_snapshot.metadata_json = {
                        **(self._pending_account_snapshot.metadata_json or {}),
                        "video_count_derived_from_complete_catalogue": True,
                        "catalogue_total": catalogue_total,
                    }
            # Insert the account snapshot now that content views are known, so a
            # derived total_view_count (platforms that omit lifetime views) can
            # ride on this new append-only row.
            await self._finalize_account_snapshot(account)
            self._set_progress(run, 92, "derived_metrics", "正在计算增长与高潜指标")
            await self.session.commit()
            if await self._aborted(run):
                return
            # Derived-metric calculation is best-effort: if it raises we must not
            # discard the content already ingested. Degrade and finalise instead.
            metrics_calc_failed = False
            try:
                await self._calculate_metrics(account, ctx.observed_at)
            except Exception as exc:  # noqa: BLE001
                metrics_calc_failed = True
                logger.exception(
                    "platform_sync_metrics_calculation_failed",
                    extra={"event": "platform.sync.metrics_failed", "sync_run_id": str(run.id)},
                )
                self._emit(
                    run,
                    "error",
                    "error",
                    f"派生指标计算失败，已采集内容保留：{exc}",
                    {"error": str(exc)},
                )
        except PlatformAdapterError as exc:
            self._record_external_attempt(
                run,
                account,
                attempt_started,
                attempt_number,
                status="failed",
                error_code=exc.code,
                error_detail=str(exc),
                retryable=exc.retryable,
            )
            if exc.retryable:
                run.status = "queued"
                run.error_code = exc.code
                run.error_message = str(exc)[:2000]
                run.error_detail = code_level_detail(exc, run=run, adapter_key=run.adapter_key)
                run.error_hint = business_hint_for(exc.code, adapter_key=run.adapter_key)
                run.metadata_json = {
                    **run.metadata_json,
                    "retry_count": int(run.metadata_json.get("retry_count", 0)) + 1,
                }
                account.sync_status = "queued"
                account.last_sync_error_code = exc.code
                account.last_sync_error_message = str(exc)[:2000]
                run.progress_stage = "retry_wait"
                run.progress_message = "平台暂时不可用，等待有限重试"
                await self.session.commit()
                raise RetryableSyncError(str(exc)) from exc
            await self._terminal_error(run, account, exc.code, str(exc), exc=exc)
            return
        except Exception as exc:
            logger.exception(
                "platform_sync_unexpected_error",
                extra={"event": "platform.sync.failed", "sync_run_id": str(run.id)},
            )
            await self._terminal_error(
                run, account, "unexpected_sync_error", "Unexpected synchronization error", exc=exc
            )
            self._record_external_attempt(
                run,
                account,
                attempt_started,
                attempt_number,
                status="failed",
                error_code="unexpected_sync_error",
                error_detail="Unexpected synchronization error",
                retryable=False,
            )
            await self.session.commit()
            raise

        finished = datetime.now(UTC)
        final_status = (
            "degraded"
            if (
                metrics_degraded
                or content_analytics_failed
                or metrics_calc_failed
                or profile_degraded
                or self._content_truncated
            )
            else "success"
        )
        # The external call itself succeeded (the profile was fetched); only the
        # downstream metric extraction failed. Record the audit row as success and
        # keep the higher-level "degraded" status on the run/account instead of
        # falsifying either, or writing an invalid external_call status.
        attempt_status = "success" if final_status == "degraded" else final_status
        self._record_external_attempt(
            run,
            account,
            attempt_started,
            attempt_number,
            status=attempt_status,
            response_summary={
                "records_created": created,
                "records_updated": updated,
                "items_processed": run.items_processed,
                "items_failed": items_failed,
                "metrics_degraded": metrics_degraded,
                "content_analytics_failed": content_analytics_failed,
                "metrics_calc_failed": metrics_calc_failed,
                "content_truncated": self._content_truncated,
            },
        )
        run.status = final_status
        run.finished_at = finished
        run.records_created = created
        run.records_updated = updated
        run.error_code = None
        run.error_message = (
            "指标提取失败，仅更新了账号资料"
            if (metrics_degraded or content_analytics_failed or metrics_calc_failed)
            else None
        )
        if self._content_truncated:
            run.error_message = "作品列表仍有后续分页，已保存游标，将在下一次同步继续"
        # Always clear any stale error surface on a successful run. A prior
        # stale-recovery pass can stamp a "worker crashed / timeout" hint on a run
        # that was still progressing and later finished fine; leaving it would
        # make a succeeded sync display a misleading failure message.
        run.error_hint = None
        run.error_detail = None
        run.lock_key = None
        run.progress_percent = 100
        run.progress_stage = "completed"
        if self._budget_exceeded or self._content_truncated:
            run.progress_message = (
                f"同步已按时间预算截断，已入库 {run.items_processed} 条；"
                "可在账号设置中调大抓取上限或再次手动同步以获取更多历史。"
            )
            run.metadata_json = {
                **run.metadata_json,
                "truncated_by_budget": self._budget_exceeded,
                "content_truncated": self._content_truncated,
            }
        else:
            run.progress_message = (
                "同步完成（部分指标提取失败，已保留已采集内容）"
                if (metrics_degraded or content_analytics_failed or metrics_calc_failed)
                else "同步完成"
            )
        run.items_total = run.items_processed
        run.metadata_json = {
            **run.metadata_json,
            "items_failed": items_failed,
            "account_metrics_degraded": metrics_degraded,
            "content_analytics_failed": content_analytics_failed,
            "metrics_calc_failed": metrics_calc_failed,
            "content_truncated": self._content_truncated,
        }
        self._emit(
            run,
            "summary",
            "error" if final_status == "error" else "info",
            f"同步结束：状态 {final_status}，新增 {created}，更新 {updated}，"
            f"失败 {items_failed}"
            + ("，指标分析降级" if content_analytics_failed else "")
            + ("，派生指标降级" if metrics_calc_failed else ""),
            {
                "status": final_status,
                "records_created": created,
                "records_updated": updated,
                "items_processed": run.items_processed,
                "items_failed": items_failed,
                "content_analytics_failed": content_analytics_failed,
                "metrics_degraded": metrics_degraded,
                "metrics_calc_failed": metrics_calc_failed,
                "duration_ms": int(
                    (finished - (run.started_at or finished)).total_seconds() * 1000
                ),
            },
        )
        account.sync_status = final_status
        account.last_synced_at = finished
        # Adaptive cadence: tune the next poll to the account's recent posting
        # rhythm so active accounts are refreshed often and dormant ones rarely.
        interval, _ = await compute_adaptive_interval(self.session, account.id)
        account.sync_interval_seconds = interval
        account.next_sync_at = finished + timedelta(
            seconds=min(interval, 300) if self._content_truncated else interval
        )
        if self._content_truncated:
            account.last_sync_error_code = "content_list_truncated"
            account.last_sync_error_message = "作品列表已分批保存游标，将在下一次同步继续"
        elif metrics_degraded or content_analytics_failed or metrics_calc_failed:
            account.last_sync_error_code = "account_metrics_extraction_failed"
            account.last_sync_error_message = "指标提取失败，仅更新了账号资料"
        else:
            account.last_sync_error_code = None
            account.last_sync_error_message = None
        await self.session.commit()

    async def mark_retry_exhausted(self, run_id: UUID, message: str) -> None:
        run = await self.repository.get_run(run_id)
        if run is None:
            return
        account = await self.repository.get_account_unscoped(run.target_id)
        await self._terminal_error(run, account, "retry_exhausted", message)

    async def mark_unexpected_failure(self, run_id: UUID, message: str) -> None:
        """Close a run that crashed with an error the engine did not anticipate.

        Called from the Celery task's last-resort handler on a *fresh* session,
        because the crash may have poisoned the run's own session (e.g. a failed
        flush leaves it in ``PendingRollbackError``). Without this, an unexpected
        exception leaves the row in ``running`` holding the account's
        ``lock_key`` forever: the UI shows a permanently "syncing" account and
        every later sync request is rejected as already-in-flight. Recovering
        only via the periodic stale sweep would take minutes, so we release the
        lock immediately here.
        """

        run = await self.repository.get_run(run_id)
        if run is None:
            return
        if run.status not in ("queued", "running"):
            return
        account = await self.repository.get_account_unscoped(run.target_id)
        await self._terminal_error(run, account, "internal_error", message)

    async def calculate_account_metrics(self, account_id: UUID) -> None:
        account = await self.repository.get_account_unscoped(account_id)
        if account is None:
            raise SyncNotFoundError("account was not found")
        await self._calculate_metrics(account, datetime.now(UTC))
        await self.session.commit()

    async def _terminal_error(
        self,
        run: SyncRun,
        account: Account | None,
        code: str,
        message: str,
        *,
        exc: BaseException | None = None,
    ) -> None:
        finished_at = datetime.now(UTC)
        run.status = "error"
        run.finished_at = finished_at
        run.error_code = code
        run.error_message = message[:2000]
        run.error_detail = code_level_detail(exc, run=run, adapter_key=run.adapter_key)
        run.error_hint = business_hint_for(code, adapter_key=run.adapter_key)
        run.lock_key = None
        run.progress_stage = "failed"
        run.progress_message = (run.error_hint or message)[:500]
        # Capture the fatal failure in the run's tracklog so the detail page can
        # show exactly where/why the sync died alongside any earlier progress.
        if getattr(self, "_event_seq", None) is not None and run.id is not None:
            self._emit(
                run,
                "error",
                "error",
                f"同步失败：{message[:500]}",
                {"code": code, "error_detail": (run.error_detail or "")[:1000]},
            )
        if account is not None:
            account.sync_status = "error"
            account.last_sync_error_code = code
            account.last_sync_error_message = message[:2000]
            account.next_sync_at = datetime.now(UTC) + timedelta(
                seconds=account.sync_interval_seconds
            )
            self.session.add(
                SystemEvent(
                    id=uuid4(),
                    workspace_id=account.workspace_id,
                    severity="error",
                    category="platform_sync",
                    event_type="platform.account.sync_failed",
                    message=f"账号「{account.display_name}」同步失败",
                    resource_type="account",
                    resource_id=account.id,
                    status="open",
                    error_code=code,
                    error_detail=message[:2000],
                    error_hint=business_hint_for(code, adapter_key=run.adapter_key),
                    metadata_safe_json={
                        "adapter_key": run.adapter_key,
                        "error_code": code,
                    },
                    trace_id=uuid4(),
                    created_at=finished_at,
                )
            )
        await self.session.commit()

    def _record_external_attempt(
        self,
        run: SyncRun,
        account: Account,
        started_at: datetime,
        attempt_number: int,
        *,
        status: str,
        error_code: str | None = None,
        error_detail: str | None = None,
        retryable: bool | None = None,
        response_summary: dict[str, Any] | None = None,
    ) -> None:
        finished_at = datetime.now(UTC)
        self.session.add(
            build_external_call_attempt(
                id=uuid4(),
                workspace_id=run.workspace_id,
                call_type="platform_api",
                provider_key=run.adapter_key,
                entity_type="account",
                entity_id=account.id,
                attempt_number=attempt_number,
                status=status,
                target_url=account.profile_url,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
                http_status=None,
                error_code=error_code,
                error_detail_safe=error_detail[:500] if error_detail else None,
                retryable=retryable,
                request_summary={"run_id": str(run.id), "target_type": run.target_type},
                response_summary=response_summary,
            )
        )
        # Mirror the external call into the run tracklog so the detail page shows
        # the platform round-trip alongside the per-step events.
        if getattr(self, "_event_seq", None) is not None and run.id is not None:
            level = "error" if status == "failed" else "info"
            self._emit(
                run,
                "external_call",
                level,
                f"外部调用 {run.adapter_key}：{status}"
                + (f"（{error_code}）" if error_code else ""),
                {
                    "status": status,
                    "error_code": error_code,
                    "retryable": retryable,
                    "response_summary": response_summary,
                },
            )

    async def _sync_account(
        self,
        account: Account,
        adapter: PlatformAdapter,
        ctx: AdapterCallContext,
        run: SyncRun,
    ) -> tuple[int, int, bool, bool]:
        profile_degraded = False
        # Cap the account-profile fetch the same way content pages are capped:
        # below the adapter's own extract timeout, so a slow/unreachable channel
        # fails this stage via asyncio.wait_for (caught just below as a retryable
        # outage, bounded by the run budget) instead of hanging inside the
        # adapter's extract-retry loop for minutes. Directly serves "no stalls".
        profile_remaining = self._remaining_budget_seconds(run)
        if profile_remaining <= 0:
            raise TransientAdapterError("sync budget exhausted before account profile fetch")
        # Never give the adapter a timeout larger than the absolute run budget;
        # otherwise the final profile call could outlive the run deadline even
        # though the outer wait_for itself is bounded.
        profile_fetch_timeout = min(
            profile_remaining,
            float(self.settings.sync_page_fetch_timeout_seconds),
        )
        try:
            profile_ctx = dataclasses.replace(ctx, timeout_seconds=profile_fetch_timeout)
            data = await asyncio.wait_for(
                adapter.resolve_account(profile_ctx, account.external_id),
                timeout=profile_fetch_timeout,
            )
        except TimeoutError:
            raise TransientAdapterError(
                f"account profile fetch exceeded {profile_fetch_timeout:.0f}s budget"
            ) from None
        if not data.external_id.strip() or not data.display_name.strip():
            raise AdapterContractError("account response is missing its identity")
        # Display-name guard (cross-platform, see
        # profile_helpers.is_invalid_display_name). Rejects error-page titles,
        # URLs leaked into the name field, and bare platform suffixes left over
        # when a nickname failed to render — all three are scrape failures that
        # would otherwise be persisted as the account's permanent name.
        # Historically this raised a hard AdapterContractError and failed the
        # whole sync, but a bad nickname is a non-critical field: the second-layer
        # guard below (should_update_display_name) already refuses to overwrite a
        # stored name with an invalid one, so the account keeps its identity. We
        # therefore skip the name update and degrade the run instead of erroring —
        # a partially-scraped but usable account beats a hard failure for the
        # monitoring use case.
        if is_invalid_display_name(data.display_name):
            profile_degraded = True
            self._emit(
                run,
                "warning",
                "warn",
                f"抓取到的显示名无效（{data.display_name[:40]}），已跳过更新以免污染账号名",
                {"raw_display_name": data.display_name[:60]},
            )
            data = dataclasses.replace(data, display_name="")
        if data.profile_url and not data.profile_url.lower().startswith(("https://", "http://")):
            raise AdapterContractError("account response contains an invalid profile URL")
        self._set_progress(run, 18, "account_profile", "账号资料已获取，正在读取公开指标")
        await self.session.commit()
        original_locator = account.external_id
        account.external_id = data.external_id
        account.username = data.username
        # Second layer of the same rule: even if the contract check above is
        # ever relaxed, a manually-set name is never clobbered and an invalid
        # scrape can never replace a good stored name.
        if (account.metadata_json or {}).get(
            "display_name_source"
        ) != "manual" and should_update_display_name(account.display_name, data.display_name):
            account.display_name = data.display_name
        account.profile_url = data.profile_url
        # Avatar guard (cross-platform, see avatar_helpers.should_update_avatar):
        # never overwrite a previously-cached real avatar with a missing or
        # platform-default value. A failed re-sync (bot-walled browser scrape)
        # must not smear one shared default image across accounts the way it
        # can for the signature field below.
        if should_update_avatar(account.avatar_url, data.avatar_url):
            account.avatar_url = data.avatar_url
            # Persist the avatar locally at sync time so it survives CDN URL
            # expiry (TikTok / Douyin signatures are short-lived). The local
            # copy is later served by GET /accounts/{id}/avatar, which falls
            # back to the remote URL, then to initials, if caching failed.
            await anyio.to_thread.run_sync(cache_avatar_for_account, account.id, data.avatar_url)
        # Only overwrite the signature when the fresh extraction actually
        # produced one — a failed re-sync (e.g. bot-walled browser scrape)
        # must not wipe a previously captured description.
        if data.description:
            account.description = data.description
        account.country = data.country
        account.language = data.language
        account.is_verified = data.is_verified
        account.metadata_json = {
            **account.metadata_json,
            **dict(data.metadata),
            "original_locator": account.metadata_json.get("original_locator", original_locator),
        }
        account.source_kind = data.source_kind
        account.source_provider = data.provider
        account.fetched_at = data.fetched_at
        account.source_url = data.profile_url

        # Profile resolution and analytics extraction are separate capabilities.
        # A provider may legitimately expose the public profile while its
        # metrics endpoint is unavailable, rate-limited, or temporarily broken.
        # Persist the profile first and bound the metrics call so this optional
        # step can never abort the whole account sync or consume the run budget.
        metrics_error: str | None = None
        remaining_budget = self._remaining_budget_seconds(run)
        metrics: PlatformMetricsData | None = None
        if remaining_budget <= 0:
            metrics_error = "account metrics skipped because the sync time budget was exhausted"
        else:
            metrics_timeout = min(
                max(5.0, float(self.settings.platform_request_timeout_seconds) * 3),
                remaining_budget,
            )
            try:
                metrics_ctx = dataclasses.replace(ctx, timeout_seconds=metrics_timeout)
                metrics = await asyncio.wait_for(
                    adapter.fetch_account_analytics(metrics_ctx, data.external_id),
                    timeout=metrics_timeout,
                )
                if not isinstance(metrics, PlatformMetricsData):
                    raise AdapterContractError(
                        "account analytics response does not match the metrics contract"
                    )
            except TimeoutError:
                metrics_error = "account metrics extraction timed out"
            except PlatformAdapterError as exc:
                metrics_error = f"{exc.code}: {exc}"
            except Exception as exc:  # noqa: BLE001 - metrics are best-effort
                logger.warning(
                    "sync_account_metrics_failed",
                    extra={
                        "event": "platform.sync.account_metrics_failed",
                        "sync_run_id": str(run.id),
                        "adapter_key": adapter.key,
                    },
                )
                metrics_error = f"{type(exc).__name__}: {exc}"

        if metrics is None:
            previous = await self.session.scalar(
                select(AccountSnapshot)
                .where(AccountSnapshot.account_id == account.id)
                .order_by(AccountSnapshot.captured_at.desc())
                .limit(1)
            )
            metric_keys = (
                "follower_count",
                "following_count",
                "total_like_count",
                "total_view_count",
                "video_count",
                "engagement_rate",
            )
            preserved: dict[str, int | float | None] = {}
            if previous is not None:
                for key in metric_keys:
                    value = getattr(previous, key)
                    preserved[key] = float(value) if isinstance(value, Decimal) else value
            metrics = PlatformMetricsData(
                external_id=data.external_id,
                captured_at=ctx.observed_at,
                metrics=preserved,
                source_kind="live",
                provider=adapter.key,
                fetched_at=ctx.observed_at,
                unavailable_metrics=tuple(key for key in metric_keys if preserved.get(key) is None),
                metadata={
                    "analytics_fetched": False,
                    "analytics_error": (metrics_error or "unknown")[:500],
                    "preserved_previous_metrics": previous is not None,
                },
            )
            self._emit(
                run,
                "analytics",
                "warn",
                f"账号指标提取失败，已保留账号资料：{metrics_error or 'unknown'}",
                {
                    "scope": "account",
                    "error": (metrics_error or "unknown")[:500],
                    "preserved_previous_metrics": previous is not None,
                },
            )
        # Defer the insert: build the snapshot object but only persist it after
        # content sync so a derived total_view_count (when the platform omits
        # lifetime views) can be applied to this new append-only row.
        self._pending_account_snapshot = self._account_snapshot(account, metrics)
        await self.session.flush()
        m = metrics.metrics
        analytics_fetched = metrics.metadata.get("analytics_fetched")
        self._emit(
            run,
            "stage",
            "info",
            f"账号资料已获取：{account.display_name}",
            {
                "external_id": account.external_id,
                "follower_count": m.get("follower_count"),
                "video_count": m.get("video_count"),
                "total_view_count": m.get("total_view_count"),
                "analytics_fetched": bool(analytics_fetched)
                if analytics_fetched is not None
                else None,
            },
        )
        # Degradation means the account analytics *genuinely* could not be
        # obtained (e.g. yt-dlp returned nothing due to a transient error), not
        # that the source merely omits some fields. yt-dlp-style adapters report
        # an explicit ``analytics_fetched`` flag; adapters that don't set it fall
        # back to the legacy heuristic (all key metrics None). A successful fetch
        # whose source simply doesn't expose follower/video counts (TikTok/Douyin
        # via yt-dlp) is a platform limitation surfaced via ``unavailable_metrics``
        # and must not be reported as a failed sync.
        if analytics_fetched is not None:
            metrics_degraded = not bool(analytics_fetched)
        else:
            metrics_degraded = (
                m.get("follower_count") is None
                and m.get("video_count") is None
                and m.get("total_view_count") is None
            )
        return 1, 1, metrics_degraded, profile_degraded

    def _account_snapshot(self, account: Account, data: PlatformMetricsData) -> AccountSnapshot:
        metrics = data.metrics
        return AccountSnapshot(
            id=uuid4(),
            account_id=account.id,
            captured_at=data.captured_at,
            follower_count=_as_int(metrics.get("follower_count")),
            following_count=_as_int(metrics.get("following_count")),
            total_like_count=_as_int(metrics.get("total_like_count")),
            total_view_count=_as_int(metrics.get("total_view_count")),
            video_count=_as_int(metrics.get("video_count")),
            engagement_rate=_as_decimal(metrics.get("engagement_rate")),
            metadata_json={
                **dict(data.metadata),
                "unavailable_metrics": list(data.unavailable_metrics),
            },
            source_kind=data.source_kind,
            source_provider=data.provider,
            fetched_at=data.fetched_at,
            raw_payload_ref=None,
            created_at=datetime.now(UTC),
        )

    async def _finalize_account_snapshot(self, account: Account) -> None:
        """Persist the pending account snapshot for this run.

        TikTok/Douyin profiles do not expose a lifetime view count through
        yt-dlp, so ``total_view_count`` arrives ``None``. Rather than leave the
        总播放量 card and history chart empty, derive it from the sum of synced
        content views and stamp it on this *new* (append-only) snapshot row. We
        must never UPDATE an existing snapshot — the model rejects it.
        """
        snap = self._pending_account_snapshot
        if snap is None:
            return
        self._pending_account_snapshot = None
        if snap.total_view_count is None:
            contents = await self.repository.contents_for_account(account.id)
            content_view_sum = 0
            derived_count = 0
            for content in contents:
                latest = (
                    await self.session.scalars(
                        select(ContentSnapshot)
                        .where(ContentSnapshot.content_item_id == content.id)
                        .order_by(ContentSnapshot.captured_at.desc())
                        .limit(1)
                    )
                ).first()
                if latest is not None and latest.view_count is not None:
                    content_view_sum += latest.view_count
                    derived_count += 1
            if content_view_sum > 0:
                snap.total_view_count = content_view_sum
                snap.metadata_json = {
                    **(snap.metadata_json or {}),
                    "total_view_count_derived_from_content": True,
                    "derived_from_content_count": derived_count,
                }
        self.session.add(snap)

    @staticmethod
    def _content_metric_values(data: PlatformMetricsData | None) -> dict[str, int | float]:
        if data is None:
            return {}
        return {
            key: value
            for key, value in data.metrics.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }

    @classmethod
    def _content_metrics_state(
        cls,
        data: PlatformContentData,
        metrics_data: PlatformMetricsData | None,
        *,
        analytics_failed: bool,
    ) -> str:
        """Classify metrics without hiding public catalogue observations.

        Browser list endpoints often expose card-level engagement counts while
        their separate analytics endpoint exposes only private/unsupported
        fields. Those public values are real and are synthesized into a
        snapshot later in the page pipeline, so they must not be rendered as
        ``missing`` merely because the analytics response is empty.
        """

        catalogue_values = cls._metrics_from_metadata(data.metadata)
        metric_values = cls._content_metric_values(metrics_data) or catalogue_values
        if analytics_failed:
            return "partial" if metric_values else "failed"
        if metrics_data is None:
            return "available" if metric_values else "missing"
        if metric_values and not metrics_data.unavailable_metrics:
            return "available"
        return "partial" if metric_values else "missing"

    @classmethod
    def _content_progress_payload(
        cls,
        data: PlatformContentData,
        *,
        item_index: int,
        page_index: int,
        page_item_index: int,
        page_total: int,
        listed_total: int,
        processed_total: int,
        status: str,
        action: str | None = None,
        error: str | None = None,
        metrics_data: PlatformMetricsData | None = None,
        metrics_state: str = "pending",
        counts: Mapping[str, int] | None = None,
    ) -> dict[str, Any]:
        metadata = dict(data.metadata or {})
        detail_level = str(metadata.get("detail_level") or "full")
        media = dict(data.media or {})
        cover_status = (
            "archived"
            if media.get("thumbnail")
            else "available"
            if data.cover_url
            else "missing"
        )
        catalogue_metrics = {
            key.removeprefix("yt_"): value
            for key, value in metadata.items()
            if key.startswith("yt_")
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }
        metric_values = cls._content_metric_values(metrics_data) or catalogue_metrics
        unavailable = list(metrics_data.unavailable_metrics) if metrics_data else []
        if metrics_data is not None and metrics_state == "pending":
            metrics_state = (
                "available"
                if metric_values and not unavailable
                else "partial"
                if metric_values
                else "missing"
            )
        return {
            "kind": "content_progress",
            "item_index": item_index,
            "page_index": page_index,
            "page_item_index": page_item_index,
            "page_total": page_total,
            "listed_total": listed_total,
            "processed_total": processed_total,
            "counts": dict(counts or {}),
            "external_id": data.external_id,
            "title": (data.title or data.external_id)[:240],
            "status": status,
            "action": action,
            "error": error[:500] if error else None,
            "elements": {
                "title": "available" if data.title else "missing",
                "content": "partial" if detail_level != "full" else "available",
                "cover": cover_status,
                "metrics": metrics_state,
            },
            "detail_level": detail_level,
            "metric_values": metric_values,
            "unavailable_metrics": unavailable,
            "source_kind": data.source_kind,
            "provider": data.provider,
        }

    @staticmethod
    def _content_progress_message(payload: Mapping[str, Any]) -> str:
        elements = payload.get("elements")
        elements = elements if isinstance(elements, Mapping) else {}
        status_labels = {
            "available": "已获取",
            "archived": "已归档",
            "partial": "部分获取",
            "pending": "待获取",
            "missing": "缺失",
            "failed": "失败",
        }
        phase_labels = {
            "processing": "正在处理",
            "stored": "已入库",
            "metrics": "指标已处理",
            "failed": "失败",
            "rejected": "已跳过",
        }
        title = str(payload.get("title") or payload.get("external_id") or "未知作品")
        item_index = payload.get("item_index", "?")
        page_item_index = payload.get("page_item_index", "?")
        page_total = payload.get("page_total", "?")
        processed_total = payload.get("processed_total", "?")
        title_status = status_labels.get(
            str(elements.get("title")), str(elements.get("title") or "待获取")
        )
        cover_status = status_labels.get(
            str(elements.get("cover")), str(elements.get("cover") or "待获取")
        )
        metrics_status = status_labels.get(
            str(elements.get("metrics")), str(elements.get("metrics") or "待获取")
        )
        phase_status = phase_labels.get(
            str(payload.get("status")), str(payload.get("status") or "正在处理")
        )
        return (
            f"作品 {item_index}（本页 {page_item_index}/{page_total}，"
            f"累计已处理 {processed_total}）"
            f"《{title[:80]}》 · "
            f"标题{title_status} · "
            f"封面{cover_status} · "
            f"数据{metrics_status} · "
            f"{phase_status}"
        )

    def _set_content_progress(
        self,
        run: SyncRun,
        payload: dict[str, Any],
        *,
        message: str,
        add_to_recent: bool = False,
    ) -> None:
        """Update the structured live item state and the human log tail.

        The structured state is consumed by the frontend; the text line keeps
        older clients and the scrolling console useful. Both are updated in
        memory and persisted by the existing batched sync commits.
        """

        run.progress_stage = "content_metrics"
        run.progress_message = message[:500]
        metadata = dict(run.metadata_json or {})
        metadata["content_progress"] = payload
        if add_to_recent:
            recent = metadata.get("content_progress_recent")
            recent_items = list(recent) if isinstance(recent, list) else []
            recent_items.append(payload)
            metadata["content_progress_recent"] = recent_items[-_SYNC_RECENT_ITEM_LIMIT:]
        run.metadata_json = metadata
        sink = self._log_sink
        if sink is not None:
            sink.push(message)

    async def _collect_page_comments(
        self,
        account: Account,
        adapter: PlatformAdapter,
        ctx: AdapterCallContext,
        page_items: list[ContentItem],
        run: "SyncRun",
        page_index: int,
    ) -> list[UUID]:
        """Optionally queue Top 20 comment enrichment for this page.

        Comment extraction is intentionally outside the normal sync path. It
        is an operator opt-in and is dispatched as independent worker tasks so
        a slow comment wall cannot hold the account lock or delay content and
        metrics persistence.
        """
        config = ctx.config if isinstance(ctx.config, Mapping) else {}
        download = config.get("download")
        if not isinstance(download, Mapping) or not download.get("fetch_comments"):
            return []
        if not page_items:
            self._emit(
                run,
                "comments",
                "warn",
                "当前适配器不支持评论采集；作品与指标已保留",
                {"page_index": page_index, "status": "unsupported"},
            )
            return []

        now = datetime.now(UTC)
        eligible: list[ContentItem] = []
        for content in page_items:
            state = (content.metadata_json or {}).get("comment_sync")
            last_fetched = state.get("fetched_at") if isinstance(state, Mapping) else None
            stale = True
            if isinstance(last_fetched, str):
                try:
                    parsed = datetime.fromisoformat(last_fetched.replace("Z", "+00:00"))
                    stale = (now - parsed.astimezone(UTC)) >= timedelta(hours=24)
                except ValueError:
                    stale = True
            if ctx.sync_backfill or stale:
                eligible.append(content)
        if not eligible:
            self._emit(
                run,
                "comments",
                "info",
                f"第 {page_index + 1} 页评论均在 24 小时缓存内，跳过重复请求",
                {"page_index": page_index, "status": "fresh_cache"},
            )
            return []

        queued_ids: list[UUID] = []
        for index, content in enumerate(eligible, start=1):
            url = content.source_url or content.canonical_url
            if not url:
                content.metadata_json = {
                    **dict(content.metadata_json or {}),
                    "comment_sync": {
                        "status": "unavailable",
                        "count": 0,
                        "limit": 20,
                        "fetched_at": None,
                        "source_kind": "live",
                        "source_provider": adapter.key,
                        "source_url": None,
                        "notice": "作品没有可用的公开来源地址",
                    },
                }
                self._emit(
                    run,
                    "comments",
                    "warn",
                    f"评论采集 {index}/{len(eligible)}：{content.title[:60]} 无可用来源地址",
                    {
                        "page_index": page_index,
                        "content_id": str(content.id),
                        "status": "unavailable",
                    },
                )
                continue
            content.metadata_json = {
                **dict(content.metadata_json or {}),
                "comment_sync": {
                    "status": "queued",
                    "count": 0,
                    "limit": 20,
                    "queued_at": datetime.now(UTC).isoformat(),
                    "fetched_at": None,
                    "source_kind": "live",
                    "source_provider": adapter.key,
                    "source_url": url,
                    "notice": "评论采集已排队，不阻塞账号同步",
                },
            }
            queued_ids.append(content.id)
            self._emit(
                run,
                "comments",
                "info",
                f"评论采集排队 {index}/{len(eligible)}：{content.title[:60]}",
                {
                    "page_index": page_index,
                    "content_id": str(content.id),
                    "status": "queued",
                    "limit": 20,
                },
            )

        run.metadata_json = {
            **run.metadata_json,
            "comments": {
                "enabled": True,
                "limit": 20,
                "works_requested": len(eligible),
                "works_queued": len(queued_ids),
                "last_page": page_index,
                "mode": "async_worker_tasks",
            },
        }
        await self.session.flush()
        return queued_ids

        # The legacy inline implementation is intentionally kept below while
        # old deployments roll forward; the return above makes it unreachable.
        # It can be removed after the next schema/runtime rollout.
        concurrency = 2 if adapter.platform == "youtube" else 1
        semaphore = asyncio.Semaphore(concurrency)

        async def collect_one(
            content: ContentItem,
        ) -> tuple[ContentItem, list[dict[str, Any]], str | None]:
            url = content.source_url or content.canonical_url
            if not url:
                return content, [], "作品没有可用来源地址"
            async with semaphore:
                try:
                    comments = await asyncio.wait_for(
                        YtDlpAdapter.extract_comments(
                            url,
                            config=config,
                            limit=20,
                            timeout_seconds=60,
                        ),
                        timeout=65,
                    )
                    return content, comments, None
                except Exception as exc:  # noqa: BLE001 - per-item isolation
                    return content, [], str(exc)[:500]

        results = await asyncio.gather(*(collect_one(content) for content in eligible))
        content_ids = [content.id for content in eligible]
        existing_rows = list(
            (
                await self.session.scalars(
                    select(Comment).where(Comment.content_item_id.in_(content_ids))
                )
            ).all()
        )
        existing_by_content: dict[UUID, dict[str, Comment]] = {}
        for row in existing_rows:
            existing_by_content.setdefault(row.content_item_id, {})[row.platform_comment_id] = row

        successes = 0
        failures = 0
        total_stored = 0
        for index, (content, comments, error) in enumerate(results, start=1):
            url = content.source_url or content.canonical_url
            fetched_at = datetime.now(UTC)
            status = "failed" if error else "success" if comments else "empty"
            content.metadata_json = {
                **dict(content.metadata_json or {}),
                "comment_sync": {
                    "status": status,
                    "count": len(comments),
                    "limit": 20,
                    "fetched_at": fetched_at.isoformat(),
                    "source_kind": "live",
                    "source_provider": adapter.key,
                    "source_url": url,
                    "notice": error
                    or (
                        None
                        if comments
                        else "公开页面或当前授权会话未返回可读评论；未用估算值填充。"
                    ),
                },
            }
            if error:
                failures += 1
            else:
                successes += 1
            existing = existing_by_content.get(content.id, {})
            for item in comments:
                comment_id = str(item.get("platform_comment_id"))
                row = existing.get(comment_id)
                if row is None:
                    self.session.add(
                        Comment(
                            id=uuid4(),
                            workspace_id=account.workspace_id,
                            content_item_id=content.id,
                            platform_comment_id=comment_id,
                            author_name=str(item.get("author_name") or "未知用户"),
                            author_url=item.get("author_url"),
                            author_avatar_url=item.get("author_avatar_url"),
                            text=str(item.get("text") or ""),
                            like_count=item.get("like_count"),
                            reply_count=item.get("reply_count"),
                            parent_comment_id=item.get("parent_comment_id"),
                            is_reply=bool(item.get("is_reply")),
                            published_at=item.get("published_at"),
                            fetched_at=fetched_at,
                            source_kind="live",
                            source_provider=adapter.key,
                            source_url=url,
                            metadata_json={"ranked_by": "like_count + 3 * reply_count"},
                        )
                    )
                    total_stored += 1
                else:
                    if item.get("author_name"):
                        row.author_name = str(item["author_name"])
                    for field in ("author_url", "author_avatar_url", "text"):
                        value = item.get(field)
                        if value not in (None, ""):
                            setattr(row, field, str(value))
                    for field in ("like_count", "reply_count", "published_at"):
                        value = item.get(field)
                        if value is not None:
                            setattr(row, field, value)
                    if item.get("parent_comment_id") is not None:
                        row.parent_comment_id = item["parent_comment_id"]
                    if "is_reply" in item:
                        row.is_reply = bool(item["is_reply"])
                    row.fetched_at = fetched_at
                    row.source_provider = adapter.key
                    row.source_url = url
            # This is a ranked/top-N enrichment, not an authoritative full
            # snapshot. Public endpoints can return fewer rows or no rows after
            # throttling. Keep historical comments instead of interpreting an
            # omission as deletion; explicit cleanup remains a separate action.
            self._emit(
                run,
                "comments",
                "error" if error else "info",
                f"评论采集 {index}/{len(results)}：{content.title[:60]} → "
                f"{f'失败：{error}' if error else f'{len(comments)} 条已保存'}",
                {
                    "page_index": page_index,
                    "content_id": str(content.id),
                    "count": len(comments),
                    "status": status,
                    "error": error,
                },
            )
        run.metadata_json = {
            **run.metadata_json,
            "comments": {
                "enabled": True,
                "limit": 20,
                "concurrency": concurrency,
                "works_requested": len(eligible),
                "works_succeeded": successes,
                "works_failed": failures,
                "comments_stored": total_stored,
                "last_page": page_index,
            },
        }
        await self.session.flush()

    async def _sync_contents(
        self,
        account: Account,
        adapter: PlatformAdapter,
        ctx: AdapterCallContext,
        run: SyncRun,
    ) -> tuple[int, int, int, bool]:
        cursor: str | None = None
        created = 0
        updated = 0
        skipped = 0
        failed = 0
        listed_total = 0
        content_analytics_failed = False
        # ── Sync decomposition (anti-bot / 风控 posture) ──────────────────────
        # Account data (profile + analytics) lives in ``_sync_account`` and uses
        # the yt-dlp channel JSON with a *browser* fallback for TikTok/Douyin
        # (platforms yt-dlp cannot read). Content (作品列表 + 详情) lives here.
        #
        # Fetch strategy: the adapter enumerates the channel window with a cheap
        # flat catalogue read and then fully extracts only the works that need
        # it, up to ``sync_fetch_concurrency`` at a time. Each adapter clamps
        # that number to a per-platform ceiling, so anti-bot-sensitive platforms
        # (TikTok / Douyin) stay near-sequential while YouTube — which tolerates
        # parallel metadata reads — finishes several times faster. Setting
        # ``sync_fetch_concurrency=1`` (or disabling ``sync_fast_list_enabled``)
        # restores the strictly sequential legacy behaviour.
        # ``fetch_content_analytics`` still reads the in-memory per-page cache
        # and launches NO extra subprocesses. Retry resilience comes from
        # yt-dlp's built-in ``--retries`` plus the run-level Celery retry.
        # Workspace-wide fetch policy (set on the Settings → Sync tab). The cap
        # bounds how many works a single sync ingests; ``skip_existing`` decides
        # whether already-known works are refreshed or left untouched.
        sync_cfg = await self.repository.get_sync_settings_config(account.workspace_id)
        account_override = account.sync_settings_override
        account_fetch = (
            account_override.get("fetch") if isinstance(account_override, dict) else None
        )
        account_max_contents = (
            account_fetch.get("max_contents") if isinstance(account_fetch, dict) else None
        )
        max_contents = (
            int(account_max_contents)
            if account_max_contents is not None
            else sync_cfg.get("max_contents")
        )
        skip_existing = bool(sync_cfg.get("skip_existing", True))
        account_metadata = dict(account.metadata_json or {})
        checkpoint = account_metadata.get("content_sync_checkpoint")
        checkpoint_cursor = None
        checkpoint_adapter = None
        if isinstance(checkpoint, dict):
            raw_cursor = checkpoint.get("cursor")
            checkpoint_cursor = str(raw_cursor) if raw_cursor not in (None, "") else None
            checkpoint_adapter = checkpoint.get("adapter_key")
        content_sync_complete = account_metadata.get("content_sync_complete") is True
        resume_backfill = not content_sync_complete
        if checkpoint_adapter not in (None, adapter.key):
            # A provider switch invalidates a provider-specific cursor. Restart
            # that account's backfill from the head rather than mixing offsets
            # from two pagination schemes.
            checkpoint_cursor = None
        # An operator-provided per-account start position is an explicit
        # backfill command, not merely an adapter hint. Honour it at the sync
        # engine level so a browser adapter cannot silently resume an old
        # durable cursor and leave the requested prefix (including covers)
        # untouched. The UI value is 1-based while adapter cursors are 0-based.
        fetch_override = account_fetch
        manual_start = (
            fetch_override.get("playlist_start")
            if isinstance(fetch_override, dict)
            else None
        )
        if manual_start is not None:
            try:
                manual_offset = max(0, int(manual_start) - 1)
            except (TypeError, ValueError):
                manual_offset = 0
            checkpoint_cursor = str(manual_offset)
            resume_backfill = True
        if resume_backfill:
            cursor = checkpoint_cursor
        catalogue_start_offset = (
            int(cursor) if cursor is not None and str(cursor).isdigit() else 0
        )
        latest_published_at = await self.session.scalar(
            select(func.max(ContentItem.published_at)).where(ContentItem.account_id == account.id)
        )
        # Hand the adapter the works we already store so it can skip their
        # (expensive) full extraction when the policy leaves them untouched.
        # This is what makes a routine incremental sync cheap: only genuinely
        # new works pay the per-video extraction cost.
        incremental_mode = False
        if self.settings.sync_fast_list_enabled:
            stored_rows = (
                await self.session.execute(
                    select(
                        ContentItem.external_id,
                        ContentItem.metadata_json,
                        ContentItem.published_at,
                        ContentItem.duration_seconds,
                        ContentItem.cover_url,
                    ).where(ContentItem.account_id == account.id)
                )
            ).all()
            known_external_ids = frozenset(
                str(external_id)
                for external_id, metadata, published_at, duration_seconds, cover_url in stored_rows
                if self._is_incrementally_complete_content_row(
                    metadata,
                    published_at,
                    duration_seconds,
                    cover_url,
                )
            )
            stored_external_ids = frozenset(str(row[0]) for row in stored_rows)
            incomplete_external_ids = stored_external_ids - known_external_ids
            incremental_mode = (
                skip_existing and bool(known_external_ids) and not resume_backfill
            )
            run.metadata_json = {
                **run.metadata_json,
                "catalogue_total_before_sync": len(known_external_ids),
                "catalogue_stored_before_sync": len(stored_external_ids),
                "catalogue_incomplete_repair": len(incomplete_external_ids),
                "sync_mode": "incremental" if incremental_mode else "backfill",
            }
            ctx = dataclasses.replace(
                ctx,
                known_external_ids=known_external_ids,
                skip_known=skip_existing and bool(known_external_ids),
                fetch_concurrency=self.settings.sync_fetch_concurrency,
                sync_backfill=resume_backfill,
            )
        incremental_since = (
            latest_published_at - timedelta(days=7)
            if latest_published_at and not resume_backfill
            else None
        )
        self._emit(
            run,
            "stage",
            "info",
            "开始获取作品列表与指标",
            {
                "max_contents": max_contents,
                "skip_existing": skip_existing,
                "mode": (
                    "resume_backfill"
                    if resume_backfill and checkpoint_cursor
                    else "initial_catalogue"
                    if resume_backfill
                    else "incremental"
                ),
                "resume_cursor": cursor,
                "published_after": incremental_since.isoformat() if incremental_since else None,
            },
        )
        # Existing accounts use a bounded overlap window so normal syncs remain
        # fast while still re-reading the recent edge for late-arriving posts.
        # A new account has no watermark and therefore starts with the adapter's
        # configured catalogue window.
        for page_index in range(self.settings.sync_page_limit):
            # Heartbeat BEFORE the (potentially slow) external page fetch so the
            # stale-recovery watchdog never mislabels a run that is merely
            # mid-page as "crashed". Without this, a single slow yt-dlp page can
            # leave the previous heartbeat older than the stale window and trip
            # recover_stale_runs on a run that is actually still making progress.
            self._set_progress(
                run,
                30 + round(55 * page_index / self.settings.sync_page_limit),
                "content_list",
                f"准备获取第 {page_index + 1}/{self.settings.sync_page_limit} 页作品列表…",
            )
            await self.session.commit()
            if max_contents is not None and (created + updated + skipped + failed) >= max_contents:
                break
            # Hard wall-clock budget: stop paging once exceeded so a single large
            # channel cannot monopolise a worker indefinitely. The run finishes
            # what it has ingested (success/degraded) rather than running unbounded.
            # Kept below SIO_TASK_STALE_AFTER_SECONDS so healthy-but-slow runs are
            # never flagged as crashed.
            if run.started_at is not None:
                elapsed = (datetime.now(UTC) - run.started_at).total_seconds()
                if elapsed >= self.settings.sync_run_timeout_seconds:
                    self._budget_exceeded = True
                    break
            window = 50
            # An account we already track only needs a small probe at the head
            # of the catalogue: enumerating a channel window is itself a paid
            # network operation (~0.7s per work on this deployment), so asking
            # for 50 when the answer is usually "nothing new" is pure waste. If
            # the probe comes back entirely new, later pages widen back to 50.
            if incremental_mode and page_index == 0:
                window = min(window, self.settings.sync_incremental_probe_size)
            if max_contents is not None:
                remaining = max_contents - (created + updated + skipped + failed)
                window = max(1, min(window, remaining))
            published_after = incremental_since
            # A failing page fetch must not abort the entire sync. If we have
            # already collected works, stop paging gracefully and finalise what
            # we have; only a first-page failure (nothing collected yet) is a
            # genuine, re-raisable outage that the caller handles as retry/error.
            remaining_budget = self._remaining_budget_seconds(run)
            if remaining_budget <= 0:
                self._budget_exceeded = True
                break
            # Cap each page fetch at sync_page_fetch_timeout_seconds — strictly
            # below the adapter's own extract timeout. A slow/unreachable channel
            # then trips asyncio.wait_for (caught just below: the loop breaks and
            # finalises what was ingested, no retry) rather than the adapter's
            # longer internal timeout which would raise retryable and burn the
            # whole run budget on repeated extracts. This is what keeps an
            # individual flaky account from stalling the worker.
            page_fetch_timeout = min(
                remaining_budget, self.settings.sync_page_fetch_timeout_seconds
            )
            try:
                page_ctx = dataclasses.replace(ctx, timeout_seconds=page_fetch_timeout)
                page = await asyncio.wait_for(
                    adapter.list_contents(
                        page_ctx,
                        account.external_id,
                        published_after=published_after,
                        cursor=cursor,
                        page_size=window,
                    ),
                    timeout=page_fetch_timeout,
                )
            except TimeoutError:
                self._budget_exceeded = True
                self._emit(
                    run,
                    "page",
                    "warn",
                    f"第 {page_index + 1} 页获取超过同步时间预算，已保留前面已入库内容",
                    {
                        "page_index": page_index,
                        "budget_seconds": self.settings.sync_run_timeout_seconds,
                    },
                )
                break
            except PlatformAdapterError as exc:
                if run.items_processed == 0 and cursor is None:
                    raise
                self._emit(
                    run,
                    "page",
                    "error",
                    f"第 {page_index + 1} 页作品列表获取失败：{exc}",
                    {"page_index": page_index, "error_code": exc.code, "error": str(exc)},
                )
                break
            except Exception as exc:  # noqa: BLE001
                if run.items_processed == 0 and cursor is None:
                    raise
                logger.warning(
                    "sync_page_list_failed",
                    extra={"event": "platform.sync.page_failed", "sync_run_id": str(run.id)},
                )
                self._emit(
                    run,
                    "page",
                    "error",
                    f"第 {page_index + 1} 页作品列表获取失败：{exc}",
                    {"page_index": page_index, "error": str(exc)},
                )
                break
            # Adapters are allowed to return a provider-sized page even when
            # the operator's per-run cap is smaller. Enforce that cap here at
            # the orchestration boundary so a platform cannot make a request
            # for 45 works ingest 60 (or more) and make the UI promise false.
            if max_contents is not None:
                remaining_slots = max_contents - (created + updated + skipped + failed)
                if remaining_slots <= 0:
                    break
                if len(page.items) > remaining_slots:
                    page = dataclasses.replace(
                        page,
                        items=page.items[:remaining_slots],
                    )
            batch_total = len(page.items)
            listed_total += batch_total
            page_items: list[ContentItem] = []
            self._emit(
                run,
                "page",
                "info",
                f"第 {page_index + 1} 页列出 {batch_total} 条作品",
                {
                    "page_index": page_index,
                    "batch_total": batch_total,
                    "has_next": bool(page.next_cursor),
                },
            )
            # Per-page heartbeat: tell the UI exactly how many works were just
            # listed and the running total, instead of only updating once the
            # whole page (upsert + analytics) is done.
            self._set_progress(
                run,
                30 + round(55 * page_index / self.settings.sync_page_limit),
                "content_list",
                f"已获取第 {page_index + 1}/{self.settings.sync_page_limit} 页作品列表，"
                f"本页 {batch_total} 条，累计 {run.items_processed} 条",
            )
            await self.session.commit()
            page_processed = 0
            page_skipped = 0
            item_data_by_external_id: dict[str, PlatformContentData] = {}
            item_context_by_external_id: dict[str, tuple[int, int]] = {}
            # Incremental platform listings are expected to be newest-first.
            # Remember whether this page has the safe shape
            # ``newer works -> known works`` so a routine sync can stop at that
            # boundary without paying for another full catalogue request. We
            # only use the optimization when the entire suffix is known; a
            # non-monotonic page (known -> new -> known) continues paging rather
            # than risking a missed work.
            page_new_to_known_boundary = False
            if incremental_mode and page.items:
                known_ids = [
                    item.external_id in known_external_ids for item in page.items
                ]
                try:
                    first_known = known_ids.index(True)
                except ValueError:
                    first_known = -1
                page_new_to_known_boundary = (
                    first_known > 0 and all(known_ids[first_known:])
                )
            for page_item_index, data in enumerate(page.items, start=1):
                item_index = listed_total - batch_total + page_item_index
                rejection = self._content_rejection_reason(data)
                if rejection is not None:
                    rejected = list(run.metadata_json.get("rejected_items", []))
                    if len(rejected) < 20:
                        rejected.append(
                            {
                                "external_id": data.external_id,
                                "reason": rejection,
                            }
                        )
                    run.metadata_json = {
                        **run.metadata_json,
                        "rejected_item_count": int(run.metadata_json.get("rejected_item_count", 0))
                        + 1,
                        "rejected_items": rejected,
                    }
                    rejected_payload = self._content_progress_payload(
                        data,
                        item_index=item_index,
                        page_index=page_index + 1,
                        page_item_index=page_item_index,
                        page_total=batch_total,
                        listed_total=listed_total,
                        processed_total=run.items_processed,
                        status="rejected",
                        action="rejected",
                        error=rejection,
                        metrics_state="missing",
                        counts={
                            "listed": listed_total,
                            "processed": run.items_processed,
                            "failed": failed,
                            "skipped": skipped,
                        },
                    )
                    rejected_message = self._content_progress_message(rejected_payload)
                    self._set_content_progress(
                        run,
                        rejected_payload,
                        message=rejected_message,
                        add_to_recent=True,
                    )
                    self._emit(run, "item", "warn", rejected_message, rejected_payload)
                    continue
                # Count every listed work (including rejected ones) so the live
                # counter matches the per-page total, then drive a fine-grained
                # progress heartbeat every 25 works during the slow per-item
                # upsert/analytics phase.
                run.items_processed += 1
                page_processed += 1
                item_data_by_external_id[data.external_id] = data
                item_context_by_external_id[data.external_id] = (item_index, page_item_index)
                processing_payload = self._content_progress_payload(
                    data,
                    item_index=item_index,
                    page_index=page_index + 1,
                    page_item_index=page_item_index,
                    page_total=batch_total,
                    listed_total=listed_total,
                    processed_total=run.items_processed,
                    status="processing",
                    action="upsert",
                    counts={
                        "listed": listed_total,
                        "processed": run.items_processed,
                        "failed": failed,
                        "skipped": skipped,
                    },
                )
                self._set_content_progress(
                    run,
                    processing_payload,
                    message=self._content_progress_message(processing_payload),
                )
                # A single work that fails to upsert must not abort the whole
                # sync. Record it, continue, and surface it in the tracklog.
                try:
                    (
                        content,
                        was_created,
                        was_skipped,
                        indexable_changed,
                    ) = await self._upsert_content(account, data, skip_existing=skip_existing)
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    item_data_by_external_id.pop(data.external_id, None)
                    item_context_by_external_id.pop(data.external_id, None)
                    logger.warning(
                        "sync_content_upsert_failed",
                        extra={
                            "event": "platform.sync.item_failed",
                            "sync_run_id": str(run.id),
                            "external_id": data.external_id,
                        },
                    )
                    failed_payload = self._content_progress_payload(
                        data,
                        item_index=item_index,
                        page_index=page_index + 1,
                        page_item_index=page_item_index,
                        page_total=batch_total,
                        listed_total=listed_total,
                        processed_total=run.items_processed,
                        status="failed",
                        action="failed",
                        error=str(exc),
                        metrics_state="failed",
                        counts={
                            "listed": listed_total,
                            "processed": run.items_processed,
                            "failed": failed,
                            "skipped": skipped,
                        },
                    )
                    failed_message = self._content_progress_message(failed_payload)
                    self._set_content_progress(
                        run,
                        failed_payload,
                        message=failed_message,
                        add_to_recent=True,
                    )
                    self._emit(run, "item", "error", failed_message, failed_payload)
                    continue
                page_items.append(content)
                created += int(was_created)
                if was_skipped:
                    skipped += 1
                    page_skipped += 1
                else:
                    updated += int(not was_created)
                action = "skipped" if was_skipped else "created" if was_created else "updated"
                stored_payload = self._content_progress_payload(
                    data,
                    item_index=item_index,
                    page_index=page_index + 1,
                    page_item_index=page_item_index,
                    page_total=batch_total,
                    listed_total=listed_total,
                    processed_total=run.items_processed,
                    status="stored",
                    action=action,
                    counts={
                        "listed": listed_total,
                        "processed": run.items_processed,
                        "failed": failed,
                        "skipped": skipped,
                    },
                )
                stored_message = self._content_progress_message(stored_payload)
                self._set_content_progress(
                    run,
                    stored_payload,
                    message=stored_message,
                    add_to_recent=True,
                )
                self._emit(run, "item", "info", stored_message, stored_payload)
                # Text-affecting fields changed (or it's brand new) -> queue a
                # fresh vector index so semantic search sees the latest text.
                if indexable_changed:
                    self._pending_index_ids.append(content.id)
                if (
                    page_processed % _SYNC_ITEM_PROGRESS_COMMIT_INTERVAL == 0
                    or page_processed == batch_total
                ):
                    self._set_progress(
                        run,
                        min(
                            30 + round(55 * (page_index + 0.5) / self.settings.sync_page_limit),
                            85,
                        ),
                        "content_metrics",
                        f"正在获取第 {run.items_processed} 条作品详情"
                        f"（本页 {page_processed}/{batch_total}，累计 {run.items_processed} 条）",
                    )
                    await self.session.commit()
                    await self._flush_pending_indexing()
            if page_skipped > 0:
                self._emit(
                    run,
                    "item",
                    "info",
                    f"第 {page_index + 1} 页跳过 {page_skipped} 条已存在作品",
                    {"page_index": page_index, "skipped": page_skipped},
                )
            await self.session.flush()
            # Analytics fetch is best-effort: a failure here degrades metrics but
            # must never discard the works already ingested this page.
            synthesized = 0
            analytics: Sequence[PlatformMetricsData] = ()
            analytics_by_external_id: dict[str, PlatformMetricsData] = {}
            try:
                remaining_budget = self._remaining_budget_seconds(run)
                if remaining_budget <= 0:
                    self._budget_exceeded = True
                    analytics = ()
                    content_analytics_failed = True
                    self._emit(
                        run,
                        "analytics",
                        "warn",
                        f"第 {page_index + 1} 页指标分析未开始：同步时间预算已耗尽",
                        {"page_index": page_index, "requested": len(page_items)},
                    )
                else:
                    analytics_ctx = dataclasses.replace(ctx, timeout_seconds=remaining_budget)
                    analytics = await asyncio.wait_for(
                        adapter.fetch_content_analytics(
                            analytics_ctx, [item.external_id for item in page_items]
                        ),
                        timeout=remaining_budget,
                    )
                by_external_id = {item.external_id: item for item in page_items}
                analytics_by_external_id = {
                    analytics_data.external_id: analytics_data for analytics_data in analytics
                }
                for analytics_data in analytics:
                    matched_content = by_external_id.get(analytics_data.external_id)
                    if matched_content is not None and analytics_data.metrics:
                        await self._upsert_content_snapshot(
                            self._content_snapshot(matched_content.id, analytics_data)
                        )
                synthesized = await self._synthesize_content_snapshots(
                    adapter, ctx, page_items, analytics
                )
            except TimeoutError:
                self._budget_exceeded = True
                content_analytics_failed = True
                self._emit(
                    run,
                    "analytics",
                    "warn",
                    f"第 {page_index + 1} 页指标分析超过同步时间预算，已保留作品",
                    {"page_index": page_index, "requested": len(page_items)},
                )
            except Exception as exc:  # noqa: BLE001
                content_analytics_failed = True
                logger.warning(
                    "sync_content_analytics_failed",
                    extra={
                        "event": "platform.sync.analytics_failed",
                        "sync_run_id": str(run.id),
                        "page_index": page_index,
                    },
                )
                self._emit(
                    run,
                    "analytics",
                    "warn",
                    f"第 {page_index + 1} 页指标分析失败：{exc}",
                    {
                        "page_index": page_index,
                        "requested": len(page_items),
                        "error": str(exc),
                    },
                )
            else:
                if not content_analytics_failed:
                    self._emit(
                        run,
                        "analytics",
                        "info",
                        f"第 {page_index + 1} 页分析完成：{len(analytics)} 条指标",
                        {
                            "page_index": page_index,
                            "requested": len(page_items),
                            "returned": len(analytics),
                            "synthesized": synthesized,
                        },
                    )
            for external_id, data in item_data_by_external_id.items():
                item_index, page_item_index = item_context_by_external_id[external_id]
                metrics_data = analytics_by_external_id.get(external_id)
                metrics_state = self._content_metrics_state(
                    data,
                    metrics_data,
                    analytics_failed=content_analytics_failed,
                )
                metric_payload = self._content_progress_payload(
                    data,
                    item_index=item_index,
                    page_index=page_index + 1,
                    page_item_index=page_item_index,
                    page_total=batch_total,
                    listed_total=listed_total,
                    processed_total=run.items_processed,
                    status="metrics",
                    action="analytics",
                    metrics_data=metrics_data,
                    metrics_state=metrics_state,
                    counts={
                        "listed": listed_total,
                        "processed": run.items_processed,
                        "failed": failed,
                        "skipped": skipped,
                    },
                )
                self._set_content_progress(
                    run,
                    metric_payload,
                    message=self._content_progress_message(metric_payload),
                    add_to_recent=True,
                )
            # Optional enrichment is deliberately after content + analytics
            # persistence. A comment wall can be unavailable or slow without
            # making a healthy page of works disappear or turning the sync into
            # an all-or-nothing transaction.
            queued_comment_ids = await self._collect_page_comments(
                account,
                adapter,
                ctx,
                page_items,
                run,
                page_index,
            )
            run.records_created = created
            # Field updates + browser-derived snapshots both count as updates.
            run.records_updated = updated + synthesized
            run.metadata_json = {
                **run.metadata_json,
                "skipped_existing": skipped,
                "items_failed": failed,
                "content_analytics_failed": content_analytics_failed,
            }
            progress = 30 + round(55 * (page_index + 1) / self.settings.sync_page_limit)
            self._set_progress(
                run,
                min(progress, 85),
                "content_metrics",
                f"本页 {len(page_items)} 条作品已入库，累计 {run.items_processed} 条，正在计算指标",
            )
            if not page.next_cursor:
                run.items_total = run.items_processed
                account_metadata.pop("content_sync_checkpoint", None)
                account_metadata["content_sync_complete"] = True
                account.metadata_json = dict(account_metadata)
            else:
                account_metadata["content_sync_complete"] = False
                account_metadata["content_sync_checkpoint"] = {
                    "adapter_key": adapter.key,
                    "cursor": str(page.next_cursor),
                }
                account.metadata_json = dict(account_metadata)
            await self.session.commit()
            if queued_comment_ids:
                dispatched_ids: list[UUID] = []
                try:
                    # Import lazily to avoid a module cycle during worker boot.
                    from app.tasks.monitoring import collect_content_comments as collect_task

                    for content_id in queued_comment_ids:
                        collect_task.delay(str(content_id))
                        dispatched_ids.append(content_id)
                    run.metadata_json = {
                        **run.metadata_json,
                        "comments": {
                            **dict(run.metadata_json.get("comments") or {}),
                            "works_dispatched": len(dispatched_ids),
                            "queue_status": "dispatched",
                        },
                    }
                except Exception as exc:  # noqa: BLE001 - comment queue is optional
                    logger.warning(
                        "comment_enrichment_dispatch_failed",
                        extra={"run_id": str(run.id), "error": str(exc)},
                    )
                    failed_ids = set(queued_comment_ids) - set(dispatched_ids)
                    for content in page_items:
                        if content.id not in failed_ids:
                            continue
                        state = dict((content.metadata_json or {}).get("comment_sync") or {})
                        content.metadata_json = {
                            **dict(content.metadata_json or {}),
                            "comment_sync": {
                                **state,
                                "status": "queue_failed",
                                "notice": "评论任务未能进入后台队列，作品同步不受影响",
                            },
                        }
                    run.metadata_json = {
                        **run.metadata_json,
                        "comments": {
                            **dict(run.metadata_json.get("comments") or {}),
                            "works_dispatched": len(dispatched_ids),
                            "queue_status": "partial" if dispatched_ids else "failed",
                            "queue_error": str(exc)[:500],
                        },
                    }
                self._emit(
                    run,
                    "comments",
                    "warn" if len(dispatched_ids) < len(queued_comment_ids) else "info",
                    (
                        f"评论任务已派发 {len(dispatched_ids)}/{len(queued_comment_ids)}，"
                        "不阻塞账号同步"
                    ),
                    {
                        "queued": len(queued_comment_ids),
                        "dispatched": len(dispatched_ids),
                    },
                )
                await self.session.commit()
            if not page.next_cursor:
                cursor = None
                break
            # Early stop at the known-works boundary. Platform listings are
            # reverse-chronological, so once an entire page consists of works we
            # already store, everything further down is older and equally known.
            # Paging on would re-enumerate the whole back catalogue on every
            # routine sync — the single largest source of wasted wall clock.
            if incremental_mode and batch_total > 0 and page_skipped == batch_total:
                run.items_total = run.items_processed
                catalogue_total = len(known_external_ids)
                run.metadata_json = {
                    **run.metadata_json,
                    "catalogue_total": catalogue_total,
                    "catalogue_complete": True,
                    "incremental_probe_items": run.items_processed,
                }
                self._emit(
                    run,
                    "page",
                    "info",
                    (
                        f"第 {page_index + 1} 页 {page_skipped} 条作品均已入库；"
                        f"当前目录已有 {catalogue_total} 条，增量探测到达边界，"
                        "跳过后续旧作品"
                    ),
                    {
                        "page_index": page_index,
                        "skipped": page_skipped,
                        "catalogue_total": catalogue_total,
                        "incremental_probe": True,
                    },
                )
                account_metadata.pop("content_sync_checkpoint", None)
                account_metadata["content_sync_complete"] = True
                account.metadata_json = dict(account_metadata)
                await self.session.commit()
                cursor = None
                break
            if page_new_to_known_boundary:
                run.items_total = run.items_processed
                self._emit(
                    run,
                    "page",
                    "info",
                    (
                        f"绗?{page_index + 1} 椤靛湪鏂颁綔鍝佸悗閬囧埌宸插叆搴撹竟鐣岋紝"
                        "鎻愬墠缁撴潫缈婚〉"
                    ),
                    {
                        "page_index": page_index,
                        "known_suffix": True,
                        "boundary_index": next(
                            index
                            for index, known in enumerate(known_ids)
                            if known
                        ),
                    },
                )
                account_metadata.pop("content_sync_checkpoint", None)
                account_metadata["content_sync_complete"] = True
                account.metadata_json = dict(account_metadata)
                await self.session.commit()
                cursor = None
                break
            cursor = page.next_cursor
        if cursor:
            # The adapter still has a page to serve when this run reaches its
            # bounded page/time budget. Keep the continuation durable and make
            # the result visibly partial instead of silently reporting success.
            self._content_truncated = True
            account_metadata["content_sync_complete"] = False
            account_metadata["content_sync_checkpoint"] = {
                "adapter_key": adapter.key,
                "cursor": str(cursor),
            }
            account.metadata_json = dict(account_metadata)
            await self.session.commit()
        else:
            raw_yt_cfg = ctx.config.get("yt_dlp") if isinstance(ctx.config, dict) else None
            has_catalogue_filter = isinstance(raw_yt_cfg, dict) and bool(
                raw_yt_cfg.get("dateafter") or raw_yt_cfg.get("datebefore")
            )
            if (
                resume_backfill
                and max_contents is None
                and incremental_since is None
                and not has_catalogue_filter
            ):
                # ``listed_total`` includes every provider row in this run,
                # while ``catalogue_start_offset`` accounts for a durable
                # continuation cursor from an earlier bounded backfill.
                self._catalogue_total = catalogue_start_offset + listed_total
                account_metadata["content_sync_catalogue_total"] = self._catalogue_total
                account.metadata_json = dict(account_metadata)
                run.metadata_json = {
                    **run.metadata_json,
                    "catalogue_total": self._catalogue_total,
                    "catalogue_complete": True,
                }
                await self.session.commit()
        self._emit(
            run,
            "stage",
            "info",
            "作品列表与指标抓取阶段结束",
            {
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "failed": failed,
                "content_analytics_failed": content_analytics_failed,
            },
        )
        return created, updated, failed, content_analytics_failed

    @staticmethod
    def _metrics_from_metadata(meta: Mapping[str, Any] | None) -> dict[str, int]:
        """Harvest interaction metrics browser adapters stash during listing.

        Browser adapters cannot call a structured analytics API, so when they
        scrape a profile/video page they record whatever the DOM exposes in
        ``ContentItem.metadata_json`` — e.g. Douyin ``digg_count``/``comment_count``/
        ``share_count``/``play_count``, Bilibili ``comment``/``play``. The default
        ``fetch_content_analytics`` therefore returns no metrics, which left
        ``ContentSnapshot`` rows with blank like/comment/share counts.

        This normalizes those aliases into the canonical snapshot fields so #61
        interaction snapshots and #62 comment counts carry real data instead of
        being dropped.
        """
        if not meta:
            return {}
        out: dict[str, int] = {}

        def take(canonical: str, *keys: str) -> None:
            for key in keys:
                raw = meta.get(key)
                if isinstance(raw, bool):
                    continue
                val: int | None = None
                if isinstance(raw, (int, float)):
                    val = int(raw)
                elif isinstance(raw, str) and raw.strip():
                    val = parse_compact_count(raw)
                if val is not None:
                    out[canonical] = val
                    return

        take("view_count", "view_count", "play_count", "view_text", "yt_view_count")
        take("like_count", "like_count", "digg_count", "yt_like_count")
        take("comment_count", "comment_count", "yt_comment_count")
        take("share_count", "share_count", "repost_count", "yt_share_count")
        take("favorite_count", "favorite_count", "yt_favorite_count")
        return out

    async def _synthesize_content_snapshots(
        self,
        adapter: PlatformAdapter,
        ctx: AdapterCallContext,
        page_items: list[ContentItem],
        analytics: Sequence[PlatformMetricsData],
    ) -> int:
        """Create a ContentSnapshot from interaction metrics browser adapters
        stashed in ``ContentItem.metadata_json`` when ``fetch_content_analytics``
        returned no structured metrics.

        Douyin/Bilibili listings expose like/comment/share/play counts; without
        harvesting them here those counts would be dropped and #61/#62 would
        show blanks. The analytics path already covers adapters that return
        real metrics, so those external ids are skipped below.
        """
        snapshotted = {a.external_id for a in analytics if a.metrics}
        made = 0
        for item in page_items:
            if item.external_id in snapshotted:
                continue
            metrics = self._metrics_from_metadata(item.metadata_json)
            if metrics:
                await self._upsert_content_snapshot(
                    self._content_snapshot(
                        item.id,
                        PlatformMetricsData(
                            external_id=item.external_id,
                            captured_at=ctx.observed_at,
                            metrics=metrics,
                            source_kind="live",
                            provider=adapter.key,
                            fetched_at=ctx.observed_at,
                        ),
                    )
                )
                made += 1
        return made

    async def _upsert_content_snapshot(self, snapshot: ContentSnapshot) -> ContentSnapshot:
        """Insert a content snapshot without poisoning the session.

        ``captured_at`` is shared by all works in a sync run. Duplicate
        catalogue entries, repeated analytics rows, or a retry at the same
        timestamp must reuse the existing immutable measurement rather than
        mutating it and triggering the append-only guard.
        """
        key = (snapshot.content_item_id, snapshot.captured_at)
        pending = self._pending_content_snapshots.get(key)
        if pending is not None:
            self._carry_forward_snapshot_metrics(pending, snapshot)
            return pending

        previous = await self.session.scalar(
            select(ContentSnapshot)
            .where(
                ContentSnapshot.content_item_id == snapshot.content_item_id,
                ContentSnapshot.captured_at < snapshot.captured_at,
            )
            .order_by(ContentSnapshot.captured_at.desc(), ContentSnapshot.id.desc())
            .limit(1)
        )
        if previous is not None:
            self._carry_forward_snapshot_metrics(snapshot, previous)

        existing = await self.session.scalar(
            select(ContentSnapshot).where(
                ContentSnapshot.content_item_id == snapshot.content_item_id,
                ContentSnapshot.captured_at == snapshot.captured_at,
            )
        )
        if existing is None:
            self.session.add(snapshot)
            self._pending_content_snapshots[key] = snapshot
            return snapshot

        self._pending_content_snapshots[key] = existing
        return existing

    @staticmethod
    def _carry_forward_snapshot_metrics(
        target: ContentSnapshot,
        source: ContentSnapshot,
    ) -> None:
        """Keep the last known metric when the current adapter response omits it.

        A fast catalogue refresh can legitimately return a new view count while
        omitting likes/comments.  Writing those omissions as ``NULL`` makes the
        newest snapshot hide real values that were already captured, so the
        works table appears to lose data.  Carrying forward is explicitly marked
        in metadata; it is not presented as a newly observed platform value.
        """
        fields = (
            "view_count",
            "like_count",
            "comment_count",
            "share_count",
            "favorite_count",
            "follower_gain",
            "average_watch_time",
            "completion_rate",
            "search_traffic_rate",
            "recommendation_traffic_rate",
            "profile_traffic_rate",
            "revenue",
            "rpm",
        )
        carried = [
            field
            for field in fields
            if getattr(target, field) is None and getattr(source, field) is not None
        ]
        for field in carried:
            setattr(target, field, getattr(source, field))
        if carried:
            target.metadata_json = {
                **(target.metadata_json or {}),
                "carried_forward_metrics": carried,
                "carried_forward_from": source.captured_at.isoformat(),
            }

    @staticmethod
    def _content_rejection_reason(data: PlatformContentData) -> str | None:
        if not data.external_id.strip():
            return "missing_external_id"
        if not data.title.strip():
            return "missing_title"
        if PlatformSyncExecutor._text_is_error_page(data.title):
            return "error_page_title"
        if not data.canonical_url.lower().startswith(("https://", "http://")):
            return "invalid_canonical_url"
        return None

    @staticmethod
    def _text_is_error_page(value: str) -> bool:
        normalized = " ".join(value.casefold().split())
        return normalized in {
            "404",
            "404 not found",
            "not found",
            "page not found",
            "页面不存在",
            "内容不存在",
            "视频不存在",
        }

    def _set_progress(self, run: SyncRun, percent: int, stage: str, message: str) -> None:
        run.progress_percent = min(100, max(run.progress_percent, percent))
        run.progress_stage = stage
        run.progress_message = message[:500]
        run.metadata_json = {
            **(run.metadata_json or {}),
            "heartbeat_at": datetime.now(UTC).isoformat(),
        }
        # Mirror every stage transition into the live log. This is what makes the
        # scrolling detail panel work identically for all four platforms: even an
        # adapter that emits nothing of its own still produces a readable
        # timeline. The sink is the single writer of the tail, so stage lines and
        # adapter lines interleave in true chronological order.
        sink = self._log_sink
        if sink is not None:
            sink.push(f"▸ {message}")

    @staticmethod
    def _index_signature(
        title: str | None,
        description: str | None,
        tags: list[str] | None,
        media: Any,
    ) -> tuple[object, ...]:
        """Stable signature of the text that feeds embedding.

        Only title / description / tags / subtitle tracks affect the embedded
        vectors; engagement metrics live in ``content_snapshots`` and must NOT
        trigger a re-index. Used to decide whether a content upsert needs a
        fresh vector index.
        """

        subs = (media or {}).get("subtitles") if isinstance(media, dict) else None
        if isinstance(subs, list):
            subs_sig = tuple(
                sorted((s.get("lang", ""), s.get("file", "")) for s in subs if isinstance(s, dict))
            )
        else:
            subs_sig = ()
        return (title, description, tuple(sorted(tags or [])), subs_sig)

    async def _upsert_content(
        self, account: Account, data: PlatformContentData, skip_existing: bool = False
    ) -> tuple[ContentItem, bool, bool, bool]:
        content = await self.session.scalar(
            select(ContentItem).where(
                ContentItem.workspace_id == account.workspace_id,
                ContentItem.platform_id == account.platform_id,
                ContentItem.account_id == account.id,
                ContentItem.external_id == data.external_id,
            )
        )
        created = content is None
        old_index_sig = (
            self._index_signature(content.title, content.description, content.tags, content.media)
            if content is not None
            else None
        )
        skipped = False
        if content is None:
            content = ContentItem(
                id=uuid4(),
                workspace_id=account.workspace_id,
                platform_id=account.platform_id,
                account_id=account.id,
                external_id=data.external_id,
                content_type=data.content_type,
                title=data.title,
                description=data.description,
                published_at=data.published_at,
                duration_seconds=_as_decimal(data.duration_seconds),
                canonical_url=data.canonical_url,
                cover_url=data.cover_url,
                language=data.language,
                status=data.status,
                metadata_json=dict(data.metadata),
                first_seen_at=data.fetched_at,
                last_seen_at=data.fetched_at,
                source_kind=data.source_kind,
                source_provider=data.provider,
                fetched_at=data.fetched_at,
                source_url=data.canonical_url,
                raw_payload_ref=None,
                media=dict(data.media) if data.media else None,
                tags=list(data.tags or []),
            )
            self.session.add(content)
        elif skip_existing:
            # Keep operator-edited fields, but repair missing acquisition
            # artifacts. Older runs often stored the work before thumbnails or
            # subtitles were available; skipping must not make that state permanent.
            content.last_seen_at = data.fetched_at
            # Repair rows created by the old TikTok DOM mapper, which stored a
            # card's numeric view label as the title. This is safe for manual
            # edits because only an unambiguously metric-shaped existing title
            # is replaced by the platform caption or stable video fallback.
            existing_title = str(content.title or "").strip()
            incoming_meta = dict(data.metadata)
            if data.title and re.fullmatch(
                r"[\d.,]+\s*[KMB]?\s*(?:views?|播放|次播放)?",
                existing_title,
                flags=re.IGNORECASE,
            ):
                content.title = data.title
            if not content.cover_url and data.cover_url:
                content.cover_url = data.cover_url
            if not content.description and data.description:
                content.description = data.description
            if content.published_at is None and data.published_at is not None:
                content.published_at = data.published_at
            if content.duration_seconds is None and data.duration_seconds is not None:
                content.duration_seconds = _as_decimal(data.duration_seconds)
            content.media = merge_media_manifest(content.media, data.media)
            stored_meta = dict(content.metadata_json or {})
            incoming_partial = bool(incoming_meta.get("partial"))
            stored_complete_detail = (
                not bool(stored_meta.get("partial"))
                and str(stored_meta.get("detail_level") or "full") == "full"
            )
            if incoming_partial and stored_complete_detail:
                # A transient detail failure must not downgrade a previously
                # complete row merely because the fast catalogue still returns
                # a truthful but partial entry.
                incoming_meta.pop("partial", None)
                incoming_meta.pop("detail_level", None)
            merged_meta = {**stored_meta, **incoming_meta}
            if not incoming_partial:
                # A successful full extraction repairs rows created by an older
                # catalogue-only run; remove the stale marker so the next
                # incremental sync can safely skip this row.
                merged_meta.pop("partial", None)
                merged_meta.pop("detail_level", None)
            content.metadata_json = merged_meta
            if data.tags:
                content.tags = list(dict.fromkeys([*(content.tags or []), *data.tags]))[:30]
            skipped = True
        else:
            # A row the adapter flagged as ``partial`` was built from a cheap
            # catalogue listing (real title and view count, but no description
            # or timestamp). Refreshing must not downgrade a work that a full
            # extraction already enriched, so partial rows only fill blanks.
            partial = bool(dict(data.metadata).get("partial"))
            if data.title:
                content.title = data.title
            if data.description is not None or not partial:
                content.description = data.description
            if data.published_at is not None or not partial:
                content.published_at = data.published_at
            if data.duration_seconds is not None or not partial:
                content.duration_seconds = _as_decimal(data.duration_seconds)
            if data.canonical_url:
                content.canonical_url = data.canonical_url
            if data.cover_url:
                content.cover_url = data.cover_url
            if data.language is not None or not partial:
                content.language = data.language
            # ``status`` is NOT NULL: an adapter that cannot determine the
            # status must leave the stored one alone rather than crash the
            # whole upsert with a constraint violation.
            if data.status is not None:
                content.status = data.status
            content.metadata_json = {**content.metadata_json, **dict(data.metadata)}
            content.last_seen_at = data.fetched_at
            content.source_kind = data.source_kind
            content.source_provider = data.provider
            content.fetched_at = data.fetched_at
            content.source_url = data.canonical_url
            # A metadata-only sync must never erase files archived by an
            # earlier download-enabled run.  Merge newly discovered files and
            # preserve the existing manifest when this adapter/fallback did
            # not produce media in the current pass.
            content.media = merge_media_manifest(content.media, data.media)
            if data.tags:
                # union with existing to avoid clobbering manually added tags
                merged = list(dict.fromkeys([*content.tags, *data.tags]))
                content.tags = merged[:30]
        if created:
            indexable_changed = True
        else:
            new_index_sig = self._index_signature(
                content.title, content.description, content.tags, content.media
            )
            indexable_changed = new_index_sig != old_index_sig
        return content, created, skipped, indexable_changed

    async def _flush_pending_indexing(self) -> None:
        """Dispatch the incremental index task for content whose text changed.

        Called right after a per-page ``commit``, so every queued id is already
        durable in the database when ``index_content_item`` picks it up. No-ops
        unless semantic search is actually enabled (otherwise there is nothing
        to index into).
        """

        if not self._pending_index_ids:
            return
        indexing_enabled = self.settings.semantic_search_enabled
        backend_ready = self.settings.embedding_backend != "none"
        if not (indexing_enabled and backend_ready):
            self._pending_index_ids.clear()
            return
        try:
            from app.tasks.embedding import index_content_item
        except Exception:  # pragma: no cover - import guard
            self._pending_index_ids.clear()
            return
        for content_id in self._pending_index_ids:
            try:
                index_content_item.delay(str(content_id))
            except Exception as exc:  # noqa: BLE001 - broker may be unavailable
                logger.warning(
                    "sync_index_dispatch_failed",
                    extra={"content_item_id": str(content_id), "error": str(exc)},
                )
        self._pending_index_ids.clear()

    def _content_snapshot(self, content_id: UUID, data: PlatformMetricsData) -> ContentSnapshot:
        value = data.metrics
        return ContentSnapshot(
            id=uuid4(),
            content_item_id=content_id,
            captured_at=data.captured_at,
            view_count=_as_int(value.get("view_count")),
            like_count=_as_int(value.get("like_count")),
            comment_count=_as_int(value.get("comment_count")),
            share_count=_as_int(value.get("share_count")),
            favorite_count=_as_int(value.get("favorite_count")),
            follower_gain=_as_int(value.get("follower_gain")),
            average_watch_time=_as_decimal(value.get("average_watch_time")),
            completion_rate=_as_decimal(value.get("completion_rate")),
            search_traffic_rate=_as_decimal(value.get("search_traffic_rate")),
            recommendation_traffic_rate=_as_decimal(value.get("recommendation_traffic_rate")),
            profile_traffic_rate=_as_decimal(value.get("profile_traffic_rate")),
            revenue=_as_decimal(value.get("revenue")),
            rpm=_as_decimal(value.get("rpm")),
            metadata_json={
                **dict(data.metadata),
                "unavailable_metrics": list(data.unavailable_metrics),
            },
            source_kind=data.source_kind,
            source_provider=data.provider,
            fetched_at=data.fetched_at,
            raw_payload_ref=None,
            created_at=datetime.now(UTC),
        )

    async def _calculate_metrics(self, account: Account, calculated_at: datetime) -> None:
        await self.session.flush()
        account_snapshots = list(
            (
                await self.session.scalars(
                    select(AccountSnapshot)
                    .where(AccountSnapshot.account_id == account.id)
                    .order_by(AccountSnapshot.captured_at.desc())
                )
            ).all()
        )
        if account_snapshots:
            latest_account = account_snapshots[0]
            previous = self._snapshot_for_window(account_snapshots, latest_account.captured_at, 24)
            if (
                latest_account.follower_count is not None
                and previous is not None
                and previous.follower_count is not None
            ):
                elapsed_hours = self._elapsed_hours(
                    latest_account.captured_at, previous.captured_at
                )
                self._metric(
                    account,
                    account.id,
                    "account",
                    "follower_growth_24h",
                    "24h",
                    latest_account.follower_count - previous.follower_count,
                    calculated_at,
                    metadata={
                        "quality": "derived",
                        "formula": "latest_follower_count - prior_follower_count",
                        "actual_window_hours": round(elapsed_hours, 3),
                        "input_snapshot_ids": [str(latest_account.id), str(previous.id)],
                    },
                )

        contents = await self.repository.contents_for_account(account.id)
        latest_views: list[int] = []
        baseline_cutoff = _utc(calculated_at) - timedelta(days=30)
        snapshots_by_content: dict[UUID, list[ContentSnapshot]] = {}
        for content in contents:
            snapshots = list(
                (
                    await self.session.scalars(
                        select(ContentSnapshot)
                        .where(ContentSnapshot.content_item_id == content.id)
                        .order_by(ContentSnapshot.captured_at.desc())
                    )
                ).all()
            )
            snapshots_by_content[content.id] = snapshots
            if (
                snapshots
                and snapshots[0].view_count is not None
                and content.published_at is not None
                and _utc(content.published_at) >= baseline_cutoff
            ):
                latest_views.append(snapshots[0].view_count)
        baseline = float(median(latest_views)) if latest_views else None
        # Latest known account follower count, used for the play/follower ratio.
        # This is a snapshot proxy for follower-at-publish (we persist only the
        # most recent account snapshot), documented in the metric metadata.
        follower_ref = account_snapshots[0].follower_count if account_snapshots else None
        calculations: list[dict[str, Any]] = []
        for content in contents:
            snapshots = snapshots_by_content[content.id]
            if not snapshots:
                continue
            latest = snapshots[0]
            views = latest.view_count
            observed_engagement = {
                "likes": latest.like_count,
                "comments": latest.comment_count,
                "shares": latest.share_count,
            }
            included_engagement = {
                key: value for key, value in observed_engagement.items() if value is not None
            }
            engagement = safe_rate(
                sum(included_engagement.values()) if included_engagement else None,
                views,
            )
            share_rate = safe_rate(latest.share_count, views)
            favorite_rate = safe_rate(latest.favorite_count, views)
            growth: dict[int, tuple[float, float, ContentSnapshot]] = {}
            for hours in (1, 6, 24):
                prior = self._snapshot_for_window(snapshots, latest.captured_at, hours)
                if views is not None and prior is not None and prior.view_count is not None:
                    elapsed_hours = self._elapsed_hours(latest.captured_at, prior.captured_at)
                    delta = float(views - prior.view_count)
                    growth[hours] = (delta, elapsed_hours, prior)
                    self._metric(
                        account,
                        content.id,
                        "content_item",
                        f"view_growth_{hours}h",
                        f"{hours}h",
                        delta,
                        calculated_at,
                        metadata={
                            "quality": "derived",
                            "formula": "latest_view_count - prior_view_count",
                            "actual_window_hours": round(elapsed_hours, 3),
                            "input_snapshot_ids": [str(latest.id), str(prior.id)],
                        },
                    )
            velocity = None
            velocity_source_hours = None
            if 1 in growth:
                velocity = growth[1][0] / growth[1][1]
                velocity_source_hours = growth[1][1]
            elif 6 in growth:
                velocity = growth[6][0] / growth[6][1]
                velocity_source_hours = growth[6][1]
            short_velocity = growth[1][0] / growth[1][1] if 1 in growth else None
            long_velocity = growth[6][0] / growth[6][1] if 6 in growth else None
            acceleration = (
                (short_velocity - long_velocity) / 5
                if short_velocity is not None and long_velocity is not None
                else None
            )
            baseline_ratio = float(views) / baseline if views is not None and baseline else None
            values: dict[str, tuple[str, float | None, dict[str, Any]]] = {
                "engagement_rate": (
                    "current",
                    engagement,
                    {
                        "quality": (
                            "derived"
                            if len(included_engagement) == len(observed_engagement)
                            else "partial"
                        ),
                        "formula": "sum(available interactions) / view_count",
                        "included_components": sorted(included_engagement),
                        "missing_components": sorted(
                            set(observed_engagement) - set(included_engagement)
                        ),
                    },
                ),
                "share_rate": (
                    "current",
                    share_rate,
                    {"quality": "derived", "formula": "share_count / view_count"},
                ),
                "favorite_rate": (
                    "current",
                    favorite_rate,
                    {"quality": "derived", "formula": "favorite_count / view_count"},
                ),
            }
            if velocity is not None:
                values["view_velocity"] = (
                    "1h",
                    velocity,
                    {
                        "quality": "derived",
                        "formula": "view_delta / actual_elapsed_hours",
                        "actual_window_hours": round(velocity_source_hours or 0, 3),
                    },
                )
            if acceleration is not None:
                values["view_acceleration"] = (
                    "6h",
                    acceleration,
                    {
                        "quality": "derived",
                        "formula": "(1h_velocity - 6h_velocity) / 5h",
                    },
                )
            if baseline is not None:
                values["median_views_30d"] = (
                    "30d",
                    baseline,
                    {
                        "quality": "derived",
                        "formula": "median(latest views of content published in trailing 30d)",
                        "sample_size": len(latest_views),
                    },
                )
            if baseline_ratio is not None:
                values["account_baseline_ratio"] = (
                    "30d",
                    baseline_ratio,
                    {"quality": "derived", "formula": "view_count / account_30d_median_views"},
                )
            # Relative metric: how many views per follower. A value > 1 means the
            # content reached well beyond the account's follower base.
            if follower_ref is not None and views is not None:
                values["play_follower_ratio"] = (
                    "current",
                    safe_rate(views, follower_ref),
                    {
                        "quality": "derived",
                        "formula": "view_count / account_follower_count (latest known snapshot)",
                    },
                )
            for key, (window, value, metadata) in values.items():
                if value is None:
                    continue
                self._metric(
                    account,
                    content.id,
                    "content_item",
                    key,
                    window,
                    value,
                    calculated_at,
                    metadata=metadata,
                )
            calculations.append(
                {
                    "content": content,
                    "engagement": engagement,
                    "share_rate": share_rate,
                    "velocity": velocity,
                    "baseline_ratio": baseline_ratio,
                }
            )

        engagement_values = [item["engagement"] for item in calculations]
        share_values = [item["share_rate"] for item in calculations]
        velocity_values = [item["velocity"] for item in calculations]
        for item in calculations:
            components = {
                "account_baseline": (ratio_score(item["baseline_ratio"]), 0.4),
                "view_velocity": (percentile_rank(item["velocity"], velocity_values), 0.3),
                "engagement": (percentile_rank(item["engagement"], engagement_values), 0.2),
                "share": (percentile_rank(item["share_rate"], share_values), 0.1),
            }
            raw_viral_score, applied_weights = weighted_available_score(
                components, minimum_components=2
            )
            if raw_viral_score is None:
                continue
            available_count = sum(value is not None for value, _weight in components.values())
            confidence = sample_confidence(len(calculations)) * (available_count / 4)
            viral_score = round(50 + (raw_viral_score - 50) * confidence, 2)
            self._metric(
                account,
                item["content"].id,
                "content_item",
                "viral_score",
                "current",
                viral_score,
                calculated_at,
                metadata={
                    "quality": "derived",
                    "formula": "weighted account-relative performance components",
                    "formula_version": "content-opportunity-v3",
                    "raw_score_before_confidence": raw_viral_score,
                    "confidence_adjusted": True,
                    "component_scores": {
                        key: value for key, (value, _weight) in components.items()
                    },
                    "applied_weights": applied_weights,
                    "sample_size": len(calculations),
                    "confidence_score": round(confidence, 4),
                    "missing_components": [
                        key for key, (value, _weight) in components.items() if value is None
                    ],
                    "incomplete_components": [
                        key for key, (value, _weight) in components.items() if value is None
                    ],
                },
            )

    @staticmethod
    def _snapshot_for_window(
        snapshots: list[SnapshotT],
        latest_at: datetime,
        window_hours: int,
    ) -> SnapshotT | None:
        """Choose the closest earlier observation inside a truthful time tolerance."""
        latest_utc = _utc(latest_at)
        minimum = window_hours * 0.75
        maximum = window_hours * 1.5
        candidates = [
            item
            for item in snapshots[1:]
            if minimum <= (latest_utc - _utc(item.captured_at)).total_seconds() / 3600 <= maximum
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: abs(
                (latest_utc - _utc(item.captured_at)).total_seconds() / 3600 - window_hours
            ),
        )

    @staticmethod
    def _elapsed_hours(latest_at: datetime, prior_at: datetime) -> float:
        return max(0.000001, (_utc(latest_at) - _utc(prior_at)).total_seconds() / 3600)

    def _metric(
        self,
        account: Account,
        entity_id: UUID,
        entity_type: str,
        key: str,
        window: str,
        value: int | float,
        calculated_at: datetime,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.session.add(
            DerivedMetric(
                id=uuid4(),
                workspace_id=account.workspace_id,
                entity_type=entity_type,
                entity_id=entity_id,
                metric_key=key,
                window=window,
                value=Decimal(str(value)),
                calculated_at=calculated_at,
                metadata_json={
                    "algorithm_version": "monitoring-derived-v3",
                    "source": "calculated_not_platform_metric",
                    **dict(metadata or {}),
                },
            )
        )


def enqueue_platform_sync(run_id: UUID) -> None:
    from app.tasks.monitoring import sync_account

    sync_account.delay(str(run_id))


async def cancel_sync_run(session: AsyncSession, workspace_id: UUID, run_id: UUID) -> SyncRunRead:
    """Mark a queued/running sync run as cancelled and release its account lock.

    Idempotent for runs that are already in a terminal state. Best-effort revokes
    the Celery task so a queued-but-not-started run is not picked up by a worker.
    The authoritative signal is the persisted ``cancelled`` status plus the lock
    release; workers also early-exit when they observe the cancelled state.
    """
    run = await session.get(SyncRun, run_id)
    if run is None or run.workspace_id != workspace_id:
        raise SyncNotFoundError("sync run was not found")
    if run.status not in ("queued", "running"):
        return SyncRunRead.model_validate(run)
    now = datetime.now(UTC)
    run.status = "cancelled"
    run.finished_at = now
    run.progress_stage = "cancelled"
    run.progress_message = "任务已被用户终止"
    run.lock_key = None
    account = await SyncRepository(session).get_account_unscoped(run.target_id)
    if account is not None:
        account.sync_status = "cancelled"
        account.last_sync_error_code = None
        account.last_sync_error_message = None
    await session.commit()
    try:
        from app.tasks.monitoring import sync_account

        sync_account.revoke(str(run.id), terminate=True)
    except Exception:  # pragma: no cover - broker may be unavailable in dev/test
        logger.warning("could not revoke celery task for cancelled sync run %s", run.id)
    return SyncRunRead.model_validate(run)


SYNC_LOG_TAIL_KEY = "sync_log_tail"


class _SyncLogSink:
    """Collects live adapter progress lines into a rolling tail on the sync run.

    Every platform feeds this sink, not just yt-dlp: the yt-dlp path streams raw
    stderr lines, while the browser adapters push short human-readable stage
    lines. The tail is stored in ``run.metadata_json[SYNC_LOG_TAIL_KEY]``
    (bounded to the last ``max_lines`` entries, with consecutive duplicates
    collapsed) so the frontend can render it as a live, scrolling log beneath
    the progress message. Each push writes the tail straight into the run's
    in-memory metadata; the surrounding sync loop's periodic ``session.commit()``
    calls persist it, so the log grows as the sync progresses.

    The instance is deliberately **callable**: adapters receive it typed as
    ``Callable[[str], None]`` (``progress_callback``), so ``sink("line")`` must
    work. ``push`` is kept as an explicit alias for readability at call sites.
    """

    def __init__(self, run: "SyncRun", max_lines: int = 80) -> None:
        self._run = run
        self._max = max_lines
        self._lines: list[str] = []
        self._last_text: str | None = None

    def push(self, text: str) -> None:
        text = (text or "").replace("\r", " ").replace("\n", " ").strip()
        if not text:
            return
        if text == self._last_text:
            # yt-dlp repeats the same progress bar line; keep the log readable.
            return
        self._last_text = text
        self._lines.append(text)
        if len(self._lines) > self._max:
            self._lines = self._lines[-self._max :]
        meta = dict(self._run.metadata_json or {})
        meta[SYNC_LOG_TAIL_KEY] = list(self._lines)
        self._run.metadata_json = meta

    # Adapters call the sink directly (``progress_callback(line)``). Without
    # this, passing the sink as ``progress_sink`` raises
    # ``TypeError: '_SyncLogSink' object is not callable`` and aborts the whole
    # sync run — which is exactly what happened in production.
    def __call__(self, text: str) -> None:
        self.push(text)

    def flush(self) -> None:
        # ``push`` already persists into run.metadata_json on every call; this is
        # a no-op kept for explicit finalization points.
        pass
