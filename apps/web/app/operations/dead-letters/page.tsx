"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Play, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import { useToast } from "@/components/toast";
import {
  Badge,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DeadLetter {
  id: string;
  event_type: string;
  aggregate_type: string;
  aggregate_id: string;
  total_attempts: number;
  last_error: string | null;
  dead_at: string;
  replay_status: "pending" | "replaying" | "replayed" | "discarded" | null;
  replayed_at: string | null;
}

interface DeadLetterPage {
  items: DeadLetter[];
  total: number;
  page: number;
  page_size: number;
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

const PAGE_SIZE = 25;

export default function DeadLettersPage() {
  const { workspaceId } = useWorkspace();
  const { notify } = useToast();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);

  // ---- Fetch dead letters ------------------------------------------------

  const deadLetters = useQuery({
    queryKey: ["dead-letters", workspaceId, page],
    queryFn: () =>
      apiRequest<DeadLetterPage>(
        `/outbox/dead-letters?page=${page}&page_size=${PAGE_SIZE}`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });

  // ---- Replay mutation ---------------------------------------------------

  const replay = useMutation({
    mutationFn: (id: string) =>
      apiRequest<void>(`/outbox/dead-letters/${id}/replay`, {
        method: "POST",
        workspaceId: workspaceId!,
        csrf: true,
      }),
    onSuccess: () => {
      notify("事件已重新投递");
      qc.invalidateQueries({ queryKey: ["dead-letters"] });
    },
    onError: (error: Error) => {
      notify(error.message || "重投失败", "error");
    },
  });

  // ---- Discard mutation --------------------------------------------------

  const discard = useMutation({
    mutationFn: (id: string) =>
      apiRequest<void>(`/outbox/dead-letters/${id}/discard`, {
        method: "POST",
        workspaceId: workspaceId!,
        csrf: true,
      }),
    onSuccess: () => {
      notify("事件已丢弃");
      qc.invalidateQueries({ queryKey: ["dead-letters"] });
    },
    onError: (error: Error) => {
      notify(error.message || "丢弃失败", "error");
    },
  });

  // ---- Column definitions ------------------------------------------------

  const columns: ColumnDef<DeadLetter, unknown>[] = [
    {
      accessorKey: "event_type",
      header: "事件类型",
      cell: ({ row }) => (
        <span className="font-medium text-white">
          {row.original.event_type}
        </span>
      ),
    },
    {
      accessorKey: "aggregate_type",
      header: "聚合类型",
      cell: ({ row }) => (
        <Badge tone="neutral">{row.original.aggregate_type}</Badge>
      ),
    },
    {
      accessorKey: "total_attempts",
      header: "尝试次数",
      cell: ({ row }) => (
        <span className="tabular-nums">{row.original.total_attempts}</span>
      ),
    },
    {
      accessorKey: "last_error",
      header: "最后错误",
      cell: ({ row }) => (
        <span
          className="line-clamp-2 max-w-xs text-rose-300"
          title={row.original.last_error ?? undefined}
        >
          {row.original.last_error ?? "—"}
        </span>
      ),
    },
    {
      accessorKey: "dead_at",
      header: "进入死信时间",
      cell: ({ row }) => (
        <span className="text-slate-400">
          {formatDate(row.original.dead_at)}
        </span>
      ),
    },
    {
      accessorKey: "replay_status",
      header: "重投状态",
      cell: ({ row }) => {
        const status = row.original.replay_status;
        if (!status) return <span className="text-slate-500">—</span>;
        const toneMap: Record<
          string,
          "success" | "warning" | "info" | "danger" | "neutral"
        > = {
          pending: "warning",
          replaying: "info",
          replayed: "success",
          discarded: "neutral",
        };
        const labelMap: Record<string, string> = {
          pending: "等待中",
          replaying: "重投中",
          replayed: "已重投",
          discarded: "已丢弃",
        };
        return (
          <Badge tone={toneMap[status] ?? "neutral"}>
            {labelMap[status] ?? status}
          </Badge>
        );
      },
    },
    {
      id: "actions",
      header: "操作",
      cell: ({ row }) => {
        const letter = row.original;
        const isReplaying = letter.replay_status === "replaying";
        const isDone =
          letter.replay_status === "replayed" ||
          letter.replay_status === "discarded";
        return (
          <div className="flex items-center gap-2">
            <button
              className={`${secondaryButtonClass} h-8 px-2`}
              disabled={isReplaying || isDone}
              onClick={() => replay.mutate(letter.id)}
            >
              {isReplaying ? (
                <RotateCcw size={13} className="animate-spin" />
              ) : (
                <Play size={13} />
              )}
              重投
            </button>
            <button
              className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-2 text-sm text-rose-300 transition hover:bg-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={isDone}
              onClick={() => {
                if (window.confirm("确定丢弃此事件？此操作不可恢复。")) {
                  discard.mutate(letter.id);
                }
              }}
            >
              <Trash2 size={13} />
              丢弃
            </button>
          </div>
        );
      },
    },
  ];

  // ---- Render ------------------------------------------------------------

  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Operations"
        title="死信队列"
        description="查看因重试耗尽而进入死信队列的事件，支持手动重投或丢弃。"
        actions={
          <button
            className={secondaryButtonClass}
            onClick={() => deadLetters.refetch()}
          >
            <RotateCcw size={15} />
            刷新
          </button>
        }
      />

      {/* Summary cards */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Panel className="p-5">
          <p className="text-sm text-slate-400">死信总数</p>
          <p className="mt-2 text-2xl font-semibold text-white">
            {deadLetters.data?.total ?? "—"}
          </p>
        </Panel>
        <Panel className="p-5">
          <p className="text-sm text-slate-400">当前页</p>
          <p className="mt-2 text-2xl font-semibold text-white">
            {deadLetters.data?.items.length ?? 0} 条
          </p>
        </Panel>
        <Panel className="p-5">
          <p className="text-sm text-slate-400">每页条数</p>
          <p className="mt-2 text-2xl font-semibold text-white">{PAGE_SIZE}</p>
        </Panel>
      </div>

      {/* Data table */}
      {deadLetters.error ? (
        <StatePanel
          type="error"
          title="死信记录加载失败"
          detail={deadLetters.error.message}
          onRetry={() => deadLetters.refetch()}
        />
      ) : deadLetters.isLoading ? (
        <Panel>
          <SkeletonRows count={8} />
        </Panel>
      ) : (
        <DataTable
          data={deadLetters.data?.items ?? []}
          columns={columns}
          total={deadLetters.data?.total ?? 0}
          page={page}
          pageSize={PAGE_SIZE}
          onPageChange={setPage}
          empty="暂无死信事件"
          getRowId={(row) => row.id}
        />
      )}
    </main>
  );
}
