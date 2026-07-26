from fastapi.testclient import TestClient

from .conftest import TEST_PASSWORD, TEST_PLATFORM_ID


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def test_manual_topic_crud_and_operations_audit(client: TestClient) -> None:
    csrf = authenticate(client)
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/topics",
        headers=headers,
        json={
            "source_type": "manual",
            "title": "真实来源待核实的比赛选题",
            "summary": "这是用户录入的选题，不是平台数据。",
            "priority": 75,
            "metadata": {},
        },
    )
    assert created.status_code == 201
    topic = created.json()
    assert topic["metadata"]["source_kind"] == "imported"

    listed = client.get("/api/v1/topics?status=inbox")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    updated = client.patch(
        f"/api/v1/topics/{topic['id']}",
        headers=headers,
        json={"status": "in_progress"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_progress"

    audits = client.get("/api/v1/operations/audits?action=topic")
    assert audits.status_code == 200
    assert {item["action"] for item in audits.json()["items"]} >= {
        "topic.created",
        "topic.updated",
    }

    tasks = client.get("/api/v1/operations/tasks")
    assert tasks.status_code == 200
    assert tasks.json()["items"] == []


def test_topic_batch_rejects_unknown_or_cross_workspace_sources(client: TestClient) -> None:
    csrf = authenticate(client)
    response = client.post(
        "/api/v1/topics/batch",
        headers={"X-CSRF-Token": csrf},
        json={
            "source_type": "content",
            "source_ids": ["00000000-0000-0000-0000-000000000001"],
        },
    )
    assert response.status_code == 404
    assert response.json()["code"] == "topic_source_not_found"


def test_automation_create_topic_action_writes_topic_entity(client: TestClient) -> None:
    csrf = authenticate(client)
    headers = {"X-CSRF-Token": csrf}
    account_response = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={
            "platform_id": str(TEST_PLATFORM_ID),
            "external_id": "automation-topic-account",
            "display_name": "自动化选题测试账号",
            "sync_interval_seconds": 3600,
            "metadata": {},
        },
    )
    assert account_response.status_code == 201
    account_id = account_response.json()["id"]

    rule_response = client.post(
        "/api/v1/automations",
        headers=headers,
        json={
            "name": "账号增长创建选题",
            "entity_type": "account",
            "condition_tree": {
                "field": "follower_count",
                "operator": "gte",
                "value": 10,
            },
            "cooldown_seconds": 0,
            "deduplication_window": 0,
            "enabled": True,
            "actions": [
                {
                    "action_type": "create_topic",
                    "config": {},
                    "sort_order": 0,
                    "enabled": True,
                }
            ],
        },
    )
    assert rule_response.status_code == 201

    evaluated = client.post(
        "/api/v1/automations/evaluate",
        headers=headers,
        json={
            "entity_type": "account",
            "entity_id": account_id,
            "facts": {"follower_count": 20},
            "previous": {"follower_count": 5},
            "event_key": "account-topic-test-1",
            "source_kind": "imported",
        },
    )
    assert evaluated.status_code == 200
    assert evaluated.json()[0]["matched"] is True

    topics = client.get("/api/v1/topics?source_type=manual")
    assert topics.status_code == 200
    saved = topics.json()["items"]
    assert len(saved) == 1
    assert saved[0]["source_id"] == account_id
    assert saved[0]["metadata"]["source_entity_type"] == "account"
