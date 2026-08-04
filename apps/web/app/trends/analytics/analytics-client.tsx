"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/browser-api";
import { useWorkspace } from "@/components/app-shell";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const PLATFORM_LABELS: Record<string, string> = {
  youtube: "YouTube",
  tiktok: "TikTok",
  douyin: "抖音",
  bilibili: "B站",
};

const PLATFORM_COLORS: Record<string, string> = {
  youtube: "#ef4444",
  tiktok: "#22d3ee",
  douyin: "#f472b6",
  bilibili: "#60a5fa",
};

const ALL_PLATFORMS = ["youtube", "tiktok", "douyin", "bilibili"];

type AggItem = {
  platform: string;
  category: string;
  title: string;
  kind: string;
  metric: number;
  metric_label: string;
  observed_at: string;
};

type Agg = {
  generated_at: string;
  window_days: number;
  platforms: string[];
  categories: string[];
  timeline: { date: string; platform: string; heat: number }[];
  ranking: AggItem[];
  index: { platform: string; value: number }[];
  matrix: { platform: string; category: string; heat: number }[];
};

const MODES: { key: string; label: string; hint: string }[] = [
  { key: "timeline", label: "趋势时间线", hint: "参考 Google Trends：每日各平台累计热度折线" },
  { key: "ranking", label: "排行榜单", hint: "参考 GitHub Trending：热点/视频按热度排行" },
  { key: "index", label: "指数对比", hint: "参考微信/百度指数：各平台热度归一化对比" },
  { key: "matrix", label: "热度矩阵", hint: "参考 Sports-OS：平台 × 分类 热度矩阵" },
];

const DAY_OPTIONS = [7, 30, 90];

