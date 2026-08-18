"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { History, Languages, ListChecks, Search } from "lucide-react";
import { apiRequest } from "@/lib/browser-api";
import { useToast } from "@/components/toast";

type ProcessStep = { stage: string; status: string; message: string };
type Result = {
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
type SearchAnalysis = {
  related_hotness: number | null;
  volume_estimate: { total_hits?: number; total_views?: number; total_likes?: number; total_comments?: number; average_views?: number; top_view_count?: number; metric_note?: string } | null;
  sentiment: string | null;
  timeline_phases: { phase?: string; note?: string; month?: string; count?: number }[] | null;
  platform_distribution: Record<string, number> | null;
  related_derivative_topics: { title: string; angle: string; predicted_heat_score: number }[] | null;
  summary: string | null;
  process_log: ProcessStep[];
};
type QueryRecord = { id: string; query_text: string; query_text_en: string | null; platform_scope: string; is_saved: boolean; saved_name: string | null; result_count: number; created_at: string };
type Response = { query: QueryRecord; analysis: SearchAnalysis; results: Result[]; language: string; notice: string | null };

const LANGUAGES = [["en", "English"], ["zh", "简体中文"], ["ja", "日本語"], ["ko", "한국어"], ["es", "Español"], ["fr", "Français"], ["de", "Deutsch"], ["pt", "Português"]] as const;
const PLATFORMS = [["all", "All platforms"], ["youtube", "YouTube"], ["bilibili", "Bilibili"], ["tiktok", "TikTok"], ["douyin", "Douyin"]] as const;

function compact(value: number | null | undefined): string {
  return value == null ? "—" : new Intl.NumberFormat("en-US", { notation: "compact" }).format(value);
}

function StatCard({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-lg font-semibold text-slate-100">{value}</p></div>;
}

export function SearchPanel({ workspaceId }: { workspaceId: string }) {
  const { notify } = useToast();
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState("all");
  const [limit, setLimit] = useState(10);
  const [running, setRunning] = useState(false);
  const [language, setLanguage] = useState("en");
  const [data, setData] = useState<Response | null>(null);
  const [savedName, setSavedName] = useState("");
  const [saving, setSaving] = useState(false);

  const history = useQuery({
    queryKey: ["trend-search-history", workspaceId],
    queryFn: () => apiRequest<{ items: QueryRecord[] }>("/trends/search?page=1&page_size=30", { workspaceId }),
  });

  const load = async (id: string) => {
    try {
      const result = await apiRequest<Response>(`/trends/search/${id}`, { workspaceId });
      setData(result);
      setQuery(result.query.query_text);
      setSavedName(result.query.saved_name ?? "");
      setLanguage("en");
    } catch (error) {
      notify(`History load failed: ${(error as Error).message}`, "error");
    }
  };

  const run = async () => {
    if (!query.trim()) {
      notify("Enter a search description", "error");
      return;
    }
    setRunning(true);
    try {
      const result = await apiRequest<Response>("/trends/search", { method: "POST", csrf: true, workspaceId, body: JSON.stringify({ query_text: query, platform, limit }) });
      setData(result);
      setSavedName(result.query.saved_name ?? "");
      setLanguage("en");
      await history.refetch();
      notify("Search completed and saved to history", "success");
    } catch (error) {
      notify(`Search failed: ${(error as Error).message}`, "error");
    } finally {
      setRunning(false);
    }
  };

  const translate = async (target: string) => {
    setLanguage(target);
    if (target === "en" || !data) {
      if (target === "en" && data) await load(data.query.id);
      return;
    }
    try {
      const result = await apiRequest<Response>(`/trends/search/${data.query.id}/translate`, { method: "POST", csrf: true, workspaceId, body: JSON.stringify({ target_language: target }) });
      setData(result);
    } catch (error) {
      notify(`Translation failed: ${(error as Error).message}`, "error");
      setLanguage("en");
    }
  };

  const save = async (isSaved: boolean) => {
    if (!data) return;
    setSaving(true);
    try {
      const queryRecord = await apiRequest<QueryRecord>(`/trends/search/${data.query.id}/saved`, { method: "PATCH", csrf: true, workspaceId, body: JSON.stringify({ is_saved: isSaved, saved_name: savedName.trim() || null }) });
      setData({ ...data, query: queryRecord });
      await history.refetch();
      notify(isSaved ? "Search saved" : "Search unsaved", "success");
    } catch (error) {
      notify(`Save failed: ${(error as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const analysis = data?.analysis;
  const volume = analysis?.volume_estimate;
  return <div className="space-y-6">
    <div className="flex items-center gap-2"><Search size={18} className="text-cyan-400" /><h2 className="font-semibold text-white">Search this track</h2><span className="text-xs text-slate-500">English search process and result metrics</span></div>
    <p className="text-sm text-slate-500">Search real platform results, persist every run, inspect the measured metrics, and translate the complete record into another language.</p>
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="space-y-5">
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
          <label className="mb-1 block text-xs font-medium text-slate-400">Search description</label>
          <textarea value={query} onChange={(event) => setQuery(event.target.value)} rows={3} placeholder="Example: controversy and best short-video angles around the latest Champions League match" className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600" />
          <div className="mt-3 flex flex-wrap items-end gap-3"><label className="text-xs text-slate-400">Scope<select value={platform} onChange={(event) => setPlatform(event.target.value)} className="mt-1 block rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100">{PLATFORMS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label className="text-xs text-slate-400">Results per platform<input type="number" min={5} max={30} value={limit} onChange={(event) => setLimit(Number(event.target.value))} className="mt-1 block w-28 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100" /></label><button type="button" onClick={() => void run()} disabled={running} className="rounded-lg bg-cyan-500 px-5 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50">{running ? "Searching…" : "Search and analyze"}</button><label className="ml-auto flex items-center gap-2 text-xs text-slate-400"><Languages size={15} /><select value={language} onChange={(event) => void translate(event.target.value)} className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-slate-100">{LANGUAGES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
          <p className="mt-3 text-xs text-slate-600">Views, likes, and comments are shown only when returned by the platform. Heat is a derived proxy and is labelled separately.</p>
        </div>
        {data && <>
          {data.notice && <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-200">{data.notice}</div>}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5"><StatCard label="Related heat" value={analysis?.related_hotness == null ? "—" : analysis.related_hotness.toFixed(1)} /><StatCard label="Results" value={compact(volume?.total_hits)} /><StatCard label="Total views" value={compact(volume?.total_views)} /><StatCard label="Likes" value={compact(volume?.total_likes)} /><StatCard label="Comments" value={compact(volume?.total_comments)} /></div>
          <div className="rounded-xl border border-cyan-900/40 bg-cyan-950/10 p-3"><div className="flex flex-wrap items-center gap-2"><span className="text-xs text-slate-400">Workspace history</span><input aria-label="Save search name" value={savedName} onChange={(event) => setSavedName(event.target.value)} placeholder="Optional saved name" className="min-w-48 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-100" /><button type="button" onClick={() => void save(true)} disabled={saving} className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-semibold text-slate-950">{data.query.is_saved ? "Update saved" : "Save search"}</button>{data.query.is_saved && <button type="button" onClick={() => void save(false)} disabled={saving} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300">Unsave</button>}</div></div>
          <section className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"><div className="mb-3 flex items-center gap-2"><ListChecks size={16} className="text-cyan-400" /><h3 className="font-semibold text-slate-100">Search process</h3></div><ol className="space-y-2">{(analysis?.process_log ?? []).map((step, index) => <li key={`${step.stage}-${index}`} className="flex gap-3 text-sm"><span className="grid size-5 shrink-0 place-items-center rounded-full bg-slate-800 text-[10px] text-slate-300">{index + 1}</span><div><p className="text-slate-200">{step.message}</p><p className="text-[11px] uppercase tracking-wide text-slate-600">{step.stage} · {step.status}</p></div></li>)}</ol></section>
          {analysis?.summary && <section className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"><h3 className="mb-2 font-semibold text-slate-100">English analysis summary</h3><p className="text-sm leading-6 text-slate-300">{analysis.summary}</p></section>}
          <section className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"><div className="mb-3 flex items-center gap-2"><Search size={16} className="text-cyan-400" /><h3 className="font-semibold text-slate-100">Search results</h3><span className="text-xs text-slate-500">{data.results.length} records</span></div><div className="space-y-2">{data.results.map((result, index) => <div key={`${result.url ?? result.title}-${index}`} className="rounded-lg border border-slate-800 p-3"><div className="flex items-start justify-between gap-3"><p className="text-sm text-slate-200">{result.title_en || result.title || "Untitled result"}</p>{result.url && <a href={result.url} target="_blank" rel="noreferrer" className="shrink-0 text-xs text-cyan-300 hover:underline">Open</a>}</div><p className="mt-1 text-xs text-slate-500">{result.platform} · {result.author_en || result.author || "Unknown author"}</p><div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500"><span>Views {compact(result.view_count)}</span><span>Likes {compact(result.like_count)}</span><span>Comments {compact(result.comment_count)}</span><span className="text-amber-300">Heat {result.heat_score == null ? "—" : result.heat_score.toFixed(1)}*</span></div></div>)}</div><p className="mt-3 text-[11px] text-slate-600">* Heat is derived from returned views, likes, and comments; it is not a platform-native metric.</p></section>
        </>}
      </div>
      <aside className="rounded-xl border border-slate-800 bg-slate-950/50 p-4"><div className="mb-3 flex items-center gap-2"><History size={16} className="text-cyan-400" /><h3 className="font-semibold text-slate-100">Search history</h3></div><div className="space-y-2">{(history.data?.items ?? []).map((record) => <button type="button" key={record.id} onClick={() => void load(record.id)} className={`w-full rounded-lg border p-3 text-left transition ${record.id === data?.query.id ? "border-cyan-500/60 bg-cyan-950/20" : "border-slate-800 hover:border-slate-600"}`}><p className="line-clamp-2 text-xs text-slate-200">{record.query_text_en || record.query_text}</p><p className="mt-2 text-[11px] text-slate-500">{new Date(record.created_at).toLocaleString("en-US")} · {record.result_count} results {record.is_saved ? "· Saved" : ""}</p></button>)}{!history.data?.items?.length && <p className="text-sm text-slate-500">No search history yet.</p>}</div></aside>
    </div>
  </div>;
}
