"use client";
import type { SavedTopicPage, SavedTopicRecord } from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Search, Sparkles, Trash2 } from "lucide-react";
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
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";
const statusLabels = {
  inbox: "待整理",
  planned: "已规划",
  in_progress: "制作中",
  completed: "已完成",
  archived: "已归档",
};
export function TopicsClient() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const params = new URLSearchParams({ page: String(page), page_size: "20" });
  if (query) params.set("query", query);
  if (status) params.set("status", status);
  const topics = useQuery({
    queryKey: ["topics", workspaceId, params.toString()],
    queryFn: () =>
      apiRequest<SavedTopicPage>(`/topics?${params}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  async function create(form: FormData) {
    if (!workspaceId) return;
    try {
      await apiRequest("/topics", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          source_type: "manual",
          title: form.get("title"),
          summary: form.get("summary") || null,
          priority: Number(form.get("priority") || 50),
          notes: null,
          metadata: {},
        }),
      });
      notify("选题已创建");
      setCreating(false);
      await qc.invalidateQueries({ queryKey: ["topics"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "创建失败", "error");
    }
  }
  async function update(topic: SavedTopicRecord, next: string) {
    if (!workspaceId) return;
    try {
      await apiRequest(`/topics/${topic.id}`, {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ status: next }),
      });
      notify("选题状态已更新");
      await qc.invalidateQueries({ queryKey: ["topics"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "更新失败", "error");
    }
  }
  async function remove(id: string) {
    if (!workspaceId || !window.confirm("确定删除此选题？")) return;
    try {
      await apiRequest(`/topics/${id}`, {
        method: "DELETE",
        workspaceId,
        csrf: true,
      });
      notify("选题已删除");
      await qc.invalidateQueries({ queryKey: ["topics"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "删除失败", "error");
    }
  }
  const columns: ColumnDef<SavedTopicRecord, unknown>[] = [
    {
      accessorKey: "title",
      header: "选题",
      cell: ({ row }) => (
        <div className="min-w-80">
          <p className="font-medium text-slate-100">{row.original.title}</p>
          <p className="mt-1 line-clamp-1 text-xs text-slate-500">
            {row.original.summary || "暂无摘要"}
          </p>
        </div>
      ),
    },
    {
      accessorKey: "source_type",
      header: "来源",
      cell: ({ row }) => <Badge tone="info">{row.original.source_type}</Badge>,
    },
    { accessorKey: "priority", header: "优先级" },
    {
      accessorKey: "status",
      header: "状态",
      cell: ({ row }) => (
        <select
          aria-label="选题状态"
          className={`${inputClass} h-8`}
          value={row.original.status}
          onChange={(e) => update(row.original, e.target.value)}
        >
          {Object.entries(statusLabels).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      ),
    },
    {
      accessorKey: "created_at",
      header: "创建时间",
      cell: ({ row }) => formatDate(row.original.created_at),
    },
    {
      id: "actions",
      header: "操作",
      enableSorting: false,
      cell: ({ row }) => (
        <div className="flex gap-3">
          {row.original.source_id && row.original.source_type !== "manual" && (
            <Link
              className="text-cyan-300"
              title="生成内容"
              href={`/generate?input_type=${row.original.source_type === "article" ? "news" : row.original.source_type}&input_id=${row.original.source_id}`}
            >
              <Sparkles size={16} />
            </Link>
          )}
          {["owner", "admin", "editor"].includes(role ?? "") && (
            <button
              className="text-rose-300"
              title="删除"
              onClick={() => remove(row.original.id)}
            >
              <Trash2 size={16} />
            </button>
          )}
        </div>
      ),
    },
  ];
  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Editorial Pipeline"
        title="选题库"
        description="保存来自作品、新闻、事件或人工录入的选题；来源边界跟随原实体保留。"
        actions={
          <button
            className={buttonClass}
            onClick={() => setCreating((v) => !v)}
          >
            <Plus size={15} />
            新建选题
          </button>
        }
      />
      <div className="flex flex-wrap gap-3">
        <label className="relative min-w-64 flex-1">
          <Search
            size={15}
            className="absolute top-1/2 left-3 -translate-y-1/2 text-slate-500"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className={`${inputClass} w-full pl-9`}
            placeholder="搜索选题"
          />
        </label>
        <select
          className={inputClass}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="">全部状态</option>
          {Object.entries(statusLabels).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {creating && (
        <form
          action={create}
          className="grid gap-3 rounded-2xl border border-cyan-900 bg-slate-950/70 p-5 md:grid-cols-2"
        >
          <input
            name="title"
            className={inputClass}
            required
            placeholder="选题标题"
          />
          <input
            name="priority"
            className={inputClass}
            type="number"
            min="0"
            max="100"
            defaultValue="50"
          />
          <textarea
            name="summary"
            className={`${inputClass} h-24 py-2 md:col-span-2`}
            placeholder="事实摘要或创作说明"
          />
          <div className="flex gap-2">
            <button className={buttonClass}>保存选题</button>
            <button
              type="button"
              className={secondaryButtonClass}
              onClick={() => setCreating(false)}
            >
              取消
            </button>
          </div>
        </form>
      )}
      {topics.isLoading ? (
        <div className="rounded-2xl border border-slate-800">
          <SkeletonRows />
        </div>
      ) : topics.error ? (
        <StatePanel
          type="error"
          title="选题加载失败"
          detail={topics.error.message}
        />
      ) : (
        <DataTable
          data={topics.data?.items ?? []}
          columns={columns}
          total={topics.data?.total ?? 0}
          page={page}
          pageSize={20}
          onPageChange={setPage}
          empty="选题库为空"
          getRowId={(row) => row.id}
        />
      )}
    </main>
  );
}
