"""Cross-platform installer contracts that do not mutate the host."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallerContractTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        path = ROOT / relative_path
        self.assertTrue(path.is_file(), f"Missing installer artifact: {relative_path}")
        return path.read_text(encoding="utf-8")

    def test_platform_entrypoints_exist(self) -> None:
        for relative_path in (
            "scripts/install.sh",
            "scripts/install-common.sh",
            "scripts/install-linux.sh",
            "scripts/install-macos.sh",
            "scripts/install-windows.ps1",
            "docs/ONE_CLICK_INSTALL.md",
        ):
            with self.subTest(relative_path=relative_path):
                self.read(relative_path)

    def test_first_install_generates_secrets_and_preserves_existing_env(self) -> None:
        common = self.read("scripts/install-common.sh")
        windows = self.read("scripts/install-windows.ps1")
        self.assertIn('if [[ ! -f "${ENV_FILE}" ]]', common)
        self.assertIn("openssl rand", common)
        self.assertIn("Preserving the existing .env", common)
        self.assertIn("if (-not (Test-Path -LiteralPath $EnvFile))", windows)
        self.assertIn("RandomNumberGenerator", windows)
        self.assertIn("Preserving the existing .env", windows)
        self.assertIn("$Arguments = @($args)", windows)
        self.assertNotIn("ValueFromRemainingArguments", windows)
        self.assertIn(".sio/", self.read(".gitignore"))

    def test_no_fixed_administrator_password_is_embedded(self) -> None:
        installers = "\n".join(
            self.read(path)
            for path in ("scripts/install-common.sh", "scripts/install-windows.ps1")
        )
        self.assertNotRegex(
            installers,
            re.compile(r"SIO_BOOTSTRAP_ADMIN_PASSWORD\s*=\s*['\"]?[^$\s'\"]+"),
        )
        self.assertIn("random", installers.lower())

    def test_bootstrap_runs_real_migrations_health_and_seed_commands(self) -> None:
        common = self.read("scripts/install-common.sh")
        for marker in (
            "docker_compose config --quiet",
            "docker_compose up -d --build",
            "http://127.0.0.1:8000/health/ready",
            "http://127.0.0.1:8080/login",
            "bootstrap-admin",
            "seed-platforms",
            "import-rules",
            "seed-generation",
            "seed-news-sources",
            "seed-automations",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, common)
        for service in ("postgres", "redis", "api", "worker", "beat", "web", "proxy"):
            self.assertIn(service, common)

    def test_demo_data_is_explicit_opt_in(self) -> None:
        common = self.read("scripts/install-common.sh")
        windows = self.read("scripts/install-windows.ps1")
        self.assertIn("--with-demo-data", common)
        self.assertIn('if [[ "${WITH_DEMO_DATA}" == "1" ]]', common)
        self.assertIn("[switch]$WithDemoData", windows)
        self.assertIn("if ($WithDemoData)", windows)
        self.assertIn("DEMO/MOCK", common)
        self.assertIn("DEMO/MOCK", windows)

    def test_os_installers_use_expected_package_sources(self) -> None:
        linux = self.read("scripts/install-linux.sh")
        windows = self.read("scripts/install-windows.ps1")
        macos = self.read("scripts/install-macos.sh")
        for distribution in ("ubuntu", "debian", "fedora", "rhel"):
            self.assertIn(distribution, linux)
        self.assertIn("https://download.docker.com/linux/", linux)
        self.assertIn("docker-compose-plugin", linux)
        self.assertIn("Docker.DockerDesktop", windows)
        self.assertIn("brew install --cask docker", macos)

    def test_documentation_explains_privilege_and_truthfulness_boundaries(self) -> None:
        docs = self.read("docs/ONE_CLICK_INSTALL.md")
        for marker in (
            "root",
            "WSL 2",
            "source_kind=mock",
            "不会被覆盖",
            "Docker Desktop",
            "docker compose down -v",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, docs)


if __name__ == "__main__":
    unittest.main()
