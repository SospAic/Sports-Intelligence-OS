"use client";

import type { ReactNode } from "react";

import { formatNumber } from "@/lib/format";
import {
  metricAvailability,
  metricConditionText,
} from "@/lib/metric-availability";

/**
 * Amber badge rendered when a gated metric field has no value because the
 * required API / login condition is not met. Never hides the data — it states
 * exactly what the user must configure.
 */
export function NeedsConditionBadge({ text }: { text: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-amber-900/60 bg-amber-950/30 px-2 py-0.5 text-xs font-medium text-amber-300"
      title={text}
    >
      <span className="size-1.5 rounded-full bg-amber-400" />
      {text}
    </span>
  );
}

/**
 * Renders a metric value according to the acquisition baseline:
 *   - real value   -> formatted number
 *   - missing + public -> "—"
 *   - missing + gated  -> amber "需要：…" badge
 *
 * Drop-in for `MetricCard` `value` (which accepts ReactNode) and for table
 * cells.
 */
export function AvailabilityValue({
  metricKey,
  value,
  format,
  className = "tabular-nums text-sm text-slate-200",
}: {
  metricKey: string;
  value: number | null | undefined;
  format?: (v: number) => string;
  className?: string;
}) {
  const present = value !== null && value !== undefined;
  const status = metricAvailability(metricKey, present);
  if (status === "data") {
    return (
      <span className={className}>
        {format ? format(value as number) : String(value)}
      </span>
    );
  }
  if (status === "no-data") {
    return <span className="text-xs text-slate-600">—</span>;
  }
  return <NeedsConditionBadge text={metricConditionText(metricKey)} />;
}

/** Small helper: returns the node to show for a metric card value. */
export function metricCardNode(
  metricKey: string,
  value: number | null | undefined,
  format: (v: number) => string,
): ReactNode {
  return (
    <AvailabilityValue
      metricKey={metricKey}
      value={value}
      format={format}
      className="text-2xl font-semibold text-white"
    />
  );
}

const TRAFFIC_SOURCES: { key: string; label: string }[] = [
  { key: "recommendation_traffic_rate", label: "推荐" },
  { key: "search_traffic_rate", label: "搜索" },
  { key: "profile_traffic_rate", label: "关注" },
];

/**
 * Renders the recommendation / search / profile traffic split for an account
 * or a single content item. Each source is a gated (`api`) metric, so when the
 * adapter returned no traffic data at all we show a single amber
 * "需要：…" badge instead of three empty bars.
 */
export function TrafficSourceBreakdown({
  split,
  format,
}: {
  split: Record<string, number | null> | undefined;
  format: (v: number) => string;
}) {
  const anyPresent = TRAFFIC_SOURCES.some((s) => split?.[s.key] != null);
  if (!anyPresent)
    return (
      <NeedsConditionBadge
        text={metricConditionText("recommendation_traffic_rate")}
      />
    );
  return (
    <div className="space-y-2">
      {TRAFFIC_SOURCES.map((s) => {
        const value = split?.[s.key];
        if (value === null || value === undefined) return null;
        return (
          <div key={s.key} className="flex items-center gap-2 text-xs">
            <span className="w-8 text-slate-400">{s.label}</span>
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-800">
              <span
                className="block h-full rounded-full bg-cyan-500"
                style={{ width: `${Math.min(Math.max(value * 100, 2), 100)}%` }}
              />
            </span>
            <span className="w-12 text-right tabular-nums text-slate-200">
              {format(value)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

type InteractionSnapshot = {
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
  favorite_count: number | null;
  share_count: number | null;
};

/**
 * Breaks an item's interactions into per-view ratios (点赞 / 评论 / 收藏 /
 * 分享 ÷ 播放). All inputs are public-browse fields, so missing values simply
 * render as "—" rather than a gated "needs-condition" badge.
 */
export function InteractionBreakdown({
  snapshot,
  format,
}: {
  snapshot: InteractionSnapshot | null;
  format: (v: number) => string;
}) {
  const views = snapshot?.view_count ?? 0;
  const items = [
    { label: "点赞率", value: snapshot?.like_count },
    { label: "评论率", value: snapshot?.comment_count },
    { label: "收藏率", value: snapshot?.favorite_count },
    { label: "分享率", value: snapshot?.share_count },
  ];
  return (
    <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {items.map((item) => {
        const rate =
          views > 0 && item.value != null ? item.value / views : null;
        return (
          <div
            key={item.label}
            className="rounded-lg border border-slate-800 bg-slate-900/40 p-3"
          >
            <p className="text-xs text-slate-400">{item.label}</p>
            <p className="mt-1 text-lg font-semibold text-slate-200">
              {rate != null ? format(rate) : "—"}
            </p>
            {item.value != null && (
              <p className="text-[10px] text-slate-500">
                {formatNumber(item.value)} 次
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
