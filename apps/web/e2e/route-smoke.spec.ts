import { expect, test } from "@playwright/test";
import { FRONTEND_FUNCTION_MANIFEST } from "../lib/frontend-function-manifest";

const ADMIN_EMAIL =
  process.env.E2E_ADMIN_EMAIL ?? "admin@sportsintelligence.local";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "CiOnly!Passw0rd#2026";

const staticRoutes = FRONTEND_FUNCTION_MANIFEST.filter(
  (entry) => !entry.route.includes("["),
).map((entry) => entry.route);
const dynamicEntries = FRONTEND_FUNCTION_MANIFEST.filter((entry) =>
  entry.route.includes("["),
);

function routePattern(route: string): RegExp {
  const escaped = route.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`^${escaped.replace(/\\\[[^\]]+\\\]/g, "[^/]+")}$`);
}

function normalizeHref(href: string): string | null {
  if (!href.startsWith("/")) return null;
  const parsed = new URL(href, "http://frontend.local");
  return parsed.pathname;
}

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login", { waitUntil: "commit", timeout: 15_000 });
  await page.getByLabel("邮箱").fill(ADMIN_EMAIL);
  await page.getByLabel("密码").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL("**/dashboard", { timeout: 15_000 });
}

async function visitAndCollect(
  page: import("@playwright/test").Page,
  path: string,
  discovered: Set<string>,
  failures: string[],
) {
  const pageErrors: string[] = [];
  const onPageError = (error: Error) => pageErrors.push(error.message);
  page.on("pageerror", onPageError);
  try {
    await page.goto(path, { waitUntil: "commit", timeout: 15_000 });
    await expect(page.locator("body")).toBeAttached({ timeout: 5_000 });
    const workspaceLoader = page.locator('[aria-label="正在加载工作区"]');
    await workspaceLoader.waitFor({ state: "hidden", timeout: 15_000 }).catch(() => {
      failures.push(`${path} workspace shell remained in loading state`);
    });
    const finalPath = new URL(page.url()).pathname;
    if (finalPath === "/login") {
      failures.push(`${path} redirected to /login`);
    }
    const bodyText = await page.locator("body").innerText();
    if (/Application error|Unhandled Runtime Error/i.test(bodyText)) {
      failures.push(`${path} rendered an application error`);
    }
    if (pageErrors.length) {
      failures.push(`${path} pageerror: ${pageErrors.join(" | ")}`);
    }
    const hrefs = await page.locator("a[href]").evaluateAll((anchors) =>
      anchors
        .map((anchor) => anchor.getAttribute("href"))
        .filter((href): href is string => Boolean(href)),
    );
    for (const href of hrefs) {
      const normalized = normalizeHref(href);
      if (normalized) discovered.add(normalized);
    }
  } catch (error) {
    failures.push(`${path} failed: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    page.off("pageerror", onPageError);
  }
}

test("all registered static routes and discoverable detail routes render", async ({ page }) => {
  test.setTimeout(120_000);
  // Route smoke intentionally checks page mounting and detail navigation. The
  // trends page also opens a long-lived SSE stream; replace it with a closed
  // test double so EventSource does not auto-reconnect on every navigation and
  // starve the API health probe. The real stream has its own feature coverage.
  await page.addInitScript(() => {
    class DisabledEventSource extends EventTarget {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;
      readonly url: string;
      readonly withCredentials = false;
      readyState = 2;
      onerror: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onopen: ((event: Event) => void) | null = null;

      constructor(url: string) {
        super();
        this.url = url;
      }

      close() {
        this.readyState = 2;
      }
    }
    Object.defineProperty(window, "EventSource", {
      configurable: true,
      writable: true,
      value: DisabledEventSource,
    });
  });
  await login(page);

  const discovered = new Set<string>();
  const failures: string[] = [];
  for (const route of staticRoutes) {
    await visitAndCollect(page, route, discovered, failures);
  }

  // Detail pages are data-dependent. Follow every detail link exposed by the
  // live list pages, then follow one additional level for nested rule/sync
  // pages. Dynamic route registration itself is separately enforced by the
  // frontend manifest unit test.
  for (let round = 0; round < 2; round += 1) {
    const candidates = [...discovered].filter((path) =>
      dynamicEntries.some((entry) => routePattern(entry.route).test(path)),
    );
    for (const path of candidates) {
      if (discovered.has(`visited:${path}`)) continue;
      discovered.add(`visited:${path}`);
      await visitAndCollect(page, path, discovered, failures);
    }
  }

  expect(failures, `Frontend route failures:\n${failures.join("\n")}`).toEqual([]);
});
