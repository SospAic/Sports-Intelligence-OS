// @vitest-environment jsdom

import type { ContentRecord } from "@sio/shared-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiRequestMock = vi.hoisted(() => vi.fn());

vi.mock("@/components/app-shell", () => ({
  useWorkspace: () => ({ workspaceId: "workspace-1" }),
}));
vi.mock("@/lib/browser-api", () => ({ apiRequest: apiRequestMock }));

import { VideoInfoModule } from "./video-info-module";

const content = {
  id: "content-1",
  title: "Tracked video",
  tags: ["sports"],
  media: {
    base: "workspace-1/account-1/content-1",
    subtitles: [{ lang: "en", file: "content-1.en.vtt" }],
  },
} as ContentRecord;

function renderModule(onChange: (value: unknown) => void) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <VideoInfoModule
        inputId="content-1"
        inputType="content"
        onChange={onChange}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiRequestMock.mockReset().mockResolvedValue(content);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        "WEBVTT\n\n00:00.000 --> 00:02.000\nFirst subtitle line\n",
    }),
  );
});

describe("VideoInfoModule subtitle material", () => {
  it("loads subtitle files into the visible preview and generation context", async () => {
    const onChange = vi.fn();
    renderModule(onChange);

    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          subtitleLangs: ["en"],
          subtitles: [{ lang: "en", text: "First subtitle line" }],
        }),
      ),
    );
    expect(
      await screen.findByText((text) => text.includes("[en] First subtitle line")),
    ).toBeInTheDocument();
  });
});
