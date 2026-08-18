"""Prompt 00 repository-contract tests with no third-party dependencies."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProjectContextContractTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        path = ROOT / relative_path
        self.assertTrue(path.is_file(), f"Missing required context file: {relative_path}")
        return path.read_text(encoding="utf-8")

    def test_required_context_files_exist(self) -> None:
        for relative_path in (
            "AGENTS.md",
            "README.md",
            "docs/PROJECT_CONTEXT.md",
            "docs/DELIVERY_PLAN.md",
            "docs/STATUS.md",
        ):
            with self.subTest(relative_path=relative_path):
                self.read(relative_path)

    def test_prompt_sequence_is_complete_and_ordered(self) -> None:
        content = self.read("docs/DELIVERY_PLAN.md")
        positions = []
        for number in range(12):
            marker = f"## Prompt {number:02d}："
            position = content.find(marker)
            self.assertNotEqual(position, -1, f"Missing stage marker: {marker}")
            positions.append(position)
        self.assertEqual(positions, sorted(positions), "Prompt stages must remain ordered")

    def test_truthfulness_contract_is_explicit(self) -> None:
        agents = self.read("AGENTS.md")
        for marker in ("`live`", "`imported`", "`mock`", "不得", "source_kind"):
            with self.subTest(marker=marker):
                self.assertIn(marker, agents)

    def test_first_delivery_vertical_slice_is_preserved(self) -> None:
        context = self.read("docs/PROJECT_CONTEXT.md")
        required_capabilities = (
            "用户登录",
            "YouTube 官方 API Adapter",
            "通用 Mock Adapter",
            "RSS 新闻源",
            "7.9 规则原文导入",
            "Prompt 模板管理",
            "自定义监控规则",
            "系统事件日志",
            "Docker Compose 一键启动",
        )
        for capability in required_capabilities:
            with self.subTest(capability=capability):
                self.assertIn(capability, context)

    def test_current_stage_reports_prompt_11_truthfully(self) -> None:
        readme = self.read("README.md")
        status = self.read("docs/STATUS.md")
        self.assertIn("第一次交付验收", readme)
        self.assertIn("Prompt 11 后续维护", status)
        self.assertIn("当前机器没有 Docker", self.read("docs/FIRST_DELIVERY_REPORT.md"))
        self.assertIn("显式 Mock 标记", readme)
        self.assertIn("verification_incomplete", status)

    def test_prompt_01_required_design_documents_exist(self) -> None:
        required_documents = (
            "docs/PRODUCT_REQUIREMENTS.md",
            "docs/ARCHITECTURE.md",
            "docs/DOMAIN_MODEL.md",
            "docs/DATABASE_DESIGN.md",
            "docs/API_DESIGN.md",
            "docs/ADAPTER_DESIGN.md",
            "docs/RULE_ENGINE_DESIGN.md",
            "docs/PROMPT_ENGINE_DESIGN.md",
            "docs/NOTIFICATION_DESIGN.md",
            "docs/SECURITY.md",
            "docs/ROADMAP.md",
            "docs/ACCEPTANCE_CRITERIA.md",
        )
        for relative_path in required_documents:
            with self.subTest(relative_path=relative_path):
                self.read(relative_path)

    def test_required_mermaid_diagrams_are_present(self) -> None:
        required_diagrams = {
            "docs/ARCHITECTURE.md": ("系统架构图", "核心数据流程图"),
            "docs/PROMPT_ENGINE_DESIGN.md": ("内容生成工作流",),
            "docs/RULE_ENGINE_DESIGN.md": ("规则触发流程",),
        }
        for relative_path, headings in required_diagrams.items():
            content = self.read(relative_path)
            self.assertGreaterEqual(content.count("```mermaid"), 1)
            self.assertEqual(
                content.count("```") % 2,
                0,
                f"Unbalanced fenced code blocks in {relative_path}",
            )
            for heading in headings:
                with self.subTest(relative_path=relative_path, heading=heading):
                    self.assertIn(heading, content)

    def test_provider_interfaces_and_registration_are_explicit(self) -> None:
        adapter_design = self.read("docs/ADAPTER_DESIGN.md")
        for interface_name in (
            "PlatformAdapter",
            "NewsProvider",
            "LLMProvider",
            "NotificationProvider",
            "ProviderRegistry",
        ):
            with self.subTest(interface_name=interface_name):
                self.assertIn(interface_name, adapter_design)

    def test_architecture_guardrails_are_preserved(self) -> None:
        architecture = self.read("docs/ARCHITECTURE.md")
        database = self.read("docs/DATABASE_DESIGN.md")
        prompt_engine = self.read("docs/PROMPT_ENGINE_DESIGN.md")
        self.assertIn("前端不保存第三方 Token，不直连外部平台", architecture)
        self.assertIn("不建立 `objects(type, data_json)`", database)
        self.assertIn("不硬编码业务 Prompt", prompt_engine)
        self.assertIn("不能作为唯一可执行规则表示", prompt_engine)


if __name__ == "__main__":
    unittest.main()
