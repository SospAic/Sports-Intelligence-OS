"use client";
import type { ArticleRecord, ArticleRecordPage } from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  CalendarClock,
  LayoutGrid,
  List,
  Search,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
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
import { buildNewsListPath } from "@/lib/admin-queries";
import { formatDate, formatNumber } from "@/lib/format";
type View = "cards" | "table" | "timeline";
export function NewsClient() {
  const { workspaceId } = useWorkspace();
  const [page, setPage] = useState(1);
  const [view, setView] = useState<View>("cards");
  const [query, setQuery] = useState("");
  const [sport, setSport] = useState("");
  const [language, setLanguage] = useState("");
  const [bookmarked, setBookmarked] = useState(false);
  const newsPath = buildNewsListPath({
    page,
    query,
    sport,
    language,
    bookmarked,
  });
  const news = useQuery({
    queryKey: ["news", workspaceId, newsPath],
    queryFn: () =>
      apiRequest<ArticleRecordPage>(newsPath, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const columns: ColumnDef<ArticleRecord, unknown>[] = [
    {
      accessorKey: "title",
      header: "新闻",
      cell: ({ row }) => (
        <div className="min-w-80">
          <Link
            className="font-medium text-cyan-300 hover:underline"
            href={`/news/${row.original.id}`}
          >
            {row.original.title}
          </Link>
          <p className="mt-1 line-clamp-1 text-xs text-slate-500">
            {row.original.summary}
          </p>
        </div>
      ),
    },
    { accessorFn: (item) => item.source.name, id: "source", header: "来源" },
    {
      accessorKey: "published_at",
      header: "发布时间",
      cell: ({ row }) => formatDate(row.original.published_at),
    },
    {
      accessorKey: "sport",
      header: "项目",
      cell: ({ row }) => row.original.sport || "综合",
    },
    {
      accessorKey: "heat_score",
      header: "热度",
      cell: ({ row }) => formatNumber(row.original.heat_score),
    },
    {
      accessorKey: "is_duplicate",
      header: "状态",
      cell: ({ row }) => (
        <Badge tone={row.original.is_duplicate ? "warning" : "success"}>
          {row.original.is_duplicate ? "重复报道" : "首发记录"}
        </Badge>
      ),
    },
  ];
  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="News Intelligence"
        title="新闻热点"
        description="聚合已授权 RSS、Atom、JSON Feed 与手动录入内容；发布时间缺失时不会用抓取时间冒充。"
        actions={
          <div className="flex rounded-lg border border-slate-700 p-1">
            {(
              [
                ["cards", LayoutGrid, "卡片"],
                ["table", List, "表格"],
                ["timeline", CalendarClock, "时间线"],
              ] as const
            ).map(([key, Icon, label]) => (
              <button
                aria-label={label}
                title={label}
                className={`rounded-md p-2 ${view === key ? "bg-cyan-400 text-slate-950" : "text-slate-400"}`}
                key={key}
                onClick={() => setView(key)}
              >
                <Icon size={16} />
              </button>
            ))}
          </div>
        }
      />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <label className="relative xl:col-span-2">
          <Search
            size={15}
            className="absolute top-1/2 left-3 -translate-y-1/2 text-slate-500"
          />
          <input
            className={`${inputClass} w-full pl-9`}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            placeholder="搜索标题、人物、队伍或赛事"
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
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          placeholder="语言，如 en"
        />
        <label className="flex h-10 items-center gap-2 rounded-lg border border-slate-700 px-3 text-sm">
          <input
            type="checkbox"
            checked={bookmarked}
            onChange={(e) => setBookmarked(e.target.checked)}
          />
          仅看已收藏
        </label>
      </div>
      {news.isLoading ? (
        <Panel>
          <SkeletonRows />
        </Panel>
      ) : news.error ? (
        <StatePanel
          type="error"
          title="新闻加载失败"
          detail={news.error.message}
          onRetry={() => news.refetch()}
        />
      ) : view === "table" ? (
        <DataTable
          data={news.data?.items ?? []}
          columns={columns}
          total={news.data?.total ?? 0}
          page={page}
          pageSize={20}
          onPageChange={setPage}
          getRowId={(row) => row.id}
        />
      ) : (
        <>
          <div
            className={
              view === "cards"
                ? "grid gap-4 md:grid-cols-2 xl:grid-cols-3"
                : "relative ml-3 space-y-4 border-l border-slate-800 pl-6"
            }
          >
            {news.data?.items.map((article) => (
              <Panel key={article.id} className="relative p-5">
                {view === "timeline" && (
                  <span className="absolute top-6 -left-[31px] size-2 rounded-full bg-cyan-400" />
                )}
                <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
                  <span>{article.source.name}</span>
                  <span>{formatDate(article.published_at)}</span>
                </div>
                <Link href={`/news/${article.id}`}>
                  <h2 className="mt-3 line-clamp-2 font-medium leading-6 text-slate-100 hover:text-cyan-300">
                    {article.title}
                  </h2>
                </Link>
                <p className="mt-2 line-clamp-3 text-sm leading-6 text-slate-400">
                  {article.summary || "来源未提供摘要"}
                </p>
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <Badge tone="info">{article.sport || "综合"}</Badge>
                  <Badge tone={article.is_duplicate ? "warning" : "neutral"}>
                    热度 {formatNumber(article.heat_score)}
                  </Badge>
                  {article.event_id && (
                    <Link
                      className="text-xs text-cyan-300"
                      href={`/events/${article.event_id}`}
                    >
                      查看事件
                    </Link>
                  )}
                  <Link
                    className={`${secondaryButtonClass} ml-auto h-8 px-2`}
                    href={`/generate?input_type=news&input_id=${article.id}`}
                  >
                    <Sparkles size={13} />
                    生成
                  </Link>
                </div>
              </Panel>
            ))}
          </div>
          {!news.data?.items.length && (
            <StatePanel
              type="empty"
              title="暂无新闻"
              detail="请在设置中配置并同步已授权的新闻源。"
            />
          )}
          <div className="flex justify-center gap-2">
            <button
              className={secondaryButtonClass}
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              上一页
            </button>
            <span className="grid place-items-center px-3 text-sm text-slate-500">
              第 {page} 页
            </span>
            <button
              className={secondaryButtonClass}
              disabled={(news.data?.items.length ?? 0) < 20}
              onClick={() => setPage(page + 1)}
            >
              下一页
            </button>
          </div>
        </>
      )}
    </main>
  );
}
