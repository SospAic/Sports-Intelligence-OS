"use client";
import type { AutomationRulePage } from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import {
  Badge,
  PageHeader,
  SkeletonRows,
  StatePanel,
  buttonClass,
  inputClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";
export function AutomationsClient() {
  const { workspaceId, role } = useWorkspace();
  const [page, setPage] = useState(1);
  const [entityType, setEntityType] = useState("");
  const [enabled, setEnabled] = useState("");
  const params = new URLSearchParams({ page: String(page), page_size: "20" });
  if (entityType) params.set("entity_type", entityType);
  if (enabled) params.set("enabled", enabled);
  const query = useQuery({
    queryKey: ["automations", workspaceId, params.toString()],
    queryFn: () =>
      apiRequest<AutomationRulePage>(`/automations?${params}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const columns: ColumnDef<AutomationRulePage["items"][number], unknown>[] = [
    {
      accessorKey: "name",
      header: "规则",
      cell: ({ row }) => (
        <div className="min-w-72">
          <Link
            className="font-medium text-cyan-300 hover:underline"
            href={`/automations/${row.original.id}`}
          >
            {row.original.name}
          </Link>
          <p className="mt-1 line-clamp-1 text-xs text-slate-500">
            {row.original.description}
          </p>
        </div>
      ),
    },
    { accessorKey: "entity_type", header: "实体" },
    { accessorKey: "trigger_type", header: "触发" },
    { accessorKey: "priority", header: "优先级" },
    {
      accessorKey: "cooldown_seconds",
      header: "冷却",
      cell: ({ row }) => `${row.original.cooldown_seconds}s`,
    },
    {
      accessorKey: "enabled",
      header: "状态",
      cell: ({ row }) => (
        <Badge tone={row.original.enabled ? "success" : "neutral"}>
          {row.original.enabled ? "已启用" : "已停用"}
        </Badge>
      ),
    },
    {
      accessorKey: "updated_at",
      header: "更新",
      cell: ({ row }) => formatDate(row.original.updated_at),
    },
  ];
  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Automation"
        title="自动化"
        description="使用可视化条件构建器定义触发条件与动作；高级用户可以切换 JSON 视图。"
        actions={
          ["owner", "admin", "editor"].includes(role ?? "") && (
            <Link className={buttonClass} href="/automations/new">
              <Plus size={15} />
              新建自动化
            </Link>
          )
        }
      />
      <div className="flex gap-3">
        <select
          className={inputClass}
          value={entityType}
          onChange={(e) => setEntityType(e.target.value)}
        >
          <option value="">全部实体</option>
          <option value="content">作品</option>
          <option value="account">账号</option>
          <option value="news">新闻</option>
          <option value="topic_event">热点事件</option>
        </select>
        <select
          className={inputClass}
          value={enabled}
          onChange={(e) => setEnabled(e.target.value)}
        >
          <option value="">全部状态</option>
          <option value="true">启用</option>
          <option value="false">停用</option>
        </select>
      </div>
      {query.isLoading ? (
        <div className="rounded-2xl border border-slate-800">
          <SkeletonRows />
        </div>
      ) : query.error ? (
        <StatePanel
          type="error"
          title="自动化加载失败"
          detail={query.error.message}
        />
      ) : (
        <DataTable
          data={query.data?.items ?? []}
          columns={columns}
          total={query.data?.total ?? 0}
          page={page}
          pageSize={20}
          onPageChange={setPage}
          empty="尚未创建自动化规则"
          getRowId={(row) => row.id}
        />
      )}
    </main>
  );
}
