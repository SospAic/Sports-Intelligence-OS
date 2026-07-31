"""Verify the Prompt 02 Alembic schema in a temporary SQLite database."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

EXPECTED_TABLES = {
    "account_snapshots",
    "accounts",
    "alembic_version",
    "audit_entries",
    "automation_actions",
    "automation_evaluations",
    "automation_rules",
    "automation_runtime_states",
    "content_items",
    "content_snapshots",
    "derived_metrics",
    "articles",
    "event_articles",
    "generation_runs",
    "generation_steps",
    "generation_workflows",
    "llm_provider_settings",
    "login_attempts",
    "news_scoring_configs",
    "news_sources",
    "news_sync_runs",
    "notification_channels",
    "notification_deliveries",
    "outbox_events",
    "platforms",
    "prompt_collections",
    "prompt_versions",
    "rule_sections",
    "rule_set_versions",
    "rule_sets",
    "rules",
    "saved_topics",
    "sessions",
    "system_events",
    "sync_runs",
    "task_runs",
    "topic_events",
    "users",
    "workspace_memberships",
    "workspaces",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    args = parser.parse_args()

    with sqlite3.connect(args.database) as connection:
        actual_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    if actual_tables != EXPECTED_TABLES:
        missing = sorted(EXPECTED_TABLES - actual_tables)
        unexpected = sorted(actual_tables - EXPECTED_TABLES)
        raise SystemExit(f"schema mismatch: missing={missing}, unexpected={unexpected}")
    print("Migration schema verified: " + ", ".join(sorted(actual_tables)))


if __name__ == "__main__":
    main()
