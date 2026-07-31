import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E configuration for Sports Intelligence OS.
 *
 * Three viewport projects cover the acceptance breakpoints:
 *   - mobile:  390x844  (iPhone 14 Pro)
 *   - tablet:  768x1024 (iPad Mini / portrait iPad)
 *   - desktop: 1440x900 (standard laptop)
 *
 * baseURL defaults to the Caddy proxy at http://localhost:8080.
 */
export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",

  /* Fail-fast in CI, allow local retries for flakiness */
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,

  /* Reporter: HTML in CI for artifact upload, list locally */
  reporter: process.env.CI
    ? [["html", { open: "never" }], ["github"]]
    : [["html", { open: "on-failure" }], ["list"]],

  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",

    /* Capture screenshot for every test (pass or fail) */
    screenshot: "on",

    /* Trace only on first retry to keep artifacts small */
    trace: "on-first-retry",

    /* Reasonable timeouts */
    actionTimeout: 15_000,
    navigationTimeout: 30_000,

    /* Accept cookies / ignore HTTPS errors in local dev */
    ignoreHTTPSErrors: true,
  },

  projects: [
    {
      name: "mobile",
      use: {
        ...devices["iPhone 14 Pro"],
        viewport: { width: 390, height: 844 },
      },
    },
    {
      name: "tablet",
      use: {
        viewport: { width: 768, height: 1024 },
        userAgent:
          "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
      },
    },
    {
      name: "desktop",
      use: {
        viewport: { width: 1440, height: 900 },
        userAgent:
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
      },
    },
  ],
});
