"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/browser-api";
import { useToast } from "@/components/toast";

interface TrendTopicItem {
  id: string;
  title: string;
  platform: string;
  heat_score: number;
}

interface DerivativeTopic {
  id: string;
  kind: string;
  angle: string | null;
  title: string;
  description: string | null;
  predicted_heat_score: number | null;
  evidence: { sample_count?: number; median_views?: number; sample_titles?: string[] };
  ai_rationale: string | null;
  status: string;
  confidence: number;
}

function HeatBadge({ value }: { value: number | null }) {
  if (value == null) return null;
  const color =
    value >= 70 ? "bg-rose-500/20 text-rose-300" : value >= 40 ? "bg-amber-500/20 text-amber-300" : "bg-slate-700/40 text-slate-300";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      预测热度 {value}
    </span>
  );
}

export function DerivativesPanel({ workspaceId }: { workspaceId: string }) {
  const { notify } = useToast();
  const [topicId, setTopicId] = useState<string>("");
  const [generating, setGenerating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const topicsQuery = useQuery({
    queryKey: ["derivatives-topics", workspaceId],
    queryFn: () =>
      apiRequest<{ items: TrendTopicItem[] }>(
        "/trends/topics?platform=&page=1&page_size=50",
        { workspaceId },
      ),
  });
  const topics = topicsQuery.data?.items ?? [];
  const effectiveTopicId = topicId || topics[0]?.id || "";

  const derivativesQuery = useQuery({
    queryKey: ["derivatives", workspaceId, effectiveTopicId],
    queryFn: () =>
      apiRequest<{ items: DerivativeTopic[] }>(
        `/trends/derivatives?topic_id=${effectiveTopicId}&page=1&page_size=100`,
        { workspaceId },
      ),
    enabled: Boolean(effectiveTopicId),
  });
  const items = derivativesQuery.data?.items ?? [];

  const generate = async () => {
    if (!effectiveTopicId) return;
    setGenerating(true);
    setNotice(null);
    try {
      const data = await apiRequest<{ items: DerivativeTopic[]; notice: string | null }>(
        "/trends/derivatives/generate",
        {
          method: "POST",
          csrf: true,
          workspaceId,
          body: JSON.stringify({ topic_id: effectiveTopicId }),
        },
      );
      setNotice(data.notice ?? "已生成衍生话题（平台上已存在 + AI 预测的潜在角度）。");
      notify("衍生话题已生成", "success");
      await derivativesQuery.refetch();
    } catch (e) {
      notify(`生成失败：${(e as Error).message}`, "error");
    } finally {
      setGenerating(false);
    }
  };

  const adopt = async (id: string) => {
    try {
      await apiRequest(`/trends/derivatives/${id}/adopt`, {
        method: "POST",
        csrf: true,
        workspaceId,
      });
      notify("已采纳，可在「内容创作」中据此生成大纲", "success");
      await derivativesQuery.refetch();
    } catch (e) {
      notify(`采纳失败：${(e as Error).message}`, "error");
    }
  };

  const existing = items.filter((i) => i.kind === "existing_on_platform");
  const predicted = items.filter((i) => i.kind === "ai_predicted");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-800 bg-slate-950/50 p-4">
        <div className="flex-1 min-w-[240px]">
          <label className="mb-1 block text-xs font-medium text-slate-400">
            选择热点话题
          </label>
          <select
            value={effectiveTopicId}
            onChange={(e) => setTopicId(e.target.value)}
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
          >
            {topics.length === 0 && <option value="">（暂无热点，请先采集趋势数据）</option>}
            {topics.map((t) => (
              <option key={t.id} value={t.id}>
                [{t.platform}] {t.title} · 热度 {Math.round(t.heat_score)}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={generate}
          disabled={generating || !effectiveTopicId}
          className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-50"
        >
          {generating ? "生成中…" : "生成衍生话题"}
        </button>
      </div>

      {notice && (
        <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-4 py-2 text-sm text-cyan-200">
          {notice}
        </div>
      )}
      {derivativesQuery.isError && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-200">
          {(derivativesQuery.error as Error)?.message ?? "加载失败"}
        </div>
      )}
      {derivativesQuery.isLoading && <p className="text-sm text-slate-400">加载中…</p>}

      {/* AI 预测的潜在衍生话题 */}
      <section>
        <h3 className="mb-3 text-base font-semibold text-white">
          AI 预测的潜在热门衍生话题
          <span className="ml-2 text-xs font-normal text-slate-500">
            {predicted.length} 个 · 尚未饱和的角度
          </span>
        </h3>
        <div className="grid gap-3 md:grid-cols-2">
          {predicted.map((d) => (
            <div
              key={d.id}
              className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  {d.angle && (
                    <span className="text-xs text-cyan-300">{d.angle}</span>
                  )}
                  <p className="font-medium text-slate-100">{d.title}</p>
                </div>
                <HeatBadge value={d.predicted_heat_score} />
              </div>
              {d.description && (
                <p className="mt-2 text-sm text-slate-400">{d.description}</p>
              )}
              {d.ai_rationale && (
                <p className="mt-2 rounded-lg bg-slate-900/60 p-2 text-xs text-slate-400">
                  理由：{d.ai_rationale}
                </p>
              )}
              <div className="mt-3 flex items-center justify-between">
                <span className="text-xs text-slate-500">
                  置信度 {Math.round(d.confidence * 100)}%
                </span>
                {d.status === "adopted" ? (
                  <span className="text-xs text-emerald-300">已采纳</span>
                ) : (
                  <button
                    onClick={() => adopt(d.id)}
                    className="rounded-md border border-cyan-500/40 px-3 py-1 text-xs text-cyan-200 transition hover:bg-cyan-500/10"
                  >
                    采纳 → 生成大纲
                  </button>
                )}
              </div>
            </div>
          ))}
          {predicted.length === 0 && (
            <p className="text-sm text-slate-500">尚无 AI 预测结果，点击「生成衍生话题」。</p>
          )}
        </div>
      </section>

      {/* 平台上已存在的衍生话题 */}
      <section>
        <h3 className="mb-3 text-base font-semibold text-white">
          平台上已存在的衍生话题
          <span className="ml-2 text-xs font-normal text-slate-500">
            {existing.length} 个 · 聚类自真实视频
          </span>
        </h3>
        <div className="grid gap-3 md:grid-cols-2">
          {existing.map((d) => (
            <div
              key={d.id}
              className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  {d.angle && (
                    <span className="text-xs text-emerald-300">{d.angle}</span>
                  )}
                  <p className="font-medium text-slate-100">{d.title}</p>
                </div>
                <HeatBadge value={d.predicted_heat_score} />
              </div>
              <p className="mt-2 text-sm text-slate-400">{d.description}</p>
              {d.evidence?.sample_titles?.length ? (
                <ul className="mt-2 space-y-1 text-xs text-slate-500">
                  {d.evidence.sample_titles.slice(0, 3).map((s, i) => (
                    <li key={i}>· {s}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ))}
          {existing.length === 0 && (
            <p className="text-sm text-slate-500">暂无平台上已存在的衍生聚类。</p>
          )}
        </div>
      </section>
    </div>
  );
}
