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
