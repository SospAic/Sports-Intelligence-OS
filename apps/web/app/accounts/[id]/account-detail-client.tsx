"use client";

import type {
  AccountContentSummary,
  AccountMetricsHistory,
  AccountMetricsHistoryPoint,
  AccountRecord,
  AccountSnapshotPage,
  AutomationRulePage,
  ContentRecordPage,
  SyncRunPage,
} from "@sio/shared-types";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  CheckCircle2,
  Circle,
  ExternalLink,
  Film,
  Loader2,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import { AccountAvatar } from "@/components/account-avatar";
import { ExternalImage } from "@/components/external-image";
import { SyncSettingsModal } from "@/components/sync-settings-modal";
import {
  NeedsConditionBadge,
  TrafficSourceBreakdown,
  metricCardNode,
} from "@/components/metric-availability";
import { TimeRangePicker } from "@/components/time-range-picker";
import { TerminateButton } from "@/components/terminate-button";
import { useToast } from "@/components/toast";
import { BackButton } from "@/components/back-button";
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
import { contentCoverUrl } from "@/lib/media";
import {
  metricConditionText,
  metricAvailability,
} from "@/lib/metric-availability";
import { resolvePublishedFrom } from "@/lib/time-range";
import { useUrlState } from "@/lib/use-persisted-state";
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
  onTerminate,
  cancelling,
}: {
  runs: SyncRunPage["items"] | undefined;
  syncStatus: string;
  onTerminate?: () => void;
  cancelling?: boolean;
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
        <span className="flex items-center gap-3">
          {onTerminate && (
            <TerminateButton
              size="sm"
              onTerminate={onTerminate}
              busy={cancelling}
              label="终止任务"
              title="终止正在进行的同步任务"
            />
          )}
          <span className="flex items-center gap-2 text-xs text-cyan-300">
            <RefreshCw size={12} className="animate-spin" />
            自动刷新中
          </span>
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
            <div className="mt-4 space-y-3 rounded-lg border border-rose-900/60 bg-rose-950/30 p-3 text-xs text-rose-300">
              <div className="flex flex-wrap items-center gap-2">
                {currentRun.error_code && (
                  <Badge tone={adapterErrorCodeTone(currentRun.error_code)}>
                    {currentRun.error_code}
                  </Badge>
                )}
                <span className="font-medium text-rose-200">同步失败</span>
              </div>
              {currentRun.error_hint && (
                <div>
                  <p className="mb-1 font-medium text-rose-200">业务层说明与处置建议</p>
                  <p className="whitespace-pre-wrap leading-relaxed">{currentRun.error_hint}</p>
                </div>
              )}
              <div>
                <p className="mb-1 font-medium text-rose-200">代码级错误详情</p>
                <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-black/40 p-2 font-mono text-[11px] leading-relaxed text-rose-300/90">
{currentRun.error_detail || currentRun.error_message}
                </pre>
              </div>
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

function contentEngagementRate(
  content: ContentRecordPage["items"][number],
): number | null {
  const snap = content.latest_snapshot;
  const views = snap?.view_count ?? 0;
  if (!snap || !views) return null;
  const interactions =
    (snap.like_count ?? 0) +
    (snap.comment_count ?? 0) +
    (snap.share_count ?? 0) +
    (snap.favorite_count ?? 0);
  return interactions / views;
}

function dominantTrafficSource(
  content: ContentRecordPage["items"][number],
): { label: string; tone: "info" | "success" | "warning" } | null {
  const snap = content.latest_snapshot;
  if (!snap) return null;
  const candidates = [
    {
      key: "recommendation",
      value: snap.recommendation_traffic_rate ?? 0,
      label: "推荐",
      tone: "info" as const,
    },
    {
      key: "search",
      value: snap.search_traffic_rate ?? 0,
      label: "搜索",
      tone: "success" as const,
    },
    {
      key: "profile",
      value: snap.profile_traffic_rate ?? 0,
      label: "关注",
      tone: "warning" as const,
    },
  ];
  const best = candidates.reduce((a, b) => (b.value > a.value ? b : a));
  if (best.value <= 0) return null;
  return { label: best.label, tone: best.tone };
}

function formatWatchTime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const total = Math.round(seconds);
  if (total < 60) return `${total}秒`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return rest ? `${minutes}分${rest}秒` : `${minutes}分`;
}

