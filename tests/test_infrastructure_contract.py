"""Prompt 02 infrastructure contracts that do not require running services."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InfrastructureContractTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        path = ROOT / relative_path
        self.assertTrue(path.is_file(), f"Missing infrastructure file: {relative_path}")
        return path.read_text(encoding="utf-8")

    def test_monorepo_entrypoints_exist(self) -> None:
        for relative_path in (
            "apps/web/package.json",
            "apps/api/app/main.py",
            "apps/worker/celery_app.py",
            "packages/shared-types/package.json",
            "packages/ui/package.json",
            "packages/config/package.json",
            "docker-compose.yml",
            "Makefile",
            "pnpm-lock.yaml",
            ".github/workflows/ci.yml",
        ):
            with self.subTest(relative_path=relative_path):
                self.read(relative_path)

    def test_compose_has_required_processes_and_health_checks(self) -> None:
        compose = self.read("docker-compose.yml")
        for service in ("postgres", "redis", "api", "worker", "beat", "web", "proxy"):
            with self.subTest(service=service):
                self.assertIn(f"  {service}:\n", compose)
        self.assertGreaterEqual(compose.count("healthcheck:"), 4)

    def test_makefile_exposes_required_commands(self) -> None:
        makefile = self.read("Makefile")
        for target in (
            "dev",
            "up",
            "down",
            "logs",
            "migrate",
            "seed",
            "test",
            "lint",
            "format",
        ):
            with self.subTest(target=target):
                self.assertIn(f"\n{target}:\n", f"\n{makefile}")

    def test_bootstrap_password_has_no_default(self) -> None:
        env_lines = {line.strip() for line in self.read(".env.example").splitlines()}
        self.assertIn("SIO_BOOTSTRAP_ADMIN_PASSWORD=", env_lines)
        compose = self.read("docker-compose.yml")
        self.assertIn(
            "SIO_BOOTSTRAP_ADMIN_PASSWORD: ${SIO_BOOTSTRAP_ADMIN_PASSWORD:-}",
            compose,
        )

    def test_authentication_contract_is_implemented(self) -> None:
        auth_routes = self.read("apps/api/app/api/routes/auth.py")
        user_routes = self.read("apps/api/app/api/routes/users.py")
        security = self.read("apps/api/app/core/security.py")
        for route in ('@router.post("/login"', '@router.post("/logout"'):
            self.assertIn(route, auth_routes)
        self.assertIn('@router.get("/me"', user_routes)
        self.assertIn("PasswordHash.recommended()", security)
        self.assertIn("token_hash", self.read("apps/api/app/models/session.py"))

    def test_prompt_03_monitoring_contract_is_present(self) -> None:
        model = self.read("apps/api/app/models/monitoring.py")
        routes = self.read("apps/api/app/api/routes/monitoring.py")
        seed = self.read("apps/api/app/services/monitoring_seed.py")
        for entity in (
            "class Platform",
            "class Account",
            "class AccountSnapshot",
            "class ContentItem",
            "class ContentSnapshot",
            "class DerivedMetric",
        ):
            self.assertIn(entity, model)
        self.assertIn('@router.get("/contents"', routes)
        self.assertIn('@router.get("/accounts/export.csv"', routes)
        self.assertIn('source_kind="mock"', seed)

    def test_prompt_04_platform_sync_contract_is_present(self) -> None:
        adapter = self.read("apps/api/app/adapters/platforms/base.py")
        youtube = self.read("apps/api/app/adapters/platforms/youtube.py")
        tasks = self.read("apps/api/app/tasks/monitoring.py")
        sync_model = self.read("apps/api/app/models/sync.py")
        for method in (
            "validate_config",
            "resolve_account",
            "fetch_account",
            "list_contents",
            "fetch_content_analytics",
            "health_check",
        ):
            self.assertIn(method, adapter)
        self.assertIn("youtube/v3", youtube)
        self.assertIn("class SyncRun", sync_model)
        for task in (
            "sync_account",
            "sync_account_contents",
            "sync_content_metrics",
            "sync_all_due_accounts",
            "calculate_derived_metrics",
        ):
            self.assertIn(task, tasks)

    def test_prompt_05_news_contract_is_present(self) -> None:
        model = self.read("apps/api/app/models/news.py")
        provider = self.read("apps/api/app/providers/news/base.py")
        routes = self.read("apps/api/app/api/routes/news.py")
        seed = self.read("apps/api/app/services/news_seed.py")
        for entity in (
            "class Source",
            "class Article",
            "class TopicEvent",
            "class EventArticle",
            "class NewsSyncRun",
            "class NewsScoringConfig",
        ):
            self.assertIn(entity, model)
        for method in (
            "validate_source",
            "fetch_latest",
            "fetch_range",
            "normalize_article",
            "health_check",
        ):
            self.assertIn(method, provider)
        self.assertIn('@router.get("/articles"', routes)
        self.assertIn('@router.post("/events/merge"', routes)
        self.assertIn("enabled=False", seed)
        self.assertIn("this never downloads or stores articles", seed)
        self.assertIn(
            "--queues=maintenance,monitoring,news", self.read("docker-compose.yml")
        )

    def test_prompt_06_editorial_rule_contract_is_present(self) -> None:
        model = self.read("apps/api/app/models/editorial_rules.py")
        parser = self.read("apps/api/app/rules/parser.py")
        validation = self.read("apps/api/app/rules/validation.py")
        routes = self.read("apps/api/app/api/routes/editorial_rules.py")
        makefile = self.read("Makefile")
        source = (
            ROOT
            / "data"
            / "rules"
            / (
                "ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_"
                "REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt"
            )
        )
        for entity in (
            "class RuleSet",
            "class RuleSetVersion",
            "class RuleSection",
            "class Rule",
        ):
            self.assertIn(entity, model)
        self.assertTrue(source.is_file())
        self.assertIn("parse_v79_bytes", parser)
        self.assertIn("cyclic_dependency", validation)
        self.assertIn("mandatory_rule_disabled", validation)
        self.assertIn('@router.post("/import"', routes)
        self.assertIn("/publish", routes)
        self.assertIn("/rollback", routes)
        self.assertIn("\nimport-rules:\n", f"\n{makefile}")

    def test_prompt_07_generation_contract_is_present(self) -> None:
        model = self.read("apps/api/app/models/generation.py")
        provider = self.read("apps/api/app/providers/llm/base.py")
        mock = self.read("apps/api/app/providers/llm/mock.py")
        workflow = self.read("apps/api/app/workflows/generation.py")
        routes = self.read("apps/api/app/api/routes/generation.py")
        prompt_seed = self.read("data/prompts/sports_short_video_full_package.json")
        for entity in (
            "class PromptCollection",
            "class PromptVersion",
            "class GenerationWorkflow",
            "class GenerationRun",
            "class GenerationStep",
        ):
            self.assertIn(entity, model)
        for method in (
            "validate_config",
            "generate",
            "stream",
            "estimate_cost",
            "health_check",
        ):
            self.assertIn(method, provider)
        self.assertIn("MOCK TEST OUTPUT", mock)
        self.assertIn("WORKFLOW_STEPS", workflow)
        self.assertIn('@router.post("/generations/preview"', routes)
        self.assertIn('@router.post("/generations"', routes)
        self.assertIn("target_min_chars", prompt_seed)
        self.assertIn("\nseed-generation:\n", f"\n{self.read('Makefile')}")

    def test_prompt_08_automation_notification_contract_is_present(self) -> None:
        model = self.read("apps/api/app/models/automation.py")
        conditions = self.read("apps/api/app/automations/conditions.py")
        provider = self.read("apps/api/app/providers/notifications/base.py")
        routes = self.read("apps/api/app/api/routes/automation.py")
        tasks = self.read("apps/api/app/tasks/automation.py")
        docs = self.read("docs/AUTOMATION_NOTIFICATIONS.md")
        for entity in (
            "class AutomationRule",
            "class AutomationAction",
            "class AutomationEvaluation",
            "class NotificationChannel",
            "class NotificationDelivery",
        ):
            self.assertIn(entity, model)
        for operator in ("consecutive_matches", "increased_percent", "regex"):
            self.assertIn(operator, conditions)
        for method in ("validate_config", "send", "test", "health_check"):
            self.assertIn(method, provider)
        self.assertIn('@router.post("/automations/evaluate"', routes)
        self.assertIn('@router.post("/notification-channels/{channel_id}/test"', routes)
        self.assertIn("scan_recent_entities", tasks)
        self.assertIn("测试只发送到 `mock_notification`", docs)
        self.assertIn("\nseed-automations:\n", f"\n{self.read('Makefile')}")

    def test_prompt_09_admin_dashboard_contract_is_present(self) -> None:
        shell = self.read("apps/web/components/app-shell.tsx")
        automation_editor = self.read("apps/web/app/automations/automation-editor.tsx")
        notification_page = self.read(
            "apps/web/app/notification-channels/notification-channels-client.tsx"
        )
        topic_model = self.read("apps/api/app/models/topics.py")
        operation_routes = self.read("apps/api/app/api/routes/operations.py")
        docs = self.read("docs/ADMIN_DASHBOARD.md")
        for route in (
            "/dashboard",
            "/accounts",
            "/contents",
            "/news",
            "/events",
            "/topics",
            "/automations",
            "/notification-channels",
            "/tasks",
            "/logs",
            "/settings",
        ):
            self.assertIn(route, shell)
        self.assertIn("ConditionGroup", automation_editor)
        self.assertIn("config_masked", notification_page)
        self.assertIn("class SavedTopic", topic_model)
        self.assertIn('@router.get("/tasks"', operation_routes)
        self.assertIn("核心页面全部读取真实后端 API", docs)

    def test_prompt_10_test_and_documentation_contract_is_present(self) -> None:
        required_docs = (
            "docs/INSTALLATION.md",
            "docs/DEVELOPMENT.md",
            "docs/DEPLOYMENT.md",
            "docs/PLATFORM_ADAPTER_GUIDE.md",
            "docs/NEWS_PROVIDER_GUIDE.md",
            "docs/LLM_PROVIDER_GUIDE.md",
            "docs/NOTIFICATION_PROVIDER_GUIDE.md",
            "docs/RULE_IMPORT_GUIDE.md",
            "docs/AUTOMATION_GUIDE.md",
            "docs/TROUBLESHOOTING.md",
        )
        for path in required_docs:
            self.assertTrue((ROOT / path).is_file(), path)
        integration = self.read("apps/api/tests/test_first_delivery_flow.py")
        frontend = self.read("apps/web/app/editor-flows.test.tsx")
        makefile = self.read("Makefile")
        self.assertIn("view_growth_1h", integration)
        self.assertIn("mock_llm", integration)
        self.assertIn("Mock Webhook", integration)
        for flow in ("LoginForm", "RuleEditor", "PromptEditor", "GenerationForm"):
            self.assertIn(flow, frontend)
        self.assertIn('cd apps/api && alembic upgrade head', makefile)
        self.assertIn('cd apps/api && pytest', makefile)

    def test_prompt_11_hardening_contract_is_present(self) -> None:
        celery = self.read("apps/api/app/tasks/celery_app.py")
        monitoring_tasks = self.read("apps/api/app/tasks/monitoring.py")
        news_tasks = self.read("apps/api/app/tasks/news.py")
        notification_tasks = self.read("apps/api/app/tasks/automation.py")
        url_security = self.read("apps/api/app/providers/news/utils.py")
        generation_qa = self.read("apps/api/app/workflows/generation.py")
        generation_tasks = self.read("apps/api/app/tasks/generation.py")
        self.assertIn("task_soft_time_limit=1800", celery)
        self.assertIn("task_reject_on_worker_lost=True", celery)
        self.assertIn("recover_stale_runs", monitoring_tasks)
        self.assertIn("recover_stale_syncs", news_tasks)
        self.assertIn("stale_delivery_recovered", notification_tasks)
        self.assertIn("ensure_public_endpoint", url_security)
        self.assertIn("protected_answer_word_revealed_too_early", generation_qa)
        self.assertIn("recover_stale_generations", generation_tasks)


if __name__ == "__main__":
    unittest.main()
