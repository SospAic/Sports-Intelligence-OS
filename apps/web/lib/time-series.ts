export type TimeSeriesPoint = {
  captured_at: string;
};

export type ChartPoint = {
  name: string;
  value: number;
  timestamp: string;
};

/**
 * Build a truthful chart series: missing observations stay missing and are
 * omitted; duplicate calendar labels receive a time component instead of
 * becoming several indistinguishable points on the same day.
 */
export function buildChartSeries<T extends TimeSeriesPoint>(
  items: T[],
  valueOf: (item: T) => number | null | undefined,
): ChartPoint[] {
  const valid = items
    .map((item) => ({
      item,
      value: valueOf(item),
      date: new Date(item.captured_at),
    }))
    .filter(
      (entry): entry is { item: T; value: number; date: Date } =>
        entry.value !== null &&
        entry.value !== undefined &&
        Number.isFinite(entry.value) &&
        !Number.isNaN(entry.date.getTime()),
    )
    .sort((left, right) => left.date.getTime() - right.date.getTime());

  const dayCounts = new Map<string, number>();
  for (const entry of valid) {
    const day = entry.date.toLocaleDateString("zh-CN", {
      month: "numeric",
      day: "numeric",
    });
    dayCounts.set(day, (dayCounts.get(day) ?? 0) + 1);
  }

  return valid.map(({ date, value }) => {
    const day = date.toLocaleDateString("zh-CN", {
      month: "numeric",
      day: "numeric",
    });
    const name =
      (dayCounts.get(day) ?? 0) > 1
        ? date.toLocaleString("zh-CN", {
            month: "numeric",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          })
        : day;
    return { name, value, timestamp: date.toISOString() };
  });
}

export function latestObservedValue<T extends TimeSeriesPoint>(
  items: T[],
  valueOf: (item: T) => number | null | undefined,
): number | null {
  const newestFirst = [...items].sort(
    (left, right) =>
      new Date(right.captured_at).getTime() -
      new Date(left.captured_at).getTime(),
  );
  for (const item of newestFirst) {
    const value = valueOf(item);
    if (value !== null && value !== undefined && Number.isFinite(value))
      return value;
  }
  return null;
}
