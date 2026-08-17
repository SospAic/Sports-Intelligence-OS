"use client";

import type {
  ContentRecordPage,
  PerformanceAttributionRecord,
  PublicationDetail,
  PublicationPage,
  PublicationRecord,
  PublicationStatus,
} from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  CheckCircle2,
  ExternalLink,
  Eye,
  FilePlus2,
  RefreshCw,
  Send,
  X,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";

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
import { formatDate, formatNumber, formatPercent, sourceKindLabel } from "@/lib/format";

const STATUS_OPTIONS: Array<{ value: PublicationStatus; label: string }> = [
  { value: "planned", label: "计划中" },
  { value: "scheduled", label: "已排期" },
  { value: "published", label: "已发布" },
  { value: "unverified", label: "待核实" },
  { value: "failed", label: "失败" },
  { value: "cancelled", label: "已取消" },
];

const WINDOW_LABELS: Record<string, string> = {
  "1h": "1 小时",
  "3h": "3 小时",
  "6h": "6 小时",
  "24h": "24 小时",
  "72h": "72 小时",
  "7d": "7 天",
  "30d": "30 天",
};

function statusLabel(status: PublicationStatus): string {
  return STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status;
}

function statusTone(
  status: PublicationStatus,
): "neutral" | "success" | "warning" | "danger" | "info" {
  if (status === "published") return "success";
  if (status === "scheduled") return "info";
  if (status === "failed" || status === "cancelled") return "danger";
  if (status === "unverified") return "warning";
  return "neutral";
}

function measurementTone(
  status: PerformanceAttributionRecord["measurement_status"],
): "neutral" | "success" | "warning" {
  if (status === "measured") return "success";
  if (status === "unavailable") return "warning";
  return "neutral";
}

type CreateForm = {
  title: string;
  content_item_id: string;
  status: PublicationStatus;
  published_at: string;
  canonical_url: string;
  external_id: string;
};

const EMPTY_FORM: CreateForm = {
  title: "",
  content_item_id: "",
  status: "planned",
  published_at: "",
  canonical_url: "",
  external_id: "",
};

