"use client";

import type {
  ContentRecord,
  ContentRecordPage,
  PlatformRecord,
} from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { BookMarked, Download, Search, Save } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import { useToast } from "@/components/toast";
import {
  PageHeader,
  SkeletonRows,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest, downloadApiFile } from "@/lib/browser-api";
import { buildContentListPath } from "@/lib/admin-queries";
import {
  formatDate,
  formatNumber,
  formatPercent,
  sourceKindLabel,
} from "@/lib/format";

function readSavedView(): { platform: string; minViews: string } {
  if (typeof window === "undefined") return { platform: "", minViews: "" };
  try {
    const saved = window.localStorage.getItem("sio-content-view");
    if (!saved) return { platform: "", minViews: "" };
    const value = JSON.parse(saved) as {
      platform?: string;
      minViews?: string;
    };
    return { platform: value.platform ?? "", minViews: value.minViews ?? "" };
  } catch {
    return { platform: "", minViews: "" };
  }
}

export function ContentsClient() {
  const { workspaceId, role } = useWorkspace();
  const router = useRouter();
  const { notify } = useToast();
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState(() => readSavedView().platform);
  const [minViews, setMinViews] = useState(() => readSavedView().minViews);
  const [publishedFrom, setPublishedFrom] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const contentPath = buildContentListPath({
    page,
    query,
    platform,
    minViews,
    publishedFrom,
  });
  const contents = useQuery({
    queryKey: ["contents", workspaceId, contentPath],
    queryFn: () =>
      apiRequest<ContentRecordPage>(contentPath, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const platforms = useQuery({
    queryKey: ["platforms"],
    queryFn: () => apiRequest<PlatformRecord[]>("/platforms?enabled=true"),
    enabled: Boolean(workspaceId),
  });
  async function createTopics() {
    if (!workspaceId || !selected.length) return;
    try {
      await apiRequest("/topics/batch", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ source_type: "content", source_ids: selected }),
      });
      notify(`已创建 ${selected.length} 个选题`);
      setSelected([]);
    } catch (error) {
      notify(error instanceof Error ? error.message : "创建选题失败", "error");
    }
  }
  function saveView() {
    window.localStorage.setItem(
      "sio-content-view",
      JSON.stringify({ platform, minViews }),
    );
    notify("筛选视图已保存到当前浏览器");
  }
  const columns: ColumnDef<ContentRecord, unknown>[] = [
    {
      id: "select",
      header: "选择",
      enableSorting: false,
      cell: ({ row }) => (
        <input
          aria-label={`选择 ${row.original.title}`}
          type="checkbox"
          checked={selected.includes(row.original.id)}
          onChange={(e) =>
            setSelected((items) =>
              e.target.checked
                ? [...items, row.original.id]
                : items.filter((id) => id !== row.original.id),
            )
          }
        />
      ),
    },
    {
      accessorKey: "title",
      header: "作品",
      cell: ({ row }) => (
        <div className="flex min-w-72 items-center gap-3">
          {row.original.cover_url ? (
            <div
              aria-hidden="true"
              className="h-12 w-20 rounded-md bg-cover bg-center"
              style={{ backgroundImage: `url(${row.original.cover_url})` }}
            />
          ) : (
            <div className="h-12 w-20 rounded-md bg-slate-800" />
          )}
          <div className="min-w-0">
            <Link
              className="line-clamp-2 font-medium text-cyan-300 hover:underline"
              href={`/contents/${row.original.id}`}
            >
              {row.original.title}
            </Link>
            <p className="mt-1 text-xs text-slate-500">
              {row.original.platform.name} ·{" "}
              {sourceKindLabel(row.original.source_kind)}
            </p>
          </div>
        </div>
      ),
    },
    {
      accessorKey: "published_at",
      header: "发布时间",
      cell: ({ row }) => formatDate(row.original.published_at),
    },
    {
      accessorFn: (item) => item.latest_snapshot?.view_count ?? -1,
      id: "views",
      header: "播放",
      cell: ({ row }) => formatNumber(row.original.latest_snapshot?.view_count),
    },
    {
      accessorKey: "view_growth_24h",
      header: "24h 增长",
      cell: ({ row }) => formatNumber(row.original.view_growth_24h),
    },
    {
      accessorFn: (item) => item.latest_snapshot?.like_count ?? -1,
      id: "likes",
      header: "点赞",
      cell: ({ row }) => formatNumber(row.original.latest_snapshot?.like_count),
    },
    {
      accessorFn: (item) => item.latest_snapshot?.comment_count ?? -1,
      id: "comments",
      header: "评论",
      cell: ({ row }) =>
        formatNumber(row.original.latest_snapshot?.comment_count),
    },
    {
      accessorFn: (item) => item.latest_snapshot?.share_count ?? -1,
      id: "shares",
      header: "分享",
      cell: ({ row }) =>
        formatNumber(row.original.latest_snapshot?.share_count),
    },
    {
      accessorFn: (item) =>
        item.latest_snapshot && item.latest_snapshot.view_count
          ? ((item.latest_snapshot.like_count ?? 0) +
              (item.latest_snapshot.comment_count ?? 0) +
              (item.latest_snapshot.share_count ?? 0)) /
            item.latest_snapshot.view_count
          : null,
      id: "engagement",
      header: "互动率",
      cell: ({ getValue }) => formatPercent(getValue<number | null>()),
    },
  ];
  return (
    <main className="mx-auto max-w-[1600px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Content Analytics"
        title="作品数据"
        description="统一排序、筛选和比较作品快照；增长量来自派生指标，不会冒充平台原始字段。"
        actions={
          <>
            <button className={secondaryButtonClass} onClick={saveView}>
              <Save size={15} />
              保存视图
            </button>
            <button
              className={secondaryButtonClass}
              onClick={() =>
                workspaceId &&
                downloadApiFile(
                  `/contents/export.csv?${contentPath.split("?")[1] ?? ""}`,
                  workspaceId,
                  "contents.csv",
                )
              }
            >
              <Download size={15} />
              导出
            </button>
            <button
              className={buttonClass}
              disabled={
                !selected.length ||
                !["owner", "admin", "editor", "analyst"].includes(role ?? "")
              }
              onClick={createTopics}
            >
              <BookMarked size={15} />
              批量创建选题 {selected.length || ""}
            </button>
            <button
              className={secondaryButtonClass}
              disabled={
                !selected.length ||
                !["owner", "admin", "editor"].includes(role ?? "")
              }
              onClick={() =>
                router.push(
                  `/automations/new?entity=content&ids=${encodeURIComponent(selected.join(","))}`,
                )
              }
            >
              批量添加监控规则
            </button>
          </>
        }
      />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <label className="relative">
          <Search
            className="absolute top-1/2 left-3 -translate-y-1/2 text-slate-500"
            size={15}
          />
          <input
            className={`${inputClass} w-full pl-9`}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            placeholder="搜索标题或描述"
          />
        </label>
        <select
          className={inputClass}
          value={platform}
          onChange={(e) => {
            setPlatform(e.target.value);
            setPage(1);
          }}
        >
          <option value="">全部平台</option>
          {platforms.data?.map((item) => (
            <option key={item.id} value={item.key}>
              {item.name}
            </option>
          ))}
        </select>
        <input
          className={inputClass}
          value={minViews}
          min="0"
          type="number"
          onChange={(e) => setMinViews(e.target.value)}
          placeholder="最低播放量"
        />
        <input
          className={inputClass}
          value={publishedFrom}
          type="date"
          onChange={(e) => setPublishedFrom(e.target.value)}
        />
      </div>
      {contents.isLoading ? (
        <div className="rounded-2xl border border-slate-800">
          <SkeletonRows />
        </div>
      ) : contents.error ? (
        <StatePanel
          type="error"
          title="作品加载失败"
          detail={contents.error.message}
          onRetry={() => contents.refetch()}
        />
      ) : (
        <DataTable
          data={contents.data?.items ?? []}
          columns={columns}
          total={contents.data?.total ?? 0}
          page={page}
          pageSize={20}
          onPageChange={setPage}
          empty="没有符合条件的作品；请先同步账号。"
          getRowId={(row) => row.id}
        />
      )}
    </main>
  );
}
