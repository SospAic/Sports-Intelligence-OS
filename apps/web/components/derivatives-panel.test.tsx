import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DerivativesPanel } from "@/components/derivatives-panel";
import { apiRequest } from "@/lib/browser-api";

vi.mock("@/lib/browser-api", () => ({ apiRequest: vi.fn() }));
vi.mock("@/components/toast", () => ({
  useToast: () => ({ notify: vi.fn() }),
}));

const apiRequestMock = vi.mocked(apiRequest);
const run = {
  id: "run-1",
  source_topic_id: "topic-1",
  source_query: "欧冠决赛",
  source_query_en: "Champions League final",
  platform: "youtube",
  status: "completed",
  process_log: [
    {
      stage: "platform_search",
      status: "completed",
      message: "Platform search completed with 1 raw result.",
    },
  ],
  result_count: 1,
  notice: null,
  created_at: "2026-08-18T08:00:00Z",
};
const detail = {
  ...run,
  items: [
    {
      id: "angle-1",
      kind: "existing_on_platform",
      angle: "深度解析",
      angle_en: "Deep analysis",
      title: "欧冠决赛 · 深度解析",
      title_en: "Champions League final · Deep analysis",
      description: "已有平台角度",
      description_en: "Existing platform angle",
      predicted_heat_score: 76,
      evidence: { sample_count: 1 },
      ai_rationale: null,
      ai_rationale_en: null,
      status: "suggested",
      confidence: 0.8,
    },
  ],
  source_results: [
    {
      title: "欧冠决赛回顾",
      title_en: "Champions League final recap",
      author: "Sports Desk",
      view_count: 1200000,
      like_count: 24000,
      comment_count: 900,
      heat_score: 74.2,
      platform: "youtube",
    },
  ],
  language: "en",
};
const generated = {
  status: "completed",
  notice: null,
  run_id: "run-2",
  process_log: [
    {
      stage: "angle_generation",
      status: "completed",
      message: "Persisted 1 derivative angle result for this run.",
    },
  ],
  items: [
    {
      ...detail.items[0],
      id: "angle-2",
      title_en: "Champions League final · Tactical breakdown",
      angle_en: "Tactical breakdown",
    },
  ],
  source_results: detail.source_results,
};

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <DerivativesPanel workspaceId="workspace-1" />
    </QueryClientProvider>,
  );
}

describe("DerivativesPanel", () => {
  beforeEach(() => {
    apiRequestMock.mockReset();
    apiRequestMock.mockImplementation(async (path) => {
      if (path === "/trends/topics?page=1&page_size=50") {
        return {
          items: [
            {
              id: "topic-1",
              title: "欧冠决赛",
              platform: "youtube",
              heat_score: 88,
            },
          ],
        };
      }
      if (path === "/trends/derivatives/runs?page=1&page_size=30") {
        return { items: [run] };
      }
      if (path === "/trends/derivatives/generate") return generated;
      if (path === "/trends/derivatives/runs/run-1") return detail;
      if (path === "/trends/derivatives/runs/run-1/translate") {
        return {
          ...detail,
          language: "zh",
          process_log: [
            {
              stage: "platform_search",
              status: "completed",
              message: "平台搜索完成。",
            },
          ],
          items: [{ ...detail.items[0], title_en: "欧冠决赛·深度解析" }],
          source_results: [{ ...detail.source_results[0], title_en: "欧冠决赛回顾" }],
        };
      }
      throw new Error(`Unexpected API path: ${path}`);
    });
  });

  it("loads a saved derivative run with process and source metrics", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: /Champions League final/ }));
    expect(await screen.findByText("来源搜索结果")).toBeInTheDocument();
    expect(screen.getByText("浏览量 1.2M")).toBeInTheDocument();
    expect(screen.getByText("派生热度 74.2*")).toBeInTheDocument();
    expect(screen.getByText("Platform search completed with 1 raw result.")).toBeInTheDocument();
  });

  it("translates a saved run without losing its metrics", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /Champions League final/ }));
    await screen.findByText("来源搜索结果");

    fireEvent.change(screen.getAllByRole("combobox")[1]!, {
      target: { value: "zh" },
    });
    await waitFor(() =>
      expect(apiRequestMock).toHaveBeenCalledWith(
        "/trends/derivatives/runs/run-1/translate",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByText("平台搜索完成。")).toBeInTheDocument();
    expect(screen.getByText("派生热度 74.2*")).toBeInTheDocument();
  });

  it("renders the generation response even before the detail query settles", async () => {
    renderPanel();

    await screen.findByRole("option", { name: /欧冠决赛/ });
    fireEvent.click(await screen.findByRole("button", { name: "生成衍生角度" }));

    expect(await screen.findByText("Champions League final · Tactical breakdown")).toBeInTheDocument();
    expect(screen.getByText("Persisted 1 derivative angle result for this run.")).toBeInTheDocument();
  });
});
