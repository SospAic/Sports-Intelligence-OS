export const ANALYTICS_PLATFORMS = ["youtube", "tiktok", "douyin", "bilibili", "web"] as const;
export const ANALYTICS_DAY_OPTIONS = [7, 30, 90] as const;
export const ANALYTICS_MODES = ["timeline", "ranking", "index", "matrix"] as const;

export type AnalyticsFilters = {
  platforms: string[];
  category: string;
  days: number;
  mode: string;
};

export const DEFAULT_ANALYTICS_FILTERS: AnalyticsFilters = {
  platforms: [],
  category: "",
  days: 30,
  mode: "timeline",
};

export function parseAnalyticsSearch(search: string): AnalyticsFilters {
  const params = new URLSearchParams(search);
  const platforms = (params.get("platforms") ?? "")
    .split(",")
    .map((platform) => platform.trim())
    .filter(
      (platform, index, all) =>
        ANALYTICS_PLATFORMS.includes(platform as (typeof ANALYTICS_PLATFORMS)[number]) &&
        all.indexOf(platform) === index,
    );
  const parsedDays = Number(params.get("days"));
  const parsedMode = params.get("mode") ?? "";
  return {
    platforms,
    category: params.get("category")?.trim() ?? "",
    days: ANALYTICS_DAY_OPTIONS.includes(parsedDays as (typeof ANALYTICS_DAY_OPTIONS)[number])
      ? parsedDays
      : DEFAULT_ANALYTICS_FILTERS.days,
    mode: ANALYTICS_MODES.includes(parsedMode as (typeof ANALYTICS_MODES)[number])
      ? parsedMode
      : DEFAULT_ANALYTICS_FILTERS.mode,
  };
}

export function writeAnalyticsSearch(filters: AnalyticsFilters): string {
  const params = new URLSearchParams();
  if (filters.platforms.length) params.set("platforms", filters.platforms.join(","));
  if (filters.category) params.set("category", filters.category);
  if (filters.days !== DEFAULT_ANALYTICS_FILTERS.days) {
    params.set("days", String(filters.days));
  }
  if (filters.mode !== DEFAULT_ANALYTICS_FILTERS.mode) params.set("mode", filters.mode);
  const query = params.toString();
  return query ? `?${query}` : "";
}
