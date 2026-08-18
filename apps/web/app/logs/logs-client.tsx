"use client";
import type {
  AuditEntryPage,
  AuditEntryRecord,
  SystemEventPage,
  SystemEventRecord,
} from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import { Badge, PageHeader, StatePanel, inputClass } from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";

// ---------------------------------------------------------------------------
// Shared error-detail renderer (code-level + business-layer)
// ---------------------------------------------------------------------------

function ErrorDetailBlock({
  errorCode,
  errorDetail,
  errorHint,
}: {
  errorCode: string | null;
  errorDetail: string | null;
  errorHint: string | null;
}) {
  if (!errorCode && !errorDetail && !errorHint) {
    return <span className="text-slate-500">—</span>;
  }
  return (
    <div className="max-w-md space-y-2">
      {errorCode && <Badge tone="danger">{errorCode}</Badge>}
      {errorDetail && (
        <pre className="whitespace-pre-wrap break-words rounded-lg border border-rose-900/50 bg-rose-950/30 p-2 text-xs text-rose-300">
          {errorDetail}
        </pre>
      )}
      {errorHint && (
        <p className="rounded-lg border border-amber-900/40 bg-amber-950/20 p-2 text-xs text-amber-200">
          <span className="font-medium">处置建议：</span>
          {errorHint}
        </p>
      )}
    </div>
  );
}

export function LogsClient() {
  const { workspaceId } = useWorkspace();
  const [tab, setTab] = useState<"events" | "audits">("events");
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const events = useQuery({
    queryKey: ["system-events", workspaceId, page, filter],
    queryFn: () =>
      apiRequest<SystemEventPage>(
        `/operations/events?page=${page}&page_size=30${filter ? `&category=${encodeURIComponent(filter)}` : ""}`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId && tab === "events"),
  });
  const audits = useQuery({
    queryKey: ["audit-entries", workspaceId, page, filter],
    queryFn: () =>
      apiRequest<AuditEntryPage>(
        `/operations/audits?page=${page}&page_size=30${filter ? `&action=${encodeURIComponent(filter)}` : ""}`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId && tab === "audits"),
  });
  const eventColumns: ColumnDef<SystemEventRecord, unknown>[] = [
    {
      accessorKey: "created_at",
      header: "时间",
      cell: ({ row }) => formatDate(row.original.created_at),
    },
    {
      accessorKey: "severity",
      header: "级别",
      cell: ({ row }) => (
        <Badge
          tone={
            row.original.severity === "error"
              ? "danger"
              : row.original.severity === "warning"
                ? "warning"
                : "info"
          }
        >
          {row.original.severity}
        </Badge>
      ),
    },
    { accessorKey: "category", header: "类别" },
    { accessorKey: "event_type", header: "事件类型" },
    {
      id: "error",
      header: "错误详情",
      cell: ({ row }) => (
        <ErrorDetailBlock
          errorCode={row.original.error_code}
          errorDetail={row.original.error_detail}
          errorHint={row.original.error_hint}
        />
      ),
    },
    {
      accessorKey: "message",
      header: "消息",
      cell: ({ row }) => (
        <span className="line-clamp-2 min-w-80">{row.original.message}</span>
      ),
    },
    {
      accessorKey: "trace_id",
      header: "Trace ID",
      cell: ({ row }) => (
        <code className="text-xs text-slate-500">
          {row.original.trace_id.slice(0, 8)}
        </code>
      ),
    },
  ];
  const auditColumns: ColumnDef<AuditEntryRecord, unknown>[] = [
    {
      accessorKey: "created_at",
      header: "时间",
      cell: ({ row }) => formatDate(row.original.created_at),
    },
    { accessorKey: "action", header: "操作" },
    { accessorKey: "resource_type", header: "资源" },
    { accessorKey: "actor_type", header: "操作者" },
    {
      accessorKey: "status",
      header: "状态",
      cell: ({ row }) => (
        <Badge tone={row.original.status === "failed" ? "danger" : "success"}>
          {row.original.status === "failed" ? "失败" : "成功"}
        </Badge>
      ),
    },
    {
      id: "error",
      header: "错误详情",
      cell: ({ row }) => (
        <ErrorDetailBlock
          errorCode={row.original.error_code}
          errorDetail={row.original.error_detail}
          errorHint={row.original.error_hint}
        />
      ),
    },
    {
      accessorKey: "change_summary",
      header: "变更摘要",
      cell: ({ row }) => (
        <code className="line-clamp-2 max-w-lg text-xs text-slate-400">
          {JSON.stringify(row.original.change_summary)}
        </code>
      ),
    },
    {
      accessorKey: "trace_id",
      header: "Trace ID",
      cell: ({ row }) => (
        <code className="text-xs text-slate-500">
          {row.original.trace_id.slice(0, 8)}
        </code>
      ),
    },
  ];
  const active = tab === "events" ? events.data : audits.data;
  return (
    <main className="mx-auto max-w-[1600px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Audit & Observability"
        title="系统日志"
        description="系统事件和不可变审计条目来自后端持久化记录；敏感凭证与 IP 明文不在响应中。"
      />
      <div className="flex flex-wrap gap-3">
        <div className="flex rounded-lg border border-slate-700 p-1">
          <button
            className={`rounded-md px-3 py-2 text-sm ${tab === "events" ? "bg-cyan-400 text-slate-950" : "text-slate-400"}`}
            onClick={() => {
              setTab("events");
              setPage(1);
            }}
          >
            系统事件
          </button>
          <button
            className={`rounded-md px-3 py-2 text-sm ${tab === "audits" ? "bg-cyan-400 text-slate-950" : "text-slate-400"}`}
            onClick={() => {
              setTab("audits");
              setPage(1);
            }}
          >
            审计日志
          </button>
        </div>
        <input
          className={inputClass}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={tab === "events" ? "按类别筛选" : "搜索操作名称"}
        />
      </div>
      {tab === "events" ? (
        events.error ? (
          <StatePanel
            type="error"
            title="系统事件加载失败"
            detail={(events.error as Error).message}
            onRetry={() => events.refetch()}
          />
        ) : (
          <DataTable
            data={events.data?.items ?? []}
            columns={eventColumns}
            total={events.data?.total ?? 0}
            page={page}
            pageSize={30}
            onPageChange={setPage}
            empty="暂无系统事件"
            getRowId={(row) => row.id}
          />
        )
      ) : audits.error ? (
        <StatePanel
          type="error"
          title="审计日志加载失败"
          detail={(audits.error as Error).message}
          onRetry={() => audits.refetch()}
        />
      ) : (
        <DataTable
          data={audits.data?.items ?? []}
          columns={auditColumns}
          total={audits.data?.total ?? 0}
          page={page}
          pageSize={30}
          onPageChange={setPage}
          empty="暂无审计记录"
          getRowId={(row) => row.id}
        />
      )}{" "}
      {active === undefined &&
        (tab === "events" ? events.isLoading : audits.isLoading) && (
          <p className="text-sm text-slate-500">加载中…</p>
        )}
    </main>
  );
}