export function PublicationsClient() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const canEdit = ["owner", "admin", "editor", "analyst"].includes(role ?? "");
  const pageSize = 20;
  const publicationPath = `/publications?page=${page}&page_size=${pageSize}${status ? `&status=${status}` : ""}`;

  const publications = useQuery({
    queryKey: ["publications", workspaceId, publicationPath],
    queryFn: () =>
      apiRequest<PublicationPage>(publicationPath, { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId),
  });
  const detail = useQuery({
    queryKey: ["publication-detail", workspaceId, selectedId],
    queryFn: () =>
      apiRequest<PublicationDetail>(`/publications/${selectedId}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId && selectedId),
  });
  const contents = useQuery({
    queryKey: ["publication-content-options", workspaceId],
    queryFn: () =>
      apiRequest<ContentRecordPage>("/contents?page=1&page_size=100", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId && showCreate),
  });

  const refreshAttribution = useCallback(async (publicationId: string) => {
    if (!workspaceId) return;
    setRefreshingId(publicationId);
    try {
      await apiRequest(`/publications/${publicationId}/attribution/refresh`, {
        method: "POST",
        workspaceId,
        csrf: true,
      });
      notify("归因窗口已按真实内容快照刷新");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["publications"] }),
        queryClient.invalidateQueries({ queryKey: ["publication-detail", workspaceId, publicationId] }),
      ]);
    } catch (error) {
      notify(error instanceof Error ? error.message : "归因刷新失败", "error");
    } finally {
      setRefreshingId(null);
    }
  }, [notify, queryClient, workspaceId]);

  const selected = detail.data;
  const columns = useMemo<ColumnDef<PublicationRecord, unknown>[]>(
    () => [
      {
        accessorKey: "title",
        header: "发布记录",
        cell: ({ row }) => (
          <button
            className="group min-w-64 text-left"
            onClick={() => setSelectedId(row.original.id)}
            type="button"
          >
            <span className="block max-w-[30rem] truncate font-medium text-cyan-200 group-hover:text-cyan-100">
              {row.original.title}
            </span>
            <span className="mt-1 block text-xs text-slate-500">
              {row.original.external_id ?? row.original.canonical_url ?? "尚未返回平台作品证据"}
            </span>
          </button>
        ),
      },
      {
        accessorKey: "status",
        header: "状态",
        cell: ({ getValue }) => {
          const value = getValue() as PublicationStatus;
          return <Badge tone={statusTone(value)}>{statusLabel(value)}</Badge>;
        },
      },
      {
        accessorKey: "source_kind",
        header: "来源",
        cell: ({ row }) => (
          <span className="text-sm text-slate-300">
            {sourceKindLabel(row.original.source_kind)}
            <span className="mt-1 block text-xs text-slate-500">{row.original.source_provider}</span>
          </span>
        ),
      },
      {
        accessorKey: "published_at",
        header: "发布时间",
        cell: ({ getValue }) => <span className="text-slate-400">{formatDate(getValue() as string | null)}</span>,
      },
      {
        accessorKey: "updated_at",
        header: "最近更新",
        cell: ({ getValue }) => <span className="text-slate-400">{formatDate(getValue() as string)}</span>,
      },
      {
        id: "actions",
        header: "操作",
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <button
              aria-label={`查看 ${row.original.title}`}
              className="rounded-lg border border-slate-700 p-2 text-slate-300 hover:border-cyan-700 hover:text-cyan-200"
              onClick={() => setSelectedId(row.original.id)}
              type="button"
            >
              <Eye size={15} />
            </button>
            <button
              aria-label={`刷新 ${row.original.title} 归因`}
              className="rounded-lg border border-slate-700 p-2 text-slate-300 hover:border-cyan-700 hover:text-cyan-200 disabled:opacity-50"
              disabled={!canEdit || !row.original.content_item_id || !row.original.published_at || refreshingId === row.original.id}
              onClick={() => void refreshAttribution(row.original.id)}
              title="只读取已有真实内容快照，不进行指标估算"
              type="button"
            >
              <RefreshCw className={refreshingId === row.original.id ? "animate-spin" : ""} size={15} />
            </button>
          </div>
        ),
      },
    ],
    [canEdit, refreshingId, refreshAttribution],
  );

  async function createPublication() {
    if (!workspaceId || !form.title.trim()) return;
    setCreating(true);
    const body: Record<string, unknown> = {
      title: form.title.trim(),
      status: form.status,
      source_kind: "imported",
      source_provider: "manual",
    };
    if (form.content_item_id) body.content_item_id = form.content_item_id;
    if (form.published_at) body.published_at = new Date(form.published_at).toISOString();
    if (form.canonical_url) body.canonical_url = form.canonical_url;
    if (form.external_id) body.external_id = form.external_id;
    try {
      const created = await apiRequest<PublicationDetail>("/publications", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify(body),
      });
      notify("发布记录已创建");
      setForm(EMPTY_FORM);
      setShowCreate(false);
      setSelectedId(created.id);
      await queryClient.invalidateQueries({ queryKey: ["publications"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "发布记录创建失败", "error");
    } finally {
      setCreating(false);
    }
  }

  return (
    <main className="mx-auto min-w-0 max-w-[1400px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="PUBLISHING INTELLIGENCE"
        title="发布与表现归因"
        description="记录计划、排期和外部发布证据，并在固定窗口到达后读取真实内容快照。没有快照时显示不可用，不用估算值替代。"
        actions={
          canEdit ? (
            <button className={buttonClass} onClick={() => setShowCreate((value) => !value)} type="button">
              {showCreate ? <X size={16} /> : <FilePlus2 size={16} />}
              {showCreate ? "收起表单" : "新建发布记录"}
            </button>
          ) : undefined
        }
      />

      {showCreate && canEdit && (
        <Panel className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <Send className="text-cyan-300" size={18} />
            <h2 className="font-medium text-white">登记发布记录</h2>
            <span className="text-xs text-slate-500">手动登记不会伪造平台发布成功</span>
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <label className="space-y-1 text-sm text-slate-300 md:col-span-2 xl:col-span-1">
              标题
              <input className={`${inputClass} w-full`} value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
            </label>
            <label className="space-y-1 text-sm text-slate-300">
              关联已监控作品
              <select className={`${inputClass} w-full`} value={form.content_item_id} onChange={(event) => setForm({ ...form, content_item_id: event.target.value })}>
                <option value="">不关联（暂不支持快照归因）</option>
                {(contents.data?.items ?? []).map((content) => (
                  <option key={content.id} value={content.id}>{content.title || content.external_id}</option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-sm text-slate-300">
              状态
              <select className={`${inputClass} w-full`} value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as PublicationStatus })}>
                {STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-sm text-slate-300">
              发布时间（已发布/待核实时必填）
              <input className={`${inputClass} w-full`} type="datetime-local" value={form.published_at} onChange={(event) => setForm({ ...form, published_at: event.target.value })} />
            </label>
            <label className="space-y-1 text-sm text-slate-300">
              平台作品 ID
              <input className={`${inputClass} w-full`} placeholder="没有则留空" value={form.external_id} onChange={(event) => setForm({ ...form, external_id: event.target.value })} />
            </label>
            <label className="space-y-1 text-sm text-slate-300">
              平台作品链接
              <input className={`${inputClass} w-full`} placeholder="https://…" type="url" value={form.canonical_url} onChange={(event) => setForm({ ...form, canonical_url: event.target.value })} />
            </label>
          </div>
          <div className="mt-4 flex justify-end">
            <button className={buttonClass} disabled={creating || !form.title.trim()} onClick={() => void createPublication()} type="button">
              {creating ? "创建中…" : "保存发布记录"}
            </button>
          </div>
        </Panel>
      )}

      <Panel className="p-4">
        <label className="flex max-w-xs items-center gap-2 text-sm text-slate-400">
          状态
          <select className={`${inputClass} flex-1`} value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}>
            <option value="">全部</option>
            {STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
      </Panel>

      {publications.isLoading ? (
        <Panel><SkeletonRows /></Panel>
      ) : publications.error ? (
        <Panel><StatePanel type="error" title="发布记录加载失败" detail={publications.error instanceof Error ? publications.error.message : "请稍后重试"} onRetry={() => void publications.refetch()} /></Panel>
      ) : (
        <>
          <DataTable
            data={publications.data?.items ?? []}
            columns={columns}
            total={publications.data?.total ?? 0}
            page={page}
            pageSize={pageSize}
            onPageChange={setPage}
            empty="尚未登记发布记录"
            getRowId={(row) => row.id}
          />
          <Pagination page={page} total={publications.data?.total ?? 0} pageSize={pageSize} onPageChange={setPage} />
        </>
      )}

      {selectedId && (
        <Panel className="overflow-hidden p-0">
          {detail.isLoading ? <SkeletonRows count={3} /> : detail.error ? (
            <StatePanel type="error" title="发布详情加载失败" detail={detail.error instanceof Error ? detail.error.message : "请稍后重试"} onRetry={() => void detail.refetch()} />
          ) : selected ? <PublicationDetailPanel detail={selected} onClose={() => setSelectedId(null)} onRefresh={() => void refreshAttribution(selected.id)} refreshing={refreshingId === selected.id} /> : null}
        </Panel>
      )}
    </main>
  );
}

function PublicationDetailPanel({
  detail,
  onClose,
  onRefresh,
  refreshing,
}: {
  detail: PublicationDetail;
  onClose: () => void;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const measured = detail.attributions.filter((item) => item.measurement_status === "measured").length;
  const unavailable = detail.attributions.filter((item) => item.measurement_status === "unavailable").length;
  const notDue = detail.attributions.filter((item) => item.measurement_status === "not_due").length;
  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-800 p-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-medium text-white">{detail.title}</h2>
            <Badge tone={statusTone(detail.status)}>{statusLabel(detail.status)}</Badge>
            <Badge tone={detail.source_kind === "live" ? "success" : "info"}>{sourceKindLabel(detail.source_kind)}</Badge>
          </div>
          <p className="mt-2 text-sm text-slate-400">发布时间：{formatDate(detail.published_at)} · 最近更新：{formatDate(detail.updated_at)}</p>
        </div>
        <div className="flex items-center gap-2">
          {detail.canonical_url && <a className={secondaryButtonClass} href={detail.canonical_url} rel="noreferrer" target="_blank"><ExternalLink size={15} />打开作品</a>}
          <button className={secondaryButtonClass} disabled={refreshing || !detail.content_item_id || !detail.published_at} onClick={onRefresh} title="只读取已有真实内容快照" type="button"><RefreshCw className={refreshing ? "animate-spin" : ""} size={15} />刷新归因</button>
          <button aria-label="关闭发布详情" className="rounded-lg border border-slate-700 p-2 text-slate-400 hover:text-white" onClick={onClose} type="button"><X size={16} /></button>
        </div>
      </div>
      <div className="grid gap-4 border-b border-slate-800 p-5 sm:grid-cols-3">
        <Summary label="已测窗口" value={String(measured)} hint="来自真实内容快照" tone="success" />
        <Summary label="未到期窗口" value={String(notDue)} hint="等待固定时间窗到达" tone="neutral" />
        <Summary label="缺失窗口" value={String(unavailable)} hint="不会用估算值填充" tone="warning" />
      </div>
      <div className="overflow-x-auto p-5">
        <table className="w-full min-w-[900px] text-left text-sm">
          <caption className="sr-only">固定窗口表现归因</caption>
          <thead className="border-b border-slate-800 text-xs text-slate-500"><tr><th className="px-3 py-3">窗口</th><th className="px-3 py-3">状态</th><th className="px-3 py-3">视图</th><th className="px-3 py-3">互动</th><th className="px-3 py-3">捕获时间</th><th className="px-3 py-3">来源与证据</th></tr></thead>
          <tbody className="divide-y divide-slate-800/80">
            {detail.attributions.map((item) => <AttributionRow item={item} key={item.id} />)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AttributionRow({ item }: { item: PerformanceAttributionRecord }) {
  const snapshotId = item.evidence.content_snapshot_id;
  return (
    <tr>
      <td className="px-3 py-3 font-medium text-slate-200">{WINDOW_LABELS[item.window_key] ?? item.window_key}<span className="mt-1 block text-xs text-slate-500">目标 {formatDate(item.target_at)}</span></td>
      <td className="px-3 py-3"><Badge tone={measurementTone(item.measurement_status)}>{item.measurement_status === "measured" ? "已测量" : item.measurement_status === "not_due" ? "未到期" : "不可用"}</Badge></td>
      <td className="px-3 py-3 tabular-nums text-slate-300">{formatNumber(item.view_count)}</td>
      <td className="px-3 py-3 text-xs text-slate-400">赞 {formatNumber(item.like_count)} · 评 {formatNumber(item.comment_count)}<span className="mt-1 block">分享 {formatNumber(item.share_count)} · 完播 {formatPercent(item.completion_rate)}</span></td>
      <td className="px-3 py-3 text-xs text-slate-400">{formatDate(item.captured_at)}{item.captured_offset_seconds !== null && <span className="mt-1 block text-slate-500">偏移 {Math.round(item.captured_offset_seconds / 60)} 分钟</span>}</td>
      <td className="max-w-[260px] px-3 py-3 text-xs text-slate-400"><span className="block">{item.source_provider ?? "—"} · {item.source_kind ? sourceKindLabel(item.source_kind) : "—"}</span><span className="mt-1 block truncate" title={typeof snapshotId === "string" ? snapshotId : undefined}>{typeof snapshotId === "string" ? `快照 ${snapshotId}` : item.note ?? "无快照证据"}</span></td>
    </tr>
  );
}

function Summary({ label, value, hint, tone }: { label: string; value: string; hint: string; tone: "success" | "neutral" | "warning" }) {
  return <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4"><div className="flex items-center gap-2 text-sm text-slate-400"><CheckCircle2 className={tone === "success" ? "text-emerald-400" : tone === "warning" ? "text-amber-400" : "text-slate-500"} size={15} />{label}</div><p className="mt-2 text-2xl font-semibold text-white">{value}</p><p className="mt-1 text-xs text-slate-500">{hint}</p></div>;
}
