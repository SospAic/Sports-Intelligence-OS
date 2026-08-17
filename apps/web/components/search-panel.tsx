"use client";

import { useState } from "react";
import { apiRequest } from "@/lib/browser-api";
import { useToast } from "@/components/toast";
import { Search } from "lucide-react";

interface SearchResult {
  title: string | null;
  url: string | null;
  author: string | null;
  view_count: number | null;
  platform: string | null;
}

interface SearchAnalysis {
  related_hotness: number | null;
  volume_estimate: { total_hits?: number; total_views?: number } | null;
  sentiment: string | null;
  timeline_phases: { phase: string; note: string }[] | null;
  platform_distribution: Record<string, number> | null;
  related_derivative_topics: {
    title: string;
    angle: string;
    predicted_heat_score: number;
  }[] | null;
  summary: string | null;
  sources: SearchResult[] | null;
}

interface SearchResponse {
  query: {
    id: string;
    query_text: string;
    platform_scope: string;
    is_saved: boolean;
    saved_name: string | null;
  };
  analysis: SearchAnalysis;
  results: SearchResult[];
  notice: string | null;
}

const PLATFORMS = [
  { key: "all", label: "全网" },
  { key: "youtube", label: "YouTube" },
  { key: "bilibili", label: "Bilibili" },
  { key: "tiktok", label: "TikTok" },
  { key: "douyin", label: "抖音" },
];

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-100">{value}</p>
    </div>
  );
}

