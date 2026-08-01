import { describe, expect, it } from "vitest";

import {
  metricAvailability,
  metricConditionText,
  METRIC_CONTRACT,
  hasMetricValue,
} from "./metric-availability";
import { rangePresetToSince, resolvePublishedFrom } from "./time-range";

describe("字段可用性契约（数据采集基线）", () => {
  it("公开浏览字段缺失时只显示占位，不要求条件", () => {
    expect(metricAvailability("view_count", false)).toBe("no-data");
    expect(metricConditionText("view_count")).toBe("");
  });

  it("公开浏览字段有值时直接展示", () => {
    expect(metricAvailability("view_count", true)).toBe("data");
  });

  it("API 依赖字段缺失时要求明确条件", () => {
    expect(metricAvailability("completion_rate", false)).toBe(
      "needs-condition",
    );
    expect(metricConditionText("completion_rate")).toContain("需要：");
    expect(metricConditionText("completion_rate")).toContain("完播率");
  });

  it("API 依赖字段有值时直接展示，不看契约方式", () => {
    // 即使契约方式标为 api，只要适配器真实返回就上页
    expect(metricAvailability("completion_rate", true)).toBe("data");
  });

  it("流量来源三类指标缺失时统一要求流量授权", () => {
    for (const key of [
      "recommendation_traffic_rate",
      "search_traffic_rate",
      "profile_traffic_rate",
    ]) {
      expect(metricAvailability(key, false)).toBe("needs-condition");
      expect(metricConditionText(key)).toContain("流量来源授权");
      expect(METRIC_CONTRACT[key]?.method).toBe("api");
    }
  });

  it("hasMetricValue 正确识别 null / undefined", () => {
    expect(hasMetricValue(null)).toBe(false);
    expect(hasMetricValue(undefined)).toBe(false);
    expect(hasMetricValue(0)).toBe(true);
    expect(hasMetricValue(0.5)).toBe(true);
  });
});

describe("全局时间范围选择器", () => {
  it("预设转换为 YYYY-MM-DD 下界", () => {
    const since = rangePresetToSince("30d");
    expect(since).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    // 30 天前的日期应早于今天
    expect(new Date(since!).getTime()).toBeLessThan(Date.now());
  });

  it("全部不设置下界", () => {
    expect(rangePresetToSince("all")).toBeNull();
    expect(rangePresetToSince("unknown")).toBeNull();
  });

  it("预设优先于自定义日期", () => {
    expect(resolvePublishedFrom("7d", "2020-01-01")).not.toBe("2020-01-01");
    expect(resolvePublishedFrom("all", "2020-01-01")).toBe("2020-01-01");
    expect(resolvePublishedFrom("all", null)).toBeNull();
  });
});
