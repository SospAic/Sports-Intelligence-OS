import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * Accessibility E2E tests.
 *
 * Combines automated axe-core scanning with manual ARIA landmark checks
 * to ensure the application meets baseline WCAG 2.1 AA requirements.
 *
 * Requires authenticated session (bootstrapped admin).
 */

const ADMIN_EMAIL =
  process.env.E2E_ADMIN_EMAIL ?? "admin@sportsintelligence.local";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "CiOnly!Passw0rd#2026";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("邮箱").fill(ADMIN_EMAIL);
  await page.getByLabel("密码").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL("**/dashboard", { timeout: 15_000 });
}

test.describe("Accessibility — axe-core scans", () => {
  test("login page has no critical a11y violations", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious",
    );

    expect(
      critical,
      `Critical/serious violations:\n${JSON.stringify(critical, null, 2)}`,
    ).toHaveLength(0);
  });

  test("dashboard has no critical a11y violations", async ({ page }) => {
    await login(page);
    await page.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      // Exclude third-party chart SVGs that may lack labels
      .exclude(".recharts-wrapper")
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious",
    );

    expect(
      critical,
      `Critical/serious violations:\n${JSON.stringify(critical, null, 2)}`,
    ).toHaveLength(0);
  });

  test("accounts page has no critical a11y violations", async ({ page }) => {
    await login(page);
    await page.goto("/accounts");
    await page.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious",
    );

    expect(
      critical,
      `Critical/serious violations:\n${JSON.stringify(critical, null, 2)}`,
    ).toHaveLength(0);
  });

  test("settings page has no critical a11y violations", async ({ page }) => {
    await login(page);
    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious",
    );

    expect(
      critical,
      `Critical/serious violations:\n${JSON.stringify(critical, null, 2)}`,
    ).toHaveLength(0);
  });
});

test.describe("Accessibility — ARIA landmarks and structure", () => {
  test("login page has proper heading hierarchy", async ({ page }) => {
    await page.goto("/login");

    // Should have exactly one h1
    const h1Count = await page.getByRole("heading", { level: 1 }).count();
    expect(h1Count).toBe(1);

    // The h1 should be the login title
    await expect(
      page.getByRole("heading", { level: 1, name: "登录工作台" }),
    ).toBeVisible();
  });

  test("html element has lang attribute", async ({ page }) => {
    await page.goto("/login");
    const lang = await page.locator("html").getAttribute("lang");
    expect(lang).toBe("zh-CN");
  });

  test("authenticated layout has navigation landmark", async ({ page }) => {
    await login(page);

    const nav = page.getByRole("navigation", { name: "主导航" });
    await expect(nav).toBeVisible();
  });

  test("form inputs have associated labels", async ({ page }) => {
    await page.goto("/login");

    // Email input
    const emailInput = page.getByLabel("邮箱");
    await expect(emailInput).toBeVisible();
    await expect(emailInput).toHaveAttribute("type", "email");

    // Password input
    const passwordInput = page.getByLabel("密码");
    await expect(passwordInput).toBeVisible();
    await expect(passwordInput).toHaveAttribute("type", "password");
  });

  test("buttons have accessible names", async ({ page }) => {
    await login(page);

    // All buttons in the header should have accessible names
    const headerButtons = page.locator("header button");
    const count = await headerButtons.count();

    for (let i = 0; i < count; i++) {
      const button = headerButtons.nth(i);
      const name = await button.getAttribute("aria-label");
      const text = await button.textContent();
      const hasAccessibleName = Boolean(
        (name && name.trim()) || (text && text.trim()),
      );
      expect(
        hasAccessibleName,
        `Button at index ${i} lacks accessible name`,
      ).toBe(true);
    }
  });

  test("global search has combobox ARIA attributes", async ({ page }) => {
    await login(page);

    const searchInput = page.getByLabel("全局搜索");
    await expect(searchInput).toHaveAttribute("role", "combobox");
    await expect(searchInput).toHaveAttribute("aria-autocomplete", "list");
    await expect(searchInput).toHaveAttribute(
      "aria-controls",
      "global-search-results",
    );
  });

  test("navigation links have aria-current for active page", async ({
    page,
  }) => {
    await login(page);

    // Dashboard link should be marked as current
    const nav = page.getByRole("navigation", { name: "主导航" });
    const dashboardLink = nav.getByRole("link", { name: "仪表盘" });
    await expect(dashboardLink).toHaveAttribute("aria-current", "page");
  });

  test("loading state has aria-busy indicator", async ({ page }) => {
    // Intercept the /me request to simulate slow loading
    await page.route("**/api/v1/me", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 2_000));
      await route.continue();
    });

    await page.goto("/dashboard");

    // The loading state should have aria-busy
    const busyElement = page.locator('[aria-busy="true"]');
    await expect(busyElement).toBeVisible({ timeout: 3_000 });
  });

  test("error alerts use role=alert", async ({ page }) => {
    await page.goto("/login");

    // Submit with invalid credentials to trigger error
    await page.getByLabel("邮箱").fill("wrong@example.com");
    await page.getByLabel("密码").fill("wrongpassword123");
    await page.getByRole("button", { name: "登录" }).click();

    // Error message should use role="alert"
    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible({ timeout: 10_000 });
  });
});
