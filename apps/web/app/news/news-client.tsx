"use client";
import type {
  ArticleRecord,
  ArticleRecordPage,
  NewsSourceRecord,
  TopicEventPage,
} from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Bookmark,
  CalendarClock,
  Eye,
  Layers,
  LayoutGrid,
  List,
  Maximize2,
  Plus,
  RefreshCw,
  Rows3,
  Search,
  Settings2,
  Sparkles,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import { Pagination } from "@/components/pagination";
import { useToast } from "@/components/toast";
import {
  Badge,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { buildNewsListPath } from "@/lib/admin-queries";
import {
  formatDate,
  formatNumber,
  formatRelativeTime,
  sourceKindLabel,
  sportLabel,
} from "@/lib/format";
import { useUrlState } from "@/lib/use-persisted-state";

type View = "cards" | "table" | "timeline" | "cluster";
type Density = "compact" | "comfortable";

/* ------------------------------------------------------------------ */
/*  Helper: score badge tone                                          */
/* ------------------------------------------------------------------ */
function heatTone(score: number | null): "danger" | "warning" | "neutral" {
  if (score === null) return "neutral";
  if (score > 80) return "danger";
  if (score > 60) return "warning";
  return "neutral";
}

function sourceKindTone(
  kind: string,
): "success" | "info" | "warning" | "neutral" {
  if (kind === "live") return "success";
  if (kind === "imported") return "info";
  return "neutral";
}

function metadataScore(
  metadata: Record<string, unknown>,
  key: string,
): number | null {
  const v = metadata?.[key];
  if (typeof v === "number") return v;
  if (typeof v === "string" && v !== "") return Number(v);
  return null;
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */
export function NewsClient() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [viewRaw, setView] = useUrlState("view", "cards");
  const view = viewRaw as View;
  const [density, setDensity] = useState<Density>("comfortable");
  const [query, setQuery] = useState("");
  const [sport, setSport] = useUrlState("sport", "");
  const [language, setLanguage] = useState("");
  const [sourceId, setSourceId] = useUrlState("source", "");
  const [league, setLeague] = useState("");
  const [country, setCountry] = useState("");
  const [publishedFrom, setPublishedFrom] = useState("");
  const [publishedTo, setPublishedTo] = useState("");
  const [minHeat, setMinHeat] = useState("");
  const [bookmarked, setBookmarked] = useState(false);
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const canEdit = ["owner", "admin", "editor"].includes(role ?? "");

  const newsPath = buildNewsListPath({
    page,
    query,
    sport,
    language,
    bookmarked,
    source: sourceId,
    league,
    country,
    publishedFrom,
    publishedTo,
    minHeat,
  });

  const news = useQuery({
    queryKey: ["news", workspaceId, newsPath],
    queryFn: () =>
      apiRequest<ArticleRecordPage>(newsPath, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });

  const sources = useQuery({
    queryKey: ["news-sources", workspaceId],
    queryFn: () =>
      apiRequest<{ items: NewsSourceRecord[] }>(
        "/news/sources?page=1&page_size=100",
        {
          workspaceId: workspaceId!,
        },
      ),
    enabled: Boolean(workspaceId),
  });

  const previewArticle = useQuery({
    queryKey: ["news-article", workspaceId, previewId],
    queryFn: () =>
      apiRequest<ArticleRecord>(`/news/articles/${previewId}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && Boolean(previewId),
  });

  const events = useQuery({
    queryKey: ["news-events", workspaceId],
    queryFn: () =>
      apiRequest<TopicEventPage>(
        "/news/events?page=1&page_size=100&sort=heat_score&order=desc",
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId) && view === "cluster",
  });

  async function syncAllSources() {
    if (!workspaceId || !sources.data) return;
    setSyncing(true);
    const enabled = sources.data.items.filter(
      (s) => s.enabled && s.source_type !== "manual",
    );
    let success = 0;
    let failed = 0;
    for (const source of enabled) {
      try {
        await apiRequest(`/news/sources/${source.id}/sync`, {
          method: "POST",
          workspaceId,
          csrf: true,
          body: JSON.stringify({}),
        });
        success++;
      } catch {
        failed++;
      }
    }
    setSyncing(false);
    if (success > 0) {
      notify(`已触发 ${success} 个源同步${failed ? `，${failed} 个失败` : ""}`);
      setTimeout(() => client.invalidateQueries({ queryKey: ["news"] }), 5000);
    } else {
      notify("没有可同步的已启用源", "error");
    }
  }

  async function toggleBookmark(article: ArticleRecord) {
    if (!workspaceId) return;
    const next = !article.is_bookmarked;
    try {
      await apiRequest(`/news/articles/${article.id}/bookmark`, {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ bookmarked: next }),
      });
      notify(next ? "已收藏" : "已取消收藏");
      await client.invalidateQueries({ queryKey: ["news"] });
    } catch {
      notify("收藏操作失败", "error");
    }
  }

  async function createArticle(form: FormData) {
    if (!workspaceId) return;
    setPending(true);
    try {
      await apiRequest<ArticleRecord>("/news/articles/manual", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          source_id: form.get("source_id"),
          title: form.get("title"),
          canonical_url: form.get("canonical_url"),
          summary: form.get("summary") || null,
          content: form.get("content") || null,
          author: form.get("author") || null,
          sport: form.get("sport") || null,
          league: form.get("league") || null,
          country: (form.get("country") as string)?.toUpperCase() || null,
          language: form.get("language") || null,
          published_at: form.get("published_at") || null,
        }),
      });
      notify("文章已添加");
      setCreating(false);
      await client.invalidateQueries({ queryKey: ["news"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "添加失败", "error");
    } finally {
      setPending(false);
    }
  }

  const activeFilterCount = [
    sourceId,
    league,
    country,
    publishedFrom,
    publishedTo,
    minHeat,
  ].filter(Boolean).length;

  /* ---------------------------------------------------------------- */
  /*  Table columns                                                    */
  /* ---------------------------------------------------------------- */
  const columns: ColumnDef<ArticleRecord, unknown>[] = [
    {
      accessorKey: "title",
      header: "新闻",
      cell: ({ row }) => (
        <div className="min-w-72 max-w-96">
          <Link
            className="font-medium text-cyan-300 hover:underline"
            href={`/news/${row.original.id}`}
          >
            {row.original.title}
          </Link>
          <p className="mt-0.5 line-clamp-1 text-xs text-slate-500">
            {row.original.summary}
          </p>
        </div>
      ),
    },
    {
      accessorFn: (item) => item.source.name,
      id: "source",
      header: "来源",
      cell: ({ row }) => (
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-slate-300">
          <span className="grid size-4 place-items-center rounded bg-slate-800 text-[9px] font-bold text-cyan-400">
            {row.original.source.name.charAt(0).toUpperCase()}
          </span>
          {row.original.source.name}
        </span>
      ),
    },
    {
      id: "sport_league",
      header: "运动/联赛",
      accessorFn: (item) => `${item.sport ?? ""} ${item.league ?? ""}`,
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-1">
          <Badge tone="info">{sportLabel(row.original.sport)}</Badge>
          {row.original.league && <Badge>{row.original.league}</Badge>}
        </div>
      ),
    },
    {
      accessorKey: "heat_score",
      header: "热度评分",
      cell: ({ row }) => (
        <Badge tone={heatTone(row.original.heat_score)}>
          {formatNumber(row.original.heat_score)}
        </Badge>
      ),
    },
    {
      id: "controversy_score",
      header: "争议度",
      accessorFn: (item) =>
        metadataScore(item.metadata, "controversy_score") ?? 0,
      cell: ({ row }) => {
        const v = metadataScore(row.original.metadata, "controversy_score");
        return <span className="text-xs tabular-nums">{v !== null ? v.toFixed(1) : "—"}</span>;
      },
    },
    {
      id: "visual_score",
      header: "视觉价值",
      accessorFn: (item) => metadataScore(item.metadata, "visual_score") ?? 0,
      cell: ({ row }) => {
        const v = metadataScore(row.original.metadata, "visual_score");
        return <span className="text-xs tabular-nums">{v !== null ? v.toFixed(1) : "—"}</span>;
      },
    },
    {
      id: "story_score",
      header: "故事价值",
      accessorFn: (item) => metadataScore(item.metadata, "story_score") ?? 0,
      cell: ({ row }) => {
        const v = metadataScore(row.original.metadata, "story_score");
        return <span className="text-xs tabular-nums">{v !== null ? v.toFixed(1) : "—"}</span>;
      },
    },
    {
      accessorKey: "published_at",
      header: "发布时间",
      cell: ({ row }) => (
        <span
          className="whitespace-nowrap text-xs text-slate-400"
          title={formatDate(row.original.published_at)}
        >
          {formatRelativeTime(row.original.published_at)}
        </span>
      ),
    },
    {
      accessorKey: "source_kind",
      header: "来源类型",
      cell: ({ row }) => (
        <Badge tone={sourceKindTone(row.original.source_kind)}>
          {sourceKindLabel(row.original.source_kind)}
        </Badge>
      ),
    },
    {
      id: "actions",
      header: "操作",
      enableSorting: false,
      cell: ({ row }) => (
        <div className="flex items-center gap-1 whitespace-nowrap">
          <button
            className="inline-flex h-7 items-center gap-1 rounded-md border border-slate-700 px-2 text-xs text-slate-300 transition hover:bg-slate-800"
            onClick={() => setPreviewId(row.original.id)}
            title="预览全文（不跳转）"
          >
            <Maximize2 size={12} />
            预览
          </button>
          <Link
            className="inline-flex h-7 items-center gap-1 rounded-md border border-slate-700 px-2 text-xs text-slate-300 transition hover:bg-slate-800"
            href={`/news/${row.original.id}`}
            title="查看详情"
          >
            <Eye size={12} />
            详情
          </Link>
          <Link
            className="inline-flex h-7 items-center gap-1 rounded-md border border-cyan-800 bg-cyan-950/40 px-2 text-xs text-cyan-300 transition hover:bg-cyan-900/50"
            href={`/generate?input_type=news&input_id=${row.original.id}`}
            title="基于此新闻创作内容"
          >
            <Sparkles size={12} />
            生成
          </Link>
          <button
            className={`inline-flex h-7 items-center gap-1 rounded-md border px-2 text-xs transition ${
              row.original.is_bookmarked
                ? "border-amber-700 bg-amber-950/40 text-amber-300 hover:bg-amber-900/50"
                : "border-slate-700 text-slate-400 hover:bg-slate-800"
            }`}
            onClick={() => toggleBookmark(row.original)}
            title={row.original.is_bookmarked ? "取消收藏" : "收藏"}
          >
            <Bookmark
              size={12}
              fill={row.original.is_bookmarked ? "currentColor" : "none"}
            />
            收藏
          </button>
        </div>
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
          <div className="flex items-center gap-2">
            <button
              className={secondaryButtonClass}
              onClick={syncAllSources}
              disabled={syncing}
              title="同步所有已启用的新闻源"
            >
              <RefreshCw size={15} className={syncing ? "animate-spin" : ""} />
              {syncing ? "同步中…" : "刷新"}
            </button>
            <Link className={secondaryButtonClass} href="/settings?tab=sources">
              <Settings2 size={15} />
              管理源
            </Link>
            {canEdit && (
              <button
                className={buttonClass}
                onClick={() => setCreating((v) => !v)}
              >
                <Plus size={16} />
                手动添加文章
              </button>
            )}
            <div className="flex rounded-lg border border-slate-700 p-1">
              {(
                [
                  ["cards", LayoutGrid, "卡片"],
                  ["table", List, "表格"],
                  ["timeline", CalendarClock, "时间线"],
                  ["cluster", Layers, "聚合"],
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
          </div>
        }
      />

      {/* Primary filters */}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
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
        <select
          className={inputClass}
          value={sourceId}
          onChange={(e) => {
            setSourceId(e.target.value);
            setPage(1);
          }}
        >
          <option value="">全部来源</option>
          {sources.data?.items?.map((s) => (
            <option value={s.id} key={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <input
          className={inputClass}
          value={sport}
          onChange={(e) => {
            setSport(e.target.value);
            setPage(1);
          }}
          placeholder="体育项目"
        />
        <input
          className={inputClass}
          value={language}
          onChange={(e) => {
            setLanguage(e.target.value);
            setPage(1);
          }}
          placeholder="语言，如 en"
        />
        <div className="flex items-center gap-3">
          <label className="flex h-10 items-center gap-2 rounded-lg border border-slate-700 px-3 text-sm">
            <input
              type="checkbox"
              checked={bookmarked}
              onChange={(e) => {
                setBookmarked(e.target.checked);
                setPage(1);
              }}
            />
            已收藏
          </label>
          <button
            className={`${secondaryButtonClass} h-10 px-3 text-xs ${showFilters || activeFilterCount > 0 ? "border-cyan-700 text-cyan-300" : ""}`}
            onClick={() => setShowFilters((v) => !v)}
          >
            更多筛选{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
          </button>
        </div>
      </div>

      {/* Extended filters */}
      {showFilters && (
        <div className="grid gap-3 rounded-xl border border-slate-800 bg-slate-950/50 p-4 md:grid-cols-3 xl:grid-cols-6">
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">联赛</span>
            <input
              className={`${inputClass} w-full`}
              value={league}
              onChange={(e) => {
                setLeague(e.target.value);
                setPage(1);
              }}
              placeholder="如 NBA、NFL"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">
              国家 (ISO)
            </span>
            <input
              className={`${inputClass} w-full`}
              value={country}
              onChange={(e) => {
                setCountry(e.target.value);
                setPage(1);
              }}
              placeholder="如 US、CN"
              maxLength={2}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">起始日期</span>
            <input
              className={`${inputClass} w-full`}
              type="date"
              value={publishedFrom}
              onChange={(e) => {
                setPublishedFrom(e.target.value);
                setPage(1);
              }}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">截止日期</span>
            <input
              className={`${inputClass} w-full`}
              type="date"
              value={publishedTo}
              onChange={(e) => {
                setPublishedTo(e.target.value);
                setPage(1);
              }}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">最低热度</span>
            <input
              className={`${inputClass} w-full`}
              type="number"
              min="0"
              max="100"
              value={minHeat}
              onChange={(e) => {
                setMinHeat(e.target.value);
                setPage(1);
              }}
              placeholder="0"
            />
          </label>
          <div className="flex items-end">
            <button
              className={`${secondaryButtonClass} w-full justify-center`}
              onClick={() => {
                setSourceId("");
                setLeague("");
                setCountry("");
                setPublishedFrom("");
                setPublishedTo("");
                setMinHeat("");
                setSport("");
                setLanguage("");
                setQuery("");
                setBookmarked(false);
                setPage(1);
              }}
            >
              清除全部筛选
            </button>
          </div>
        </div>
      )}

      {creating && (
        <form
          action={createArticle}
          className="grid gap-3 rounded-2xl border border-cyan-900/60 bg-slate-950/70 p-5 md:grid-cols-2 xl:grid-cols-3"
        >
          <select name="source_id" required className={inputClass}>
            <option value="">选择手动录入源</option>
            {sources.data?.items
              ?.filter((s) => s.source_type === "manual")
              .map((s) => (
                <option value={s.id} key={s.id}>
                  {s.name}
                </option>
              ))}
          </select>
          {sources.data?.items?.filter((s) => s.source_type === "manual")
            .length === 0 && (
            <p className="text-xs text-amber-400 md:col-span-2 xl:col-span-3">
              暂无手动录入源，请先在「设置 →
              新闻源」中创建一个类型为“手动录入”的源。
            </p>
          )}
          <input
            name="title"
            required
            className={inputClass}
            placeholder="文章标题"
          />
          <input
            name="canonical_url"
            required
            type="url"
            className={inputClass}
            placeholder="文章链接 (https://...)"
          />
          <input
            name="author"
            className={inputClass}
            placeholder="作者（可选）"
          />
          <input
            name="sport"
            className={inputClass}
            placeholder="体育项目（可选，如 basketball）"
          />
          <input
            name="league"
            className={inputClass}
            placeholder="联赛（可选，如 NBA）"
          />
          <input
            name="country"
            className={inputClass}
            placeholder="国家代码（可选，如 US）"
            maxLength={2}
          />
          <input
            name="language"
            className={inputClass}
            placeholder="语言（可选，如 en）"
          />
          <input
            name="published_at"
            type="datetime-local"
            className={inputClass}
            placeholder="发布时间（可选）"
          />
          <textarea
            name="summary"
            className={`${inputClass} h-20 resize-none md:col-span-2 xl:col-span-3`}
            placeholder="摘要（可选）"
          />
          <textarea
            name="content"
            className={`${inputClass} h-28 resize-none md:col-span-2 xl:col-span-3`}
            placeholder="正文内容（可选）"
          />
          <div className="flex gap-2 md:col-span-2 xl:col-span-3">
            <button disabled={pending} className={buttonClass}>
              {pending ? "保存中…" : "保存文章"}
            </button>
            <button
              type="button"
              className={secondaryButtonClass}
              onClick={() => setCreating(false)}
            >
              取消
            </button>
          </div>
          <p className="text-xs text-slate-500 md:col-span-2 xl:col-span-3">
            手动添加的文章标记为 imported 来源；需要关联一个已配置的新闻源。
          </p>
        </form>
      )}

      {news.isLoading ? (
        <Panel>
          <SkeletonRows />
        </Panel>
      ) : news.error ? (
        <StatePanel
          type="error"
          title="新闻加载失败"
          detail={(news.error as Error).message}
          onRetry={() => news.refetch()}
        />
      ) : view === "table" ? (
        <>
          {/* Density toggle */}
          <div className="flex items-center justify-end gap-2">
            <span className="text-xs text-slate-500">行密度</span>
            <div className="flex rounded-lg border border-slate-700 p-0.5">
              {(
                [
                  ["comfortable", "宽松"],
                  ["compact", "紧凑"],
                ] as const
              ).map(([key, label]) => (
                <button
                  className={`rounded-md px-2.5 py-1 text-xs transition ${
                    density === key
                      ? "bg-cyan-400 text-slate-950"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                  key={key}
                  onClick={() => setDensity(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            <Rows3 size={14} className="text-slate-500" />
          </div>
          <DataTable
            data={news.data?.items ?? []}
            columns={columns}
            total={news.data?.total ?? 0}
            page={page}
            pageSize={20}
            onPageChange={setPage}
            getRowId={(row) => row.id}
            density={density}
            stickyHeader
          />
        </>
      ) : view === "cluster" ? (
        events.isLoading ? (
          <Panel>
            <SkeletonRows />
          </Panel>
        ) : events.error ? (
          <StatePanel
            type="error"
            title="事件聚类加载失败"
            detail={(events.error as Error).message}
            onRetry={() => events.refetch()}
          />
        ) : !events.data?.items.length ? (
          <StatePanel
            type="empty"
            title="暂无聚类事件"
            detail="当多篇报道被归并到同一事件时，这里会按事件聚合展示多来源报道。"
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {events.data.items.map((event) => (
              <Panel key={event.id} className="relative p-5">
                <div className="flex items-start justify-between gap-3">
                  <Link
                    href={`/events/${event.id}`}
                    className="font-medium leading-6 text-slate-100 hover:text-cyan-300"
                  >
                    {event.title}
                  </Link>
                  {event.is_bookmarked && (
                    <Bookmark
                      size={14}
                      className="mt-1 shrink-0 text-amber-300"
                      fill="currentColor"
                    />
                  )}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Badge tone="info">{sportLabel(event.sport)}</Badge>
                  {event.league && <Badge>{event.league}</Badge>}
                  <Badge tone={heatTone(event.heat_score)}>
                    热度 {formatNumber(event.heat_score)}
                  </Badge>
                  <Badge>来源 {event.source_count}</Badge>
                  <Badge tone="neutral">{eventStatusLabel(event.status)}</Badge>
                </div>
                {event.summary && (
                  <p className="mt-3 line-clamp-2 text-sm leading-6 text-slate-400">
                    {event.summary}
                  </p>
                )}
                <div className="mt-4 flex items-center gap-2 border-t border-slate-800/60 pt-3">
                  <Link
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 text-xs text-slate-300 transition hover:bg-slate-800"
                    href={`/events/${event.id}`}
                  >
                    查看 {event.article_count} 篇报道
                  </Link>
                </div>
              </Panel>
            ))}
          </div>
        )
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
                  <span className="inline-flex items-center gap-1.5">
                    <span className="grid size-4 place-items-center rounded bg-slate-800 text-[9px] font-bold text-cyan-400">
                      {article.source.name.charAt(0).toUpperCase()}
                    </span>
                    {article.source.name}
                  </span>
                  <span title={formatDate(article.published_at)}>
                    {formatRelativeTime(article.published_at)}
                  </span>
                </div>
                <Link href={`/news/${article.id}`}>
                  <h2 className="mt-3 line-clamp-2 font-medium leading-6 text-slate-100 hover:text-cyan-300">
                    {article.title}
                  </h2>
                </Link>
                <p className="mt-2 line-clamp-3 text-sm leading-6 text-slate-400">
                  {article.summary || "来源未提供摘要"}
                </p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Badge tone="info">{sportLabel(article.sport)}</Badge>
                  {article.league && <Badge>{article.league}</Badge>}
                  <Badge tone={heatTone(article.heat_score)}>
                    热度 {formatNumber(article.heat_score)}
                  </Badge>
                  <Badge tone={sourceKindTone(article.source_kind)}>
                    {sourceKindLabel(article.source_kind)}
                  </Badge>
                  {article.event_id && (
                    <Link
                      className="text-xs text-cyan-300"
                      href={`/events/${article.event_id}`}
                    >
                      查看事件
                    </Link>
                  )}
                </div>
                {/* Action buttons - consistent across views */}
                <div className="mt-4 flex items-center gap-2 border-t border-slate-800/60 pt-3">
                  <button
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 text-xs text-slate-300 transition hover:bg-slate-800"
                    onClick={() => setPreviewId(article.id)}
                    title="预览全文（不跳转）"
                  >
                    <Maximize2 size={13} />
                    预览
                  </button>
                  <Link
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 text-xs text-slate-300 transition hover:bg-slate-800"
                    href={`/news/${article.id}`}
                    title="查看详情"
                  >
                    <Eye size={13} />
                    查看详情
                  </Link>
                  <Link
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-cyan-800 bg-cyan-950/40 px-2.5 text-xs text-cyan-300 transition hover:bg-cyan-900/50"
                    href={`/generate?input_type=news&input_id=${article.id}`}
                    title="基于此新闻创作内容"
                  >
                    <Sparkles size={13} />
                    生成
                  </Link>
                  <button
                    className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs transition ${
                      article.is_bookmarked
                        ? "border-amber-700 bg-amber-950/40 text-amber-300 hover:bg-amber-900/50"
                        : "border-slate-700 text-slate-400 hover:bg-slate-800"
                    }`}
                    onClick={() => toggleBookmark(article)}
                    title={article.is_bookmarked ? "取消收藏" : "收藏"}
                  >
                    <Bookmark
                      size={13}
                      fill={article.is_bookmarked ? "currentColor" : "none"}
                    />
                    收藏
                  </button>
                </div>
              </Panel>
            ))}
          </div>
          {!news.data?.items.length && (
            <StatePanel
              type="empty"
              title="暂无新闻"
              detail="请点击右上角「刷新」同步已启用的新闻源，或在「管理源」中配置新的新闻源。"
            />
          )}
          <Pagination
            page={page}
            total={news.data?.total ?? 0}
            pageSize={20}
            onPageChange={setPage}
          />
        </>
      )}
      {previewId && (
        <ArticlePreviewDrawer
          article={previewArticle.data}
          isLoading={previewArticle.isLoading}
          error={previewArticle.error as Error | null}
          onClose={() => setPreviewId(null)}
        />
      )}
    </main>
  );
}

/* ------------------------------------------------------------------ */
/*  Helper: event status label                                        */
/* ------------------------------------------------------------------ */
function eventStatusLabel(status: string): string {
  if (status === "active") return "进行中";
  if (status === "developing") return "发展中";
  if (status === "closed") return "已结束";
  return status;
}

/* ------------------------------------------------------------------ */
/*  Article preview Drawer (no navigation)                            */
/* ------------------------------------------------------------------ */
function ArticlePreviewDrawer({
  article,
  isLoading,
  error,
  onClose,
}: {
  article: ArticleRecord | undefined;
  isLoading: boolean;
  error: Error | null;
  onClose: () => void;
}) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label="新闻预览"
    >
      <button
        aria-label="关闭预览"
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
        tabIndex={-1}
      />
      <aside className="relative flex h-full w-full max-w-xl flex-col border-l border-slate-800 bg-slate-950 shadow-2xl">
        <div className="flex items-center justify-between gap-3 border-b border-slate-800 px-5 py-4">
          <span className="text-xs uppercase tracking-wider text-slate-500">
            新闻预览
          </span>
          <button
            aria-label="关闭"
            className="grid size-8 place-items-center rounded-lg border border-slate-700 text-slate-400 hover:bg-slate-800"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {isLoading ? (
            <SkeletonRows />
          ) : error ? (
            <StatePanel
              type="error"
              title="预览加载失败"
              detail={error.message}
              onRetry={onClose}
            />
          ) : article ? (
            <article className="space-y-4">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span className="inline-flex items-center gap-1.5">
                  <span className="grid size-4 place-items-center rounded bg-slate-800 text-[9px] font-bold text-cyan-400">
                    {article.source.name.charAt(0).toUpperCase()}
                  </span>
                  {article.source.name}
                </span>
                <span title={formatDate(article.published_at)}>
                  {article.published_at
                    ? formatRelativeTime(article.published_at)
                    : "时间未知"}
                </span>
                <Badge tone={sourceKindTone(article.source_kind)}>
                  {sourceKindLabel(article.source_kind)}
                </Badge>
              </div>
              <h1 className="text-xl font-semibold leading-7 text-slate-100">
                {article.title}
              </h1>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="info">{sportLabel(article.sport)}</Badge>
                {article.league && <Badge>{article.league}</Badge>}
                <Badge tone={heatTone(article.heat_score)}>
                  热度 {formatNumber(article.heat_score)}
                </Badge>
                {article.author && (
                  <span className="text-xs text-slate-500">{article.author}</span>
                )}
              </div>
              {article.summary && (
                <p className="text-sm leading-7 text-slate-300">
                  {article.summary}
                </p>
              )}
              {article.content ? (
                <div className="whitespace-pre-wrap text-sm leading-7 text-slate-400">
                  {article.content}
                </div>
              ) : (
                <p className="text-sm text-slate-500">
                  来源未提供正文，点击下方链接查看原文。
                </p>
              )}
              {article.canonical_url && (
                <a
                  href={article.canonical_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-block text-xs text-cyan-300 hover:underline"
                >
                  打开原文 ↗
                </a>
              )}
              <div className="flex items-center gap-2 border-t border-slate-800 pt-4">
                <Link
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 text-xs text-slate-300 transition hover:bg-slate-800"
                  href={`/news/${article.id}`}
                >
                  <Eye size={13} />
                  查看完整详情
                </Link>
                <Link
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-cyan-800 bg-cyan-950/40 px-2.5 text-xs text-cyan-300 transition hover:bg-cyan-900/50"
                  href={`/generate?input_type=news&input_id=${article.id}`}
                >
                  <Sparkles size={13} />
                  基于此创作
                </Link>
              </div>
            </article>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
