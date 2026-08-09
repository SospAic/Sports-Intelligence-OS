"use client";

import type {
  AccountRecord,
  AccountRecordPage,
  PlatformRecord,
  SyncRunPage,
  SyncRunRecord,
} from "@sio/shared-types";
import { useQuery, useQueryClient, useQueries } from "@tanstack/react-query";
import type { ColumnDef, VisibilityState } from "@tanstack/react-table";
import {
  CheckCircle2,
  Circle,
  Columns3,
  Download,
  Info,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  Search,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import { AccountAvatar } from "@/components/account-avatar";
import { TerminateButton } from "@/components/terminate-button";
import { SyncSettingsModal } from "@/components/sync-settings-modal";
import { AddAccountModal } from "@/components/add-account-modal";
import { useToast } from "@/components/toast";
import {
  Badge,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest, downloadApiFile } from "@/lib/browser-api";
import {
  buildAccountExportPath,
  buildAccountListPath,
} from "@/lib/admin-queries";
import { adapterErrorCodeTone } from "@/lib/adapter-errors";
import { formatDate, formatNumber, sourceKindLabel } from "@/lib/format";
import { OPERATION_STATUS_LABELS } from "@/lib/operation-labels";
import { accountDisplayName } from "@/lib/account-label";

type ActiveState = "active" | "inactive" | "all";

type AccountViewPrefs = {
  platform: string;
  activeState: ActiveState;
  visibility: VisibilityState;
};

const ACCOUNT_VIEW_DEFAULTS: AccountViewPrefs = {
  platform: "",
  activeState: "active",
  visibility: {},
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

const SYNC_STAGE_LABELS: Record<string, string> = {
  queued: "排队",
  validating: "校验",
  account_profile: "账号资料",
  content_list: "作品列表",
  content_metrics: "指标",
  derived_metrics: "派生",
  completed: "完成",
  retry_wait: "等待重试",
  failed: "失败",
};

function readLocalAccountView(): AccountViewPrefs {
  if (typeof window === "undefined") return ACCOUNT_VIEW_DEFAULTS;
  try {
    const value = JSON.parse(
      window.localStorage.getItem("sio-account-view") ?? "{}",
    ) as Partial<AccountViewPrefs>;
    return {
      platform: value.platform ?? "",
      activeState: value.activeState ?? "active",
      visibility: value.visibility ?? {},
    };
  } catch {
    return ACCOUNT_VIEW_DEFAULTS;
  }
}

function writeLocalAccountView(prefs: AccountViewPrefs) {
  try {
    window.localStorage.setItem("sio-account-view", JSON.stringify(prefs));
  } catch {
    // localStorage unavailable; ignore
  }
}

type ViewPreferenceResponse = {
  id: string;
  preferences: Record<string, unknown>;
} | null;

function SyncStatusBadge({ status }: { status: string }) {
  switch (status) {
    case "syncing":
      return (
        <Badge tone="info">
          <span className="inline-flex items-center gap-1">
            <Loader2 size={11} className="animate-spin" />
            同步中
          </span>
        </Badge>
      );
    case "queued":
      return <Badge tone="warning">排队中</Badge>;
    case "success":
      return <Badge tone="success">监控中</Badge>;
    case "degraded":
      return <Badge tone="warning">部分同步（指标缺失）</Badge>;
    case "error":
      return <Badge tone="danger">错误</Badge>;
    case "disabled":
      return <Badge tone="neutral">已停用</Badge>;
    default:
      return <Badge tone="neutral">尚未同步</Badge>;
  }
}

function ProgressBadge({
  account,
  latestRun,
}: {
  account: AccountRecord;
  latestRun: SyncRunRecord | undefined;
}) {
  const isSyncing = ["syncing", "queued"].includes(account.sync_status);

  if (isSyncing && latestRun) {
    const percent = latestRun.progress_percent ?? 0;
    return (
      <div className="min-w-[100px]">
        <div className="mb-1 flex items-center justify-between text-xs">
          <span className="text-cyan-300">{percent}%</span>
          <span className="text-slate-500">
            {SYNC_STAGE_LABELS[latestRun.progress_stage] ??
              latestRun.progress_stage}
          </span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
          <div
            className="h-full rounded-full bg-cyan-400 transition-all duration-700 ease-out"
            style={{ width: `${Math.max(percent, 2)}%` }}
          />
        </div>
      </div>
    );
  }

  if (account.sync_status === "success" || account.last_synced_at) {
    return <Badge tone="success">100%</Badge>;
  }

  return <Badge tone="neutral">0%</Badge>;
}

function StageIcon({ state }: { state: "done" | "active" | "pending" }) {
  if (state === "done")
    return <CheckCircle2 size={15} className="shrink-0 text-emerald-400" />;
  if (state === "active")
    return (
      <Loader2 size={15} className="shrink-0 animate-spin text-cyan-400" />
    );
  return <Circle size={15} className="shrink-0 text-slate-600" />;
}

function SyncDetailDrawer({
  account,
  onClose,
}: {
  account: AccountRecord;
  onClose: () => void;
}) {
  const { workspaceId } = useWorkspace();
  const runs = useQuery({
    queryKey: ["account-runs", account.id],
    queryFn: () =>
      apiRequest<SyncRunPage>(
        `/accounts/${encodeURIComponent(account.id)}/sync-runs?page=1&page_size=5`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
    refetchInterval: ["syncing", "queued"].includes(account.sync_status)
      ? 5000
      : false,
  });

  const currentRun =
    runs.data?.items.find((run) =>
      ["syncing", "running", "queued"].includes(run.status),
    ) ?? runs.data?.items[0];

  const currentStageIndex = currentRun
    ? SYNC_STAGE_ORDER.indexOf(
        currentRun.progress_stage as (typeof SYNC_STAGE_ORDER)[number],
      )
    : -1;

  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panelRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sync-detail-title"
    >
      <button
        aria-label="关闭详情面板"
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <aside
        ref={panelRef}
        tabIndex={-1}
        className="relative flex h-full w-full max-w-md flex-col border-l border-slate-700 bg-slate-950 shadow-2xl outline-none"
      >
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
          <div className="min-w-0">
            <h2 id="sync-detail-title" className="truncate text-sm font-semibold text-white">
              同步详情
            </h2>
            <p className="mt-0.5 truncate text-xs text-slate-500">
              {accountDisplayName({
                ...account,
                platform_name: account.platform.name,
              })}
              {" · "}
              {account.platform.name}
            </p>
          </div>
          <button
            aria-label="关闭"
            className="grid size-8 place-items-center rounded-lg text-slate-400 hover:bg-slate-800 hover:text-white"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          {/* Current run info */}
          {currentRun && (
            <Panel className="p-4">
              <h3 className="text-xs font-semibold tracking-wide text-slate-400 uppercase">
                当前同步任务
              </h3>
              <dl className="mt-3 space-y-2 text-sm">
                <div className="flex justify-between">
                  <dt className="text-slate-500">适配器</dt>
                  <dd className="text-slate-200">{currentRun.adapter_key}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">开始时间</dt>
                  <dd className="text-slate-200">
                    {formatDate(currentRun.started_at)}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">阶段</dt>
                  <dd className="text-cyan-300">
                    {SYNC_STAGE_LABELS[currentRun.progress_stage] ??
                      currentRun.progress_stage}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">进度</dt>
                  <dd className="tabular-nums text-slate-200">
                    {currentRun.progress_percent}%
                  </dd>
                </div>
              </dl>
              <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-800">
                <div
                  className="h-full rounded-full bg-cyan-400 transition-all duration-700"
                  style={{
                    width: `${Math.max(currentRun.progress_percent, 2)}%`,
                  }}
                />
              </div>
              {currentRun.progress_message && (
                <p className="mt-2 text-xs text-slate-500">
                  {currentRun.progress_message}
                </p>
              )}
            </Panel>
          )}

          {/* Stage breakdown */}
          <Panel className="p-4">
            <h3 className="text-xs font-semibold tracking-wide text-slate-400 uppercase">
              阶段进度
            </h3>
            <ol className="mt-3 space-y-2.5">
              {SYNC_STAGE_ORDER.map((stage, index) => {
                let state: "done" | "active" | "pending" = "pending";
                if (currentRun) {
                  if (currentRun.status === "success") {
                    state = "done";
                  } else if (currentRun.status === "error") {
                    state = index < currentStageIndex ? "done" : "pending";
                  } else if (index < currentStageIndex) {
                    state = "done";
                  } else if (index === currentStageIndex) {
                    state = "active";
                  }
                }
                return (
                  <li className="flex items-center gap-3 text-sm" key={stage}>
                    <StageIcon state={state} />
                    <span
                      className={
                        state === "done"
                          ? "text-slate-300"
                          : state === "active"
                            ? "font-medium text-cyan-300"
                            : "text-slate-600"
                      }
                    >
                      {SYNC_STAGE_LABELS[stage]}
                    </span>
                  </li>
                );
              })}
            </ol>
          </Panel>

          {/* Error details */}
          {currentRun?.error_message && (
            <Panel className="border-rose-900/60 p-4">
              <h3 className="text-xs font-semibold tracking-wide text-rose-400 uppercase">
                错误信息
              </h3>
              <p className="mt-2 text-sm text-rose-300">
                {currentRun.error_code && (
                  <Badge tone={adapterErrorCodeTone(currentRun.error_code)}>
                    {currentRun.error_code}
                  </Badge>
                )}
                {currentRun.error_message}
              </p>
            </Panel>
          )}

          {/* Recent sync history */}
          <Panel className="p-4">
            <h3 className="text-xs font-semibold tracking-wide text-slate-400 uppercase">
              最近同步记录
            </h3>
            {runs.data?.items.length ? (
              <div className="mt-3 space-y-3">
                {runs.data.items.map((run) => (
                  <div
                    className="rounded-lg border border-slate-800 p-3"
                    key={run.id}
                  >
                    <div className="flex items-center justify-between text-xs">
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
                      <span className="text-slate-500">
                        {formatDate(run.started_at)}
                      </span>
                    </div>
                    <div className="mt-2 flex gap-4 text-xs text-slate-400">
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
                    </div>
                    {run.error_message && (
                      <p className="mt-1.5 text-xs text-rose-400">
                        {run.error_message}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-500">暂无同步记录</p>
            )}
          </Panel>
        </div>
      </aside>
    </div>
  );
}

export function AccountsClient() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [virtualized, setVirtualized] = useState(false);
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState(
    () => readLocalAccountView().platform,
  );
  const [activeState, setActiveState] = useState<ActiveState>(
    () => readLocalAccountView().activeState,
  );
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(
    () => readLocalAccountView().visibility,
  );
  const [creating, setCreating] = useState(false);
  const [highlightExternalId, setHighlightExternalId] = useState<string | null>(
    null,
  );
  const [drawerAccount, setDrawerAccount] = useState<AccountRecord | null>(
    null,
  );
  const [syncTarget, setSyncTarget] = useState<AccountRecord | null>(null);
  const serverPrefsApplied = useRef(false);

  const serverPrefs = useQuery({
    queryKey: ["account-view-preferences", workspaceId],
    queryFn: () =>
      apiRequest<ViewPreferenceResponse>("/accounts/view-preferences", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
    staleTime: Infinity,
  });

  useEffect(() => {
    if (serverPrefsApplied.current || !serverPrefs.data) return;
    serverPrefsApplied.current = true;
    const prefs = serverPrefs.data.preferences as
      | Partial<AccountViewPrefs>
      | undefined;
    if (!prefs) return;
    // One-time application of server-stored view preferences; guarded by a ref
    // so it runs exactly once and cannot loop.
    /* eslint-disable react-hooks/set-state-in-effect */
    if (prefs.platform !== undefined) setPlatform(prefs.platform);
    if (prefs.activeState !== undefined) setActiveState(prefs.activeState);
    if (prefs.visibility !== undefined) setColumnVisibility(prefs.visibility);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [serverPrefs.data]);

  const accounts = useQuery({
    queryKey: ["accounts", workspaceId, page, query, platform, activeState],
    queryFn: () =>
      apiRequest<AccountRecordPage>(
        buildAccountListPath({ page, query, platform, activeState }),
        {
          workspaceId: workspaceId!,
        },
      ),
    enabled: Boolean(workspaceId),
    refetchInterval: (query) => {
      const items = query.state.data?.items;
      if (!items) return false;
      return items.some((item) =>
        ["syncing", "queued"].includes(item.sync_status),
      )
        ? 5000
        : false;
    },
  });

  const platforms = useQuery({
    queryKey: ["platforms"],
    queryFn: () => apiRequest<PlatformRecord[]>("/platforms?enabled=true"),
    enabled: Boolean(workspaceId),
  });

  // Fetch latest sync run for accounts that are actively syncing
  const syncingAccounts = useMemo(
    () =>
      (accounts.data?.items ?? []).filter((item) =>
        ["syncing", "queued"].includes(item.sync_status),
      ),
    [accounts.data],
  );

  const syncRunQueries = useQueries({
    queries: syncingAccounts.map((account) => ({
      queryKey: ["account-latest-run", account.id],
      queryFn: () =>
        apiRequest<SyncRunPage>(
          `/accounts/${encodeURIComponent(account.id)}/sync-runs?page=1&page_size=1`,
          { workspaceId: workspaceId! },
        ),
      enabled: Boolean(workspaceId),
      refetchInterval: 5000,
    })),
  });

  const latestRunMap = useMemo(() => {
    const map = new Map<string, SyncRunRecord | undefined>();
    syncingAccounts.forEach((account, index) => {
      map.set(account.id, syncRunQueries[index]?.data?.items[0]);
    });
    return map;
  }, [syncingAccounts, syncRunQueries]);

  const canEdit = ["owner", "admin", "editor"].includes(role ?? "");
  const canDelete = ["owner", "admin"].includes(role ?? "");

  async function saveView() {
    const prefs: AccountViewPrefs = {
      platform,
      activeState,
      visibility: columnVisibility,
    };
    writeLocalAccountView(prefs);
    if (!workspaceId) {
      notify("账号筛选和列设置已保存到当前浏览器");
      return;
    }
    try {
      await apiRequest("/accounts/view-preferences", {
        method: "PUT",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ preferences: prefs }),
      });
      await client.invalidateQueries({
        queryKey: ["account-view-preferences"],
      });
      notify("视图设置已同步到服务端");
    } catch {
      notify("视图设置已保存到当前浏览器（服务端同步失败）");
    }
  }
  function openSync(account: AccountRecord) {
    if (!canEdit || !account.is_active) return;
    setSyncTarget(account);
  }
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  async function cancelSync(account: AccountRecord, runId?: string) {
    if (!workspaceId || !runId) return;
    setCancellingId(account.id);
    try {
      await apiRequest(
        `/accounts/${encodeURIComponent(account.id)}/sync/${runId}/cancel`,
        { method: "POST", workspaceId, csrf: true },
      );
      notify("已发送终止请求，任务将尽快停止");
      await client.invalidateQueries({ queryKey: ["accounts"] });
      await client.invalidateQueries({
        queryKey: ["account-latest-run", account.id],
      });
    } catch (error) {
      notify(error instanceof Error ? error.message : "终止失败", "error");
    } finally {
      setCancellingId(null);
    }
  }
  async function deleteAccount(account: AccountRecord) {
    if (!workspaceId) return;
    if (!canDelete) {
      notify("无删除账号权限（需 owner 或 admin 角色）", "error");
      return;
    }
    if (["queued", "syncing"].includes(account.sync_status)) {
      notify("账号正在同步，请稍后再删除", "error");
      return;
    }
    if (
      !window.confirm(
        `确定删除账号「${account.display_name || account.username}」？\n该操作会将账号停用并移出监控，不可撤销。`,
      )
    )
      return;
    try {
      await apiRequest<void>(`/accounts/${encodeURIComponent(account.id)}`, {
        method: "DELETE",
        workspaceId,
        csrf: true,
      });
      notify("账号已删除");
      await client.invalidateQueries({ queryKey: ["accounts"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "删除失败", "error");
    }
  }
  const columns: ColumnDef<AccountRecord, unknown>[] = [
    {
      accessorKey: "display_name",
      header: "账号",
      cell: ({ row }) => (
        <div className="flex items-center gap-3">
          <AccountAvatar
            url={`/accounts/${row.original.id}/avatar`}
            remoteUrl={row.original.avatar_url}
            name={accountDisplayName({
              ...row.original,
              platform_name: row.original.platform.name,
            })}
          />
          <div>
            <Link
              className="font-medium text-cyan-300 hover:underline"
              href={`/accounts/${row.original.id}`}
            >
              {accountDisplayName({
                ...row.original,
                platform_name: row.original.platform.name,
              })}
            </Link>
            <p className="mt-0.5 text-xs text-slate-500">
              {row.original.username ?? row.original.external_id}
            </p>
          </div>
        </div>
      ),
    },
    {
      accessorFn: (item) => item.platform.name,
      id: "platform",
      header: "平台",
      cell: ({ row }) => (
        <div>
          {row.original.platform.name}
          <div className="mt-1">
            <Badge tone="success">
              {sourceKindLabel(row.original.source_kind)}
            </Badge>
          </div>
        </div>
      ),
    },
    {
      accessorKey: "sync_status",
      header: "状态",
      cell: ({ row }) => <SyncStatusBadge status={row.original.sync_status} />,
    },
    {
      id: "sync_progress",
      header: "同步进度",
      enableSorting: false,
      cell: ({ row }) => (
        <ProgressBadge
          account={row.original}
          latestRun={latestRunMap.get(row.original.id)}
        />
      ),
    },
    {
      accessorFn: (item) => item.latest_snapshot?.follower_count ?? -1,
      id: "followers",
      header: "粉丝",
      cell: ({ row }) =>
        formatNumber(row.original.latest_snapshot?.follower_count),
    },
    {
      accessorKey: "follower_growth_24h",
      header: "24h 增长",
      cell: ({ row }) => formatNumber(row.original.follower_growth_24h),
    },
    {
      accessorFn: (item) => item.latest_snapshot?.video_count ?? -1,
      id: "videos",
      header: "平台作品总数",
      cell: ({ row }) =>
        formatNumber(row.original.latest_snapshot?.video_count),
    },
    {
      accessorKey: "last_synced_at",
      header: "最近同步",
      cell: ({ row }) => (
        <div className="whitespace-nowrap">
          {formatDate(row.original.last_synced_at)}
          <p className="mt-1 text-xs text-slate-500">
            {OPERATION_STATUS_LABELS[row.original.sync_status] ??
              row.original.sync_status}
          </p>
        </div>
      ),
    },
    {
      id: "actions",
      header: "操作",
      enableSorting: false,
      cell: ({ row }) => {
        const isSkeleton =
          row.original.platform.capabilities?.implementation_status !==
          "implemented";
        const isSyncing = ["queued", "syncing"].includes(
          row.original.sync_status,
        );
        return (
          <div className="flex items-center gap-2 whitespace-nowrap">
            <button
              disabled={
                !canEdit || !row.original.is_active || isSyncing || isSkeleton
              }
              onClick={() => openSync(row.original)}
              title={
                !row.original.is_active
                  ? "账号已停用"
                  : isSkeleton
                    ? "该平台适配器暂未实现"
                    : isSyncing
                      ? "同步进行中"
                      : undefined
              }
              className="inline-flex items-center gap-1 text-cyan-300 disabled:text-slate-600 disabled:cursor-not-allowed"
            >
              {isSyncing ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <RefreshCw size={14} />
              )}
              {!row.original.is_active
                ? "已停用"
                : isSkeleton
                  ? "不支持"
                  : isSyncing
                    ? "同步中…"
                    : "同步"}
            </button>
            {isSyncing && (
              <TerminateButton
                size="sm"
                label="终止"
                confirmingLabel="确认终止？"
                busy={cancellingId === row.original.id}
                onTerminate={() =>
                  cancelSync(
                    row.original,
                    latestRunMap.get(row.original.id)?.id,
                  )
                }
                title="终止正在进行的同步"
              />
            )}
            <button
              disabled={!isSyncing}
              onClick={() => setDrawerAccount(row.original)}
              title={isSyncing ? "查看同步详情" : "暂无同步任务"}
              className={`inline-flex items-center gap-1 text-xs ${
                isSyncing
                  ? "text-cyan-300 hover:text-cyan-200"
                  : "text-slate-600 cursor-not-allowed"
              }`}
            >
              <Info size={13} />
              详情
            </button>
            {canDelete && (
              <button
                disabled={isSyncing}
                onClick={() => deleteAccount(row.original)}
                title={
                  isSyncing
                    ? "同步进行中，暂不可删除"
                    : "删除该账号（停用并移出监控）"
                }
                className="inline-flex items-center gap-1 text-xs text-rose-400 hover:text-rose-300 disabled:text-slate-600 disabled:cursor-not-allowed"
              >
                <Trash2 size={13} />
                删除
              </button>
            )}
          </div>
        );
      },
    },
  ];
  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Monitoring"
        title="账号监控"
        description="统一查看多平台账号、增长与同步状态；未同步字段保持为空。"
        actions={
          <>
            <button className={secondaryButtonClass} onClick={saveView}>
              <Save size={16} />
              保存视图
            </button>
            <button
              className={`px-3 py-1.5 text-sm rounded-lg border border-slate-700 ${
                virtualized
                  ? "bg-cyan-500/20 text-cyan-200"
                  : "text-slate-400 hover:bg-slate-800"
              }`}
              onClick={() => setVirtualized((v) => !v)}
              title="切换为虚拟滚动（适合超长账号列表）"
            >
              虚拟滚动
            </button>
            <Link
              href="/accounts/compare"
              className={`px-3 py-1.5 text-sm rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800`}
            >
              账号对比
            </Link>
            <details className="relative">
              <summary
                className={`${secondaryButtonClass} list-none cursor-pointer`}
              >
                <Columns3 size={16} />
                列显示
              </summary>
              <div className="absolute top-12 left-0 z-20 w-44 space-y-2 rounded-xl border border-slate-700 bg-slate-950 p-3 shadow-2xl sm:right-0 sm:left-auto">
                {(
                  [
                    ["sync_status", "状态"],
                    ["sync_progress", "同步进度"],
                    ["followers", "粉丝"],
                    ["follower_growth_24h", "24h 增长"],
                    ["videos", "平台作品总数"],
                    ["last_synced_at", "最近同步"],
                  ] as const
                ).map(([key, label]) => (
                  <label className="flex items-center gap-2 text-xs" key={key}>
                    <input
                      type="checkbox"
                      checked={columnVisibility[key] !== false}
                      onChange={(event) =>
                        setColumnVisibility((value) => ({
                          ...value,
                          [key]: event.target.checked,
                        }))
                      }
                    />
                    {label}
                  </label>
                ))}
              </div>
            </details>
            <button
              className={secondaryButtonClass}
              onClick={() =>
                workspaceId &&
                downloadApiFile(
                  buildAccountExportPath({ query, platform, activeState }),
                  workspaceId,
                  "accounts.csv",
                )
              }
            >
              <Download size={16} />
              导出 CSV
            </button>
            {canEdit && (
              <button
                className={buttonClass}
                onClick={() => setCreating((value) => !value)}
              >
                <Plus size={16} />
                添加账号
              </button>
            )}
          </>
        }
      />
      <div className="flex flex-wrap gap-3">
        <label className="relative min-w-64 flex-1">
          <Search
            className="absolute top-1/2 left-3 -translate-y-1/2 text-slate-500"
            size={15}
          />
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            className={`${inputClass} w-full pl-9`}
            placeholder="搜索账号、用户名或外部 ID"
          />
        </label>
        <select
          value={platform}
          onChange={(e) => {
            setPlatform(e.target.value);
            setPage(1);
          }}
          className={inputClass}
        >
          <option value="">全部平台</option>
          {platforms.data?.map((item) => (
            <option value={item.key} key={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <select
          aria-label="监控状态"
          value={activeState}
          onChange={(event) => {
            setActiveState(event.target.value as ActiveState);
            setPage(1);
          }}
          className={inputClass}
        >
          <option value="active">监控中</option>
          <option value="inactive">已停用</option>
          <option value="all">全部状态</option>
        </select>
      </div>
      {creating && (
        <AddAccountModal
          onClose={() => setCreating(false)}
          onCreated={() => {
            /* modal refreshes the accounts list itself */
          }}
          onDuplicate={(externalId) => {
            // Surface the existing account in the list and flash its row.
            setQuery(externalId);
            setPlatform("");
            setActiveState("all");
            setPage(1);
            setHighlightExternalId(externalId);
            window.setTimeout(() => setHighlightExternalId(null), 3200);
          }}
        />
      )}
      {accounts.isLoading ? (
        <div className="rounded-2xl border border-slate-800">
          <SkeletonRows />
        </div>
      ) : accounts.error ? (
        <StatePanel
          type="error"
          title="账号加载失败"
          detail={(accounts.error as Error).message}
          onRetry={() => accounts.refetch()}
        />
      ) : (
        <DataTable
          data={accounts.data?.items ?? []}
          columns={columns}
          total={accounts.data?.total ?? 0}
          page={page}
          pageSize={virtualized ? 200 : 20}
          onPageChange={setPage}
          empty="尚未添加监控账号"
          getRowId={(row) => row.id}
          getRowClassName={(row) =>
            row.external_id === highlightExternalId
              ? "animate-account-flash"
              : ""
          }
          columnVisibility={columnVisibility}
          onColumnVisibilityChange={setColumnVisibility}
          virtualized={virtualized}
        />
      )}
      {drawerAccount && (
        <SyncDetailDrawer
          account={drawerAccount}
          onClose={() => setDrawerAccount(null)}
        />
      )}
      {syncTarget && (
        <SyncSettingsModal
          account={syncTarget}
          onClose={() => setSyncTarget(null)}
          onSynced={async () => {
            await client.invalidateQueries({ queryKey: ["accounts"] });
            await client.invalidateQueries({
              queryKey: ["account-latest-run", syncTarget.id],
            });
          }}
        />
      )}
    </main>
  );
}
