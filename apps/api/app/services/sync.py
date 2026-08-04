import logging
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.platforms.base import (
    AdapterCallContext,
    AdapterConfigurationError,
    AdapterContractError,
    PlatformAdapter,
    PlatformAdapterError,
    PlatformContentData,
    PlatformMetricsData,
    parse_compact_count,
)
from app.core.config import Settings
from app.models.monitoring import (
    Account,
    AccountSnapshot,
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





def _as_int(value: int | float | None) -> int | None:
    return int(value) if value is not None else None


def _as_decimal(value: int | float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


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
        mode, _ = await PlatformCredentialService(
            self.session, self.settings
        ).resolve(workspace_id, account.platform.key)
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
                    select(SyncRun)
                    .where(SyncRun.status.in_(("queued", "running")))
                    .limit(500)
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
                    SyncRun.status.in_(
                        ("success", "degraded", "error", "cancelled", "skipped")
                    ),
                )
                .order_by(
                    SyncRun.started_at.desc().nullslast(),
                    SyncRun.queued_at.desc(),
                )
                .limit(1)
            )
            newer_anchor = (
                _utc(newer.started_at or newer.queued_at) if newer is not None else None
            )
            if newer is None or (
                anchor is not None
                and newer_anchor is not None
                and newer_anchor < anchor
            ):
                account.sync_status = "error"
                account.last_sync_error_code = run.error_code
                account.last_sync_error_message = run.error_message
                account.next_sync_at = now


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
        self.session.add(
            SyncRunEvent(
                id=uuid4(),
                workspace_id=run.workspace_id,
                sync_run_id=run.id,
                sequence=self._event_seq,
                event_type=event_type,
                level=level,
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
        mode, config = await PlatformCredentialService(
            self.session, self.settings
        ).resolve(account.workspace_id, account.platform.key)
        if mode == "unconfigured" and account.platform.key in MANAGED_PLATFORM_KEYS:
            raise AdapterConfigurationError(
                "platform acquisition policy is no longer configured"
            )
        # Merge the workspace's global fetch policy (yt-dlp window / passthrough
        # args, plus the works cap) on top of the platform-resolved credential
        # config. The global ``sync_settings`` wins on conflict so operators tune
        # behaviour once, centrally, instead of per account.
        sync_cfg = await self.repository.get_sync_settings_config(account.workspace_id)
        yt_cfg = dict(sync_cfg.get("yt_dlp") or {})
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
                    result[key], value  # type: ignore[arg-type]
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
        self._set_progress(run, 5, "validating", "正在验证采集方式与凭证")
        await self.session.commit()
        if await self._aborted(run):
            return
        attempt_started = datetime.now(UTC)
        attempt_number = int(run.metadata_json.get("retry_count", 0)) + 1

        try:
            ctx = AdapterCallContext(
                config=await self._config_for(account),
                observed_at=now,
                request_id=run.request_id,
            )
            await adapter.validate_config(ctx.config)
            self._set_progress(run, 12, "account_profile", "正在同步账号资料与公开指标")
            await self.session.commit()
            if await self._aborted(run):
                return
            created, updated, metrics_degraded = await self._sync_account(
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
            if (metrics_degraded or content_analytics_failed or metrics_calc_failed)
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
        # Always clear any stale error surface on a successful run. A prior
        # stale-recovery pass can stamp a "worker crashed / timeout" hint on a run
        # that was still progressing and later finished fine; leaving it would
        # make a succeeded sync display a misleading failure message.
        run.error_hint = None
        run.error_detail = None
        run.lock_key = None
        run.progress_percent = 100
        run.progress_stage = "completed"
        if self._budget_exceeded:
            run.progress_message = (
                f"同步已按时间预算截断，已入库 {run.items_processed} 条；"
                "可在账号设置中调大抓取上限或再次手动同步以获取更多历史。"
            )
            run.metadata_json = {
                **run.metadata_json,
                "truncated_by_budget": True,
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
            "content_analytics_failed": content_analytics_failed,
            "metrics_calc_failed": metrics_calc_failed,
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
        account.next_sync_at = finished + timedelta(seconds=interval)
        if metrics_degraded:
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
                duration_ms=max(
                    0, int((finished_at - started_at).total_seconds() * 1000)
                ),
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
    ) -> tuple[int, int, bool]:
        data = await adapter.resolve_account(ctx, account.external_id)
        if not data.external_id.strip() or not data.display_name.strip():
            raise AdapterContractError("account response is missing its identity")
        if self._text_is_error_page(data.display_name):
            raise AdapterContractError("account response contains an error-page title")
        if data.profile_url and not data.profile_url.lower().startswith(("https://", "http://")):
            raise AdapterContractError("account response contains an invalid profile URL")
        self._set_progress(run, 18, "account_profile", "账号资料已获取，正在读取公开指标")
        await self.session.commit()
        metrics = await adapter.fetch_account_analytics(ctx, data.external_id)
        original_locator = account.external_id
        account.external_id = data.external_id
        account.username = data.username
        account.display_name = data.display_name
        account.profile_url = data.profile_url
        if data.avatar_url:
            account.avatar_url = data.avatar_url
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
        return 1, 1, metrics_degraded

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
        content_analytics_failed = False
        # ── Sync decomposition (anti-bot / 风控 posture) ──────────────────────
        # Account data (profile + analytics) lives in ``_sync_account`` and uses
        # the yt-dlp channel JSON with a *browser* fallback for TikTok/Douyin
        # (platforms yt-dlp cannot read). Content (作品列表 + 详情) lives here and
        # is fetched **single-threaded**: one yt-dlp subprocess per page
        # (``list_contents``) and a strictly sequential per-item upsert loop —
        # ``fetch_content_analytics`` reads the in-memory per-page cache and
        # launches NO extra yt-dlp subprocesses. We deliberately avoid any
        # asyncio.gather / fan-out of yt-dlp calls, because concurrent requests
        # are precisely what trips platform rate-limit / 风控 heuristics. Retry
        # resilience comes from yt-dlp's built-in ``--retries`` (default 10,
        # configurable) plus the run-level Celery retry, never a custom loop.
        # Workspace-wide fetch policy (set on the Settings → Sync tab). The cap
        # bounds how many works a single sync ingests; ``skip_existing`` decides
        # whether already-known works are refreshed or left untouched.
        sync_cfg = await self.repository.get_sync_settings_config(account.workspace_id)
        max_contents = sync_cfg.get("max_contents")
        skip_existing = bool(sync_cfg.get("skip_existing", True))
        self._emit(
            run,
            "stage",
            "info",
            "开始获取作品列表与指标",
            {"max_contents": max_contents, "skip_existing": skip_existing},
        )
        # Default behaviour is a full-catalogue fetch: we never shortcut by the
        # newest-known publish date. The yt-dlp date window (``dateafter`` /
        # ``datebefore``) from the global policy is applied by the adapter, so
        # narrowing the range is done through settings, not incremental state.
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
            if max_contents is not None:
                remaining = max_contents - (created + updated + skipped + failed)
                window = max(1, min(window, remaining))
            published_after = None
            # A failing page fetch must not abort the entire sync. If we have
            # already collected works, stop paging gracefully and finalise what
            # we have; only a first-page failure (nothing collected yet) is a
            # genuine, re-raisable outage that the caller handles as retry/error.
            try:
                page = await adapter.list_contents(
                    ctx,
                    account.external_id,
                    published_after=published_after,
                    cursor=cursor,
                    page_size=window,
                )
            except PlatformAdapterError as exc:
                if run.items_processed == 0:
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
                if run.items_processed == 0:
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
            batch_total = len(page.items)
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
            for data in page.items:
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
                        "rejected_item_count": int(
                            run.metadata_json.get("rejected_item_count", 0)
                        )
                        + 1,
                        "rejected_items": rejected,
                    }
                    continue
                # Count every listed work (including rejected ones) so the live
                # counter matches the per-page total, then drive a fine-grained
                # progress heartbeat every 25 works during the slow per-item
                # upsert/analytics phase.
                run.items_processed += 1
                page_processed += 1
                # A single work that fails to upsert must not abort the whole
                # sync. Record it, continue, and surface it in the tracklog.
                try:
                    content, was_created, was_skipped = await self._upsert_content(
                        account, data, skip_existing=skip_existing
                    )
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    logger.warning(
                        "sync_content_upsert_failed",
                        extra={
                            "event": "platform.sync.item_failed",
                            "sync_run_id": str(run.id),
                            "external_id": data.external_id,
                        },
                    )
                    self._emit(
                        run,
                        "item",
                        "error",
                        f"作品 {data.external_id} 入库失败：{exc}",
                        {
                            "external_id": data.external_id,
                            "title": (data.title or "")[:200],
                            "action": "failed",
                            "error": str(exc),
                        },
                    )
                    continue
                page_items.append(content)
                created += int(was_created)
                if was_skipped:
                    skipped += 1
                    page_skipped += 1
                else:
                    updated += int(not was_created)
                    action = "created" if was_created else "updated"
                    self._emit(
                        run,
                        "item",
                        "info",
                        f"作品 {data.external_id} {action}",
                        {
                            "external_id": data.external_id,
                            "title": (data.title or "")[:200],
                            "action": action,
                        },
                    )
                if page_processed % 25 == 0 or page_processed == batch_total:
                    self._set_progress(
                        run,
                        min(
                            30
                            + round(55 * (page_index + 0.5) / self.settings.sync_page_limit),
                            85,
                        ),
                        "content_metrics",
                        f"正在获取第 {run.items_processed} 条作品详情"
                        f"（本页 {page_processed}/{batch_total}，累计 {run.items_processed} 条）",
                    )
                    await self.session.commit()
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
            try:
                analytics = await adapter.fetch_content_analytics(
                    ctx, [item.external_id for item in page_items]
                )
                by_external_id = {item.external_id: item for item in page_items}
                for analytics_data in analytics:
                    matched_content = by_external_id.get(analytics_data.external_id)
                    if matched_content is not None and analytics_data.metrics:
                        self.session.add(
                            self._content_snapshot(matched_content.id, analytics_data)
                        )
                synthesized = self._synthesize_content_snapshots(
                    adapter, ctx, page_items, analytics
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
            await self.session.commit()
            if not page.next_cursor:
                break
            cursor = page.next_cursor
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
    def _view_count_from_metadata(meta: Mapping[str, Any] | None) -> int | None:
        """Recover a per-work view count captured by browser adapters.

        Browser adapters stash ``view_count`` (int) or ``view_text`` (e.g.
        '1.2M views') in ``ContentItem.metadata_json`` because their
        ``fetch_content_analytics`` cannot retrieve structured metrics. We
        surface that as a real ``ContentSnapshot.view_count`` so the UI shows
        "相关数据" instead of blanks.
        """
        if not meta:
            return None
        for key in ("view_count", "play_count"):
            vc = meta.get(key)
            if isinstance(vc, bool):
                continue
            if isinstance(vc, int) and not isinstance(vc, bool):
                return vc
            if isinstance(vc, float):
                return int(vc)
            if isinstance(vc, str) and vc.strip():
                parsed = parse_compact_count(vc)
                if parsed is not None:
                    return parsed
        vt = meta.get("view_text")
        if isinstance(vt, str) and vt.strip():
            return parse_compact_count(vt)
        return None

    def _synthesize_content_snapshots(
        self,
        adapter: PlatformAdapter,
        ctx: AdapterCallContext,
        page_items: list[ContentItem],
        analytics: Sequence[PlatformMetricsData],
    ) -> int:
        """Create a ContentSnapshot from adapter-captured view counts when the
        platform's ``fetch_content_analytics`` returned no structured metrics."""
        snapshotted = {a.external_id for a in analytics if a.metrics}
        made = 0
        for item in page_items:
            if item.external_id in snapshotted:
                continue
            vc = self._view_count_from_metadata(item.metadata_json)
            if vc is not None:
                self.session.add(
                    self._content_snapshot(
                        item.id,
                        PlatformMetricsData(
                            external_id=item.external_id,
                            captured_at=ctx.observed_at,
                            metrics={"view_count": vc},
                            source_kind="live",
                            provider=adapter.key,
                            fetched_at=ctx.observed_at,
                        ),
                    )
                )
                made += 1
        return made

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

    @staticmethod
    def _set_progress(run: SyncRun, percent: int, stage: str, message: str) -> None:
        run.progress_percent = min(100, max(run.progress_percent, percent))
        run.progress_stage = stage
        run.progress_message = message[:500]
        run.metadata_json = {
            **(run.metadata_json or {}),
            "heartbeat_at": datetime.now(UTC).isoformat(),
        }

    async def _upsert_content(
        self, account: Account, data: PlatformContentData, skip_existing: bool = False
    ) -> tuple[ContentItem, bool, bool]:
        content = await self.session.scalar(
            select(ContentItem).where(
                ContentItem.workspace_id == account.workspace_id,
                ContentItem.platform_id == account.platform_id,
                ContentItem.account_id == account.id,
                ContentItem.external_id == data.external_id,
            )
        )
        created = content is None
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
            # Dedup-on-scrape: the work already exists, so keep the operator's
            # stored editable fields (title / cover / canonical) and only bump
            # last_seen_at. A fresh metrics snapshot is still appended upstream,
            # so analytics stay current without clobbering edited data.
            content.last_seen_at = data.fetched_at
            skipped = True
        else:
            content.title = data.title
            content.description = data.description
            content.published_at = data.published_at
            content.duration_seconds = _as_decimal(data.duration_seconds)
            content.canonical_url = data.canonical_url
            if data.cover_url:
                content.cover_url = data.cover_url
            content.language = data.language
            content.status = data.status
            content.metadata_json = {**content.metadata_json, **dict(data.metadata)}
            content.last_seen_at = data.fetched_at
            content.source_kind = data.source_kind
            content.source_provider = data.provider
            content.fetched_at = data.fetched_at
            content.source_url = data.canonical_url
            content.media = dict(data.media) if data.media else None
            if data.tags:
                # union with existing to avoid clobbering manually added tags
                merged = list(dict.fromkeys([*content.tags, *data.tags]))
                content.tags = merged[:30]
        return content, created, skipped

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
            if minimum
            <= (latest_utc - _utc(item.captured_at)).total_seconds() / 3600
            <= maximum
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


async def cancel_sync_run(
    session: AsyncSession, workspace_id: UUID, run_id: UUID
) -> SyncRunRead:
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
        logger.warning(
            "could not revoke celery task for cancelled sync run %s", run.id
        )
    return SyncRunRead.model_validate(run)
