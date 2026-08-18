import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SearchPanel } from "@/components/search-panel";
import { apiRequest } from "@/lib/browser-api";

vi.mock("@/lib/browser-api", () => ({ apiRequest: vi.fn() }));
vi.mock("@/components/toast", () => ({
  useToast: () => ({ notify: vi.fn() }),
}));

const apiRequestMock = vi.mocked(apiRequest);
const historyRecord = {
  id: "query-1",
  query_text: "欧冠决赛",
  query_text_en: "Champions League final",
  platform_scope: "youtube",
  is_saved: false,
  saved_name: null,
  result_count: 1,
  created_at: "2026-08-18T08:00:00Z",
};
const englishResponse = {
  query: historyRecord,
  analysis: {
    related_hotness: 82.4,
    volume_estimate: {
      total_hits: 1,
      total_views: 1200000,
      total_likes: 24000,
      total_comments: 900,
      metric_note: "Heat is derived.",
    },
    sentiment: null,
    timeline_phases: [],
    platform_distribution: { YouTube: 1 },
    related_derivative_topics: [],
    summary: "The final is attracting strong attention.",
    process_log: [
      {
        stage: "platform_search",
        status: "completed",
        message: "Completed platform search with 1 raw result.",
      },
    ],
  },
  results: [
    {
      title: "欧冠决赛全场回顾",
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
  notice: null,
};

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SearchPanel workspaceId="workspace-1" />
    </QueryClientProvider>,
  );
}

describe("SearchPanel", () => {
  beforeEach(() => {
    apiRequestMock.mockReset();
    apiRequestMock.mockImplementation(async (path) => {
      if (path === "/trends/search?page=1&page_size=30") {
        return { items: [historyRecord] };
      }
      if (path === "/trends/search/query-1") return englishResponse;
      if (path === "/trends/search/query-1/translate") {
        return {
          ...englishResponse,
          language: "zh",
          query: { ...historyRecord, query_text: "欧冠决赛" },
          analysis: {
            ...englishResponse.analysis,
            summary: "决赛正在获得大量关注。",
            process_log: [
              {
                stage: "platform_search",
                status: "completed",
                message: "平台搜索完成。",
              },
            ],
          },
          results: [
            { ...englishResponse.results[0], title: "欧冠决赛回顾" },
          ],
        };
      }
      throw new Error(`Unexpected API path: ${path}`);
    });
  });

  it("loads history and shows measured views, engagement, and heat", async () => {
    renderPanel();

    expect(await screen.findByText("Champions League final")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Champions League final/ }));

    expect(await screen.findByText("英文分析摘要")).toBeInTheDocument();
    expect(screen.getByText("1.2M")).toBeInTheDocument();
    expect(screen.getByText("派生热度 74.2*")).toBeInTheDocument();
    expect(screen.getByText("Completed platform search with 1 raw result.")).toBeInTheDocument();
  });

  it("requests and renders a translated historical result", async () => {
    renderPanel();
    fireEvent.click(
      await screen.findByRole("button", { name: /Champions League final/ }),
    );
    await screen.findByText("英文分析摘要");

    fireEvent.change(screen.getAllByRole("combobox")[1]!, {
      target: { value: "zh" },
    });

    await waitFor(() =>
      expect(apiRequestMock).toHaveBeenCalledWith(
        "/trends/search/query-1/translate",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByText("决赛正在获得大量关注。")).toBeInTheDocument();
    expect(screen.getByText("平台搜索完成。")).toBeInTheDocument();
  });
});
