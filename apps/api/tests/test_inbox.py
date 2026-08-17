from uuid import uuid4

from fastapi.testclient import TestClient

from .conftest import TEST_PASSWORD


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
