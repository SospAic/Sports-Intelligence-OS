"use client";
import type { OperationTaskPage, OperationTaskRecord } from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import { TerminateButton } from "@/components/terminate-button";
import { useToast } from "@/components/toast";
import {
  Badge,
  PageHeader,
  SkeletonRows,
  StatePanel,
  inputClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";
import {
  OPERATION_CATEGORY_LABELS,
  OPERATION_STATUS_LABELS,
  operationTaskLabel,
} from "@/lib/operation-labels";
export function TasksClient() {
  const { workspaceId } = useWorkspace();
  const { notify } = useToast();
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [terminatingId, setTerminatingId] = useState<string | null>(null);
  const ACTIVE_STATUSES = ["queued", "running", "syncing", "retrying"];

  const params = new URLSearchParams({ page: String(page), page_size: "30" });
  if (category) params.set("category", category);
  if (status) params.set("status", status);
  const query = useQuery({
    queryKey: ["operations-tasks", workspaceId, params.toString()],
    queryFn: () =>
      apiRequest<OperationTaskPage>(`/operations/tasks?${params}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
    refetchInterval: 10000,
  });

  async function terminate(taskId: string, taskCategory: string) {
    if (!workspaceId) return;
    setTerminatingId(taskId);
    try {
      await apiRequest(`/operations/tasks/${taskId}/cancel`, {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ category: taskCategory }),
      });
      notify("已发送终止请求，任务将尽快停止");
      await query.refetch();
    } catch (error) {
      notify(error instanceof Error ? error.message : "终止失败", "error");
    } finally {
      setTerminatingId(null);
    }
  }
  const columns: ColumnDef<OperationTaskRecord, unknown>[] = [
    {
      accessorKey: "started_at",
      header: "开始时间",
      cell: ({ row }) => formatDate(row.original.started_at),
    },
    {
      accessorKey: "category",
      header: "类别",
      cell: ({ row }) => (
        <Badge tone="info">
          {OPERATION_CATEGORY_LABELS[row.original.category] ??
            row.original.category}
        </Badge>
      ),
    },
    {
      accessorKey: "task_type",
      header: "任务",
      cell: ({ row }) => operationTaskLabel(row.original.task_type),
    },
    {
      accessorKey: "status",
      header: "状态",
      cell: ({ row }) => (
        <Badge
          tone={
            ["success", "completed"].includes(row.original.status)
              ? "success"
              : ["error", "failed"].includes(row.original.status)
                ? "danger"
                : "warning"
          }
        >
          {OPERATION_STATUS_LABELS[row.original.status] ?? row.original.status}
        </Badge>
      ),
    },
    {
      accessorKey: "finished_at",
      header: "完成时间",
      cell: ({ row }) => formatDate(row.original.finished_at),
    },
    {
      accessorKey: "error_message",
      header: "错误详情",
      cell: ({ row }) => {
        const { error_code, error_detail, error_hint, error_message } =
          row.original;
        const degraded = row.original.status === "degraded";
        if (!error_code && !error_detail && !error_hint && !error_message) {
          return <span className="text-slate-500">—</span>;
        }
        return (
          <div className="max-w-lg space-y-1">
            {error_code && (
              <Badge tone={degraded ? "warning" : "danger"}>{error_code}</Badge>
            )}
            {error_detail && (
              <pre
                className={`whitespace-pre-wrap break-words rounded border p-2 text-xs ${
                  degraded
                    ? "border-amber-900/40 bg-amber-950/20 text-amber-200"
                    : "border-rose-900/40 bg-rose-950/20 text-rose-300"
                }`}
              >
                {error_detail}
              </pre>
            )}
            {error_message && !error_detail && (
              <p
                className={
                  degraded ? "text-xs text-amber-200" : "text-xs text-rose-300"
                }
              >
                {error_message}
              </p>
            )}
            {error_hint && (
              <p className="rounded border border-amber-900/30 bg-amber-950/10 p-2 text-xs text-amber-200">
                {error_hint}
              </p>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: "id",
      header: "操作",
      cell: ({ row }) => {
        const rec = row.original;
        const active = ACTIVE_STATUSES.includes(rec.status);
        if (!active) {
          return <span className="text-xs text-slate-600">—</span>;
        }
        if (rec.category !== "platform_sync") {
          return (
            <span
              className="text-xs text-slate-500"
              title="该任务类型暂不支持在界面终止"
            >
              暂不支持
            </span>
          );
        }
        return (
          <TerminateButton
            size="sm"
            onTerminate={() => terminate(rec.id, rec.category)}
            busy={terminatingId === rec.id}
            label="终止"
            title="终止正在进行的任务"
          />
        );
      },
    },
  ];
  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Operations"
        title="任务记录"
        description="统一汇总平台同步、新闻同步、内容生成与通用后台任务；每 10 秒刷新。"
      />
      <div className="flex gap-3">
        <select
          className={inputClass}
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">全部类别</option>
          <option value="platform_sync">平台同步</option>
          <option value="news_sync">新闻同步</option>
          <option value="generation">内容生成</option>
          <option value="worker">通用 Worker</option>
        </select>
        <select
          className={inputClass}
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
        >
          <option value="">全部状态</option>
          <option value="queued">排队中</option>
          <option value="running">执行中</option>
          <option value="syncing">同步中</option>
          <option value="retrying">等待重试</option>
          <option value="success">成功</option>
          <option value="completed">完成</option>
          <option value="failed">失败</option>
          <option value="error">错误</option>
        </select>
      </div>
      {query.isLoading ? (
        <div className="rounded-2xl border border-slate-800">
          <SkeletonRows />
        </div>
      ) : query.error ? (
        <StatePanel
          type="error"
          title="任务记录加载失败"
          detail={query.error.message}
          onRetry={() => query.refetch()}
        />
      ) : (
        <DataTable
          data={query.data?.items ?? []}
          columns={columns}
          total={query.data?.total ?? 0}
          page={page}
          pageSize={30}
          onPageChange={setPage}
          empty="暂无任务记录"
          getRowId={(row) => row.id}
        />
      )}
    </main>
  );
}
