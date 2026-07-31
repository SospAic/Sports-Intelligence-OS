import { expect, test } from "@playwright/test";

/**
 * Authentication E2E tests.
 *
 * Requires a running stack (docker compose up) with a bootstrapped admin:
 *   docker compose run --rm api python -m app.cli bootstrap-admin
 *
 * Environment variables:
 *   E2E_ADMIN_EMAIL    - admin email (default: admin@sportsintelligence.local)
 *   E2E_ADMIN_PASSWORD - admin password (default: CiOnly!Passw0rd#2026)
 */

const ADMIN_EMAIL =
  process.env.E2E_ADMIN_EMAIL ?? "admin@sportsintelligence.local";
const ADMIN_PASSWORD =
  process.env.E2E_ADMIN_PASSWORD ?? "CiOnly!Passw0rd#2026";

test.describe("Login flow", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
  });

  test("renders login form with email and password fields", async ({
    page,
  }) => {
    await expect(
      page.getByRole("heading", { name: "登录工作台" }),
    ).toBeVisible();
    await expect(page.getByLabel("邮箱")).toBeVisible();
    await expect(page.getByLabel("密码")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "登录" }),
    ).toBeVisible();
  });

  test("shows validation error for empty submission", async ({ page }) => {
    await page.getByRole("button", { name: "登录" }).click();

    // Zod validation messages
    await expect(page.getByText("请输入有效邮箱")).toBeVisible();
    await expect(page.getByText("请输入密码")).toBeVisible();
  });

  test("shows validation error for invalid email format", async ({ page }) => {
    await page.getByLabel("邮箱").fill("not-an-email");
    await page.getByLabel("密码").fill("somepassword");
    await page.getByRole("button", { name: "登录" }).click();

    await expect(page.getByText("请输入有效邮箱")).toBeVisible();
  });

  test("shows error alert for wrong credentials", async ({ page }) => {
    await page.getByLabel("邮箱").fill("wrong@example.com");
    await page.getByLabel("密码").fill("wrongpassword123");
    await page.getByRole("button", { name: "登录" }).click();

    // The form displays a role="alert" element on API failure
    await expect(page.getByRole("alert")).toBeVisible({ timeout: 10_000 });
  });

  test("successful login redirects to dashboard", async ({ page }) => {
    await page.getByLabel("邮箱").fill(ADMIN_EMAIL);
    await page.getByLabel("密码").fill(ADMIN_PASSWORD);
    await page.getByRole("button", { name: "登录" }).click();

    // Wait for navigation to dashboard
    await page.waitForURL("**/dashboard", { timeout: 15_000 });
    await expect(page).toHaveURL(/\/dashboard/);
  });

  test("authenticated user visiting /login is redirected to /dashboard", async ({
    page,
  }) => {
    // First login
    await page.getByLabel("邮箱").fill(ADMIN_EMAIL);
    await page.getByLabel("密码").fill(ADMIN_PASSWORD);
    await page.getByRole("button", { name: "登录" }).click();
    await page.waitForURL("**/dashboard", { timeout: 15_000 });

    // Navigate back to /login — should redirect
    await page.goto("/login");
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 });
  });

  test("unauthenticated user visiting /dashboard is redirected to /login", async ({
    page,
  }) => {
    // Clear any existing cookies
    await page.context().clearCookies();
    await page.goto("/dashboard");

    // Should end up on login page
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });
});
