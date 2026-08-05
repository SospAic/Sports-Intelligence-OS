"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronRight,
  Clock,
  Loader2,
  XCircle,
} from "lucide-react";
import { useWorkspace } from "@/components/app-shell";
import { BackButton } from "@/components/back-button";
import { Badge, PageHeader, Panel, StatePanel } from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { buildAccountDetailPaths } from "@/lib/admin-queries";
import { adapterErrorCodeTone } from "@/lib/adapter-errors";
import { formatDate, formatNumber } from "@/lib/format";
import {
  SyncRunDetail,
  SyncRunEvent,
  SyncRunEventLevel,
} from "@sio/shared-types";

const statusTone: Record<string, "success" | "warning" | "danger" | "info" | "neutral"> = {
  success: "success",
  degraded: "warning",
  error: "danger",
  cancelled: "neutral",
  queued: "info",
  running: "info",
  syncing: "info",
};

const eventTypeLabel: Record<string, string> = {
  stage: "阶段",
  page: "分页",
  item: "作品",
  analytics: "指标",
  external_call: "外部调用",
  warning: "警告",
  error: "错误",
  info: "信息",
  summary: "汇总",
};

const levelTone: Record<SyncRunEventLevel, "success" | "warning" | "danger" | "info"> = {
  info: "info",
  warn: "warning",
  error: "danger",
};

function durationText(startedAt: string | null, finishedAt: string | null): string | null {
  if (!startedAt) return null;
  const end = finishedAt ? new Date(finishedAt) : new Date();
  const seconds = Math.max(0, Math.round((end.getTime() - new Date(startedAt).getTime()) / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function SyncRunDetailClient({
  accountId,
  runId,
}: {
  accountId: string;
  runId: string;
}) {
  const { workspaceId } = useWorkspace();
  const paths = buildAccountDetailPaths(accountId);
  const [openEvent, setOpenEvent] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["sync-run-detail", accountId, runId],
    queryFn: () =>
      apiRequest<SyncRunDetail>(paths.syncRunDetail(runId), {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });

  const run = detail.data?.run;
  const events = detail.data?.events ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <BackButton label="返回账号" />
      </div>

      <PageHeader
        title="同步详情"
        description={run ? `运行 ${run.id}` : "加载中…"}
      />

      {detail.isLoading && (
        <Panel>
          <div className="flex items-center gap-2 p-8 text-slate-400">
            <Loader2 size={16} className="animate-spin" />
            正在加载同步记录…
          </div>
        </Panel>
      )}

      {detail.isError && (
        <StatePanel
          type="error"
          title="无法加载同步详情"
          detail="请检查网络或返回账号页重试。"
        />
      )}

      {run && (
        <Panel>
          <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
            <Summary label="状态">
              <Badge tone={statusTone[run.status] ?? "neutral"}>
                {run.status === "success"
                  ? "成功"
                  : run.status === "degraded"
                    ? "降级"
                    : run.status === "error"
                      ? "失败"
                      : run.status === "cancelled"
                        ? "已取消"
                        : run.status}
              </Badge>
            </Summary>
            <Summary label="新增 / 更新">
              <span className="text-emerald-400">{run.records_created}</span>
              <span className="text-slate-500"> / </span>
              <span className="text-cyan-300">{run.records_updated}</span>
            </Summary>
            <Summary label="已处理作品">
              {formatNumber(run.items_processed)}
              {run.items_total != null && run.items_total > 0 && (
                <span className="text-slate-500"> / {formatNumber(run.items_total)}</span>
              )}
            </Summary>
            <Summary label="耗时">
              <span className="inline-flex items-center gap-1">
                <Clock size={14} className="text-slate-500" />
                {durationText(run.started_at, run.finished_at) ?? "—"}
              </span>
            </Summary>
            <Summary label="适配器">
              <span className="font-mono text-xs text-slate-300">{run.adapter_key}</span>
            </Summary>
            <Summary label="开始时间">
              {run.started_at ? formatDate(run.started_at) : "—"}
            </Summary>
            <Summary label="完成时间">
              {run.finished_at ? formatDate(run.finished_at) : "—"}
            </Summary>
            <Summary label="失败条目">
              <span
                className={
                  (run.metadata?.items_failed as number) > 0
                    ? "text-rose-300"
                    : "text-slate-300"
                }
              >
                {String(run.metadata?.items_failed ?? 0)}
              </span>
            </Summary>
          </div>

          {run.error_message && (
            <div className="space-y-2 border-t border-slate-800 p-5">
              <div className="flex flex-wrap items-center gap-2">
                {run.error_code && (
                  <Badge tone={adapterErrorCodeTone(run.error_code)}>{run.error_code}</Badge>
                )}
                <span className="text-rose-200">同步失败</span>
              </div>
              {run.error_hint && (
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-rose-300/90">
                  <span className="font-medium text-rose-200">业务层说明：</span>
                  {run.error_hint}
                </p>
              )}
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-rose-300/90">
{run.error_detail || run.error_message}
              </pre>
            </div>
          )}

          {run.progress_message && !run.error_message && (
            <div className="border-t border-slate-800 p-5 text-sm text-slate-400">
              {run.progress_message}
            </div>
          )}
        </Panel>
      )}

      {run && (
        <Panel>
          <div className="flex items-center justify-between border-b border-slate-800 p-5">
            <h2 className="font-medium text-white">
              Tracklog（共 {events.length} 条记录）
            </h2>
            <span className="text-xs text-slate-500">按执行顺序完整记录</span>
          </div>

          {events.length === 0 ? (
            <StatePanel type="empty" title="暂无详细记录" detail="本次同步未写入逐步日志。" />
          ) : (
            <ol className="divide-y divide-slate-800">
              {events.map((event) => (
                <li key={event.id}>
                  <button
                    type="button"
                    onClick={() => setOpenEvent(openEvent === event.id ? null : event.id)}
                    className="flex w-full items-start gap-3 p-4 text-left hover:bg-slate-900/40"
                  >
                    <span className="mt-0.5">
                      {event.level === "error" ? (
                        <XCircle size={16} className="text-rose-400" />
                      ) : event.level === "warn" ? (
                        <Clock size={16} className="text-amber-400" />
                      ) : (
                        <CheckCircle2 size={16} className="text-slate-500" />
                      )}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={levelTone[event.level]}>
                          {eventTypeLabel[event.event_type] ?? event.event_type}
                        </Badge>
                        <span className="text-sm text-slate-200">{event.message}</span>
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        #{event.sequence} · {formatDate(event.created_at)}
                      </div>
                    </div>
                    <ChevronRight
                      size={16}
                      className={`mt-1 shrink-0 text-slate-600 transition-transform ${
                        openEvent === event.id ? "rotate-90" : ""
                      }`}
                    />
                  </button>
                  {openEvent === event.id && (
                    <div className="border-t border-slate-800 bg-black/20 px-4 pb-4 pl-12">
                      <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-slate-300">
{JSON.stringify(event.payload, null, 2)}
                      </pre>
                    </div>
                  )}
                </li>
              ))}
            </ol>
          )}
        </Panel>
      )}
    </div>
  );
}

function Summary({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-sm text-slate-200">{children}</div>
    </div>
  );
}
