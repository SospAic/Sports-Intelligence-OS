"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { GitBranch, History, Languages, ListChecks, Search } from "lucide-react";
import { apiRequest } from "@/lib/browser-api";
import { useToast } from "@/components/toast";

type Topic = { id: string; title: string; platform: string; heat_score: number };
type ProcessStep = {
  stage: string;
  status: string;
  message: string;
  result_count?: number;
};
type SearchResult = {
  title?: string | null;
  title_en?: string | null;
  url?: string | null;
  author?: string | null;
  author_en?: string | null;
  view_count?: number | null;
  like_count?: number | null;
  comment_count?: number | null;
  heat_score?: number | null;
  platform?: string | null;
  metric_source?: string;
};
type Derivative = {
  id: string;
  kind: string;
  angle: string | null;
  angle_en: string | null;
  title: string;
  title_en: string | null;
  description: string | null;
  description_en: string | null;
  predicted_heat_score: number | null;
  evidence: { sample_count?: number; median_views?: number; sample_results?: SearchResult[] };
  ai_rationale: string | null;
  ai_rationale_en: string | null;
  status: string;
  confidence: number;
};
type Run = {
  id: string;
  source_topic_id: string;
  source_query: string;
  source_query_en: string | null;
  platform: string;
  status: string;
  process_log: ProcessStep[];
  result_count: number;
  notice: string | null;
  created_at: string;
};
type RunDetail = Run & {
  items: Derivative[];
  source_results: SearchResult[];
  language: string;
};

type GenerateResponse = {
  status: string;
  notice: string | null;
  items: Derivative[];
  run_id: string | null;
  process_log: ProcessStep[];
  source_results: SearchResult[];
};

const LANGUAGES = [
  ["en", "English"],
  ["zh", "简体中文"],
  ["ja", "日本語"],
  ["ko", "한국어"],
  ["es", "Español"],
  ["fr", "Français"],
  ["de", "Deutsch"],
  ["pt", "Português"],
] as const;

function number(value: number | null | undefined): string {
  return value == null ? "—" : new Intl.NumberFormat("en-US", { notation: "compact" }).format(value);
}

function heat(value: number | null | undefined): string {
  return value == null ? "—" : value.toFixed(1);
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    completed: "已完成",
    degraded: "部分完成",
    failed: "失败",
    running: "执行中",
    pending: "排队中",
  };
  return labels[status] ?? status;
}

function ResultMetrics({ result }: { result: SearchResult }) {
  return (
    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
      <span>浏览量 {number(result.view_count)}</span>
      <span>点赞 {number(result.like_count)}</span>
      <span>评论 {number(result.comment_count)}</span>
      <span className="text-amber-300">派生热度 {heat(result.heat_score)}*</span>
    </div>
  );
}

