"use client";

import type {
  AccountRecord,
  AccountRecordPage,
  PlatformRecord,
} from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef, VisibilityState } from "@tanstack/react-table";
import {
  Columns3,
  Download,
  Plus,
  RefreshCw,
  Save,
  Search,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import { useToast } from "@/components/toast";
import {
  Badge,
  PageHeader,
  SkeletonRows,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest, downloadApiFile } from "@/lib/browser-api";
import { buildAccountListPath } from "@/lib/admin-queries";
import { formatDate, formatNumber, sourceKindLabel } from "@/lib/format";

function readAccountView(): { platform: string; visibility: VisibilityState } {
  if (typeof window === "undefined") return { platform: "", visibility: {} };
  try {
    const value = JSON.parse(
      window.localStorage.getItem("sio-account-view") ?? "{}",
    ) as {
      platform?: string;
      visibility?: VisibilityState;
    };
    return {
      platform: value.platform ?? "",
      visibility: value.visibility ?? {},
    };
  } catch {
    return { platform: "", visibility: {} };
  }
}

export function AccountsClient() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState(() => readAccountView().platform);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(
    () => readAccountView().visibility,
  );
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState(false);
  const accounts = useQuery({
    queryKey: ["accounts", workspaceId, page, query, platform],
    queryFn: () =>
      apiRequest<AccountRecordPage>(
        buildAccountListPath({ page, query, platform }),
        {
          workspaceId: workspaceId!,
        },
      ),
    enabled: Boolean(workspaceId),
  });
  const platforms = useQuery({
    queryKey: ["platforms"],
    queryFn: () => apiRequest<PlatformRecord[]>("/platforms?enabled=true"),
    enabled: Boolean(workspaceId),
  });
  const canEdit = ["owner", "admin", "editor"].includes(role ?? "");
  function saveView() {
    window.localStorage.setItem(
      "sio-account-view",
      JSON.stringify({ platform, visibility: columnVisibility }),
    );
    notify("账号筛选和列设置已保存到当前浏览器");
  }
  async function createAccount(form: FormData) {
    if (!workspaceId) return;
    setPending(true);
    try {
      await apiRequest<AccountRecord>("/accounts", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          platform_id: form.get("platform_id"),
          external_id: form.get("external_id"),
          username: form.get("username") || null,
          display_name: form.get("display_name"),
          profile_url: form.get("profile_url") || null,
          sync_interval_seconds: Number(
            form.get("sync_interval_seconds") || 3600,
          ),
          metadata: {},
        }),
      });
      notify("账号已添加；真实数据将在同步成功后出现。");
      setCreating(false);
      await client.invalidateQueries({ queryKey: ["accounts"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "添加失败", "error");
    } finally {
      setPending(false);
    }
  }
  async function sync(id: string) {
    if (!workspaceId) return;
    try {
      await apiRequest(`/accounts/${id}/sync`, {
        method: "POST",
        workspaceId,
        csrf: true,
      });
      notify("同步任务已进入队列");
      await client.invalidateQueries({ queryKey: ["accounts"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "同步失败", "error");
    }
  }
  const columns: ColumnDef<AccountRecord, unknown>[] = [
    {
      accessorKey: "display_name",
      header: "账号",
      cell: ({ row }) => (
        <div>
          <Link
            className="font-medium text-cyan-300 hover:underline"
            href={`/accounts/${row.original.id}`}
          >
            {row.original.display_name}
          </Link>
          <p className="mt-1 text-xs text-slate-500">
            {row.original.username ?? row.original.external_id}
          </p>
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
            <Badge
              tone={row.original.source_kind === "mock" ? "warning" : "success"}
            >
              {sourceKindLabel(row.original.source_kind)}
            </Badge>
          </div>
        </div>
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
      header: "作品数",
      cell: ({ row }) =>
        formatNumber(row.original.latest_snapshot?.video_count),
    },
    {
      accessorKey: "last_synced_at",
      header: "最近同步",
      cell: ({ row }) => (
        <div>
          {formatDate(row.original.last_synced_at)}
          <p className="mt-1 text-xs text-slate-500">
            {row.original.sync_status}
          </p>
        </div>
      ),
    },
    {
      id: "actions",
      header: "操作",
      enableSorting: false,
      cell: ({ row }) => (
        <button
          disabled={
            !canEdit || ["queued", "syncing"].includes(row.original.sync_status)
          }
          onClick={() => sync(row.original.id)}
          className="inline-flex items-center gap-1 text-cyan-300 disabled:text-slate-600"
        >
          <RefreshCw size={14} />
          同步
        </button>
      ),
    },
  ];
  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Monitoring"
        title="账号监控"
        description="统一查看多平台账号、增长与同步状态；Mock 来源会被显著标记，未同步字段保持为空。"
        actions={
          <>
            <button className={secondaryButtonClass} onClick={saveView}>
              <Save size={16} />
              保存视图
            </button>
            <details className="relative">
              <summary
                className={`${secondaryButtonClass} list-none cursor-pointer`}
              >
                <Columns3 size={16} />
                列显示
              </summary>
              <div className="absolute top-12 right-0 z-20 w-44 space-y-2 rounded-xl border border-slate-700 bg-slate-950 p-3 shadow-2xl">
                {(
                  [
                    ["followers", "粉丝"],
                    ["follower_growth_24h", "24h 增长"],
                    ["videos", "作品数"],
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
                  "/accounts/export.csv",
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
      </div>
      {creating && (
        <form
          action={createAccount}
          className="grid gap-3 rounded-2xl border border-cyan-900/60 bg-slate-950/70 p-5 md:grid-cols-2 xl:grid-cols-3"
        >
          <select name="platform_id" required className={inputClass}>
            <option value="">选择平台</option>
            {platforms.data?.map((item) => (
              <option value={item.id} key={item.id}>
                {item.name}
                {item.adapter_key === "mock" ? "（Mock）" : ""}
              </option>
            ))}
          </select>
          <input
            name="external_id"
            required
            className={inputClass}
            placeholder="官方平台外部 ID"
          />
          <input
            name="display_name"
            required
            className={inputClass}
            placeholder="显示名称"
          />
          <input
            name="username"
            className={inputClass}
            placeholder="用户名（可选）"
          />
          <input
            name="profile_url"
            type="url"
            className={inputClass}
            placeholder="主页 URL（可选）"
          />
          <input
            name="sync_interval_seconds"
            type="number"
            min="300"
            defaultValue="3600"
            className={inputClass}
          />
          <div className="flex gap-2">
            <button disabled={pending} className={buttonClass}>
              {pending ? "保存中…" : "保存账号"}
            </button>
            <button
              type="button"
              className={secondaryButtonClass}
              onClick={() => setCreating(false)}
            >
              取消
            </button>
          </div>
          <p className="text-xs text-slate-500 md:col-span-2">
            添加账号不会伪造统计数据；只有 Adapter 同步成功后才会写入真实快照。
          </p>
        </form>
      )}
      {accounts.isLoading ? (
        <div className="rounded-2xl border border-slate-800">
          <SkeletonRows />
        </div>
      ) : accounts.error ? (
        <StatePanel
          type="error"
          title="账号加载失败"
          detail={accounts.error.message}
          onRetry={() => accounts.refetch()}
        />
      ) : (
        <DataTable
          data={accounts.data?.items ?? []}
          columns={columns}
          total={accounts.data?.total ?? 0}
          page={page}
          pageSize={20}
          onPageChange={setPage}
          empty="尚未添加监控账号"
          getRowId={(row) => row.id}
          columnVisibility={columnVisibility}
          onColumnVisibilityChange={setColumnVisibility}
        />
      )}
    </main>
  );
}
