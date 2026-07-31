from __future__ import annotations

import unittest

from scripts.acceptance_smoke import _resolve_request_url


class AcceptanceSmokeUrlTests(unittest.TestCase):
    def test_resolves_http_path_on_configured_origin(self) -> None:
        self.assertEqual(
            _resolve_request_url("http://localhost:8080", "/health/live"),
            "http://localhost:8080/health/live",
        )

    def test_rejects_non_http_scheme(self) -> None:
        with self.assertRaisesRegex(ValueError, "http or https"):
            _resolve_request_url("file:///tmp", "/health/live")

    def test_rejects_credentials_in_base_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "credentials"):
            _resolve_request_url("http://user:password@localhost:8080", "/health/live")

    def test_rejects_absolute_url_that_changes_origin(self) -> None:
        with self.assertRaisesRegex(ValueError, "configured origin"):
            _resolve_request_url("http://localhost:8080", "https://example.com/health/live")


if __name__ == "__main__":
    unittest.main()
