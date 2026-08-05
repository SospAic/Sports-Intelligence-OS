from __future__ import annotations

import os
import sys
import time
from typing import Any

import httpx


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("items", [])
    return value if isinstance(value, list) else []


def main() -> int:
    email = os.getenv("SIO_ACCEPTANCE_EMAIL") or os.getenv("SIO_BOOTSTRAP_ADMIN_EMAIL")
    password = os.getenv("SIO_ACCEPTANCE_PASSWORD") or os.getenv("SIO_BOOTSTRAP_ADMIN_PASSWORD")
    base_url = os.getenv("SIO_ACCEPTANCE_BASE_URL", "http://127.0.0.1:8000/api/v1")
    if not email or not password:
        print("FAIL  acceptance credentials are not configured", file=sys.stderr)
        return 2

    with httpx.Client(base_url=base_url, timeout=20) as client:
        login = client.post("/auth/login", json={"email": email, "password": password})
        login.raise_for_status()
        csrf = str(login.json()["csrf_token"])
        current = client.get("/me")
        current.raise_for_status()
        memberships = current.json().get("memberships", [])
        if not memberships:
            print("FAIL  acceptance user has no workspace", file=sys.stderr)
            return 1
        workspace_id = str(memberships[0]["workspace_id"])
        read_headers = {"X-Workspace-Id": workspace_id}
        write_headers = {**read_headers, "X-CSRF-Token": csrf}

        sources_response = client.get("/news/sources?page=1&page_size=100", headers=read_headers)
        sources_response.raise_for_status()
        sources = [
            item
            for item in _items(sources_response.json())
            if item.get("enabled") and item.get("source_type") in {"rss", "atom", "json"}
        ]
        source_runs: dict[str, tuple[str, str]] = {}
        for source in sources:
            response = client.post(
                f"/news/sources/{source['id']}/sync",
                headers=write_headers,
                json={},
            )
            if response.status_code == 202:
                run = response.json()
                source_runs[str(source["id"])] = (str(source["name"]), str(run["id"]))
            else:
                print(f"WARN  news sync queue {source['name']}: HTTP {response.status_code}")

        accounts_response = client.get("/accounts?page=1&page_size=100", headers=read_headers)
        accounts_response.raise_for_status()
        queued_accounts = 0
        for account in _items(accounts_response.json()):
            if not account.get("is_active") or account.get("source_kind") != "live":
                continue
            response = client.post(
                f"/accounts/{account['id']}/sync",
                headers=write_headers,
                json={},
            )
            if response.status_code == 202:
                queued_accounts += 1
            else:
                print(
                    f"WARN  account sync queue {account['display_name']}: "
                    f"HTTP {response.status_code}"
                )

        trend_response = client.post("/trends/collect", headers=write_headers, json={})
        trend_response.raise_for_status()

        terminal: dict[str, dict[str, Any]] = {}
        deadline = time.monotonic() + 120
        while source_runs and time.monotonic() < deadline:
            for source_id, (_name, run_id) in source_runs.items():
                response = client.get(
                    f"/news/sources/{source_id}/sync-runs?page=1&page_size=20",
                    headers=read_headers,
                )
                response.raise_for_status()
                run = next(
                    (item for item in _items(response.json()) if str(item["id"]) == run_id),
                    None,
                )
                if run and run.get("status") in {"success", "error", "skipped"}:
                    terminal[run_id] = run
            if len(terminal) == len(source_runs):
                break
            time.sleep(2)

        # Let the independently queued trend and account jobs reach the worker.
        time.sleep(5)
        checks = {
            "accounts": "/accounts?page=1&page_size=100",
            "contents": "/contents?page=1&page_size=100",
            "articles": "/news/articles?page=1&page_size=100",
            "events": "/news/events?page=1&page_size=100",
            "trend_dashboard": "/trends/dashboard",
            "trend_topics": "/trends/topics?page=1&page_size=100",
            "trend_videos": "/trends/videos?page=1&page_size=100",
            "dashboard": "/dashboard/stats",
            "search": "/search?q=NBA&page=1&page_size=20",
            "credentials": "/settings/platform-credentials",
            "dead_letters": "/outbox/dead-letters?page=1&page_size=20",
            "external_calls": "/external-call-attempts?page=1&page_size=20",
            "templates": "/notification-templates?page=1&page_size=20",
        }
        payloads: dict[str, dict[str, Any]] = {}
        for label, path in checks.items():
            response = client.get(path, headers=read_headers)
            response.raise_for_status()
            payloads[label] = response.json()

        refresh = client.post("/dashboard/stats/refresh", headers=write_headers, json={})
        refresh.raise_for_status()

        successful_sources = [run for run in terminal.values() if run.get("status") == "success"]
        failed_sources = [run for run in terminal.values() if run.get("status") == "error"]
        live_articles = sum(
            item.get("source_kind") == "live" for item in _items(payloads["articles"])
        )
        live_trend_videos = sum(
            item.get("metadata", {}).get("source_kind") == "live"
            for item in _items(payloads["trend_videos"])
        )
        print(f"PASS  authenticated API checks: {len(checks)}")
        print(f"PASS  account sync jobs queued: {queued_accounts}")
        print(
            "PASS  real news syncs: "
            f"{len(successful_sources)} success, {len(failed_sources)} error, "
            f"{len(source_runs) - len(terminal)} pending"
        )
        print(f"PASS  live articles in first page: {live_articles}")
        print(f"PASS  live trend videos in first page: {live_trend_videos}")
        for name, run_id in source_runs.values():
            run = terminal.get(run_id)
            status = str(run.get("status")) if run else "pending"
            created = int(run.get("records_created", 0)) if run else 0
            updated = int(run.get("records_updated", 0)) if run else 0
            print(f"INFO  {name}: {status}, created={created}, updated={updated}")

        if not successful_sources or live_articles == 0 or live_trend_videos == 0:
            print("FAIL  real-data acceptance minimum was not met", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
