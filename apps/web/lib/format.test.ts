import { describe, expect, it } from "vitest";

import { formatDate, formatNumber, sourceKindLabel } from "./format";

describe("dashboard formatters", () => {
  it("keeps missing metrics visibly empty", () => {
    expect(formatNumber(null)).toBe("—");
    expect(formatDate(null)).toBe("—");
  });

  it("labels mock data explicitly", () => {
    expect(sourceKindLabel("mock")).toBe("模拟数据");
    expect(sourceKindLabel("live")).toBe("实时来源");
    expect(sourceKindLabel("imported")).toBe("用户导入");
  });
});
