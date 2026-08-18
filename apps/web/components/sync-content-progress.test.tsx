// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  readSyncContentProgress,
  SyncContentProgressCard,
} from "./sync-content-progress";

const metadata = {
  content_progress: {
    item_index: 7,
    page_index: 1,
    page_item_index: 7,
    page_total: 10,
    listed_total: 10,
    processed_total: 7,
    external_id: "video-7",
    title: "决赛最后一跳",
    status: "metrics",
    action: "analytics",
    error: null,
    elements: {
      title: "available",
      content: "available",
      cover: "archived",
      metrics: "partial",
    },
    detail_level: "full",
    metric_values: { view_count: 1234 },
    unavailable_metrics: ["completion_rate"],
    counts: { listed: 10, processed: 7, failed: 1, skipped: 2 },
  },
};

describe("sync content progress", () => {
  it("normalizes structured progress metadata", () => {
    const progress = readSyncContentProgress(metadata);
    expect(progress?.title).toBe("决赛最后一跳");
    expect(progress?.elements.cover).toBe("archived");
    expect(progress?.metric_values.view_count).toBe(1234);
    expect(progress?.unavailable_metrics).toEqual(["completion_rate"]);
  });

  it("renders the current item and element-level acquisition states", () => {
    const progress = readSyncContentProgress(metadata);
    expect(progress).not.toBeNull();
    render(<SyncContentProgressCard progress={progress!} />);

    expect(screen.getByText("作品级同步详情")).toBeTruthy();
    expect(screen.getByText("决赛最后一跳")).toBeTruthy();
    expect(screen.getByText(/封面 已归档/)).toBeTruthy();
    expect(screen.getByText(/数据 1 项 部分/)).toBeTruthy();
    expect(screen.getByText(/未返回指标：completion_rate/)).toBeTruthy();
  });
});
