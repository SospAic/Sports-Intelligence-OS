import { describe, expect, it } from "vitest";

import {
  DEFAULT_ANALYTICS_FILTERS,
  parseAnalyticsSearch,
  writeAnalyticsSearch,
} from "./analytics-query";

describe("analytics URL state", () => {
  it("parses valid filters and removes duplicate/unknown platforms", () => {
    expect(
      parseAnalyticsSearch(
        "?platforms=youtube,unknown,youtube,bilibili&category=NBA&days=7&mode=matrix",
      ),
    ).toEqual({
      platforms: ["youtube", "bilibili"],
      category: "NBA",
      days: 7,
      mode: "matrix",
    });
  });

  it("falls back to safe defaults for invalid query values", () => {
    expect(parseAnalyticsSearch("?platforms=unknown&days=12&mode=bad")).toEqual(
      DEFAULT_ANALYTICS_FILTERS,
    );
  });

  it("serializes non-default filters for refreshable navigation", () => {
    expect(
      writeAnalyticsSearch({
        platforms: ["youtube", "bilibili"],
        category: "NBA",
        days: 7,
        mode: "ranking",
      }),
    ).toBe("?platforms=youtube%2Cbilibili&category=NBA&days=7&mode=ranking");
    expect(writeAnalyticsSearch(DEFAULT_ANALYTICS_FILTERS)).toBe("");
  });
});
