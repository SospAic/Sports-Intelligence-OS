export const DERIVED_METRIC_LABELS: Record<string, string> = {
  view_growth_1h: "约 1 小时播放净增",
  view_growth_6h: "约 6 小时播放净增",
  view_growth_24h: "约 24 小时播放净增",
  follower_growth_24h: "约 24 小时粉丝净增",
  engagement_rate: "可观测互动率",
  share_rate: "分享率",
  favorite_rate: "收藏率",
  view_velocity: "小时播放速度",
  view_acceleration: "播放加速度",
  median_views_30d: "账号近 30 日播放中位数",
  account_baseline_ratio: "相对账号基线",
  play_follower_ratio: "播放 / 粉丝比",
  viral_score: "高潜分",
};

export const METRIC_KIND_LABELS: Record<string, string> = {
  raw: "平台原始值",
  derived: "系统推算",
  unavailable: "平台未提供",
  partial: "部分字段推算",
};

export function metricQualityLabel(metadata: Record<string, unknown>): string {
  const quality =
    typeof metadata.quality === "string" ? metadata.quality : "derived";
  const base = METRIC_KIND_LABELS[quality] ?? "系统推算";
  const confidence = metadata.confidence_score;
  return typeof confidence === "number"
    ? `${base} · 置信度 ${Math.round(confidence * 100)}%`
    : base;
}

export function formatDerivedMetricValue(key: string, value: number): string {
  if (["engagement_rate", "share_rate", "favorite_rate"].includes(key)) {
    return `${(value * 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`;
  }
  if (key === "account_baseline_ratio" || key === "play_follower_ratio") {
    return `${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}×`;
  }
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}
