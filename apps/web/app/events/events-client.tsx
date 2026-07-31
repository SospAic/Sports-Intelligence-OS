"use client";
import type { TopicEventPage, TopicEventRecord } from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Bookmark, Search, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import { ScoreExplanationPanel } from "@/components/score-explanation";
import { useToast } from "@/components/toast";
import {
  PageHeader,
  SkeletonRows,
  StatePanel,
  inputClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate, sportLabel } from "@/lib/format";
import { isEventScoreAvailable } from "@/lib/news-metrics";
export function EventsClient() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [sport, setSport] = useState("");
  const [minHeat, setMinHeat] = useState("");
  const params = new URLSearchParams({
    page: String(page),
    page_size: "20",
    sort: "heat_score",
    order: "desc",
  });
  if (query) params.set("query", query);
  if (sport) params.set("sport", sport);
  if (minHeat) params.set("min_heat", minHeat);
  const events = useQuery({
    queryKey: ["events", workspaceId, params.toString()],
    queryFn: () =>
      apiRequest<TopicEventPage>(`/news/events?${params}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  async function bookmark(item: TopicEventRecord) {
    if (!workspaceId) return;
    try {
      await apiRequest(`/news/events/${item.id}/bookmark`, {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ bookmarked: !item.is_bookmarked }),
      });
      notify(item.is_bookmarked ? "已取消收藏" : "已加入选题库");
      await qc.invalidateQueries({ queryKey: ["events"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "操作失败", "error");
    }
  }
  const columns: ColumnDef<TopicEventRecord, unknown>[] = [
    {
      accessorKey: "title",
      header: "热点事件",
      cell: ({ row }) => (
        <div className="min-w-80">
          <Link
            className="font-medium text-cyan-300 hover:underline"
            href={`/events/${row.original.id}`}
          >
            {row.original.title}
          </Link>
          <p className="mt-1 line-clamp-1 text-xs text-slate-500">
            {row.original.summary}
          </p>
          {workspaceId && (
            <ScoreExplanationPanel
              entityType="event"
              entityId={row.original.id}
              apiPath={`/news/events/${row.original.id}/explain`}
              workspaceId={workspaceId}
            />
          )}
        </div>
      ),
    },
    {
      accessorKey: "sport",
      header: "项目",
      cell: ({ row }) => sportLabel(row.original.sport),
    },
    {
      accessorKey: "last_update_time",
      header: "最近更新",
      cell: ({ row }) => formatDate(row.original.last_update_time),
    },
    { accessorKey: "heat_score", header: "热度" },
    {
      accessorKey: "source_count",
      header: "来源数",
      cell: ({ row }) => (
        <span>
          {row.original.source_count} 个
          {row.original.source_count < 2 && (
            <span className="ml-2 text-xs text-amber-400">未交叉验证</span>
          )}
        </span>
      ),
    },
    {
      accessorKey: "article_count",
      header: "报道",
      cell: ({ row }) => `${row.original.article_count} 篇`,
    },
    {
      accessorKey: "story_score",
      header: "故事性",
      cell: ({ row }) =>
        isEventScoreAvailable(row.original.metadata, "story_score")
          ? row.original.story_score
          : "—",
    },
    {
      id: "actions",
      header: "操作",
      enableSorting: false,
      cell: ({ row }) => (
        <div className="flex gap-3 whitespace-nowrap">
          <button
            aria-label="收藏事件"
            disabled={
              !["owner", "admin", "editor", "analyst"].includes(role ?? "")
            }
            className={
              row.original.is_bookmarked ? "text-amber-300" : "text-slate-500"
            }
            onClick={() => bookmark(row.original)}
          >
            <Bookmark
              size={16}
              fill={row.original.is_bookmarked ? "currentColor" : "none"}
            />
          </button>
          <Link
            aria-label="生成内容"
            className="text-cyan-300"
            href={`/generate?input_type=event&input_id=${row.original.id}`}
          >
            <Sparkles size={16} />
          </Link>
        </div>
      ),
    },
  ];
  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Event Clustering"
        title="事件中心"
        description="将多来源报道聚合为事件，展示来源数、可靠度、客观热度和故事价值；聚类结合标题与可审计实体相似度。"
      />
      <div className="grid gap-3 md:grid-cols-3">
        <label className="relative">
          <Search
            size={15}
            className="absolute top-1/2 left-3 -translate-y-1/2 text-slate-500"
          />
          <input
            className={`${inputClass} w-full pl-9`}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索事件、人物或队伍"
          />
        </label>
        <input
          className={inputClass}
          value={sport}
          onChange={(e) => setSport(e.target.value)}
          placeholder="体育项目"
        />
        <input
          className={inputClass}
          type="number"
          min="0"
          max="100"
          value={minHeat}
          onChange={(e) => setMinHeat(e.target.value)}
          placeholder="最低热度"
        />
      </div>
      {events.isLoading ? (
        <div className="rounded-2xl border border-slate-800">
          <SkeletonRows />
        </div>
      ) : events.error ? (
        <StatePanel
          type="error"
          title="事件加载失败"
          detail={events.error.message}
          onRetry={() => events.refetch()}
        />
      ) : (
        <DataTable
          data={events.data?.items ?? []}
          columns={columns}
          total={events.data?.total ?? 0}
          page={page}
          pageSize={20}
          onPageChange={setPage}
          empty="暂无聚类事件"
          getRowId={(row) => row.id}
        />
      )}
    </main>
  );
}
