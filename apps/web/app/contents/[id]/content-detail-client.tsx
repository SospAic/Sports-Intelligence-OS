"use client";

import type {
  ContentRecord,
  ContentSnapshotPage,
  DerivedMetricPage,
} from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Sparkles } from "lucide-react";
import Link from "next/link";
import { useWorkspace } from "@/components/app-shell";
import { ExternalImage } from "@/components/external-image";
import { TrendChart } from "@/components/trend-chart";
import {
  MetricCard,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import {
  DERIVED_METRIC_LABELS,
  formatDerivedMetricValue,
  metricQualityLabel,
} from "@/lib/metric-definitions";
import {
  formatDate,
  formatNumber,
  formatPercent,
  sourceKindLabel,
} from "@/lib/format";
import { buildChartSeries, latestObservedValue } from "@/lib/time-series";
export function ContentDetailClient({ id }: { id: string }) {
  const { workspaceId, loading: workspaceLoading } = useWorkspace();
  const item = useQuery({
    queryKey: ["content", id],
    queryFn: () =>
      apiRequest<ContentRecord>(`/contents/${id}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const snapshots = useQuery({
    queryKey: ["content-snapshots", id],
    queryFn: () =>
      apiRequest<ContentSnapshotPage>(
        `/contents/${id}/snapshots?page=1&page_size=100`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });
  const metrics = useQuery({
    queryKey: ["content-metrics", id],
    queryFn: () =>
      apiRequest<DerivedMetricPage>(
        `/contents/${id}/metrics?page=1&page_size=100`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });
  if (workspaceLoading || !workspaceId || item.isLoading)
    return (
      <main className="p-8">
        <SkeletonRows />
      </main>
    );
  if (!item.data || item.error)
    return (
      <main className="p-8">
        <StatePanel
          type="error"
          title="作品详情加载失败"
          detail={item.error?.message}
        />
      </main>
    );
  const data = item.data;
  const history = snapshots.data?.items ?? [];
  const snapshot = data.latest_snapshot;
  const latestMetrics = Array.from(
    (metrics.data?.items ?? []).reduce((latest, metric) => {
      const key = `${metric.metric_key}:${metric.window}`;
      // The API is newest-first. Keep the first observation instead of letting
      // an older historical calculation overwrite it in the UI.
      if (!latest.has(key)) latest.set(key, metric);
      return latest;
    }, new Map<string, NonNullable<typeof metrics.data>["items"][number]>()),
  ).map(([, metric]) => metric);
  const trend = buildChartSeries(history, (point) => point.view_count);
  return (
    <main className="mx-auto max-w-[1400px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow={`${data.platform.name} · ${sourceKindLabel(data.source_kind)}`}
        title={data.title}
        description={`发布于 ${formatDate(data.published_at)} · 最近观测 ${formatDate(data.last_seen_at)}`}
        actions={
          <>
            <Link
              className={secondaryButtonClass}
              href={`/generate?input_type=content&input_id=${id}`}
            >
              <Sparkles size={15} />
              生成内容
            </Link>
            <a
              className={secondaryButtonClass}
              href={data.canonical_url}
              target="_blank"
              rel="noreferrer"
            >
              查看原作品
              <ExternalLink size={15} />
            </a>
          </>
        }
      />
      {data.cover_url && (
        <ExternalImage
          src={data.cover_url}
          alt={data.title}
          className="max-h-72 w-full rounded-2xl border border-slate-800 object-cover"
        />
      )}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard
          label="播放量"
          value={formatNumber(
            latestObservedValue(history, (point) => point.view_count) ??
              snapshot?.view_count,
          )}
          hint={`24h ${formatNumber(data.view_growth_24h)}`}
        />
        <MetricCard
          label="点赞"
          value={formatNumber(
            latestObservedValue(history, (point) => point.like_count) ??
              snapshot?.like_count,
          )}
        />
        <MetricCard
          label="评论"
          value={formatNumber(
            latestObservedValue(history, (point) => point.comment_count) ??
              snapshot?.comment_count,
          )}
        />
        <MetricCard
          label="分享"
          value={formatNumber(
            latestObservedValue(history, (point) => point.share_count) ??
              snapshot?.share_count,
          )}
        />
        <MetricCard
          label="完播率"
          value={formatPercent(
            latestObservedValue(history, (point) => point.completion_rate) ??
              snapshot?.completion_rate,
          )}
        />
      </div>
      <div className="grid gap-5 xl:grid-cols-[2fr_1fr]">
        <Panel className="p-5">
          <h2 className="font-medium text-white">播放趋势</h2>
          <TrendChart data={trend} />
        </Panel>
        <Panel className="p-5">
          <h2 className="font-medium text-white">派生指标</h2>
          <div className="mt-3 divide-y divide-slate-800">
            {latestMetrics.map((metric) => (
              <div
                className="flex justify-between py-3 text-sm"
                key={metric.id}
              >
                <span className="text-slate-400">
                  {DERIVED_METRIC_LABELS[metric.metric_key] ??
                    metric.metric_key}{" "}
                  · {metric.window}
                </span>
                <span className="text-right">
                  <span className="block">
                    {formatDerivedMetricValue(metric.metric_key, metric.value)}
                  </span>
                  <span className="text-[10px] text-slate-500">
                    {metricQualityLabel(metric.metadata)}
                  </span>
                </span>
              </div>
            ))}
          </div>
          {!latestMetrics.length && (
            <p className="mt-4 text-sm text-slate-500">暂无已计算指标</p>
          )}
        </Panel>
      </div>
      <Panel className="p-5">
        <h2 className="font-medium text-white">作品说明</h2>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-400">
          {data.description || "平台未提供说明"}
        </p>
      </Panel>
    </main>
  );
}
