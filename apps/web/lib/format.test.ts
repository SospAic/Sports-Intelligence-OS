import { describe, expect, it } from "vitest";

import { formatDate, formatNumber, sourceKindLabel } from "./format";

describe("dashboard formatters", () => {
  it("keeps missing metrics visibly empty", () => {
    expect(formatNumber(null)).toBe("—");
    expect(formatDate(null)).toBe("—");
  });

  it("labels source kinds", () => {
    expect(sourceKindLabel("live")).toBe("实时来源");
    expect(sourceKindLabel("imported")).toBe("用户导入");
    expect(sourceKindLabel("unknown")).toBe("unknown");
  });
});
