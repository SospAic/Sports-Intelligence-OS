"use client";

import type {
  AccountMetricsHistory,
  AccountMetricsHistoryPoint,
  AccountRecord,
  AccountSnapshotPage,
  AutomationRulePage,
  ContentRecordPage,
  SyncRunPage,
} from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Circle,
  ExternalLink,
  Loader2,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useWorkspace } from "@/components/app-shell";
import { ExternalImage } from "@/components/external-image";
import { useToast } from "@/components/toast";
import { TrendChart } from "@/components/trend-chart";
import {
  Badge,
  MetricCard,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { buildAccountDetailPaths } from "@/lib/admin-queries";
import {
  formatDate,
  formatNumber,
  formatPercent,
  sourceKindLabel,
} from "@/lib/format";
import { adapterErrorCodeTone } from "@/lib/adapter-errors";
import { operationTaskLabel } from "@/lib/operation-labels";
import { buildChartSeries, latestObservedValue } from "@/lib/time-series";

const tabs = [
  "概览",
  "作品",
  "数据趋势",
  "同步记录",
  "自动化",
  "设置",
] as const;

const syncStageLabels: Record<string, string> = {
  queued: "等待执行",
  validating: "校验账号与采集方式",
  account_profile: "同步账号资料",
  content_list: "读取作品列表",
  content_metrics: "同步作品指标",
  derived_metrics: "计算派生指标",
  retry_wait: "等待重试",
  completed: "同步完成",
  failed: "同步失败",
};

const SYNC_STAGE_ORDER = [
  "queued",
  "validating",
  "account_profile",
  "content_list",
  "content_metrics",
  "derived_metrics",
  "completed",
] as const;

const SYNC_STAGE_SHORT: Record<string, string> = {
  queued: "排队",
  validating: "校验",
  account_profile: "账号资料",
  content_list: "作品列表",
  content_metrics: "指标",
  derived_metrics: "派生",
  completed: "完成",
};

function SyncProgressPanel({
  runs,
  syncStatus,
}: {
  runs: SyncRunPage["items"] | undefined;
  syncStatus: string;
}) {
  const currentRun =
    runs?.find((run) =>
      ["syncing", "running", "queued"].includes(run.status),
    ) ?? runs?.[0];

  const currentStageIndex = currentRun
    ? SYNC_STAGE_ORDER.indexOf(
        currentRun.progress_stage as (typeof SYNC_STAGE_ORDER)[number],
      )
    : -1;

  return (
    <Panel className="border-cyan-900/60 p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Loader2 size={18} className="animate-spin text-cyan-400" />
          <h2 className="text-sm font-semibold text-white">
            {syncStatus === "queued" ? "同步排队中" : "正在同步"}
          </h2>
        </div>
        <span className="flex items-center gap-2 text-xs text-cyan-300">
          <RefreshCw size={12} className="animate-spin" />
          自动刷新中
        </span>
      </div>

      {currentRun && (
        <>
          <div className="mt-4">
            <div className="mb-1.5 flex items-center justify-between text-xs">
              <span className="text-slate-300">
                {syncStageLabels[currentRun.progress_stage] ??
                  currentRun.progress_stage}
              </span>
              <span className="tabular-nums text-cyan-300">
                {currentRun.items_total !== null && currentRun.items_total > 0
                  ? `${currentRun.items_processed}/${currentRun.items_total} · `
                  : ""}
                {currentRun.progress_percent}%
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
              <div
                className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-cyan-300 transition-all duration-700 ease-out"
                style={{
                  width: `${Math.max(currentRun.progress_percent, 2)}%`,
                }}
              />
            </div>
            {currentRun.progress_message && (
              <p className="mt-1.5 text-xs text-slate-500">
                {currentRun.progress_message}
              </p>
            )}
          </div>

          {/* Stage stepper */}
          <div className="mt-5 flex items-center gap-1">
            {SYNC_STAGE_ORDER.map((stage, index) => {
              let state: "done" | "active" | "pending" = "pending";
              if (currentRun.status === "success") {
                state = "done";
              } else if (currentRun.status === "error") {
                state = index < currentStageIndex ? "done" : "pending";
              } else if (index < currentStageIndex) {
                state = "done";
              } else if (index === currentStageIndex) {
                state = "active";
              }
              return (
                <div className="flex flex-1 flex-col items-center" key={stage}>
                  <div className="flex w-full items-center">
                    {index > 0 && (
                      <div
                        className={`h-0.5 flex-1 ${
                          state === "done" ||
                          (state === "active" && index <= currentStageIndex)
                            ? "bg-cyan-500"
                            : "bg-slate-700"
                        }`}
                      />
                    )}
                    <div className="grid size-6 shrink-0 place-items-center">
                      {state === "done" ? (
                        <CheckCircle2 size={16} className="text-emerald-400" />
                      ) : state === "active" ? (
                        <Loader2
                          size={16}
                          className="animate-spin text-cyan-400"
                        />
                      ) : (
                        <Circle size={14} className="text-slate-600" />
                      )}
                    </div>
                    {index < SYNC_STAGE_ORDER.length - 1 && (
                      <div
                        className={`h-0.5 flex-1 ${
                          index < currentStageIndex
                            ? "bg-cyan-500"
                            : "bg-slate-700"
                        }`}
                      />
                    )}
                  </div>
                  <span
                    className={`mt-1.5 text-[10px] ${
                      state === "done"
                        ? "text-slate-400"
                        : state === "active"
                          ? "font-medium text-cyan-300"
                          : "text-slate-600"
                    }`}
                  >
                    {SYNC_STAGE_SHORT[stage]}
                  </span>
                </div>
              );
            })}
          </div>

          {currentRun.error_message && (
            <div className="mt-4 rounded-lg border border-rose-900/60 bg-rose-950/30 p-3 text-xs text-rose-300">
              {currentRun.error_code && (
                <Badge tone={adapterErrorCodeTone(currentRun.error_code)}>
                  {currentRun.error_code}
                </Badge>
              )}
              {currentRun.error_message}
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

function MetricTrendChart({
  title,
  points,
  pick,
}: {
  title: string;
  points: AccountMetricsHistoryPoint[];
  pick: (p: AccountMetricsHistoryPoint) => number | null | undefined;
}) {
  const data = buildChartSeries(points, pick);
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="mb-2 text-sm text-slate-300">{title}</div>
      <TrendChart data={data} />
    </div>
  );
}

export function AccountDetailClient({ id }: { id: string }) {
  const { workspaceId, role, loading: workspaceLoading } = useWorkspace();
  const { notify } = useToast();
  const qc = useQueryClient();
  const router = useRouter();
  const [tab, setTab] = useState<(typeof tabs)[number]>("概览");
  const [historyDays, setHistoryDays] = useState(30);
  const paths = buildAccountDetailPaths(id);
  const account = useQuery({
    queryKey: ["account", id, workspaceId],
    queryFn: () =>
      apiRequest<AccountRecord>(paths.account, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
    refetchInterval: (query) => {
      const status = query.state.data?.sync_status;
      return status === "queued" || status === "syncing" ? 5000 : false;
    },
  });
  const snapshots = useQuery({
    queryKey: ["account-snapshots", id],
    queryFn: () =>
      apiRequest<AccountSnapshotPage>(paths.snapshots, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const contents = useQuery({
    queryKey: ["account-contents", id],
    queryFn: () =>
      apiRequest<ContentRecordPage>(paths.contents, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const runs = useQuery({
    queryKey: ["account-runs", id],
    queryFn: () =>
      apiRequest<SyncRunPage>(paths.syncRuns, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
    refetchInterval: () => {
      const status = account.data?.sync_status;
      return status === "queued" || status === "syncing" ? 5000 : false;
    },
  });
  const automations = useQuery({
    queryKey: ["account-automations", workspaceId],
    queryFn: () =>
      apiRequest<AutomationRulePage>(paths.automations, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const metricsHistory = useQuery({
    queryKey: ["account-metrics-history", id, historyDays],
    queryFn: () =>
      apiRequest<AccountMetricsHistory>(
        `/accounts/${id}/metrics/history?days=${historyDays}`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });
  async function sync() {
    if (!workspaceId) return;
    try {
      await apiRequest(`/accounts/${id}/sync`, {
        method: "POST",
        workspaceId,
        csrf: true,
      });
      notify("同步任务已排队");
      await qc.invalidateQueries({ queryKey: ["account"] });
      await qc.invalidateQueries({ queryKey: ["account-runs", id] });
    } catch (error) {
      if (error instanceof Error) {
        const apiErr = error as { status?: number; code?: string };
        if (apiErr.status === 422 && apiErr.code === "sync_validation_error") {
          notify(
            "该账号当前无法同步，可能适配器尚未实现或账号已停用。请检查平台配置后重试。",
            "error",
          );
          return;
        }
        notify(error.message, "error");
      } else {
        notify("同步失败", "error");
      }
    }
  }
  async function deleteAccount() {
    if (!workspaceId) return;
    if (!window.confirm("确定停用该账号并删除关联数据？此操作不可撤销。"))
      return;
    try {
      await apiRequest<void>(`/accounts/${id}`, {
        method: "DELETE",
        workspaceId,
        csrf: true,
      });
      notify("账号已删除");
      router.push("/accounts");
    } catch (error) {
      notify(error instanceof Error ? error.message : "删除失败", "error");
    }
  }
  async function save(form: FormData) {
    if (!workspaceId) return;
    try {
      const body: Record<string, unknown> = {
        display_name: form.get("display_name"),
        username: form.get("username") || null,
        description: form.get("description") || null,
        profile_url: form.get("profile_url") || null,
        avatar_url: form.get("avatar_url") || null,
        country: (form.get("country") as string)?.toUpperCase() || null,
        language: form.get("language") || null,
        sync_interval_seconds: Number(form.get("sync_interval_seconds")),
        is_active: form.get("is_active") === "on",
      };
      await apiRequest(`/accounts/${id}`, {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify(body),
      });
      notify("账号设置已保存");
      await qc.invalidateQueries({ queryKey: ["account"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "保存失败", "error");
    }
  }
  if (workspaceLoading || !workspaceId || account.isLoading)
    return (
      <main className="p-8">
        <SkeletonRows />
      </main>
    );
  if (account.error || !account.data)
    return (
      <main className="p-8">
        <StatePanel
          type="error"
          title="账号详情加载失败"
          detail={account.error?.message}
          onRetry={() => account.refetch()}
        />
      </main>
    );
  const item = account.data;
  const history = snapshots.data?.items ?? [];
  const snapshot = item.latest_snapshot;
  const followerCount = latestObservedValue(
    history,
    (point) => point.follower_count,
  );
  const totalViews = latestObservedValue(
    history,
    (point) => point.total_view_count,
  );
  const videoCount = latestObservedValue(history, (point) => point.video_count);
  const engagementRate = latestObservedValue(
    history,
    (point) => point.engagement_rate,
  );
  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <div className="flex items-start gap-4">
        {item.avatar_url ? (
          <ExternalImage
            src={item.avatar_url}
            alt={item.display_name}
            className="size-16 shrink-0 rounded-full object-cover ring-2 ring-slate-700"
          />
        ) : (
          <span className="grid size-16 shrink-0 place-items-center rounded-full bg-slate-800 text-lg font-bold text-slate-400 ring-2 ring-slate-700">
            {(item.display_name || "?").slice(0, 2)}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <PageHeader
            eyebrow={`${item.platform.name} · ${sourceKindLabel(item.source_kind)}`}
            title={item.display_name}
            description={item.description ?? `外部 ID：${item.external_id}`}
            actions={
              <>
                {item.profile_url && (
                  <a
                    className={secondaryButtonClass}
                    href={item.profile_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    平台主页
                    <ExternalLink size={15} />
                  </a>
                )}
                <button
                  className={buttonClass}
                  onClick={sync}
                  disabled={
                    ["queued", "syncing"].includes(item.sync_status) ||
                    !item.is_active ||
                    item.platform.capabilities?.implementation_status !==
                      "implemented"
                  }
                  title={
                    item.platform.capabilities?.implementation_status !==
                    "implemented"
                      ? "该平台适配器暂未实现"
                      : undefined
                  }
                >
                  <RefreshCw size={15} />
                  {item.platform.capabilities?.implementation_status !==
                  "implemented"
                    ? "不支持"
                    : "立即同步"}
                </button>
                {["owner", "admin"].includes(role ?? "") && (
                  <button
                    className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-red-900/60 bg-slate-950 px-4 text-sm font-medium text-red-400 transition hover:bg-red-950/40"
                    onClick={deleteAccount}
                  >
                    <Trash2 size={15} />
                    删除账号
                  </button>
                )}
              </>
            }
          />
        </div>
      </div>
      {item.source_kind === "mock" && (
        <div className="rounded-xl border border-amber-800 bg-amber-950/30 p-3 text-sm text-amber-200">
          此账号来自 Mock Adapter，仅用于开发与契约测试，不代表真实平台数据。
        </div>
      )}
      {["queued", "syncing"].includes(item.sync_status) && (
        <SyncProgressPanel runs={runs.data?.items} syncStatus={item.sync_status} />
      )}
      <div className="flex gap-1 overflow-x-auto border-b border-slate-800">
        {tabs.map((name) => (
          <button
            key={name}
            onClick={() => setTab(name)}
            className={`whitespace-nowrap border-b-2 px-4 py-3 text-sm ${tab === name ? "border-cyan-400 text-cyan-300" : "border-transparent text-slate-500"}`}
          >
            {name}
          </button>
        ))}
      </div>
      {tab === "概览" && (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="粉丝数"
              value={formatNumber(followerCount ?? snapshot?.follower_count)}
              hint={`24h ${formatNumber(item.follower_growth_24h)}`}
            />
            <MetricCard
              label="总播放量"
              value={formatNumber(totalViews ?? snapshot?.total_view_count)}
            />
            <MetricCard
              label="作品数"
              value={formatNumber(videoCount ?? snapshot?.video_count)}
            />
            <MetricCard
              label="互动率"
              value={formatPercent(engagementRate ?? snapshot?.engagement_rate)}
            />
          </div>
          <Panel className="p-5">
            <h2 className="font-medium text-white">
              粉丝趋势（最近 {historyDays} 天）
            </h2>
            <MetricTrendChart
              title="粉丝数"
              points={metricsHistory.data?.points ?? []}
              pick={(p) => p.follower_count}
            />
          </Panel>
        </>
      )}
      {tab === "作品" && (
        <Panel>
          <div className="border-b border-slate-800 p-5">
            <h2 className="font-medium text-white">最近作品</h2>
          </div>
          {contents.data?.items.length ? (
            <div className="divide-y divide-slate-800">
              {contents.data.items.map((content) => (
                <Link
                  href={`/contents/${content.id}`}
                  className="flex items-center gap-4 p-4 hover:bg-slate-900/50"
                  key={content.id}
                >
                  {content.cover_url ? (
                    <ExternalImage
                      src={content.cover_url}
                      alt=""
                      className="h-14 w-24 shrink-0 rounded-lg object-cover ring-1 ring-slate-700"
                    />
                  ) : null}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-slate-200">
                      {content.title}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {formatDate(content.published_at)}
                    </p>
                  </div>
                  <span className="shrink-0 text-sm text-slate-400">
                    {formatNumber(content.latest_snapshot?.view_count)} 播放
                  </span>
                </Link>
              ))}
            </div>
          ) : (
            <StatePanel
              type="empty"
              title="尚无作品"
              detail="运行账号同步后，Adapter 返回的作品会出现在这里。"
            />
          )}
        </Panel>
      )}
      {tab === "数据趋势" && (
        <Panel className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-medium text-white">账号历史趋势</h2>
            <div className="flex flex-wrap gap-2">
              {[30, 90, 180, 365].map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setHistoryDays(d)}
                  className={historyDays === d ? buttonClass : secondaryButtonClass}
                >
                  {d} 天
                </button>
              ))}
            </div>
          </div>
          <p className="mt-1 text-xs text-slate-400">
            共 {metricsHistory.data?.points.length ?? 0} 个快照（最近 {historyDays} 天）
          </p>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <MetricTrendChart
              title="粉丝数"
              points={metricsHistory.data?.points ?? []}
              pick={(p) => p.follower_count}
            />
            <MetricTrendChart
              title="总播放量"
              points={metricsHistory.data?.points ?? []}
              pick={(p) => p.total_view_count}
            />
            <MetricTrendChart
              title="作品数"
              points={metricsHistory.data?.points ?? []}
              pick={(p) => p.video_count}
            />
          </div>
        </Panel>
      )}
      {tab === "同步记录" && (
        <Panel>
          <div className="flex items-center justify-between border-b border-slate-800 p-5">
            <h2 className="font-medium text-white">
              同步记录（共 {runs.data?.total ?? 0} 次，显示最近 20 次）
            </h2>
            {["queued", "syncing"].includes(item.sync_status) && (
              <span className="flex items-center gap-2 text-xs text-cyan-300">
                <RefreshCw size={12} className="animate-spin" />
                同步进行中，自动刷新…
              </span>
            )}
          </div>
          <div className="divide-y divide-slate-800">
            {runs.data?.items.map((run) => {
              const duration =
                run.started_at && run.finished_at
                  ? Math.round(
                      (new Date(run.finished_at).getTime() -
                        new Date(run.started_at).getTime()) /
                        1000,
                    )
                  : null;
              return (
                <div className="p-4" key={run.id}>
                  <div className="flex flex-wrap items-center gap-3 text-sm">
                    <Badge
                      tone={
                        run.status === "success"
                          ? "success"
                          : run.status === "error"
                            ? "danger"
                            : "info"
                      }
                    >
                      {run.status === "success"
                        ? "成功"
                        : run.status === "error"
                          ? "失败"
                          : ["syncing", "running"].includes(run.status)
                            ? "同步中"
                            : run.status === "queued"
                              ? "排队中"
                              : run.status}
                    </Badge>
                    <span className="text-slate-400">
                      {formatDate(run.started_at)}
                    </span>
                    {duration !== null && (
                      <span className="text-xs text-slate-500">
                        耗时{" "}
                        {duration < 60
                          ? `${duration}s`
                          : `${Math.floor(duration / 60)}m ${duration % 60}s`}
                      </span>
                    )}
                    <span className="ml-auto text-xs text-slate-500">
                      {operationTaskLabel(run.adapter_key)}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-4 text-xs text-slate-400">
                    <span>
                      新增{" "}
                      <strong className="text-emerald-400">
                        {run.records_created}
                      </strong>
                    </span>
                    <span>
                      更新{" "}
                      <strong className="text-cyan-300">
                        {run.records_updated}
                      </strong>
                    </span>
                    {run.error_message && (
                      <span className="text-rose-400">
                        {run.error_code && (
                          <Badge tone={adapterErrorCodeTone(run.error_code)}>
                            {run.error_code}
                          </Badge>
                        )}{" "}
                        {run.error_message}
                      </span>
                    )}
                  </div>
                  <div
                    className="mt-3"
                    aria-label={`同步进度 ${run.progress_percent}%`}
                  >
                    <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
                      <span className="text-slate-300">
                        {syncStageLabels[run.progress_stage] ??
                          run.progress_stage}
                      </span>
                      <span className="tabular-nums text-slate-500">
                        {run.items_total !== null && run.items_total > 0
                          ? `${run.items_processed}/${run.items_total} · `
                          : run.items_processed > 0
                            ? `已处理 ${run.items_processed} · `
                            : ""}
                        {run.progress_percent}%
                      </span>
                    </div>
                    <progress
                      className="sync-progress h-1.5 w-full overflow-hidden rounded-full"
                      value={run.progress_percent}
                      max={100}
                    />
                    {run.progress_message && (
                      <p className="mt-1.5 text-xs text-slate-500">
                        {run.progress_message}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {!runs.data?.items.length && (
            <StatePanel
              type="empty"
              title="暂无同步记录"
              detail="点击「立即同步」开始首次数据抓取。"
            />
          )}
        </Panel>
      )}
      {tab === "自动化" && (
        <Panel>
          <div className="divide-y divide-slate-800">
            {automations.data?.items.map((rule) => (
              <Link
                href={`/automations/${rule.id}`}
                className="flex justify-between p-4 hover:bg-slate-900/50"
                key={rule.id}
              >
                <span>{rule.name}</span>
                <Badge tone={rule.enabled ? "success" : "neutral"}>
                  {rule.enabled ? "启用" : "停用"}
                </Badge>
              </Link>
            ))}
          </div>
          {!automations.data?.items.length && (
            <StatePanel
              type="empty"
              title="暂无账号自动化"
              detail="规则适用于同类型实体，具体账号可在条件中限定。"
            />
          )}
        </Panel>
      )}
      {tab === "设置" && (
        <form
          action={save}
          className="max-w-2xl space-y-4 rounded-2xl border border-slate-800 bg-slate-950/70 p-6"
        >
          <label className="grid gap-2 text-sm">
            显示名称
            <input
              name="display_name"
              defaultValue={item.display_name}
              className={inputClass}
              disabled={!["owner", "admin", "editor"].includes(role ?? "")}
            />
          </label>
          <label className="grid gap-2 text-sm">
            用户名
            <input
              name="username"
              defaultValue={item.username ?? ""}
              placeholder="平台用户名"
              className={inputClass}
              disabled={!["owner", "admin", "editor"].includes(role ?? "")}
            />
          </label>
          <label className="grid gap-2 text-sm">
            简介
            <textarea
              name="description"
              defaultValue={item.description ?? ""}
              rows={3}
              maxLength={10000}
              placeholder="账号简介或备注"
              className={inputClass}
            />
          </label>
          <div className="grid grid-cols-2 gap-4">
            <label className="grid gap-2 text-sm">
              个人主页
              <input
                name="profile_url"
                type="url"
                defaultValue={item.profile_url ?? ""}
                placeholder="https://..."
                className={inputClass}
              />
            </label>
            <label className="grid gap-2 text-sm">
              头像链接
              <input
                name="avatar_url"
                type="url"
                defaultValue={item.avatar_url ?? ""}
                placeholder="https://..."
                className={inputClass}
              />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <label className="grid gap-2 text-sm">
              国家/地区
              <input
                name="country"
                defaultValue={item.country ?? ""}
                maxLength={2}
                placeholder="CN / US"
                className={inputClass}
              />
            </label>
            <label className="grid gap-2 text-sm">
              语言
              <input
                name="language"
                defaultValue={item.language ?? ""}
                maxLength={16}
                placeholder="zh / en"
                className={inputClass}
              />
            </label>
          </div>
          <label className="grid gap-2 text-sm">
            同步周期（秒）
            <input
              name="sync_interval_seconds"
              type="number"
              min="300"
              max="604800"
              defaultValue={item.sync_interval_seconds}
              className={inputClass}
            />
          </label>
          <p className="text-xs text-slate-500">
            平台 API 凭证请在「设置 → 平台管理」中统一配置。
          </p>
          <label className="flex items-center gap-2 text-sm">
            <input
              name="is_active"
              type="checkbox"
              defaultChecked={item.is_active}
            />
            启用监控
          </label>
          <button className={buttonClass}>
            <Save size={15} />
            保存设置
          </button>
        </form>
      )}
    </main>
  );
}
