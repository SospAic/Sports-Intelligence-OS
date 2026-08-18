"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Plus, RefreshCw } from "lucide-react";
import { useState } from "react";

import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import {
  Badge,
  PageHeader,
  Panel,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";

type Dimension = "title" | "hook" | "story_order" | "thumbnail";
type Status = "draft" | "running" | "completed" | "archived";
type Experiment = {
  id: string;
  name: string;
  hypothesis: string | null;
  dimension: Dimension;
  status: Status;
  variant_count: number;
  created_at: string;
  updated_at: string;
};
type Variant = {
  id: string;
  label: string;
  description: string | null;
  publication_id: string | null;
  content_item_id: string | null;
  created_at: string;
};
type Detail = Experiment & { variants: Variant[] };
type ExperimentPage = { items: Experiment[]; total: number };
type Publication = { id: string; title: string; status: string; published_at: string | null };
type PublicationPage = { items: Publication[] };
type Report = {
  experiment: Detail;
  window_key: string;
  comparison_type: "observational";
  variants: Array<{
    variant_id: string;
    label: string;
    sample_count: number;
    measured_count: number;
    average_views: number | null;
    average_interaction_rate: number | null;
    average_completion_rate: number | null;
    source_kinds: string[];
  }>;
  caveats: string[];
};

const DIMENSIONS: Array<{ value: Dimension; label: string }> = [
  { value: "title", label: "标题" },
  { value: "hook", label: "Hook" },
  { value: "story_order", label: "叙事顺序" },
  { value: "thumbnail", label: "缩略图" },
];
const STATUSES: Array<{ value: Status; label: string }> = [
  { value: "draft", label: "草稿" },
  { value: "running", label: "观察中" },
  { value: "completed", label: "已完成" },
  { value: "archived", label: "已归档" },
];

export function ExperimentsClient() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  const [dimension, setDimension] = useState<Dimension>("title");
  const [variantLabel, setVariantLabel] = useState("");
  const [publicationId, setPublicationId] = useState("");
  const [status, setStatus] = useState<Status>("draft");
  const [pending, setPending] = useState(false);
  const canEdit = ["owner", "admin", "editor", "analyst"].includes(role ?? "");
  const canManage = ["owner", "admin", "editor"].includes(role ?? "");

  const experiments = useQuery({
    queryKey: ["content-experiments", workspaceId],
    queryFn: () => apiRequest<ExperimentPage>("/content-experiments?page=1&page_size=100", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId),
  });
  const detail = useQuery({
    queryKey: ["content-experiment", workspaceId, selectedId],
    queryFn: () => apiRequest<Detail>(`/content-experiments/${selectedId}`, { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId && selectedId),
  });
  const publications = useQuery({
    queryKey: ["experiment-publications", workspaceId],
    queryFn: () => apiRequest<PublicationPage>("/publications?page=1&page_size=100&status=published", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId && selectedId),
  });
  const report = useQuery({
    queryKey: ["content-experiment-report", workspaceId, selectedId],
    queryFn: () => apiRequest<Report>(`/content-experiments/${selectedId}/report?window_key=24h`, { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId && selectedId),
  });

  async function createExperiment() {
    if (!workspaceId || !name.trim()) return;
    setPending(true);
    try {
      const created = await apiRequest<Detail>("/content-experiments", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ name: name.trim(), hypothesis: hypothesis.trim() || null, dimension }),
      });
      setSelectedId(created.id);
      setName("");
      setHypothesis("");
      notify("观察性实验已创建");
      await queryClient.invalidateQueries({ queryKey: ["content-experiments"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "实验创建失败", "error");
    } finally {
      setPending(false);
    }
  }

  async function addVariant() {
    if (!workspaceId || !selectedId || !variantLabel.trim() || !publicationId) return;
    setPending(true);
    try {
      await apiRequest(`/content-experiments/${selectedId}/variants`, {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ label: variantLabel.trim(), publication_id: publicationId }),
      });
      setVariantLabel("");
      setPublicationId("");
      notify("变体已关联发布证据");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["content-experiment", workspaceId, selectedId] }),
        queryClient.invalidateQueries({ queryKey: ["content-experiment-report", workspaceId, selectedId] }),
        queryClient.invalidateQueries({ queryKey: ["content-experiments"] }),
      ]);
    } catch (error) {
      notify(error instanceof Error ? error.message : "变体关联失败", "error");
    } finally {
      setPending(false);
    }
  }

  async function updateStatus(nextStatus: Status) {
    if (!workspaceId || !selectedId) return;
    setPending(true);
    try {
      await apiRequest(`/content-experiments/${selectedId}`, {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ status: nextStatus }),
      });
      setStatus(nextStatus);
      notify("实验状态已更新");
      await queryClient.invalidateQueries({ queryKey: ["content-experiment", workspaceId, selectedId] });
      await queryClient.invalidateQueries({ queryKey: ["content-experiments"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "实验状态更新失败", "error");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="OBSERVATIONAL EXPERIMENTS"
        title="内容观察性实验"
        description="比较标题、Hook、叙事顺序或缩略图的真实发布表现；结果只描述关联，不自动宣称 A/B 因果。"
        actions={<Badge tone="warning">非因果比较</Badge>}
      />
      <Panel className="border-amber-900/40 bg-amber-950/10 p-4 text-sm text-amber-100">
        只有关联了真实发布记录且存在固定窗口归因的变体才会进入报告。不同平台、发布时间、受众和分发条件不会被系统自动校正。
      </Panel>
      {canEdit && (
        <Panel className="space-y-4 p-5">
          <div className="flex items-center gap-2"><FlaskConical size={17} className="text-cyan-300" /><h2 className="font-medium text-white">新建观察计划</h2></div>
          <div className="grid gap-3 md:grid-cols-3">
            <input className={inputClass} placeholder="实验名称" value={name} onChange={(event) => setName(event.target.value)} />
            <select className={inputClass} value={dimension} onChange={(event) => setDimension(event.target.value as Dimension)}>{DIMENSIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
            <input className={inputClass} placeholder="假设（可选）" value={hypothesis} onChange={(event) => setHypothesis(event.target.value)} />
          </div>
          <button className={buttonClass} type="button" onClick={() => void createExperiment()} disabled={pending || !name.trim()}><Plus size={15} />创建实验</button>
        </Panel>
      )}
      {experiments.isLoading ? <Panel className="p-5">加载中…</Panel> : experiments.error ? <StatePanel type="error" title="实验加载失败" detail={experiments.error.message} /> : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <Panel className="overflow-hidden">
            <div className="border-b border-slate-800 px-5 py-4 text-sm text-slate-400">{experiments.data?.total ?? 0} 个观察计划</div>
            <div className="divide-y divide-slate-800">
              {(experiments.data?.items ?? []).map((item) => <button key={item.id} type="button" onClick={() => { setSelectedId(item.id); setStatus(item.status); }} className={`w-full px-5 py-4 text-left hover:bg-slate-900/70 ${selectedId === item.id ? "bg-cyan-950/20" : ""}`}><div className="flex items-center justify-between gap-3"><span className="truncate font-medium text-white">{item.name}</span><Badge tone={item.status === "running" ? "success" : "neutral"}>{STATUSES.find((statusItem) => statusItem.value === item.status)?.label ?? item.status}</Badge></div><p className="mt-1 text-xs text-slate-500">{DIMENSIONS.find((dimensionItem) => dimensionItem.value === item.dimension)?.label} · {item.variant_count} 个变体 · 更新 {formatDate(item.updated_at)}</p></button>)}
              {!experiments.data?.items.length && <p className="px-5 py-10 text-sm text-slate-500">暂无观察计划。</p>}
            </div>
          </Panel>
          <Panel className="p-5">
            {!selectedId || !detail.data ? <p className="text-sm text-slate-500">选择一个实验查看变体和固定窗口归因。</p> : (
              <div className="space-y-5">
                <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold text-white">{detail.data.name}</h2><p className="mt-1 text-sm text-slate-400">{detail.data.hypothesis || "未填写假设"}</p></div><div className="flex items-center gap-2"><select className={inputClass} value={status} onChange={(event) => void updateStatus(event.target.value as Status)} disabled={!canManage || pending}>{STATUSES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select><button type="button" className={secondaryButtonClass} onClick={() => void report.refetch()} title="刷新真实归因"><RefreshCw size={15} /></button></div></div>
                {canEdit && <div className="grid gap-2 md:grid-cols-[1fr_1.5fr_auto]"><input className={inputClass} placeholder="变体名称，例如 A" value={variantLabel} onChange={(event) => setVariantLabel(event.target.value)} /><select className={inputClass} value={publicationId} onChange={(event) => setPublicationId(event.target.value)}><option value="">选择已发布记录</option>{(publications.data?.items ?? []).map((publication) => <option key={publication.id} value={publication.id}>{publication.title}</option>)}</select><button type="button" className={buttonClass} onClick={() => void addVariant()} disabled={pending || !variantLabel.trim() || !publicationId}><Plus size={15} />关联</button></div>}
                <div className="space-y-2">{detail.data.variants.map((variant) => <div key={variant.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 p-3"><span className="font-medium text-slate-200">{variant.label}</span><span className="text-xs text-slate-500">发布证据 {variant.publication_id ? "已关联" : "未关联"} · {formatDate(variant.created_at)}</span></div>)}</div>
                {report.data && <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-sm"><caption className="mb-2 text-left text-xs text-slate-500">24 小时固定窗口 · 描述性观察</caption><thead className="border-b border-slate-800 text-xs text-slate-500"><tr><th className="px-2 py-2">变体</th><th className="px-2 py-2">样本/已测</th><th className="px-2 py-2">平均播放</th><th className="px-2 py-2">互动率</th><th className="px-2 py-2">完播率</th></tr></thead><tbody className="divide-y divide-slate-800">{report.data.variants.map((variant) => <tr key={variant.variant_id}><td className="px-2 py-3 text-slate-200">{variant.label}</td><td className="px-2 py-3 text-slate-400">{variant.sample_count} / {variant.measured_count}</td><td className="px-2 py-3 text-slate-300">{formatNumber(variant.average_views)}</td><td className="px-2 py-3 text-slate-300">{formatPercent(variant.average_interaction_rate)}</td><td className="px-2 py-3 text-slate-300">{formatPercent(variant.average_completion_rate)}</td></tr>)}</tbody></table><ul className="mt-3 space-y-1 text-xs text-amber-200">{report.data.caveats.map((caveat) => <li key={caveat}>· {caveat}</li>)}</ul></div>}
              </div>
            )}
          </Panel>
        </div>
      )}
    </main>
  );
}
