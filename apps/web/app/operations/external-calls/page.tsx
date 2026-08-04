"use client";

import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { ChevronDown, ChevronUp, RefreshCw, X } from "lucide-react";
import { useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import {
  Badge,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ExternalCallAttempt {
  id: string;
  workspace_id: string | null;
  call_type: string;
  provider_key: string;
  entity_type: string | null;
  entity_id: string | null;
  attempt_number: number;
  status: "success" | "failed" | "timeout";
  target_url: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  http_status: number | null;
  error_code: string | null;
  error_detail_safe: string | null;
  error_hint: string | null;
  retryable: boolean | null;
  request_summary: Record<string, unknown> | null;
  response_summary: Record<string, unknown> | null;
}

interface ExternalCallAttemptPage {
  items: ExternalCallAttempt[];
  total: number;
  page: number;
  page_size: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 25;

const CALL_TYPE_OPTIONS = [
  { value: "", label: "全部类型" },
  { value: "notification", label: "通知" },
  { value: "webhook", label: "Webhook" },
  { value: "news_sync", label: "新闻同步" },
  { value: "platform_api", label: "平台 API" },
  { value: "llm", label: "LLM" },
  { value: "other", label: "其他" },
];

const STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "success", label: "成功" },
  { value: "failed", label: "失败" },
  { value: "timeout", label: "超时" },
];

const STATUS_LABEL: Record<string, string> = {
  success: "成功",
  failed: "失败",
  timeout: "超时",
};

const CALL_TYPE_LABEL: Record<string, string> = {
  notification: "通知",
  webhook: "Webhook",
  news_sync: "新闻同步",
  platform_api: "平台 API",
  llm: "LLM",
  other: "其他",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusTone(status: string): "success" | "danger" | "warning" {
  if (status === "success") return "success";
  if (status === "timeout") return "warning";
  return "danger";
}

function formatDuration(ms: number | null): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

// ---------------------------------------------------------------------------
// Select component
// ---------------------------------------------------------------------------

function FilterSelect({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      className={`${inputClass} cursor-pointer`}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// Detail panel
// ---------------------------------------------------------------------------

function DetailPanel({
  attempt,
  onClose,
}: {
  attempt: ExternalCallAttempt;
  onClose: () => void;
}) {
  return (
    <Panel className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">
          调用详情 &mdash;{" "}
          <code className="text-cyan-400">{attempt.id.slice(0, 8)}</code>
        </h3>
        <button
          className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-800 hover:text-white"
          onClick={onClose}
        >
          <X size={16} />
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <p className="text-xs text-slate-500">目标 URL</p>
          <p className="mt-1 break-all text-sm text-slate-300">
            {attempt.target_url ?? "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">HTTP 状态码</p>
          <p className="mt-1 text-sm text-slate-300">
            {attempt.http_status ?? "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">错误代码</p>
          <p className="mt-1 text-sm text-rose-300">
            {attempt.error_code ?? "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">可重试</p>
          <p className="mt-1 text-sm text-slate-300">
            {attempt.retryable === null ? "—" : attempt.retryable ? "是" : "否"}
          </p>
        </div>
      </div>

      {attempt.error_detail_safe && (
        <div className="mt-4">
          <p className="text-xs text-slate-500">错误详情（代码级）</p>
          <pre className="mt-1 whitespace-pre-wrap break-words rounded-lg border border-rose-900/50 bg-rose-950/30 p-3 text-xs text-rose-300">
            {attempt.error_detail_safe}
          </pre>
        </div>
      )}

      {attempt.error_hint && (
        <div className="mt-4">
          <p className="text-xs text-slate-500">处置建议（业务层）</p>
          <p className="mt-1 rounded-lg border border-amber-900/40 bg-amber-950/20 p-3 text-xs text-amber-200">
            {attempt.error_hint}
          </p>
        </div>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <p className="mb-2 text-xs font-medium text-slate-400">请求摘要</p>
          {attempt.request_summary ? (
            <pre className="max-h-60 overflow-auto rounded-lg border border-slate-800 bg-slate-900/80 p-3 text-xs text-slate-300">
              {JSON.stringify(attempt.request_summary, null, 2)}
            </pre>
          ) : (
            <p className="text-xs text-slate-600">无请求摘要</p>
          )}
        </div>
        <div>
          <p className="mb-2 text-xs font-medium text-slate-400">响应摘要</p>
          {attempt.response_summary ? (
            <pre className="max-h-60 overflow-auto rounded-lg border border-slate-800 bg-slate-900/80 p-3 text-xs text-slate-300">
              {JSON.stringify(attempt.response_summary, null, 2)}
            </pre>
          ) : (
            <p className="text-xs text-slate-600">无响应摘要</p>
          )}
        </div>
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function ExternalCallsPage() {
  const { workspaceId } = useWorkspace();
  const [page, setPage] = useState(1);
  const [providerFilter, setProviderFilter] = useState("");
  const [callTypeFilter, setCallTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // ---- Build query params ------------------------------------------------

  const params = new URLSearchParams({
    page: String(page),
    page_size: String(PAGE_SIZE),
  });
  if (providerFilter) params.set("provider_key", providerFilter);
  if (callTypeFilter) params.set("call_type", callTypeFilter);
  if (statusFilter) params.set("status", statusFilter);

  // ---- Fetch data --------------------------------------------------------

  const query = useQuery({
    queryKey: [
      "external-call-attempts",
      workspaceId,
      page,
      providerFilter,
      callTypeFilter,
      statusFilter,
    ],
    queryFn: () =>
      apiRequest<ExternalCallAttemptPage>(
        `/external-call-attempts?${params.toString()}`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });

  // ---- Column definitions ------------------------------------------------

  const columns: ColumnDef<ExternalCallAttempt, unknown>[] = [
    {
      accessorKey: "call_type",
      header: "调用类型",
      cell: ({ row }) => (
        <Badge tone="info">
          {CALL_TYPE_LABEL[row.original.call_type] ?? row.original.call_type}
        </Badge>
      ),
    },
    {
      accessorKey: "provider_key",
      header: "提供方",
      cell: ({ row }) => (
        <span className="font-medium text-white">
          {row.original.provider_key}
        </span>
      ),
    },
    {
      accessorKey: "entity_type",
      header: "关联实体",
      cell: ({ row }) => {
        const { entity_type, entity_id } = row.original;
        if (!entity_type) return <span className="text-slate-500">—</span>;
        return (
          <span className="text-slate-300">
            {entity_type}
            {entity_id && (
              <code className="ml-1 text-xs text-slate-500">
                {entity_id.slice(0, 8)}
              </code>
            )}
          </span>
        );
      },
    },
    {
      accessorKey: "attempt_number",
      header: "尝试次数",
      cell: ({ row }) => (
        <span className="tabular-nums">#{row.original.attempt_number}</span>
      ),
    },
    {
      accessorKey: "status",
      header: "状态",
      cell: ({ row }) => (
        <Badge tone={statusTone(row.original.status)}>
          {STATUS_LABEL[row.original.status] ?? row.original.status}
        </Badge>
      ),
    },
    {
      accessorKey: "duration_ms",
      header: "耗时",
      cell: ({ row }) => (
        <span className="tabular-nums text-slate-300">
          {formatDuration(row.original.duration_ms)}
        </span>
      ),
    },
    {
      accessorKey: "error_detail_safe",
      header: "错误",
      cell: ({ row }) => {
        const err = row.original.error_detail_safe;
        if (!err) return <span className="text-slate-500">—</span>;
        return (
          <span className="line-clamp-2 max-w-xs text-rose-300" title={err}>
            {err}
          </span>
        );
      },
    },
    {
      accessorKey: "started_at",
      header: "开始时间",
      cell: ({ row }) => (
        <span className="text-slate-400">
          {formatDate(row.original.started_at)}
        </span>
      ),
    },
    {
      id: "expand",
      header: "",
      cell: ({ row }) => {
        const isExpanded = expandedId === row.original.id;
        return (
          <button
            className="rounded-md p-1 text-slate-400 transition hover:bg-slate-800 hover:text-white"
            onClick={(e) => {
              e.stopPropagation();
              setExpandedId(isExpanded ? null : row.original.id);
            }}
          >
            {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        );
      },
    },
  ];

  // ---- Find expanded attempt ---------------------------------------------

  const expandedAttempt =
    query.data?.items.find((item) => item.id === expandedId) ?? null;

  // ---- Render ------------------------------------------------------------

  return (
    <main className="mx-auto max-w-[1600px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Operations"
        title="外部调用记录"
        description="检查所有外部调用尝试，包括通知、Webhook、新闻同步、平台 API 和 LLM 调用。点击展开按钮查看请求/响应摘要。"
        actions={
          <button
            className={secondaryButtonClass}
            onClick={() => query.refetch()}
          >
            <RefreshCw size={15} />
            刷新
          </button>
        }
      />

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label className="block text-xs text-slate-500">提供方</label>
          <input
            className={`${inputClass} w-48`}
            placeholder="输入提供方标识"
            value={providerFilter}
            onChange={(e) => {
              setProviderFilter(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <div className="space-y-1">
          <label className="block text-xs text-slate-500">调用类型</label>
          <FilterSelect
            value={callTypeFilter}
            onChange={(v) => {
              setCallTypeFilter(v);
              setPage(1);
            }}
            options={CALL_TYPE_OPTIONS}
          />
        </div>
        <div className="space-y-1">
          <label className="block text-xs text-slate-500">状态</label>
          <FilterSelect
            value={statusFilter}
            onChange={(v) => {
              setStatusFilter(v);
              setPage(1);
            }}
            options={STATUS_OPTIONS}
          />
        </div>
        {(providerFilter || callTypeFilter || statusFilter) && (
          <button
            className="inline-flex h-10 items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-3 text-sm text-slate-400 transition hover:bg-slate-900 hover:text-white"
            onClick={() => {
              setProviderFilter("");
              setCallTypeFilter("");
              setStatusFilter("");
              setPage(1);
            }}
          >
            <X size={14} />
            清除筛选
          </button>
        )}
      </div>

      {/* Data table */}
      {query.error ? (
        <StatePanel
          type="error"
          title="外部调用记录加载失败"
          detail={query.error.message}
          onRetry={() => query.refetch()}
        />
      ) : query.isLoading ? (
        <Panel>
          <SkeletonRows count={8} />
        </Panel>
      ) : (
        <>
          <DataTable
            data={query.data?.items ?? []}
            columns={columns}
            total={query.data?.total ?? 0}
            page={page}
            pageSize={PAGE_SIZE}
            onPageChange={(p) => {
              setPage(p);
              setExpandedId(null);
            }}
            empty="暂无外部调用记录"
            getRowId={(row) => row.id}
          />

          {/* Expanded detail panel */}
          {expandedAttempt && (
            <DetailPanel
              attempt={expandedAttempt}
              onClose={() => setExpandedId(null)}
            />
          )}
        </>
      )}
    </main>
  );
}
