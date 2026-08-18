// @vitest-environment jsdom

import type { AutomationRulePage } from "@sio/shared-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiRequestMock = vi.hoisted(() => vi.fn());
const notifyMock = vi.hoisted(() => vi.fn());

vi.mock("@/components/app-shell", () => ({
  useWorkspace: () => ({ workspaceId: "workspace-1", role: "admin" }),
}));
vi.mock("@/components/toast", () => ({
  useToast: () => ({ notify: notifyMock }),
}));
vi.mock("@/lib/browser-api", () => ({ apiRequest: apiRequestMock }));

import { AutomationsClient } from "./automations-client";

const page: AutomationRulePage = {
  items: [
    {
      id: "rule-1",
      created_by: "user-1",
      name: "播放量提醒",
      description: "测试规则",
      entity_type: "content",
      trigger_type: "entity_updated",
      condition_tree: {},
      schedule: {},
      cooldown_seconds: 3600,
      deduplication_window: 3600,
      enabled: true,
      priority: 100,
      created_at: "2026-08-14T00:00:00Z",
      updated_at: "2026-08-14T00:00:00Z",
    },
  ],
  page: 1,
  page_size: 20,
  total: 1,
};

function renderClient() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AutomationsClient />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiRequestMock.mockReset().mockImplementation((path: string) =>
    path.startsWith("/automations?") ? Promise.resolve(page) : Promise.resolve({}),
  );
  notifyMock.mockReset();
});

describe("automation rule list actions", () => {
  it("shows an edit column and toggles an existing rule through PATCH", async () => {
    renderClient();

    expect(await screen.findByRole("link", { name: "编辑" })).toHaveAttribute(
      "href",
      "/automations/rule-1",
    );
    const toggle = screen.getByRole("button", { name: "停用规则" });
    await userEvent.click(toggle);

    await waitFor(() =>
      expect(apiRequestMock).toHaveBeenCalledWith(
        "/automations/rule-1",
        expect.objectContaining({
          method: "PATCH",
          csrf: true,
          body: JSON.stringify({ enabled: false }),
        }),
      ),
    );
    expect(notifyMock).toHaveBeenCalledWith("自动化规则已停用");
  });
});
