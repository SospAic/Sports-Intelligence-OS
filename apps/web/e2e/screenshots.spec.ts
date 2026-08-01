import { expect, test } from "@playwright/test";

/**
 * Visual regression screenshot tests.
 *
 * Captures full-page screenshots at all 3 configured viewports (mobile 390px,
 * tablet 768px, desktop 1440px) for key application pages.
 *
 * Screenshots are stored in test-results/ and can be compared across runs
 * using Playwright's built-in snapshot comparison or external diffing tools.
 *
 * Requires authenticated session (bootstrapped admin).
 */

const ADMIN_EMAIL =
  process.env.E2E_ADMIN_EMAIL ?? "admin@sportsintelligence.local";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "CiOnly!Passw0rd#2026";

/** Pages that require authentication. */
const AUTHENTICATED_PAGES = [
  { name: "dashboard", path: "/dashboard" },
  { name: "accounts", path: "/accounts" },
  { name: "news", path: "/news" },
  { name: "trends", path: "/trends" },
  { name: "rules", path: "/rules" },
  { name: "generate", path: "/generate" },
  { name: "settings", path: "/settings" },
] as const;

test.describe("Visual regression screenshots", () => {
  test("login page screenshot", async ({ page }, testInfo) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    // Ensure the form is fully rendered
    await expect(page.getByLabel("邮箱")).toBeVisible();

    await page.screenshot({
      path: `${testInfo.outputDir}/screenshots/${testInfo.project.name}-login.png`,
      fullPage: true,
    });
  });

  for (const { name, path } of AUTHENTICATED_PAGES) {
    test(`${name} page screenshot (${path})`, async ({ page }, testInfo) => {
      // Login first
      await page.goto("/login");
      await page.getByLabel("邮箱").fill(ADMIN_EMAIL);
      await page.getByLabel("密码").fill(ADMIN_PASSWORD);
      await page.getByRole("button", { name: "登录" }).click();
      await page.waitForURL("**/dashboard", { timeout: 15_000 });

      // Navigate to target page
      await page.goto(path);
      await page.waitForLoadState("networkidle");

      // Wait for the app shell to settle (loading spinner gone)
      await page
        .waitForSelector('[aria-busy="true"]', {
          state: "hidden",
          timeout: 10_000,
        })
        .catch(() => {
          /* spinner may not appear for fast loads */
        });

      // Small stabilization delay for animations/charts
      await page.waitForTimeout(1_000);

      await page.screenshot({
        path: `${testInfo.outputDir}/screenshots/${testInfo.project.name}-${name}.png`,
        fullPage: true,
      });
    });
  }

  test("login page validation state screenshot", async ({ page }, testInfo) => {
    await page.goto("/login");
    await page.getByRole("button", { name: "登录" }).click();

    // Wait for validation messages
    await expect(page.getByText("请输入有效邮箱")).toBeVisible();

    await page.screenshot({
      path: `${testInfo.outputDir}/screenshots/${testInfo.project.name}-login-validation.png`,
      fullPage: true,
    });
  });

  test("mobile drawer open state screenshot", async ({
    page,
    isMobile,
  }, testInfo) => {
    test.skip(!isMobile, "Drawer screenshot only relevant on mobile");

    // Login
    await page.goto("/login");
    await page.getByLabel("邮箱").fill(ADMIN_EMAIL);
    await page.getByLabel("密码").fill(ADMIN_PASSWORD);
    await page.getByRole("button", { name: "登录" }).click();
    await page.waitForURL("**/dashboard", { timeout: 15_000 });

    // Open drawer
    await page.getByLabel("打开导航").click();
    await expect(
      page.getByRole("navigation", { name: "主导航" }),
    ).toBeVisible();

    await page.screenshot({
      path: `${testInfo.outputDir}/screenshots/${testInfo.project.name}-drawer-open.png`,
      fullPage: false,
    });
  });
});
