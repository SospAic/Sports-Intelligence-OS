/**
 * Field-level acquisition contract and "needs-condition" decision logic.
 *
 * This module is the front-end realization of `docs/DATA_ACQUISITION_BASELINE.md`
 * (and AGENTS.md §4.5). The governing rule from the project owner:
 *
 *   - Data obtainable from public/anonymous browse channels MUST appear on the
 *     page. It is never hidden because its contract method happens to need a
 *     condition — once the adapter actually returns a value, we show it.
 *   - Data that genuinely requires an API key / OAuth / login authorization,
 *     and for which that condition is NOT met, must render an explicit
 *     "需要：<具体条件>" badge instead of being hidden or faked.
 *
 * Rendering precedence (mirrors baseline §4):
 *   1. hasValue            -> "data"            (show the number)
 *   2. no value + public   -> "no-data"         (show "—")
 *   3. no value + gated    -> "needs-condition" (show amber "需要：…" badge)
 */

export type AcquisitionMethod =
  | "public_browse"
  | "api"
  | "login"
  | "api_or_login";

export type MetricAvailabilityStatus = "data" | "no-data" | "needs-condition";

interface MetricContract {
  /** How the value is obtained. `public_browse` never needs a condition. */
  method: AcquisitionMethod;
  /** Shown when the field is missing AND its method requires a condition. */
  conditionText: string;
  /** Human label used in tooltips / debugging. */
  label: string;
}

/**
 * The canonical contract. Keys match the snapshot / summary field names used
 * across the API (`ContentSnapshot`, `AccountContentSummary`). When a new
 * gated field is added on the backend, add it here so the UI knows to render
 * the required condition instead of a blank.
 */
export const METRIC_CONTRACT: Record<string, MetricContract> = {
  // Public-browse fields: always available once the adapter returns them.
  follower_count: {
    method: "public_browse",
    conditionText: "",
    label: "粉丝数",
  },
  total_view_count: {
    method: "public_browse",
    conditionText: "",
    label: "总播放量",
  },
  video_count: { method: "public_browse", conditionText: "", label: "作品数" },
  engagement_rate: {
    method: "public_browse",
    conditionText: "",
    label: "互动率",
  },
  view_count: { method: "public_browse", conditionText: "", label: "播放量" },
  like_count: { method: "public_browse", conditionText: "", label: "点赞" },
  comment_count: { method: "public_browse", conditionText: "", label: "评论" },
  share_count: { method: "public_browse", conditionText: "", label: "分享" },
  favorite_count: { method: "public_browse", conditionText: "", label: "收藏" },

  // API / OAuth / private-analytics fields: gated behind a condition.
  completion_rate: {
    method: "api",
    conditionText: "配置该平台官方 API / 私有分析授权（完播率）",
    label: "完播率",
  },
  average_watch_time: {
    method: "api",
    conditionText: "配置该平台官方 API / 私有分析授权",
    label: "平均观看时长",
  },
  recommendation_traffic_rate: {
    method: "api",
    conditionText: "配置该平台官方 API / 流量来源授权",
    label: "推荐流量占比",
  },
  search_traffic_rate: {
    method: "api",
    conditionText: "配置该平台官方 API / 流量来源授权",
    label: "搜索流量占比",
  },
  profile_traffic_rate: {
    method: "api",
    conditionText: "配置该平台官方 API / 流量来源授权",
    label: "关注页流量占比",
  },
  revenue: {
    method: "api",
    conditionText: "配置该平台变现 / 收益 API 授权",
    label: "变现收入",
  },
  rpm: {
    method: "api",
    conditionText: "配置该平台变现 / 收益 API 授权",
    label: "每千次播放收益",
  },
  search_terms: {
    method: "api",
    conditionText: "配置该平台官方 API / 搜索词授权",
    label: "搜索词",
  },
};

/** Returns true when the metric value is present (not null / undefined). */
export function hasMetricValue(value: number | null | undefined): boolean {
  return value !== null && value !== undefined;
}

/**
 * Decide how a metric field should render given its contract and whether a
 * real value is present. This is the single source of truth used by both the
 * helper component and inline table cells.
 */
export function metricAvailability(
  metricKey: string,
  valuePresent: boolean,
): MetricAvailabilityStatus {
  if (valuePresent) return "data";
  const contract = METRIC_CONTRACT[metricKey];
  if (!contract || contract.method === "public_browse") return "no-data";
  return "needs-condition";
}

/** The full "需要：…" text for a gated field, or "" for public / unknown keys. */
export function metricConditionText(metricKey: string): string {
  const contract = METRIC_CONTRACT[metricKey];
  if (!contract || contract.method === "public_browse") return "";
  return `需要：${contract.conditionText}`;
}
