/**
 * Shared time-range presets and helpers for the global time-range picker.
 *
 * The picker is reused across the account "作品" tab and the content list.
 * It writes a `range` preset (and optional custom `from` date) to the URL so
 * the selection is shareable and survives reloads. The computed `since` date
 * is passed to the backend `published_from` filter.
 */

export interface TimeRangePreset {
  key: string;
  label: string;
  days: number | null;
}

export const TIME_RANGE_PRESETS: TimeRangePreset[] = [
  { key: "7d", label: "近 7 天", days: 7 },
  { key: "30d", label: "近 30 天", days: 30 },
  { key: "90d", label: "近 90 天", days: 90 },
  { key: "all", label: "全部", days: null },
];

/** Convert a preset key into a `YYYY-MM-DD` lower bound, or null for "all". */
export function rangePresetToSince(key: string): string | null {
  if (key === "all") return null;
  const preset = TIME_RANGE_PRESETS.find((p) => p.key === key);
  if (!preset || preset.days === null) return null;
  const since = new Date();
  since.setUTCHours(0, 0, 0, 0);
  since.setUTCDate(since.getUTCDate() - preset.days);
  return since.toISOString().slice(0, 10);
}

/**
 * Resolve the effective `published_from` lower bound from a preset and an
 * optional explicit custom date. The preset wins unless it is "all".
 */
export function resolvePublishedFrom(
  range: string,
  customFrom: string | null,
): string | null {
  return rangePresetToSince(range) ?? customFrom ?? null;
}