export function DerivativesPanel({ workspaceId }: { workspaceId: string }) {
  const { notify } = useToast();
  const [topicId, setTopicId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [generating, setGenerating] = useState(false);
  const [language, setLanguage] = useState("en");
  const [translated, setTranslated] = useState<RunDetail | null>(null);
  const [generatedDetail, setGeneratedDetail] = useState<RunDetail | null>(null);

  const topics = useQuery({
    queryKey: ["derivatives-topics", workspaceId],
    queryFn: () => apiRequest<{ items: Topic[] }>("/trends/topics?page=1&page_size=50", { workspaceId }),
  });
  const effectiveTopicId = topicId || topics.data?.items?.[0]?.id || "";
  const runs = useQuery({
    queryKey: ["derivative-runs", workspaceId],
    queryFn: () => apiRequest<{ items: Run[] }>("/trends/derivatives/runs?page=1&page_size=30", { workspaceId }),
  });
  const activeRunId = selectedRunId || runs.data?.items?.[0]?.id || "";
  const detail = useQuery({
    queryKey: ["derivative-run", workspaceId, activeRunId],
    queryFn: () => apiRequest<RunDetail>(`/trends/derivatives/runs/${activeRunId}`, { workspaceId }),
    enabled: Boolean(activeRunId),
  });
  // Render the POST response immediately.  The detail query is still used to
  // hydrate the complete persisted run, but a transient detail request error
  // must not make a successful generation appear empty.
  const persistedDetail = detail.data?.id === activeRunId ? detail.data : undefined;
  const active = translated?.id === activeRunId
    ? translated
    : persistedDetail ?? (generatedDetail?.id === activeRunId ? generatedDetail : undefined);

  const generate = async () => {
    if (!effectiveTopicId) return;
    setGenerating(true);
    try {
      const result = await apiRequest<GenerateResponse>("/trends/derivatives/generate", {
        method: "POST",
        csrf: true,
        workspaceId,
        body: JSON.stringify({ topic_id: effectiveTopicId }),
      });
      setTranslated(null);
      if (result.run_id) {
        const selectedTopic = topics.data?.items?.find((topic) => topic.id === effectiveTopicId);
        setGeneratedDetail({
          id: result.run_id,
          source_topic_id: effectiveTopicId,
          source_query: selectedTopic?.title ?? "",
          source_query_en: null,
          platform: selectedTopic?.platform ?? "",
          status: result.notice ? "degraded" : "completed",
          process_log: result.process_log ?? [],
          result_count: result.items?.length ?? 0,
          notice: result.notice ?? null,
          created_at: new Date().toISOString(),
          items: result.items ?? [],
          source_results: result.source_results ?? [],
          language: "en",
        });
        setSelectedRunId(result.run_id);
      }
      await runs.refetch();
      notify("衍生角度生成完成，已保存到执行历史", "success");
    } catch (error) {
      notify(`生成失败：${(error as Error).message}`, "error");
    } finally {
      setGenerating(false);
    }
  };

  const translate = async (target: string) => {
    setLanguage(target);
    if (target === "en" || !activeRunId) {
      setTranslated(null);
      return;
    }
    try {
      const value = await apiRequest<RunDetail>(`/trends/derivatives/runs/${activeRunId}/translate`, {
        method: "POST",
        csrf: true,
        workspaceId,
        body: JSON.stringify({ target_language: target }),
      });
      setTranslated(value);
    } catch (error) {
      notify(`翻译失败：${(error as Error).message}`, "error");
      setLanguage("en");
    }
  };

  const adopt = async (id: string) => {
    try {
      await apiRequest(`/trends/derivatives/${id}/adopt`, { method: "POST", csrf: true, workspaceId });
      await detail.refetch();
      notify("已采用该衍生角度", "success");
    } catch (error) {
      notify(`采用失败：${(error as Error).message}`, "error");
    }
  };

  const selectRun = (runId: string) => {
    setSelectedRunId(runId);
    setGeneratedDetail(null);
    setTranslated(null);
    setLanguage("en");
  };

  const items = active?.items ?? [];
  const predicted = items.filter((item) => item.kind === "ai_predicted");
  const existing = items.filter((item) => item.kind === "existing_on_platform");

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <GitBranch size={18} className="text-cyan-400" />
        <h2 className="font-semibold text-white">衍生角度</h2>
        <span className="text-xs text-slate-500">后台过程与结果默认英文</span>
      </div>
      <p className="text-sm text-slate-500">
        每次生成都会保存为一条执行记录，可查看英文检索过程、来源指标、角度聚类及多语言翻译结果。
      </p>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="space-y-4 rounded-xl border border-slate-800 bg-slate-950/50 p-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[240px] flex-1">
              <label className="mb-1 block text-xs font-medium text-slate-400">热点话题</label>
              <select value={effectiveTopicId} onChange={(event) => setTopicId(event.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100">
                {!topics.data?.items?.length && <option value="">暂无热点话题</option>}
                {(topics.data?.items ?? []).map((topic) => <option key={topic.id} value={topic.id}>[{topic.platform}] {topic.title} · 热度 {Math.round(topic.heat_score)}</option>)}
              </select>
            </div>
            <button type="button" onClick={() => void generate()} disabled={generating || !effectiveTopicId} className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50">
              {generating ? "生成中…" : "生成衍生角度"}
            </button>
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <Languages size={15} />
              <span>结果语言</span>
              <select value={language} onChange={(event) => void translate(event.target.value)} className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-slate-100">
                {LANGUAGES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
          </div>

          {active && (
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-slate-800 p-3"><p className="text-xs text-slate-500">搜索关键词</p><p className="mt-1 text-sm text-slate-200">{active.source_query_en || active.source_query}</p></div>
              <div className="rounded-lg border border-slate-800 p-3"><p className="text-xs text-slate-500">来源结果</p><p className="mt-1 text-lg font-semibold text-slate-100">{active.source_results.length}</p></div>
              <div className="rounded-lg border border-slate-800 p-3"><p className="text-xs text-slate-500">任务状态</p><p className="mt-1 text-sm font-semibold text-emerald-300">{statusLabel(active.status)}</p></div>
            </div>
          )}

          {active && (
            <>
              <section className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <div className="mb-3 flex items-center gap-2"><ListChecks size={16} className="text-cyan-400" /><h3 className="font-semibold text-slate-100">执行过程</h3><span className="text-xs text-slate-500">英文日志</span></div>
                <ol className="space-y-2">
                  {active.process_log.map((step, index) => <li key={`${step.stage}-${index}`} className="flex gap-3 text-sm"><span className="grid size-5 shrink-0 place-items-center rounded-full bg-slate-800 text-[10px] text-slate-300">{index + 1}</span><div><p className="text-slate-200">{step.message}</p><p className="text-[11px] uppercase tracking-wide text-slate-600">{step.stage} · {statusLabel(step.status)}</p></div></li>)}
                </ol>
              </section>
              <section className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <div className="mb-3 flex items-center gap-2"><Search size={16} className="text-cyan-400" /><h3 className="font-semibold text-slate-100">来源搜索结果</h3><span className="text-xs text-slate-500">{active.source_results.length} 条</span></div>
                <div className="space-y-2">{active.source_results.map((result, index) => <div key={`${result.url ?? result.title}-${index}`} className="rounded-lg border border-slate-800 p-3"><div className="flex items-start justify-between gap-3"><p className="text-sm text-slate-200">{result.title_en || result.title || "未命名结果"}</p>{result.url && <a className="shrink-0 text-xs text-cyan-300 hover:underline" href={result.url} target="_blank" rel="noreferrer">查看来源</a>}</div><p className="mt-1 text-xs text-slate-500">{result.platform} · {result.author_en || result.author || "未知作者"}</p><ResultMetrics result={result} /></div>)}</div>
                <p className="mt-3 text-[11px] text-slate-600">* 派生热度根据返回的平台指标计算，不代表平台原生热度分数。</p>
              </section>
              <AngleSection title="预测衍生角度" items={predicted} onAdopt={adopt} />
              <AngleSection title="平台已有角度" items={existing} onAdopt={adopt} />
            </>
          )}
          {!active && <p className="py-10 text-center text-sm text-slate-500">生成一次任务或选择历史记录，查看英文执行过程和结果。</p>}
          {!active && detail.isLoading && <p className="py-4 text-center text-sm text-slate-500">正在加载执行结果…</p>}
          {!active && detail.isError && <div className="rounded-lg border border-rose-500/30 bg-rose-950/20 p-4 text-sm text-rose-200"><p>执行记录加载失败，结果暂时无法展示。</p><button type="button" onClick={() => void detail.refetch()} className="mt-2 rounded-md border border-rose-400/50 px-3 py-1 text-xs">重新加载</button></div>}
        </div>

        <aside className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
          <div className="mb-3 flex items-center gap-2"><History size={16} className="text-cyan-400" /><h3 className="font-semibold text-slate-100">执行历史</h3></div>
          <div className="space-y-2">
            {(runs.data?.items ?? []).map((run) => <button type="button" key={run.id} onClick={() => selectRun(run.id)} className={`w-full rounded-lg border p-3 text-left transition ${run.id === activeRunId ? "border-cyan-500/60 bg-cyan-950/20" : "border-slate-800 hover:border-slate-600"}`}><p className="line-clamp-2 text-xs text-slate-200">{run.source_query_en || run.source_query}</p><p className="mt-2 text-[11px] text-slate-500">{new Date(run.created_at).toLocaleString("zh-CN")} · {run.result_count} 条角度 · {statusLabel(run.status)}</p></button>)}
            {!runs.data?.items?.length && <p className="text-sm text-slate-500">暂无执行记录。</p>}
          </div>
        </aside>
      </div>
    </div>
  );
}

function AngleSection({ title, items, onAdopt }: { title: string; items: Derivative[]; onAdopt: (id: string) => void }) {
  return <section><h3 className="mb-3 text-base font-semibold text-white">{title}<span className="ml-2 text-xs font-normal text-slate-500">{items.length} 条</span></h3><div className="grid gap-3 md:grid-cols-2">{items.map((item) => <div key={item.id} className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"><div className="flex items-start justify-between gap-2"><div><span className="text-xs text-cyan-300">{item.angle_en || item.angle || "未命名角度"}</span><p className="font-medium text-slate-100">{item.title_en || item.title}</p></div><span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-xs text-amber-300">预测热度 {heat(item.predicted_heat_score)}</span></div>{(item.description_en || item.description) && <p className="mt-2 text-sm text-slate-400">{item.description_en || item.description}</p>}{(item.ai_rationale_en || item.ai_rationale) && <p className="mt-2 rounded-lg bg-slate-900/60 p-2 text-xs text-slate-400">生成依据：{item.ai_rationale_en || item.ai_rationale}</p>}<div className="mt-3 flex items-center justify-between"><span className="text-xs text-slate-500">置信度 {Math.round(item.confidence * 100)}%</span>{item.status === "adopted" ? <span className="text-xs text-emerald-300">已采用</span> : <button type="button" onClick={() => onAdopt(item.id)} className="rounded-md border border-cyan-500/40 px-3 py-1 text-xs text-cyan-200">采用并创建 →</button>}</div></div>)}{!items.length && <p className="text-sm text-slate-500">该分类暂无结果。</p>}</div></section>;
}