const CONTENT_SORT_OPTIONS: { key: string; label: string }[] = [
  { key: "published_at", label: "发布时间" },
  { key: "view_count", label: "播放量" },
  { key: "like_count", label: "点赞" },
  { key: "comment_count", label: "评论" },
  { key: "share_count", label: "分享" },
  { key: "completion_rate", label: "完播率" },
  { key: "engagement_rate", label: "互动率" },
];

function ContentTable({
  rows,
  total,
  page,
  pageSize,
  onPageChange,
}: {
  rows: ContentRecordPage["items"];
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}) {
  const columns = useMemo<
    ColumnDef<ContentRecordPage["items"][number], unknown>[]
  >(
    () => [
      {
        id: "cover",
        header: "",
        enableSorting: false,
        cell: ({ row }) => {
          const cover = contentCoverUrl(row.original);
          return cover ? (
            <ExternalImage
              src={cover}
              alt=""
              className="h-12 w-20 shrink-0 rounded-md object-cover ring-1 ring-slate-700"
            />
          ) : (
            <span className="grid h-12 w-20 place-items-center rounded-md bg-slate-800 text-slate-600">
              <Film size={16} />
            </span>
          );
        },
      },
      {
        id: "title",
        header: "标题",
        accessorFn: (row) => row.title,
        cell: ({ row }) => (
          <Link
            href={`/contents/${row.original.id}`}
            className="block max-w-[280px] truncate text-sm text-slate-200 hover:text-cyan-300"
          >
            {row.original.title}
          </Link>
        ),
      },
      {
        id: "published_at",
        header: "发布时间",
        accessorFn: (row) => row.published_at ?? "",
        cell: ({ row }) => (
          <span className="text-xs text-slate-400">
            {formatDate(row.original.published_at)}
          </span>
        ),
      },
      {
        id: "view_count",
        header: "播放",
        accessorFn: (row) => row.latest_snapshot?.view_count ?? 0,
        cell: ({ row }) => (
          <span className="tabular-nums text-sm text-slate-200">
            {formatNumber(row.original.latest_snapshot?.view_count)}
          </span>
        ),
      },
      {
        id: "like_count",
        header: "点赞",
        accessorFn: (row) => row.latest_snapshot?.like_count ?? 0,
        cell: ({ row }) => (
          <span className="tabular-nums text-sm text-slate-400">
            {formatNumber(row.original.latest_snapshot?.like_count)}
          </span>
        ),
      },
      {
        id: "comment_count",
        header: "评论",
        accessorFn: (row) => row.latest_snapshot?.comment_count ?? 0,
        cell: ({ row }) => (
          <span className="tabular-nums text-sm text-slate-400">
            {formatNumber(row.original.latest_snapshot?.comment_count)}
          </span>
        ),
      },
      {
        id: "completion_rate",
        header: "完播率",
        accessorFn: (row) => row.latest_snapshot?.completion_rate ?? 0,
        cell: ({ row }) => {
          const value = row.original.latest_snapshot?.completion_rate;
          const status = metricAvailability(
            "completion_rate",
            value !== null && value !== undefined,
          );
          if (status === "needs-condition")
            return (
              <NeedsConditionBadge
                text={metricConditionText("completion_rate")}
              />
            );
          if (value === null || value === undefined)
            return <span className="text-xs text-slate-600">—</span>;
          const weak = value < 0.15;
          return (
            <span
              className={`tabular-nums text-sm ${weak ? "text-rose-400" : "text-emerald-400"}`}
            >
              {formatPercent(value)}
            </span>
          );
        },
      },
      {
        id: "engagement_rate",
        header: "互动率",
        accessorFn: (row) => contentEngagementRate(row) ?? 0,
        cell: ({ row }) => {
          const value = contentEngagementRate(row.original);
          if (value === null)
            return <span className="text-xs text-slate-600">—</span>;
          const weak = value < 0.03;
          return (
            <span
              className={`tabular-nums text-sm ${weak ? "text-amber-400" : "text-cyan-300"}`}
            >
              {formatPercent(value)}
            </span>
          );
        },
      },
      {
        id: "traffic_source",
        header: "主导流量",
        enableSorting: false,
        cell: ({ row }) => {
          const snap = row.original.latest_snapshot;
          const anyTraffic = [
            snap?.recommendation_traffic_rate,
            snap?.search_traffic_rate,
            snap?.profile_traffic_rate,
          ].some((v) => v !== null && v !== undefined);
          if (!anyTraffic)
            return (
              <NeedsConditionBadge
                text={metricConditionText("recommendation_traffic_rate")}
              />
            );
          const src = dominantTrafficSource(row.original);
          if (!src) return <span className="text-xs text-slate-600">—</span>;
          return <Badge tone={src.tone}>{src.label}</Badge>;
        },
      },
      {
        id: "view_growth_24h",
        header: "近24h增量",
        accessorFn: (row) => row.view_growth_24h ?? 0,
        cell: ({ row }) => {
          const value = row.original.view_growth_24h;
          if (!value) return <span className="text-xs text-slate-600">—</span>;
          return (
            <span
              className={`tabular-nums text-sm ${value > 0 ? "text-emerald-400" : "text-slate-400"}`}
            >
              +{formatNumber(value)}
            </span>
          );
        },
      },
    ],
    [],
  );

  return (
    <DataTable
      data={rows}
      columns={columns}
      total={total}
      page={page}
      pageSize={pageSize}
      onPageChange={onPageChange}
      empty="尚无作品数据"
    />
  );
}