export function SearchPanel({ workspaceId }: { workspaceId: string }) {
  const { notify } = useToast();
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState("all");
  const [limit, setLimit] = useState(10);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [savedName, setSavedName] = useState("");
  const [saving, setSaving] = useState(false);

  const run = async () => {
    if (!query.trim()) {
      notify("请输入检索描述", "error");
      return;
    }
    setRunning(true);
    setError(null);
    setNotice(null);
    try {
      const res = await apiRequest<SearchResponse>("/trends/search", {
        method: "POST",
        csrf: true,
        workspaceId,
        body: JSON.stringify({ query_text: query, platform, limit }),
      });
      setData(res);
      setNotice(res.notice ?? null);
      setSavedName(res.query.saved_name ?? "");
    } catch (e) {
      setError((e as Error).message);
      notify(`搜索失败：${(e as Error).message}`, "error");
    } finally {
      setRunning(false);
    }
  };

  const saveCurrentQuery = async (isSaved: boolean) => {
    if (!data) return;
    setSaving(true);
    try {
      const saved = await apiRequest<SearchResponse["query"]>(
        `/trends/search/${data.query.id}/saved`,
        {
          method: "PATCH",
          csrf: true,
          workspaceId,
          body: JSON.stringify({
            is_saved: isSaved,
            saved_name: savedName.trim() || null,
          }),
        },
      );
      setData({ ...data, query: saved });
      setSavedName(saved.saved_name ?? "");
      notify(isSaved ? "检索已保存到工作区" : "已取消保存检索", "success");
    } catch (e) {
      notify(`保存检索失败：${(e as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const a = data?.analysis;

  return (
    <div className="space-y-6">
      {/* 智能搜索 标题与副标题（与情报分析区块风格一致） */}
      <div className="mb-1 flex items-center gap-2">
        <Search size={18} className="text-cyan-400" />
        <h2 className="font-semibold text-white">智能搜索</h2>
      </div>
      <p className="mb-4 text-sm text-slate-500">
        用自然语言描述需求，跨平台检索相关视频并分析热度、情绪、时间线与衍生话题，辅助选题与舆情研判。
      </p>

      <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
        <label className="mb-1 block text-xs font-medium text-slate-400">
          用一段描述来检索（自然语言）
        </label>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          rows={3}
          placeholder="例如：巴黎奥运会乒乓球女单决赛 相关争议与精彩混剪"
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600"
        />
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-slate-400">平台范围</label>
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            >
              {PLATFORMS.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-400">每条结果数</label>
            <input
              type="number"
              min={5}
              max={30}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="w-24 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            />
          </div>
          <button
            onClick={run}
            disabled={running}
            className="rounded-lg bg-cyan-500 px-5 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-50"
          >
            {running ? "检索分析中…" : "搜索并分析"}
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-600">
          提示：TikTok / 抖音 暂未接入搜索（受反爬限制），选择「全网」将检索 YouTube 与 Bilibili。
        </p>
      </div>

      {notice && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-200">
          {notice}
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-200">
          {error}
        </div>
      )}

      {a && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard
              label="检索条件相关热度"
              value={a.related_hotness != null ? `${Math.round(a.related_hotness)}` : "—"}
            />
            <StatCard
              label="命中内容"
              value={`${a.volume_estimate?.total_hits ?? 0} 条`}
            />
            <StatCard
              label="合计播放"
              value={`${((a.volume_estimate?.total_views ?? 0) / 10000).toFixed(1)} 万`}
            />
            <StatCard label="整体情绪" value={a.sentiment ?? "—"} />
          </div>

          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-cyan-900/40 bg-cyan-950/10 p-3">
            <span className="text-xs text-slate-400">工作区检索</span>
            <input
              aria-label="保存检索名称"
              value={savedName}
              onChange={(event) => setSavedName(event.target.value)}
              placeholder="保存名称（可选）"
              className="min-w-48 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-100 placeholder:text-slate-600"
              disabled={saving}
            />
            <button
              type="button"
              onClick={() => void saveCurrentQuery(true)}
              disabled={saving}
              className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-semibold text-slate-950 disabled:opacity-50"
            >
              {saving ? "保存中…" : data.query.is_saved ? "更新保存" : "保存检索"}
            </button>
            {data.query.is_saved && (
              <button
                type="button"
                onClick={() => void saveCurrentQuery(false)}
                disabled={saving}
                className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 disabled:opacity-50"
              >
                取消保存
              </button>
            )}
          </div>

          {a.summary && (
            <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
              <h3 className="mb-2 text-sm font-semibold text-slate-200">分析摘要</h3>
              <p className="text-sm leading-6 text-slate-300">{a.summary}</p>
            </div>
          )}

          <div className="grid gap-4 md:grid-cols-2">
            {a.platform_distribution && (
              <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <h3 className="mb-2 text-sm font-semibold text-slate-200">平台分布</h3>
                <ul className="space-y-1 text-sm text-slate-300">
                  {Object.entries(a.platform_distribution).map(([k, v]) => (
                    <li key={k} className="flex justify-between">
                      <span>{k}</span>
                      <span className="text-slate-500">{v} 条</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {a.timeline_phases && a.timeline_phases.length > 0 && (
              <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                <h3 className="mb-2 text-sm font-semibold text-slate-200">时间线</h3>
                <ul className="space-y-1 text-sm text-slate-300">
                  {a.timeline_phases.map((p, i) => (
                    <li key={i}>
                      <span className="text-cyan-300">{p.phase}</span>：{p.note}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {a.related_derivative_topics && a.related_derivative_topics.length > 0 && (
            <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
              <h3 className="mb-2 text-sm font-semibold text-slate-200">
                相关衍生话题（AI）
              </h3>
              <div className="flex flex-wrap gap-2">
                {a.related_derivative_topics.map((t, i) => (
                  <span
                    key={i}
                    className="rounded-full bg-cyan-500/10 px-3 py-1 text-xs text-cyan-200"
                  >
                    {t.title} · 热度 {t.predicted_heat_score}
                  </span>
                ))}
              </div>
            </div>
          )}

          {data?.results && data.results.length > 0 && (
            <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
              <h3 className="mb-2 text-sm font-semibold text-slate-200">检索结果</h3>
              <ul className="divide-y divide-slate-800">
                {data.results.map((r, i) => (
                  <li key={i} className="flex items-center justify-between gap-3 py-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm text-slate-100">
                        {r.title ?? "（无标题）"}
                      </p>
                      <p className="text-xs text-slate-500">
                        {r.platform} · {r.author ?? "—"} ·{" "}
                        {r.view_count != null
                          ? `${(r.view_count / 10000).toFixed(1)} 万播放`
                          : "播放未知"}
                      </p>
                    </div>
                    {r.url && (
                      <a
                        href={r.url}
                        target="_blank"
                        rel="noreferrer"
                        className="shrink-0 text-xs text-cyan-300 hover:underline"
                      >
                        打开
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
