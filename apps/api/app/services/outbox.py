from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.operations import DeadLetterEvent, OutboxEvent, OutboxEventAttempt
from app.services.error_detail import business_hint_for

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

_MAX_ATTEMPTS = 5
_MAX_BACKOFF_SECONDS = 300
_CONSUMER_NAME = "internal"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class OutboxError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class OutboxNotFound(OutboxError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="outbox_not_found", status_code=404)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class OutboxService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # 1. publish
    # ------------------------------------------------------------------

    async def publish(
        self,
        workspace_id: UUID,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        payload: dict[str, Any],
        trace_id: UUID,
        correlation_id: UUID,
        *,
        causation_id: UUID | None = None,
    ) -> OutboxEvent:
        """Create an ``OutboxEvent`` record within the caller's transaction.

        The caller is responsible for committing the session so that the
        outbox row is persisted atomically with the business data that
        triggered the event.
        """
        now = datetime.now(UTC)
        event = OutboxEvent(
            id=uuid4(),
            workspace_id=workspace_id,
            event_id=uuid4(),
            event_type=event_type,
            schema_version=1,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload_json=payload,
            occurred_at=now,
            trace_id=trace_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            publish_status="pending",
            attempts=0,
            next_attempt_at=now,
            published_at=None,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    # ------------------------------------------------------------------
    # 2. consume_pending
    # ------------------------------------------------------------------

    async def consume_pending(self, *, limit: int = 50) -> list[OutboxEvent]:
        """Select and process pending outbox events whose retry time has passed.

        Returns the list of events that were processed (both successes and
        those that failed but were updated).
        """
        now = datetime.now(UTC)

        events = (
            await self.session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.publish_status == "pending",
                    OutboxEvent.next_attempt_at <= now,
                )
                .order_by(OutboxEvent.next_attempt_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()

        processed: list[OutboxEvent] = []

        for event in events:
            attempt_started = datetime.now(UTC)
            attempt_number = event.attempts + 1
            attempt = OutboxEventAttempt(
                id=uuid4(),
                outbox_event_id=event.id,
                attempt_number=attempt_number,
                status="failed",
                consumer=_CONSUMER_NAME,
                started_at=attempt_started,
                finished_at=None,
                error_code=None,
                error_detail_safe=None,
                duration_ms=None,
            )
            self.session.add(attempt)

            try:
                await self._dispatch_event(event)
            except Exception as exc:
                await self._handle_dispatch_failure(event, attempt, attempt_started, exc)
                processed.append(event)
                continue

            # Success path
            finished = datetime.now(UTC)
            attempt.status = "success"
            attempt.finished_at = finished
            attempt.duration_ms = int((finished - attempt_started).total_seconds() * 1000)

            event.attempts = attempt_number
            event.publish_status = "published"
            event.published_at = finished

            processed.append(event)

        if processed:
            await self.session.commit()

        return processed

    # ------------------------------------------------------------------
    # 3. list_dead_letters
    # ------------------------------------------------------------------

    async def list_dead_letters(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[DeadLetterEvent], int]:
        """Return a paginated list of dead-letter events for a workspace."""
        filters = [DeadLetterEvent.workspace_id == workspace_id]
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(DeadLetterEvent).where(*filters)
            )
            or 0
        )
        items = (
            await self.session.scalars(
                select(DeadLetterEvent)
                .where(*filters)
                .order_by(DeadLetterEvent.dead_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(items), total

    # ------------------------------------------------------------------
    # 4. replay_dead_letter
    # ------------------------------------------------------------------

    async def replay_dead_letter(self, workspace_id: UUID, dead_letter_id: UUID) -> OutboxEvent:
        """Reset a dead-lettered event back to ``pending`` for retry."""
        dead_letter = await self.session.scalar(
            select(DeadLetterEvent).where(
                DeadLetterEvent.id == dead_letter_id,
                DeadLetterEvent.workspace_id == workspace_id,
            )
        )
        if dead_letter is None:
            raise OutboxNotFound("死信事件不存在")

        if dead_letter.replay_status == "discarded":
            raise OutboxError(
                "已丢弃的死信事件不能重放",
                code="dead_letter_discarded",
                status_code=409,
            )
        if dead_letter.replay_status in {"replaying", "replayed"}:
            raise OutboxError(
                "死信事件已在重放中或已重放完成",
                code="dead_letter_already_replayed",
                status_code=409,
            )

        event = await self.session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.id == dead_letter.outbox_event_id,
                OutboxEvent.workspace_id == workspace_id,
            )
        )
        if event is None:
            raise OutboxNotFound("关联的 Outbox 事件不存在")

        now = datetime.now(UTC)
        event.publish_status = "pending"
        event.attempts = 0
        event.published_at = None
        event.next_attempt_at = now

        dead_letter.replay_status = "replaying"
        dead_letter.replayed_at = now

        await self.session.commit()
        await self.session.refresh(event)
        return event

    # ------------------------------------------------------------------
    # 5. discard_dead_letter
    # ------------------------------------------------------------------

    async def discard_dead_letter(
        self, workspace_id: UUID, dead_letter_id: UUID
    ) -> DeadLetterEvent:
        """Mark a dead-letter event as permanently discarded."""
        dead_letter = await self.session.scalar(
            select(DeadLetterEvent).where(
                DeadLetterEvent.id == dead_letter_id,
                DeadLetterEvent.workspace_id == workspace_id,
            )
        )
        if dead_letter is None:
            raise OutboxNotFound("死信事件不存在")

        if dead_letter.replay_status == "discarded":
            raise OutboxError(
                "死信事件已被丢弃",
                code="dead_letter_already_discarded",
                status_code=409,
            )

        dead_letter.replay_status = "discarded"

        # Also mark the source outbox event so it is never picked up again.
        await self.session.execute(
            update(OutboxEvent)
            .where(
                OutboxEvent.id == dead_letter.outbox_event_id,
                OutboxEvent.workspace_id == workspace_id,
            )
            .values(publish_status="discarded")
        )

        await self.session.commit()
        await self.session.refresh(dead_letter)
        return dead_letter

    # ------------------------------------------------------------------
    # 6. list_attempts
    # ------------------------------------------------------------------

    async def list_attempts(
        self, workspace_id: UUID, outbox_event_id: UUID
    ) -> list[OutboxEventAttempt]:
        """Return all delivery attempts for a given outbox event, oldest first."""
        event_exists = await self.session.scalar(
            select(OutboxEvent.id).where(
                OutboxEvent.id == outbox_event_id,
                OutboxEvent.workspace_id == workspace_id,
            )
        )
        if event_exists is None:
            raise OutboxNotFound("Outbox event was not found")
        items = (
            await self.session.scalars(
                select(OutboxEventAttempt)
                .where(OutboxEventAttempt.outbox_event_id == outbox_event_id)
                .order_by(OutboxEventAttempt.attempt_number)
            )
        ).all()
        return list(items)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _dispatch_event(self, event: OutboxEvent) -> None:
        """Publish the outbox event to Redis Pub/Sub for downstream consumers.

        A publish failure must propagate to the retry/dead-letter path. Marking
        the row as published without delivering it would silently lose events.
        """
        logger.debug(
            "Dispatching outbox event %s (type=%s, aggregate=%s:%s)",
            event.id,
            event.event_type,
            event.aggregate_type,
            event.aggregate_id,
        )

        settings = get_settings()
        redis_client = aioredis.from_url(  # type: ignore[no-untyped-call]
            settings.redis_url, decode_responses=True
        )
        try:
            channel = f"sio:outbox:{event.event_type}"
            payload = json.dumps(
                {
                    "id": str(event.id),
                    "workspace_id": str(event.workspace_id),
                    "event_type": event.event_type,
                    "aggregate_type": event.aggregate_type,
                    "aggregate_id": str(event.aggregate_id),
                    "payload": event.payload_json,
                },
                default=str,
            )
            subscribers = await redis_client.publish(channel, payload)
            logger.debug(
                "Published outbox event to %s (%d subscribers)",
                channel,
                subscribers,
            )
        finally:
            await redis_client.aclose()

    async def _handle_dispatch_failure(
        self,
        event: OutboxEvent,
        attempt: OutboxEventAttempt,
        attempt_started: datetime,
        exc: Exception,
    ) -> None:
        """Update the event and attempt records after a dispatch failure."""
        finished = datetime.now(UTC)
        error_code = getattr(exc, "code", "dispatch_failed")
        error_detail = str(exc)[:1000]

        attempt.status = "failed"
        attempt.finished_at = finished
        attempt.duration_ms = int((finished - attempt_started).total_seconds() * 1000)
        attempt.error_code = str(error_code)
        attempt.error_detail_safe = error_detail
        attempt.error_hint = business_hint_for(error_code, category="outbox")

        event.attempts = attempt.attempt_number

        if event.attempts >= _MAX_ATTEMPTS:
            # Move to dead-letter table.
            now = datetime.now(UTC)
            dead_letter = DeadLetterEvent(
                id=uuid4(),
                outbox_event_id=event.id,
                workspace_id=event.workspace_id,
                event_type=event.event_type,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                payload_json=event.payload_json,
                original_occurred_at=event.occurred_at,
                total_attempts=event.attempts,
                last_error_code=str(error_code),
                last_error_detail=error_detail,
                last_error_hint=business_hint_for(error_code, category="outbox"),
                dead_at=now,
                replay_status="pending",
                replayed_at=None,
            )
            self.session.add(dead_letter)
            event.publish_status = "dead_letter"

            logger.warning(
                "Outbox event %s moved to dead-letter after %d attempts: %s",
                event.id,
                event.attempts,
                error_detail,
            )
        else:
            # Exponential backoff: min(2^attempts, 300) seconds.
            backoff_seconds = min(2**event.attempts, _MAX_BACKOFF_SECONDS)
            event.next_attempt_at = finished + timedelta(seconds=backoff_seconds)

            logger.info(
                "Outbox event %s attempt %d failed, next retry in %ds: %s",
                event.id,
                event.attempts,
                backoff_seconds,
                error_detail,
            )