export function AccountDetailClient({ id }: { id: string }) {
  const { workspaceId, role, loading: workspaceLoading } = useWorkspace();
  const { notify } = useToast();
  const qc = useQueryClient();
  const router = useRouter();
  const [tab, setTab] = useState<(typeof tabs)[number]>("概览");
  const [historyDays, setHistoryDays] = useState(30);
  const [range, setRange] = useUrlState("range", "all");
  const [from, setFrom] = useUrlState("from", "");
  const [contentSort, setContentSort] = useUrlState("csort", "published_at");
  const publishedFrom = resolvePublishedFrom(range, from || null);
  const [contentPage, setContentPage] = useState(1);
  const [contentPageSize, setContentPageSize] = useState(20);
  const [cancelling, setCancelling] = useState(false);
  const [syncTarget, setSyncTarget] = useState<AccountRecord | null>(null);
  const paths = buildAccountDetailPaths(id);
  const contentsPath = buildAccountDetailPaths(id, {
    sort: contentSort,
    publishedFrom,
    page: contentPage,
    pageSize: contentPageSize,
  }).contents;
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
    queryKey: ["account-contents", id, contentsPath],
    queryFn: () =>
      apiRequest<ContentRecordPage>(contentsPath, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
    placeholderData: keepPreviousData,
  });
  const contentSummary = useQuery({
    queryKey: ["account-content-summary", id],
    queryFn: () =>
      apiRequest<AccountContentSummary>(`/accounts/${id}/content-summary`, {
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
  const activeRun = runs.data?.items?.find((r) =>
    ["queued", "running", "syncing"].includes(r.status),
  );
  const activeRunId = activeRun?.id;
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
  async function cancelSync(runId?: string) {
    if (!workspaceId || !runId) return;
    setCancelling(true);
    try {
      await apiRequest(`/accounts/${id}/sync/${runId}/cancel`, {
        method: "POST",
        workspaceId,
        csrf: true,
      });
      notify("已发送终止请求，任务将尽快停止");
      await qc.invalidateQueries({ queryKey: ["account"] });
      await qc.invalidateQueries({ queryKey: ["account-runs", id] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "终止失败", "error");
    } finally {
      setCancelling(false);
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
  const totalViews =
    latestObservedValue(history, (point) => point.total_view_count) ??
    contentSummary.data?.account_total_views ??
    snapshot?.total_view_count;
  const videoCount = latestObservedValue(history, (point) => point.video_count);
  const engagementRate = latestObservedValue(
    history,
    (point) => point.engagement_rate,
  );
  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <BackButton />
      <div className="flex items-start gap-4">
        <AccountAvatar
          url={`/accounts/${item.id}/avatar`}
          remoteUrl={item.avatar_url}
          name={item.display_name}
          className="size-16 shrink-0 rounded-full object-cover ring-2 ring-slate-700"
          fallbackClassName="grid size-16 shrink-0 place-items-center rounded-full bg-slate-800 text-lg font-bold text-slate-400 ring-2 ring-slate-700"
        />
        <div className="min-w-0 flex-1">
          <PageHeader
            eyebrow={`${item.platform.name} · ${sourceKindLabel(item.source_kind)}`}
            title={
              item.is_verified
                ? `${item.display_name} ✓`
                : item.display_name
            }
            description={undefined}
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
                {item.platform.capabilities?.implementation_status !==
                "implemented" ? (
                  <button
                    className={buttonClass}
                    disabled
                    title="该平台适配器暂未实现"
                  >
                    <RefreshCw size={15} />
                    不支持
                  </button>
                ) : ["queued", "syncing"].includes(item.sync_status) ? (
                  <TerminateButton
                    onTerminate={() => cancelSync(activeRunId)}
                    busy={cancelling}
                    title="终止正在进行的同步任务"
                  />
                ) : (
                  <>
                    <button
                      className={buttonClass}
                      onClick={() => setSyncTarget(item)}
                      disabled={!item.is_active}
                    >
                      <RefreshCw size={15} />
                      立即同步
                    </button>
                  </>
                )}
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
      <section className="rounded-2xl border border-slate-800 bg-slate-950/40 p-4">
        <div className="flex flex-wrap items-center gap-2">
          {item.is_verified ? (
            <Badge tone="success">
              <CheckCircle2 size={14} className="mr-1 inline" />
              官方认证
            </Badge>
          ) : (
            <Badge tone="neutral">未认证</Badge>
          )}
          {item.country ? (
            <Badge tone="info">国家 / 地区：{item.country}</Badge>
          ) : null}
          <Badge tone="neutral">外部 ID：{item.external_id}</Badge>
          {followerCount != null ? (
            <Badge tone="neutral">{formatNumber(followerCount)} 粉丝</Badge>
          ) : null}
        </div>
        {item.description ? (
          <p className="mt-3 whitespace-pre-line text-sm leading-relaxed text-slate-300">
            {item.description}
          </p>
        ) : (
          <p className="mt-3 text-sm text-slate-600">
            暂无简介，同步成功后将自动填充账号签名 / Bio。
          </p>
        )}
      </section>
      {["queued", "syncing"].includes(item.sync_status) && (
        <SyncProgressPanel
          runs={runs.data?.items}
          syncStatus={item.sync_status}
          onTerminate={() => cancelSync(activeRunId)}
          cancelling={cancelling}
        />
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
              value={formatNumber(totalViews ?? snapshot?.total_view_count ?? contentSummary.data?.account_total_views)}
              hint={
                snapshot?.metadata &&
                (snapshot.metadata as Record<string, unknown>)[
                  "total_view_count_derived_from_content"
                ]
                  ? `由已同步作品播放量合计（${(
                      snapshot.metadata as Record<string, unknown>
                    )["derived_from_content_count"] ?? "?"} 个作品）推算`
                  : undefined
              }
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
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="平均完播率"
              value={metricCardNode(
                "completion_rate",
                contentSummary.data?.avg_completion_rate,
                formatPercent,
              )}
              hint="账号作品均值 · 需官方 API"
            />
            <MetricCard
              label="平均观看时长"
              value={metricCardNode(
                "average_watch_time",
                contentSummary.data?.avg_watch_time_seconds,
                formatWatchTime,
              )}
              hint="账号作品均值 · 需官方 API"
            />
            <MetricCard
              label="近 24h 作品播放增量"
              value={
                <span className="text-2xl font-semibold text-white">
                  {contentSummary.data?.recent_24h_view_growth != null
                    ? `+${formatNumber(contentSummary.data.recent_24h_view_growth)}`
                    : "—"}
                </span>
              }
            />
            <MetricCard
              label="总互动量"
              value={
                <span className="text-2xl font-semibold text-white">
                  {(() => {
                    const v =
                      contentSummary.data?.account_total_likes ??
                      contentSummary.data?.total_interactions;
                    return v != null ? formatNumber(v) : "—";
                  })()}
                </span>
              }
              hint={
                contentSummary.data?.account_total_likes != null
                  ? "账号级累计互动（平台公开资料）"
                  : "已同步作品的互动合计"
              }
            />
          </div>
          <Panel className="p-5">
            <h2 className="font-medium text-white">
              流量来源占比（账号作品平均）
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              推荐 / 搜索 / 关注流量占比；需要配置该平台官方 API
              或流量来源授权后才会返回真实值。
            </p>
            <TrafficSourceBreakdown
              split={contentSummary.data?.traffic_source_split}
              format={formatPercent}
            />
          </Panel>
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
        <Panel className="overflow-hidden p-0">
          <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
            <div>
              <h2 className="font-medium text-white">作品清单</h2>
              <p className="mt-0.5 text-xs text-slate-500">
                共 {contents.data?.total ?? contents.data?.items.length ?? 0} 条
                · 点击标题查看单作品深度诊断
              </p>
            </div>
            {contents.isFetching && (
              <span className="flex items-center gap-2 text-xs text-cyan-300">
                <RefreshCw size={12} className="animate-spin" />
                加载中
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-5 py-3">
            <TimeRangePicker
              value={range}
              onChange={(value) => {
                setRange(value);
                setContentPage(1);
              }}
              customFrom={from}
              onCustomFromChange={(value) => {
                setFrom(value);
                setContentPage(1);
              }}
            />
            <label className="flex items-center gap-2 text-xs text-slate-400">
              排序
              <select
                className={`${inputClass} h-8 w-auto px-2 text-xs`}
                value={contentSort}
                onChange={(event) => {
                  setContentSort(event.target.value);
                  setContentPage(1);
                }}
              >
                {CONTENT_SORT_OPTIONS.map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-xs text-slate-400">
              每页
              <select
                className={`${inputClass} h-8 w-auto px-2 text-xs`}
                value={contentPageSize}
                onChange={(event) => {
                  setContentPageSize(Number(event.target.value));
                  setContentPage(1);
                }}
              >
                {[20, 50, 100].map((size) => (
                  <option key={size} value={size}>
                    {size} 条
                  </option>
                ))}
              </select>
            </label>
          </div>
          {contents.data?.items.length ? (
            <ContentTable
              rows={contents.data.items}
              total={contents.data.total}
              page={contentPage}
              pageSize={contentPageSize}
              onPageChange={setContentPage}
            />
          ) : (
            <StatePanel
              type="empty"
              title="尚无作品数据"
              detail="运行一次账号同步（需该平台适配器已配置凭证）后，Adapter 返回的作品及播放、互动、完播、流量来源等指标会出现在这里。所有指标均标注数据来源（live / imported），不会用模拟数据冒充真实平台数据。"
              action={
                item.is_active &&
                item.platform.capabilities?.implementation_status ===
                  "implemented" ? (
                  ["queued", "syncing"].includes(item.sync_status) ? (
                    <TerminateButton
                      onTerminate={() => cancelSync(activeRunId)}
                      busy={cancelling}
                      title="终止正在进行的同步任务"
                    />
                  ) : (
                    <button
                      className={buttonClass}
                      onClick={() => setSyncTarget(item)}
                    >
                      <RefreshCw size={15} />
                      立即同步
                    </button>
                  )
                ) : undefined
              }
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
                  className={
                    historyDays === d ? buttonClass : secondaryButtonClass
                  }
                >
                  {d} 天
                </button>
              ))}
            </div>
          </div>
          <p className="mt-1 text-xs text-slate-400">
            共 {metricsHistory.data?.points.length ?? 0} 个快照（最近{" "}
            {historyDays} 天）
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
                    {["queued", "running", "syncing"].includes(run.status) && (
                      <TerminateButton
                        size="sm"
                        onTerminate={() => cancelSync(run.id)}
                        busy={cancelling && activeRunId === run.id}
                        label="终止"
                        title="终止正在进行的同步任务"
                      />
                    )}
                    <span className="ml-auto flex items-center gap-3 text-xs text-slate-500">
                      <Link
                        href={`/accounts/${id}/sync-runs/${run.id}`}
                        className="text-cyan-400 hover:text-cyan-300"
                      >
                        查看详情
                      </Link>
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
                      <div className="space-y-2 rounded-md border border-rose-900/50 bg-rose-950/20 p-2 text-rose-300">
                        <div className="flex flex-wrap items-center gap-2">
                          {run.error_code && (
                            <Badge tone={adapterErrorCodeTone(run.error_code)}>
                              {run.error_code}
                            </Badge>
                          )}
                          <span className="text-rose-200">同步失败</span>
                        </div>
                        {run.error_hint && (
                          <p className="whitespace-pre-wrap leading-relaxed text-rose-300/90">
                            <span className="font-medium text-rose-200">业务层说明：</span>
                            {run.error_hint}
                          </p>
                        )}
                        <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-black/40 p-2 font-mono text-[11px] leading-relaxed text-rose-300/90">
{run.error_detail || run.error_message}
                        </pre>
                      </div>
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
            平台 API 凭证请在「设置 → 平台管理」中统一配置；抓取范围、量级与去重策略请在「设置 →
            同步设置」中统一设置。
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
      {syncTarget && (
        <SyncSettingsModal
          account={syncTarget}
          onClose={() => setSyncTarget(null)}
          onSynced={async () => {
            await qc.invalidateQueries({ queryKey: ["account", id] });
            await qc.invalidateQueries({ queryKey: ["account-runs", id] });
            await qc.invalidateQueries({ queryKey: ["account-contents", id] });
          }}
        />
      )}
    </main>
  );
}