export function AnalyticsClient() {
  const { workspaceId } = useWorkspace();
  const [selected, setSelected] = useState<string[]>([]); // 空 = 全部平台
  const [category, setCategory] = useState<string>(""); // 空 = 全部分类
  const [days, setDays] = useState<number>(30);
  const [mode, setMode] = useState<string>("timeline");

  const params = new URLSearchParams();
  if (selected.length) params.set("platforms", selected.join(","));
  if (category) params.set("category", category);
  params.set("days", String(days));
  const qs = params.toString();

  const { data, isLoading, error } = useQuery({
    queryKey: ["trends-aggregate", qs, workspaceId],
    enabled: Boolean(workspaceId),
    queryFn: () =>
      apiRequest<Agg>(`/trends/aggregate?${qs}`, {
        workspaceId: workspaceId ?? undefined,
      }),
  });

  const activePlatforms = selected.length
    ? selected
    : data?.platforms?.length
      ? data.platforms
      : ALL_PLATFORMS;

  // 趋势时间线：按日期透视成 平台→热度 序列
  const timelineData = useMemo(() => {
    if (!data) return [] as Record<string, string | number>[];
    const dates = Array.from(new Set(data.timeline.map((t) => t.date))).sort();
    const byKey = new Map<string, number>();
    for (const t of data.timeline) byKey.set(`${t.date}|${t.platform}`, t.heat);
    return dates.map((d) => {
      const row: Record<string, string | number> = { date: d };
      for (const p of activePlatforms) row[p] = byKey.get(`${d}|${p}`) ?? 0;
      return row;
    });
  }, [data, activePlatforms]);

  // 热度矩阵：按分类透视成 平台→热度
  const matrixRows = useMemo(() => {
    if (!data)
      return [] as { category: string; cells: Record<string, number>; maxHeat: number }[];
    const cats = data.categories;
    const lookup = new Map<string, number>();
    for (const m of data.matrix) lookup.set(`${m.category}|${m.platform}`, m.heat);
    const maxHeat = Math.max(1, ...data.matrix.map((m) => m.heat));
    return cats.map((c) => {
      const cells: Record<string, number> = {};
      for (const p of activePlatforms) cells[p] = lookup.get(`${c}|${p}`) ?? 0;
      return { category: c, cells, maxHeat };
    });
  }, [data, activePlatforms]);
  // 类型标注与返回值对齐

  const togglePlatform = (p: string) =>
    setSelected((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p],
    );

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 text-slate-200">
      <header className="mb-5">
        <h1 className="text-xl font-semibold text-white">热点情报 · 聚合分析</h1>
        <p className="mt-1 text-sm text-slate-400">
          单/多平台 + 分类数据聚合展示。支持趋势时间线、排行榜单、指数对比、热度矩阵四种视角。
        </p>
      </header>

      {/* 过滤器 */}
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/50 p-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">平台</span>
          {ALL_PLATFORMS.map((p) => {
            const on = selected.includes(p) || selected.length === 0;
            return (
              <button
                key={p}
                type="button"
                onClick={() => togglePlatform(p)}
                className={`rounded-full px-3 py-1 text-xs transition ${
                  on
                    ? "bg-cyan-500/20 text-cyan-300 ring-1 ring-cyan-500/40"
                    : "bg-slate-800 text-slate-500 hover:text-slate-300"
                }`}
              >
                {PLATFORM_LABELS[p] ?? p}
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">分类</span>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-200"
          >
            <option value="">全部分类</option>
            {data?.categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">窗口</span>
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={`rounded-md px-2 py-1 text-xs ${
                days === d
                  ? "bg-cyan-500/20 text-cyan-300"
                  : "bg-slate-800 text-slate-400 hover:text-slate-200"
              }`}
            >
              {d}天
            </button>
          ))}
        </div>
      </div>

      {/* 模式切换 */}
      <div className="mb-4 flex flex-wrap gap-2">
        {MODES.map((m) => (
          <button
            key={m.key}
            type="button"
            onClick={() => setMode(m.key)}
            title={m.hint}
            className={`rounded-lg px-3 py-1.5 text-sm transition ${
              mode === m.key
                ? "bg-cyan-500 text-slate-900"
                : "bg-slate-800 text-slate-300 hover:bg-slate-700"
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {isLoading && <p className="text-sm text-slate-500">加载中…</p>}
      {error && (
        <p className="text-sm text-rose-400">加载失败：{(error as Error).message}</p>
      )}
      {data && !isLoading && (
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
          <p className="mb-3 text-xs text-slate-500">
            {MODES.find((m) => m.key === mode)?.hint} · 窗口 {data.window_days} 天 · 平台{" "}
            {activePlatforms.map((p) => PLATFORM_LABELS[p] ?? p).join("/") || "全部"}
          </p>

          {mode === "timeline" && (
            <ResponsiveContainer width="100%" height={360}>
              <LineChart data={timelineData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" stroke="#64748b" fontSize={11} />
                <YAxis stroke="#64748b" fontSize={11} />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }}
                  labelStyle={{ color: "#e2e8f0" }}
                />
                <Legend />
                {activePlatforms.map((p) => (
                  <Line
                    key={p}
                    type="monotone"
                    dataKey={p}
                    name={PLATFORM_LABELS[p] ?? p}
                    stroke={PLATFORM_COLORS[p] ?? "#38bdf8"}
                    dot={false}
                    strokeWidth={2}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}

          {mode === "ranking" && (
            <ol className="space-y-2">
              {data.ranking.slice(0, 25).map((item, i) => (
                <li
                  key={`${item.kind}-${item.title}-${i}`}
                  className="flex items-center gap-3 rounded-md bg-slate-800/60 px-3 py-2"
                >
                  <span className="w-6 text-right text-sm font-semibold text-slate-500">
                    {i + 1}
                  </span>
                  <span
                    className="rounded px-2 py-0.5 text-[11px]"
                    style={{
                      background: `${PLATFORM_COLORS[item.platform] ?? "#38bdf8"}22`,
                      color: PLATFORM_COLORS[item.platform] ?? "#38bdf8",
                    }}
                  >
                    {PLATFORM_LABELS[item.platform] ?? item.platform}
                  </span>
                  <span className="rounded bg-slate-700 px-2 py-0.5 text-[11px] text-slate-300">
                    {item.category}
                  </span>
                  <span className="flex-1 truncate text-sm text-slate-100">
                    {item.title}
                  </span>
                  <span className="text-xs text-slate-400">
                    {item.kind === "video" ? "视频" : "话题"} · {item.metric_label}{" "}
                    <b className="text-cyan-300">{item.metric.toFixed(1)}</b>
                  </span>
                </li>
              ))}
              {data.ranking.length === 0 && (
                <li className="text-sm text-slate-500">暂无排行数据</li>
              )}
            </ol>
          )}

          {mode === "index" && (
            <ResponsiveContainer width="100%" height={360}>
              <BarChart data={data.index}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  dataKey="platform"
                  stroke="#64748b"
                  fontSize={11}
                  tickFormatter={(v: string) => PLATFORM_LABELS[v] ?? v}
                />
                <YAxis stroke="#64748b" fontSize={11} domain={[0, 100]} />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }}
                  labelStyle={{ color: "#e2e8f0" }}
                  formatter={(value) => [`${value}`, "归一化热度"] as [string, string]}
                  labelFormatter={(v) => PLATFORM_LABELS[String(v)] ?? String(v)}
                />
                <Bar dataKey="value" name="归一化热度" fill="#22d3ee" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}

          {mode === "matrix" && (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="text-left text-slate-400">
                    <th className="p-2">分类 \ 平台</th>
                    {activePlatforms.map((p) => (
                      <th key={p} className="p-2 text-center">
                        {PLATFORM_LABELS[p] ?? p}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {matrixRows.map((row) => (
                    <tr key={row.category} className="border-t border-slate-800">
                      <td className="p-2 font-medium text-slate-200">{row.category}</td>
                      {activePlatforms.map((p) => {
                        const v = row.cells[p] ?? 0;
                        const intensity = row.maxHeat
                          ? Math.min(1, v / row.maxHeat)
                          : 0;
                        return (
                          <td
                            key={p}
                            className="p-2 text-center text-xs"
                            style={{
                              background: `rgba(34, 211, 238, ${intensity * 0.55})`,
                              color: intensity > 0.4 ? "#06202a" : "#cbd5e1",
                            }}
                          >
                            {v.toFixed(0)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                  {matrixRows.length === 0 && (
                    <tr>
                      <td className="p-2 text-slate-500" colSpan={activePlatforms.length + 1}>
                        暂无矩阵数据
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
