import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_engine_and_session
from app.models.inbox_queue import InboxQueueState
from app.models.operations import SystemEvent
from app.models.workspace import Workspace
from app.services.inbox import InboxService

from .conftest import PG_ASYNC_URL, PG_SYNC_URL, TEST_PASSWORD, TEST_REDIS_URL


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def test_inbox_read_states_are_workspace_user_scoped_and_idempotent(
    client: TestClient,
) -> None:
    assert client.get("/api/v1/inbox/read-states").status_code == 401

    csrf = authenticate(client)
    task_key = f"task:{uuid4()}"
    notification_key = f"notification:{uuid4()}"

    empty = client.get(
        "/api/v1/inbox/read-states",
        params=[("item_key", task_key), ("item_key", notification_key)],
    )
    assert empty.status_code == 200
    assert empty.json() == []

    marked = client.post(
        "/api/v1/inbox/read-states",
        headers={"X-CSRF-Token": csrf},
        json={"item_key": task_key},
    )
    assert marked.status_code == 200
    assert marked.json()["item_key"] == task_key
    assert marked.json()["item_kind"] == "task"

    marked_again = client.post(
        "/api/v1/inbox/read-states",
        headers={"X-CSRF-Token": csrf},
        json={"item_key": task_key},
    )
    assert marked_again.status_code == 200
    assert marked_again.json()["item_key"] == task_key

    listed = client.get(
        "/api/v1/inbox/read-states",
        params=[("item_key", task_key), ("item_key", notification_key)],
    )
    assert listed.status_code == 200
    assert [item["item_key"] for item in listed.json()] == [task_key]

    bulk = client.post(
        "/api/v1/inbox/read-states/bulk",
        headers={"X-CSRF-Token": csrf},
        json={"item_keys": [task_key, notification_key, notification_key]},
    )
    assert bulk.status_code == 200
    assert {item["item_key"] for item in bulk.json()} == {task_key, notification_key}


def test_inbox_read_states_reject_malformed_item_keys(client: TestClient) -> None:
    csrf = authenticate(client)
    response = client.post(
        "/api/v1/inbox/read-states",
        headers={"X-CSRF-Token": csrf},
        json={"item_key": "editorial:invalid"},
    )
    assert response.status_code == 422


def test_inbox_adapters_accept_review_alert_and_dead_letter_keys(client: TestClient) -> None:
    csrf = authenticate(client)
    extended = client.get("/api/v1/inbox/items")
    assert extended.status_code == 200
    assert isinstance(extended.json(), list)

    comment_key = f"editorial_comment:{uuid4()}"
    marked = client.post(
        "/api/v1/inbox/read-states",
        headers={"X-CSRF-Token": csrf},
        json={"item_key": comment_key},
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["item_kind"] == "editorial_comment"

    queue = client.patch(
        f"/api/v1/inbox/queue-states/{comment_key}",
        headers={"X-CSRF-Token": csrf},
        json={"state": "in_progress"},
    )
    assert queue.status_code == 200, queue.text
    assert queue.json()["item_kind"] == "editorial_comment"


def test_inbox_queue_state_bulk_and_saved_view_are_workspace_scoped(
    client: TestClient,
) -> None:
    csrf = authenticate(client)
    task_key = f"task:{uuid4()}"
    notification_key = f"notification:{uuid4()}"

    updated = client.patch(
        f"/api/v1/inbox/queue-states/{task_key}",
        headers={"X-CSRF-Token": csrf},
        json={"state": "in_progress", "labels": ["高优先级", "热点"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["state"] == "in_progress"
    assert updated.json()["labels"] == ["高优先级", "热点"]

    bulk = client.patch(
        "/api/v1/inbox/queue-states/bulk",
        headers={"X-CSRF-Token": csrf},
        json={"item_keys": [task_key, notification_key], "state": "completed"},
    )
    assert bulk.status_code == 200, bulk.text
    assert {item["item_key"] for item in bulk.json()} == {task_key, notification_key}
    assert {item["state"] for item in bulk.json()} == {"completed"}

    states = client.get(
        "/api/v1/inbox/queue-states",
        params=[("item_key", task_key), ("item_key", notification_key)],
    )
    assert states.status_code == 200
    assert {item["item_key"] for item in states.json()} == {task_key, notification_key}

    created = client.post(
        "/api/v1/inbox/views",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "我的失败与热点",
            "filters": {"kind": "all", "status": "failed", "queue_state": "open"},
            "is_default": True,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["filters"]["queue_state"] == "open"

    duplicate = client.post(
        "/api/v1/inbox/views",
        headers={"X-CSRF-Token": csrf},
        json={"name": "我的失败与热点", "filters": {}},
    )
    assert duplicate.status_code == 422


def test_inbox_sla_summary_and_overdue_escalation_are_auditable(client: TestClient) -> None:
    csrf = authenticate(client)
    now = datetime.now(UTC)
    overdue_key = f"task:{uuid4()}"
    due_soon_key = f"notification:{uuid4()}"
    for item_key, due_at in (
        (overdue_key, now - timedelta(minutes=5)),
        (due_soon_key, now + timedelta(minutes=30)),
    ):
        response = client.patch(
            f"/api/v1/inbox/queue-states/{item_key}",
            headers={"X-CSRF-Token": csrf},
            json={"due_at": due_at.isoformat()},
        )
        assert response.status_code == 200, response.text

    summary = client.get("/api/v1/inbox/sla?window_minutes=60")
    assert summary.status_code == 200, summary.text
    assert summary.json()["overdue_count"] == 1
    assert summary.json()["due_soon_count"] == 1

    sync_engine = create_engine(PG_SYNC_URL)
    with Session(sync_engine) as session:
        workspace = session.scalar(select(Workspace).where(Workspace.slug == "test-workspace"))
        assert workspace is not None
        workspace_id = workspace.id
    sync_engine.dispose()

    async def sweep() -> dict[str, int]:
        settings = Settings(
            environment="test",
            database_url=PG_ASYNC_URL,
            redis_url=TEST_REDIS_URL,
            secret_key=SecretStr("test-only-inbox-secret"),
            session_cookie_secure=False,
            cors_origins=["http://testserver"],
        )
        engine, session_factory = create_engine_and_session(settings)
        try:
            async with session_factory() as session:
                return await InboxService(session).sweep_sla(workspace_id, now=now)
        finally:
            await engine.dispose()

    report = asyncio.run(sweep())
    assert report == {"scanned": 2, "escalated": 1, "cleared": 0}

    sync_engine = create_engine(PG_SYNC_URL)
    with Session(sync_engine) as session:
        state = session.scalar(
            select(InboxQueueState).where(
                InboxQueueState.workspace_id == workspace_id,
                InboxQueueState.item_id == UUID(overdue_key.split(":", 1)[1]),
            )
        )
        event = session.scalar(
            select(SystemEvent).where(
                SystemEvent.workspace_id == workspace_id,
                SystemEvent.event_type == "inbox.sla_overdue",
            )
        )
        assert state is not None
        assert "sla_overdue" in state.labels
        assert event is not None
    sync_engine.dispose()
