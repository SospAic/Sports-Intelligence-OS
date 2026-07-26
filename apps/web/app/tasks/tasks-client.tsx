"use client";
import type { OperationTaskPage, OperationTaskRecord } from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import {
  Badge,
  PageHeader,
  SkeletonRows,
  StatePanel,
  inputClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";
export function TasksClient() {
  const { workspaceId } = useWorkspace();
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
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
  const columns: ColumnDef<OperationTaskRecord, unknown>[] = [
    {
      accessorKey: "started_at",
      header: "开始时间",
      cell: ({ row }) => formatDate(row.original.started_at),
    },
    {
      accessorKey: "category",
      header: "类别",
      cell: ({ row }) => <Badge tone="info">{row.original.category}</Badge>,
    },
    { accessorKey: "task_type", header: "任务" },
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
          {row.original.status}
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
      header: "错误",
      cell: ({ row }) => (
        <span className="line-clamp-2 max-w-lg text-rose-300">
          {row.original.error_message || "—"}
        </span>
      ),
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
        <input
          className={inputClass}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          placeholder="状态（可选）"
        />
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
