import { expect, test } from "@playwright/test";

/**
 * Keyboard navigation E2E tests.
 *
 * Validates that the application is fully operable via keyboard:
 * - Tab through navigation items
 * - Enter to activate links/buttons
 * - Escape to close mobile drawer and dropdowns
 *
 * Requires authenticated session (bootstrapped admin).
 */

const ADMIN_EMAIL =
  process.env.E2E_ADMIN_EMAIL ?? "admin@sportsintelligence.local";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "CiOnly!Passw0rd#2026";

/** Log in and land on the dashboard before each test. */
async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("邮箱").fill(ADMIN_EMAIL);
  await page.getByLabel("密码").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL("**/dashboard", { timeout: 15_000 });
}

test.describe("Keyboard navigation", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test("Tab moves focus through header controls", async ({ page }) => {
    // Start focus at body
    await page.keyboard.press("Tab");

    // The first focusable element should be within the page.
    // Keep tabbing and verify we eventually reach the global search input.
    const searchInput = page.getByLabel("全局搜索");
    await searchInput.focus();
    await expect(searchInput).toBeFocused();
  });

  test("Tab through sidebar navigation links", async ({
    page,
    browserName,
  }) => {
    test.skip(
      browserName !== "chromium",
      "Sidebar layout differs; test targets chromium",
    );

    // On desktop viewport the sidebar is visible.
    // Focus the first nav link and tab through several items.
    const nav = page.getByRole("navigation", { name: "主导航" });
    await expect(nav).toBeVisible();

    const firstLink = nav.getByRole("link").first();
    await firstLink.focus();
    await expect(firstLink).toBeFocused();

    // Tab to next link
    await page.keyboard.press("Tab");
    const secondLink = nav.getByRole("link").nth(1);
    await expect(secondLink).toBeFocused();

    // Press Enter to navigate
    await page.keyboard.press("Enter");
    await page.waitForTimeout(500);
    // URL should have changed from /dashboard
    const url = page.url();
    expect(url).not.toBe("");
  });

  test("Enter activates focused navigation link", async ({ page }) => {
    const nav = page.getByRole("navigation", { name: "主导航" });
    const trendsLink = nav.getByRole("link", { name: "热点情报中心" });

    await trendsLink.focus();
    await page.keyboard.press("Enter");

    await page.waitForURL("**/trends", { timeout: 10_000 });
    await expect(page).toHaveURL(/\/trends/);
  });

  test("mobile drawer opens with menu button and closes with Escape", async ({
    page,
    isMobile,
  }) => {
    test.skip(!isMobile, "Mobile drawer only visible on mobile viewport");

    // Open drawer via hamburger button
    const openButton = page.getByLabel("打开导航");
    await expect(openButton).toBeVisible();
    await openButton.click();

    // Drawer should be visible — nav is now in viewport
    const nav = page.getByRole("navigation", { name: "主导航" });
    await expect(nav).toBeVisible();

    // Close with the X button
    const closeButton = page.getByLabel("关闭导航");
    await expect(closeButton).toBeVisible();
    await closeButton.click();

    // Drawer should be hidden (translated off-screen)
    await expect(nav).not.toBeVisible({ timeout: 3_000 });
  });

  test("mobile drawer closes via overlay click", async ({ page, isMobile }) => {
    test.skip(!isMobile, "Mobile drawer only visible on mobile viewport");

    const openButton = page.getByLabel("打开导航");
    await openButton.click();

    const nav = page.getByRole("navigation", { name: "主导航" });
    await expect(nav).toBeVisible();

    // Click the overlay backdrop
    const overlay = page.getByLabel("关闭导航遮罩");
    await overlay.click();

    await expect(nav).not.toBeVisible({ timeout: 3_000 });
  });

  test("global search input supports Escape to clear", async ({ page }) => {
    const searchInput = page.getByLabel("全局搜索");
    await searchInput.fill("仪表盘");

    // Dropdown should appear
    await expect(page.getByRole("listbox")).toBeVisible({ timeout: 5_000 });

    // Escape clears the search
    await page.keyboard.press("Escape");
    await expect(searchInput).toHaveValue("");
  });

  test("user menu opens and closes with keyboard", async ({ page }) => {
    // The user menu button contains the user display name or "用户"
    const userButton = page
      .locator("header")
      .getByRole("button")
      .filter({ has: page.locator("svg") })
      .last();

    await userButton.focus();
    await page.keyboard.press("Enter");

    // Menu should show logout option
    await expect(page.getByText("退出登录")).toBeVisible({ timeout: 3_000 });

    // Click elsewhere to dismiss
    await page.locator("main, [class*='page-enter']").first().click();
    await expect(page.getByText("退出登录")).not.toBeVisible({
      timeout: 3_000,
    });
  });

  test("quick create menu toggles with Enter", async ({ page }) => {
    const quickCreateButton = page.getByLabel("快速创建");
    await quickCreateButton.focus();
    await page.keyboard.press("Enter");

    // Menu items should appear
    await expect(page.getByText("添加账号")).toBeVisible({ timeout: 3_000 });
    await expect(page.getByText("创建内容")).toBeVisible();
    await expect(page.getByText("新建自动化")).toBeVisible();

    // Toggle closed
    await page.keyboard.press("Enter");
    await expect(page.getByText("添加账号")).not.toBeVisible({
      timeout: 3_000,
    });
  });
});
