"use client";

import { CheckCircle2, CircleAlert, Clock3, ImageOff, Loader2 } from "lucide-react";

type ElementState = "available" | "archived" | "partial" | "pending" | "missing" | "failed";

export type SyncContentProgress = {
  item_index: number;
  page_index: number;
  page_item_index: number;
  page_total: number;
  listed_total: number;
  processed_total: number;
  external_id: string;
  title: string;
  status: string;
  action: string | null;
  error: string | null;
  elements: {
    title: ElementState;
    content: ElementState;
    cover: ElementState;
    metrics: ElementState;
  };
  detail_level: string;
  metric_values: Record<string, number>;
  unavailable_metrics: string[];
  counts: {
    listed?: number;
    processed?: number;
    failed?: number;
    skipped?: number;
  };
};

type Metadata = Record<string, unknown> | null | undefined;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function state(value: unknown): ElementState {
  if (
    value === "available" ||
    value === "archived" ||
    value === "partial" ||
    value === "pending" ||
    value === "missing" ||
    value === "failed"
  ) {
    return value;
  }
  return "missing";
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function readSyncContentProgress(metadata: Metadata): SyncContentProgress | null {
  const raw = metadata?.content_progress;
  if (!isRecord(raw) || !raw.external_id) return null;
  const rawElements = isRecord(raw.elements) ? raw.elements : {};
  const rawCounts = isRecord(raw.counts) ? raw.counts : {};
  const rawMetrics = isRecord(raw.metric_values) ? raw.metric_values : {};
  const metricValues = Object.fromEntries(
    Object.entries(rawMetrics).filter(
      ([, value]) => typeof value === "number" && Number.isFinite(value),
    ),
  ) as Record<string, number>;
  const unavailable = Array.isArray(raw.unavailable_metrics)
    ? raw.unavailable_metrics.filter((value): value is string => typeof value === "string")
    : [];
  return {
    item_index: numberValue(raw.item_index),
    page_index: numberValue(raw.page_index),
    page_item_index: numberValue(raw.page_item_index),
    page_total: numberValue(raw.page_total),
    listed_total: numberValue(raw.listed_total),
    processed_total: numberValue(raw.processed_total),
    external_id: stringValue(raw.external_id),
    title: stringValue(raw.title, stringValue(raw.external_id)),
    status: stringValue(raw.status),
    action: typeof raw.action === "string" ? raw.action : null,
    error: typeof raw.error === "string" ? raw.error : null,
    elements: {
      title: state(rawElements.title),
      content: state(rawElements.content),
      cover: state(rawElements.cover),
      metrics: state(rawElements.metrics),
    },
    detail_level: stringValue(raw.detail_level, "full"),
    metric_values: metricValues,
    unavailable_metrics: unavailable,
    counts: {
      listed: numberValue(rawCounts.listed),
      processed: numberValue(rawCounts.processed),
      failed: numberValue(rawCounts.failed),
      skipped: numberValue(rawCounts.skipped),
    },
  };
}

function stateLabel(value: ElementState): string {
  return {
    available: "已获取",
    archived: "已归档",
    partial: "部分",
    pending: "待获取",
    missing: "缺失",
    failed: "失败",
  }[value];
}

function ElementStatus({ label, value }: { label: string; value: ElementState }) {
  const Icon =
    value === "failed" || value === "missing"
      ? CircleAlert
      : value === "pending"
        ? Clock3
        : value === "archived"
          ? CheckCircle2
          : value === "partial"
            ? ImageOff
            : CheckCircle2;
  const tone =
    value === "failed" || value === "missing"
      ? "text-rose-300"
      : value === "pending"
        ? "text-amber-300"
        : value === "partial"
          ? "text-sky-300"
          : "text-emerald-300";
  return (
    <span className={`inline-flex items-center gap-1 rounded border border-slate-700 px-1.5 py-0.5 ${tone}`}>
      <Icon size={11} />
      {label} {stateLabel(value)}
    </span>
  );
}

export function SyncContentProgressCard({ progress }: { progress: SyncContentProgress }) {
  const counts = progress.counts;
  const metricCount = Object.keys(progress.metric_values).length;
  return (
    <div className="mt-3 rounded-lg border border-cyan-900/60 bg-slate-950/50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-medium text-slate-200">
          <Loader2 size={14} className="animate-spin text-cyan-300" />
          作品级同步详情
        </div>
        <div className="text-[11px] tabular-nums text-slate-500">
          已获取 {counts.listed ?? progress.listed_total} 条 · 已处理 {counts.processed ?? progress.processed_total} 条
          {(counts.failed ?? 0) > 0 ? ` · 失败 ${counts.failed}` : ""}
          {(counts.skipped ?? 0) > 0 ? ` · 跳过 ${counts.skipped}` : ""}
        </div>
      </div>
      <div className="mt-2 flex min-w-0 items-center gap-2 text-xs text-slate-300">
        <span className="shrink-0 rounded bg-cyan-950 px-1.5 py-0.5 text-cyan-200">
          第 {progress.page_item_index}/{progress.page_total} 条
        </span>
        <span className="truncate" title={progress.title}>{progress.title}</span>
        <span className="shrink-0 text-slate-500">#{progress.external_id}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
        <ElementStatus label="标题" value={progress.elements.title} />
        <ElementStatus label="内容" value={progress.elements.content} />
        <ElementStatus label="封面" value={progress.elements.cover} />
        <ElementStatus label={`数据${metricCount ? ` ${metricCount} 项` : ""}`} value={progress.elements.metrics} />
      </div>
      {progress.unavailable_metrics.length > 0 && (
        <p className="mt-1.5 text-[10px] text-slate-500">
          未返回指标：{progress.unavailable_metrics.join("、")}
        </p>
      )}
      {progress.error && (
        <p className="mt-1.5 truncate text-[10px] text-rose-300" title={progress.error}>
          失败原因：{progress.error}
        </p>
      )}
    </div>
  );
}
