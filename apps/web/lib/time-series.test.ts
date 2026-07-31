import { describe, expect, it } from "vitest";

import { buildChartSeries, latestObservedValue } from "./time-series";

describe("time-series", () => {
  const points = [
    { captured_at: "2026-07-28T01:00:00Z", value: 250_000 },
    { captured_at: "2026-07-28T03:00:00Z", value: null },
    { captured_at: "2026-07-28T05:00:00Z", value: 251_000 },
    { captured_at: "2026-07-29T05:00:00Z", value: 252_000 },
  ];

  it("does not convert a missing metric to zero and disambiguates intraday labels", () => {
    const result = buildChartSeries(points, (point) => point.value);
    expect(result.map((point) => point.value)).toEqual([
      250_000, 251_000, 252_000,
    ]);
    expect(result[0]!.name).not.toBe(result[1]!.name);
    expect(result[2]!.name).toContain("7");
  });

  it("returns the latest actually observed value", () => {
    expect(latestObservedValue(points.slice(1), (point) => point.value)).toBe(
      252_000,
    );
  });
});
