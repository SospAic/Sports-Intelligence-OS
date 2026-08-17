"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import {
  Badge,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  inputClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";

type SloMetric = {
  key: string;
  metric_kind: "derived";
  observations: number;
  successes: number;
  failures: number;
  in_progress: number;
  success_rate: number | null;
  average_latency_ms: number | null;
  latest_at: string | null;
  notes: string[];
};

type SloSummary = {
  window_minutes: number;
  generated_at: string;
  metrics: SloMetric[];
};

const labels: Record<string, string> = {
  sync_runs: "账号同步",
  external_calls: "外部调用",
  notification_attempts: "通知投递",
  task_runs: "后台任务",
  inbox_queue: "运营队列",
};

function rateLabel(rate: number | null): string {
  return rate === null ? "无结果" : `${(rate * 100).toFixed(1)}%`;
}

function tone(metric: SloMetric): "success" | "warning" | "danger" | "neutral" {
  if (metric.failures > 0) return "danger";
  if (metric.in_progress > 0) return "warning";
  if (metric.observations > 0) return "success";
  return "neutral";
}

export default function ReliabilitySloPage() {
  const { workspaceId } = useWorkspace();
  const [windowMinutes, setWindowMinutes] = useState("1440");
  const query = useQuery({
    queryKey: ["reliability-slo", workspaceId, windowMinutes],
    queryFn: () =>
      apiRequest<SloSummary>(`/reliability/slo?window_minutes=${windowMinutes}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });

  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Reliability"
        title="可靠性 SLO"
        description="按工作区窗口汇总已持久化的同步、任务、调用、通知和队列证据。"
        actions={
          <select
            className={inputClass}
            value={windowMinutes}
            onChange={(event) => setWindowMinutes(event.target.value)}
            aria-label="SLO统计窗口"
          >
            <option value="60">最近 1 小时</option>
            <option value="1440">最近 24 小时</option>
            <option value="10080">最近 7 天</option>
          </select>
        }
      />
      <Panel className="border-cyan-900/40 bg-cyan-950/10 p-4 text-sm text-cyan-100">
        这些指标是内部运行记录的派生统计，不代表未配置凭证的平台、第三方通知目标或私有
        Analytics 已经可用；没有记录时显示“无结果”，不会用 Mock 数据补齐。
        {query.data?.generated_at ? (
          <span className="ml-2 text-xs text-slate-400">
            生成于 {formatDate(query.data.generated_at)}
          </span>
        ) : null}
      </Panel>
      {query.isLoading ? (
        <Panel className="p-5">
          <SkeletonRows />
        </Panel>
      ) : query.error ? (
        <StatePanel type="error" title="SLO 数据加载失败" detail={query.error.message} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {(query.data?.metrics ?? []).map((metric) => (
            <Panel key={metric.key} className="p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-white">
                    {labels[metric.key] ?? metric.key}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">{metric.observations} 条窗口记录</p>
                </div>
                <Badge tone={tone(metric)}>{rateLabel(metric.success_rate)}</Badge>
              </div>
              <div className="mt-5 grid grid-cols-3 gap-3 text-center text-xs">
                <div className="rounded-lg bg-slate-900/70 p-3">
                  <p className="text-slate-500">成功</p>
                  <p className="mt-1 text-base text-emerald-300">{metric.successes}</p>
                </div>
                <div className="rounded-lg bg-slate-900/70 p-3">
                  <p className="text-slate-500">失败</p>
                  <p className="mt-1 text-base text-rose-300">{metric.failures}</p>
                </div>
                <div className="rounded-lg bg-slate-900/70 p-3">
                  <p className="text-slate-500">处理中</p>
                  <p className="mt-1 text-base text-amber-300">{metric.in_progress}</p>
                </div>
              </div>
              <div className="mt-4 space-y-1 text-xs text-slate-500">
                <p>
                  平均延迟：{metric.average_latency_ms === null ? "无结果" : `${metric.average_latency_ms}ms`}
                </p>
                <p>最新记录：{metric.latest_at ? formatDate(metric.latest_at) : "无结果"}</p>
                {metric.notes.map((note) => (
                  <p key={note} className="text-slate-400">
                    {note}
                  </p>
                ))}
              </div>
            </Panel>
          ))}
        </div>
      )}
    </main>
  );
}
