"use client";

import type {
  AccountRecordPage,
  ContentRecord,
  ContentRecordPage,
  PlatformRecord,
} from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  BookMarked,
  Download,
  Pencil,
  Plus,
  Search,
  Save,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import { ExternalImage } from "@/components/external-image";
import {
  AvailabilityValue,
  NeedsConditionBadge,
} from "@/components/metric-availability";
import { TimeRangePicker } from "@/components/time-range-picker";
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
import { ContentCalendar } from "./content-calendar";
import { buildContentListPath } from "@/lib/admin-queries";
import {
  metricAvailability,
  metricConditionText,
} from "@/lib/metric-availability";
import { resolvePublishedFrom } from "@/lib/time-range";
import { useUrlState } from "@/lib/use-persisted-state";
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
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState(() => readSavedView().platform);
  const [minViews, setMinViews] = useState(() => readSavedView().minViews);
  const [range, setRange] = useUrlState("range", "all");
  const [from, setFrom] = useUrlState("from", "");
  const [view, setView] = useUrlState("view", "list");
  const publishedFrom = resolvePublishedFrom(range, from || null) ?? undefined;
  const [selected, setSelected] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const canEdit = ["owner", "admin", "editor"].includes(role ?? "");
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
  const accounts = useQuery({
    queryKey: ["accounts-for-content"],
    queryFn: () =>
      apiRequest<AccountRecordPage>("/accounts?page_size=200", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && creating,
  });
  const [pending, setPending] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  async function createContent(form: FormData) {
    if (!workspaceId) return;
    setPending(true);
    try {
      await apiRequest<ContentRecord>("/contents", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          account_id: form.get("account_id"),
          external_id: form.get("external_id"),
          title: form.get("title"),
          canonical_url: form.get("canonical_url"),
          content_type: form.get("content_type") || "video",
          description: form.get("description") || null,
          cover_url: form.get("cover_url") || null,
          published_at: form.get("published_at") || null,
          language: form.get("language") || null,
        }),
      });
      notify("作品已添加");
      setCreating(false);
      await client.invalidateQueries({ queryKey: ["contents"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "添加失败", "error");
    } finally {
      setPending(false);
    }
  }
  async function deleteContent(id: string) {
    if (!workspaceId) return;
    if (!window.confirm("确定删除该作品？此操作不可撤销。")) return;
    try {
      await apiRequest<void>(`/contents/${id}`, {
        method: "DELETE",
        workspaceId,
        csrf: true,
      });
      notify("作品已删除");
      await client.invalidateQueries({ queryKey: ["contents"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "删除失败", "error");
    }
  }
  async function updateContent(id: string) {
    if (!workspaceId) return;
    setPending(true);
    try {
      const body: Record<string, unknown> = {};
      if (editTitle.trim()) body.title = editTitle.trim();
      if (editDescription.trim()) body.description = editDescription.trim();
      if (!Object.keys(body).length) {
        setEditingId(null);
        return;
      }
      await apiRequest<ContentRecord>(`/contents/${id}`, {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify(body),
      });
      notify("作品已更新");
      setEditingId(null);
      await client.invalidateQueries({ queryKey: ["contents"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "更新失败", "error");
    } finally {
      setPending(false);
    }
  }
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
          <ExternalImage
            src={row.original.cover_url}
            alt=""
            className="h-12 w-20 rounded-md object-cover"
          />
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
      header: "约 24h 净增",
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
      accessorFn: (item) => {
        const snapshot = item.latest_snapshot;
        if (!snapshot?.view_count) return null;
        const observed = [
          snapshot.like_count,
          snapshot.comment_count,
          snapshot.share_count,
        ].filter(
          (value): value is number => value !== undefined && value !== null,
        );
        return observed.length
          ? observed.reduce((sum, value) => sum + value, 0) /
              snapshot.view_count
          : null;
      },
      id: "engagement",
      header: "互动率",
      cell: ({ getValue }) => formatPercent(getValue<number | null>()),
    },
    {
      accessorFn: (item) => item.latest_snapshot?.completion_rate ?? -1,
      id: "completion_rate",
      header: "完播率",
      cell: ({ row }) => {
        const value = row.original.latest_snapshot?.completion_rate;
        const status = metricAvailability(
          "completion_rate",
          value !== null && value !== undefined,
        );
        if (status === "needs-condition")
          return (
            <NeedsConditionBadge
              text={metricConditionText("completion_rate")}
            />
          );
        return (
          <AvailabilityValue
            metricKey="completion_rate"
            value={value}
            format={formatPercent}
          />
        );
      },
    },
    ...(canEdit
      ? [
          {
            id: "actions",
            header: "操作",
            enableSorting: false,
            cell: ({ row }: { row: { original: ContentRecord } }) => (
              <div className="flex items-center gap-2 whitespace-nowrap">
                {editingId === row.original.id ? (
                  <>
                    <input
                      className={`${inputClass} h-8 w-32 text-xs`}
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      placeholder="新标题"
                    />
                    <button
                      className="text-cyan-300 disabled:text-slate-600"
                      disabled={pending}
                      onClick={() => updateContent(row.original.id)}
                    >
                      保存
                    </button>
                    <button
                      className="text-slate-500"
                      onClick={() => setEditingId(null)}
                    >
                      取消
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      className="inline-flex items-center gap-1 text-cyan-300 hover:text-cyan-200"
                      onClick={() => {
                        setEditingId(row.original.id);
                        setEditTitle(row.original.title);
                        setEditDescription(row.original.description ?? "");
                      }}
                    >
                      <Pencil size={14} />
                      编辑
                    </button>
                    {["owner", "admin"].includes(role ?? "") && (
                      <button
                        className="inline-flex items-center gap-1 text-red-400 hover:text-red-300"
                        onClick={() => deleteContent(row.original.id)}
                      >
                        <Trash2 size={14} />
                        删除
                      </button>
                    )}
                  </>
                )}
              </div>
            ),
          } as ColumnDef<ContentRecord, unknown>,
        ]
      : []),
  ];
  return (
    <main className="mx-auto max-w-[1600px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Content Analytics"
        title="作品数据"
        description="统一排序、筛选和比较作品快照；增长量来自派生指标，不会冒充平台原始字段。"
        actions={
          <>
            <div className="flex overflow-hidden rounded-lg border border-slate-700">
              <button
                className={`px-3 py-1.5 text-sm ${
                  view === "list"
                    ? "bg-cyan-500/20 text-cyan-200"
                    : "text-slate-400 hover:bg-slate-800"
                }`}
                onClick={() => setView("list")}
              >
                列表
              </button>
              <button
                className={`px-3 py-1.5 text-sm ${
                  view === "calendar"
                    ? "bg-cyan-500/20 text-cyan-200"
                    : "text-slate-400 hover:bg-slate-800"
                }`}
                onClick={() => setView("calendar")}
              >
                日历
              </button>
            </div>
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
            {canEdit && (
              <button
                className={buttonClass}
                onClick={() => setCreating((value) => !value)}
              >
                <Plus size={16} />
                手动添加作品
              </button>
            )}
          </>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <TimeRangePicker
          value={range}
          onChange={setRange}
          customFrom={from}
          onCustomFromChange={setFrom}
        />
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
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
      </div>
      {creating && (
        <form
          action={createContent}
          className="grid gap-3 rounded-2xl border border-cyan-900/60 bg-slate-950/70 p-5 md:grid-cols-2 xl:grid-cols-3"
        >
          <select name="account_id" required className={inputClass}>
            <option value="">选择关联账号</option>
            {accounts.data?.items?.map((acc) => (
              <option value={acc.id} key={acc.id}>
                {acc.display_name} ({acc.platform.name})
              </option>
            ))}
          </select>
          <input
            name="external_id"
            required
            className={inputClass}
            placeholder="平台作品 ID"
          />
          <input
            name="title"
            required
            className={inputClass}
            placeholder="作品标题"
          />
          <input
            name="canonical_url"
            required
            type="url"
            className={inputClass}
            placeholder="作品链接 (https://...)"
          />
          <input
            name="cover_url"
            type="url"
            className={inputClass}
            placeholder="缩略图链接（可选）"
          />
          <select
            name="content_type"
            className={inputClass}
            defaultValue="video"
          >
            <option value="video">视频</option>
            <option value="short">短视频</option>
            <option value="live">直播</option>
            <option value="article">图文</option>
          </select>
          <input
            name="published_at"
            type="datetime-local"
            className={inputClass}
            placeholder="发布时间（可选）"
          />
          <input
            name="language"
            className={inputClass}
            placeholder="语言代码（可选，如 zh）"
          />
          <textarea
            name="description"
            className={`${inputClass} h-20 resize-none md:col-span-2`}
            placeholder="作品描述（可选）"
          />
          <div className="flex gap-2 md:col-span-2 xl:col-span-3">
            <button disabled={pending} className={buttonClass}>
              {pending ? "保存中…" : "保存作品"}
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
            手动添加的作品会标记为 imported
            来源；播放、点赞等数据需要账号同步后才会出现。
          </p>
        </form>
      )}
      {view === "calendar" ? (
        <ContentCalendar platform={platform} query={query} />
      ) : contents.isLoading ? (
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
