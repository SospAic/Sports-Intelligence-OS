"use client";

import type { AccountRecord } from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Check,
  Filter,
  Loader2,
  Search,
  Trophy,
  UsersRound,
  Video,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { BackButton } from "@/components/back-button";
import { useWorkspace } from "@/components/app-shell";
import {
  Badge,
  PageHeader,
  Panel,
  StatePanel,
  buttonClass,
  inputClass,
} from "@/components/ui";
import { accountDisplayName } from "@/lib/account-label";
import { apiRequest } from "@/lib/browser-api";
import {
  formatNumber,
  formatPercent,
  sourceKindLabel,
} from "@/lib/format";

interface ComparisonSnapshot {
  captured_at: string;
  follower_count: number | null;
  total_view_count: number | null;
  video_count: number | null;
  engagement_rate: number | null;
  source_kind: string;
}

interface ComparisonRow {
  account_id: string;
  platform_key: string;
  display_name: string;
  username: string | null;
  is_active: boolean;
  sync_status: string;
  latest: ComparisonSnapshot | null;
  previous: ComparisonSnapshot | null;
  follower_delta: number | null;
  view_delta: number | null;
  window_hours: number | null;
}

interface ComparisonSummary {
  account_count: number;
  total_followers: number | null;
  total_views: number | null;
  total_videos: number | null;
  best_followers_account_id: string | null;
  best_views_account_id: string | null;
  best_engagement_account_id: string | null;
}

interface ComparisonResponse {
  rows: ComparisonRow[];
  summary: ComparisonSummary;
}

type RankingMetric = "followers" | "growth" | "views" | "engagement";

const PLATFORM_LABELS: Record<string, string> = {
  bilibili: "Bilibili",
  douyin: "抖音",
  facebook: "Facebook",
  instagram: "Instagram",
  tiktok: "TikTok",
  youtube: "YouTube",
};

const SYNC_STATUS_LABELS: Record<string, string> = {
  disabled: "已停用",
  error: "同步错误",
  never: "未同步",
  queued: "排队中",
  syncing: "同步中",
  success: "已同步",
};

function fmt(value: number | null | undefined): string {
  return formatNumber(value);
}

function delta(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${formatNumber(value)}`;
}

function median(values: Array<number | null | undefined>): number | null {
  const valid = values
    .filter((value): value is number => value !== null && value !== undefined)
    .sort((a, b) => a - b);
  if (!valid.length) return null;
  const middle = Math.floor(valid.length / 2);
  return valid.length % 2
    ? valid[middle]!
    : (valid[middle - 1]! + valid[middle]!) / 2;
}

function platformLabel(value: string): string {
  return PLATFORM_LABELS[value.toLowerCase()] ?? value;
}

function syncStatusLabel(value: string): string {
  return SYNC_STATUS_LABELS[value] ?? value;
}

function metricValue(row: ComparisonRow, metric: RankingMetric): number | null {
  if (metric === "followers") return row.latest?.follower_count ?? null;
  if (metric === "growth") return row.follower_delta;
  if (metric === "views") return row.latest?.total_view_count ?? null;
  return row.latest?.engagement_rate ?? null;
}

function metricLabel(metric: RankingMetric): string {
  return {
    followers: "粉丝规模",
    growth: "粉丝增长",
    views: "累计播放",
    engagement: "互动率",
  }[metric];
}

function metricText(value: number | null, metric: RankingMetric): string {
  if (value === null || value === undefined) return "—";
  return metric === "growth"
    ? delta(value)
    : metric === "engagement"
      ? formatPercent(value)
      : fmt(value);
}

function relativeToBaseline(value: number | null, baseline: number | null): string {
  if (value === null || baseline === null || baseline === 0) return "—";
  const ratio = ((value - baseline) / Math.abs(baseline)) * 100;
  return `${ratio > 0 ? "+" : ""}${ratio.toFixed(1)}%`;
}

export function AccountCompare() {
  const { workspaceId } = useWorkspace();
  const [selected, setSelected] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [platform, setPlatform] = useState("");
  const [activeOnly, setActiveOnly] = useState(true);
  const [rankingMetric, setRankingMetric] = useState<RankingMetric>("growth");
  const [result, setResult] = useState<ComparisonResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initialSelectionDone = useRef(false);

  const accounts = useQuery({
    queryKey: ["accounts-all", workspaceId],
    queryFn: () =>
      apiRequest<{ items: AccountRecord[] }>("/accounts?page_size=100", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });

  const items = useMemo(() => accounts.data?.items ?? [], [accounts.data?.items]);
  useEffect(() => {
    if (initialSelectionDone.current || !items.length) return;
    const preferred = items.filter((item) => item.is_active).slice(0, 3);
    setSelected((preferred.length ? preferred : items.slice(0, 3)).map((item) => item.id));
    initialSelectionDone.current = true;
  }, [items]);

  const platforms = useMemo(
    () =>
      Array.from(
        new Set(items.map((item) => item.platform?.key).filter(Boolean)),
      ).sort(),
    [items],
  );
  const filteredAccounts = useMemo(() => {
    const query = search.trim().toLowerCase();
    return items.filter((account) => {
      if (activeOnly && !account.is_active) return false;
      if (platform && account.platform?.key !== platform) return false;
      if (!query) return true;
      return [
        account.display_name,
        account.username,
        account.platform?.name,
        account.platform?.key,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    });
  }, [activeOnly, items, platform, search]);
  const selectedSet = useMemo(() => new Set(selected), [selected]);

  function toggle(id: string) {
    setSelected((previous) => {
      if (previous.includes(id)) return previous.filter((item) => item !== id);
      if (previous.length >= 8) return previous;
      return [...previous, id];
    });
  }

  function selectVisible() {
    setSelected((previous) => {
      const next = [...previous];
      for (const account of filteredAccounts) {
        if (!next.includes(account.id) && next.length < 8) next.push(account.id);
      }
      return next;
    });
  }

  async function runCompare() {
    if (selected.length < 2) {
      setError("请至少选择 2 个账号进行对比");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const qs = selected.map((id) => `account_ids=${encodeURIComponent(id)}`).join("&");
      const data = await apiRequest<ComparisonResponse>(
        `/accounts/compare?${qs}`,
        { workspaceId: workspaceId! },
      );
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "对比失败");
    } finally {
      setLoading(false);
    }
  }

  const resultRows = useMemo(() => {
    if (!result) return [];
    const order = new Map(selected.map((id, index) => [id, index]));
    return [...result.rows].sort(
      (a, b) => (order.get(a.account_id) ?? 999) - (order.get(b.account_id) ?? 999),
    );
  }, [result, selected]);
  const metricBaseline = median(resultRows.map((row) => metricValue(row, rankingMetric)));
  const rankingRows = useMemo(
    () =>
      [...resultRows].sort(
        (a, b) =>
          (metricValue(b, rankingMetric) ?? Number.NEGATIVE_INFINITY) -
          (metricValue(a, rankingMetric) ?? Number.NEGATIVE_INFINITY),
      ),
    [rankingMetric, resultRows],
  );
  const rankingMax = Math.max(
    ...rankingRows.map((row) => Math.max(metricValue(row, rankingMetric) ?? 0, 0)),
    0,
  );

  function rowFor(id: string | null) {
    return id ? resultRows.find((row) => row.account_id === id) : undefined;
  }

  const leaderFollowers = rowFor(result?.summary.best_followers_account_id ?? null);
  const leaderViews = rowFor(result?.summary.best_views_account_id ?? null);
  const leaderEngagement = rowFor(result?.summary.best_engagement_account_id ?? null);

  return (
    <main className="mx-auto min-w-0 max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <BackButton label="返回账号监控" />
      <PageHeader
        eyebrow="BENCHMARK WORKSPACE"
        title="账号横向对比"
        description="用组内基准、增长排名和数据新鲜度识别账号差异。所有数值来自已同步快照，不跨平台伪造统一口径。"
        actions={
          <Badge tone="info">最多选择 8 个账号</Badge>
        }
      />

      <div className="grid min-w-0 gap-6 xl:grid-cols-[330px_minmax(0,1fr)]">
        <Panel className="min-w-0 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-medium text-slate-200">选择对比对象</h2>
              <p className="mt-1 text-xs text-slate-500">先选账号，再运行一次对比快照</p>
            </div>
            <span className="text-xs tabular-nums text-cyan-300">{selected.length}/8</span>
          </div>
          <div className="mt-4 space-y-2">
            <label className="relative block">
              <Search className="absolute top-1/2 left-3 -translate-y-1/2 text-slate-500" size={15} />
              <input
                aria-label="搜索账号"
                className={`${inputClass} pl-9 text-sm`}
                placeholder="搜索账号或平台"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <div className="grid grid-cols-[1fr_auto] gap-2">
              <select
                aria-label="按平台筛选"
                className={`${inputClass} text-sm`}
                value={platform}
                onChange={(event) => setPlatform(event.target.value)}
              >
                <option value="">全部平台</option>
                {platforms.map((value) => (
                  <option key={value} value={value}>
                    {platformLabel(value)}
                  </option>
                ))}
              </select>
              <button
                aria-label="选择当前可见账号"
                className="grid size-10 place-items-center rounded-lg border border-slate-700 text-slate-400 hover:bg-slate-900 hover:text-white"
                onClick={selectVisible}
                title="选择当前可见账号"
                type="button"
              >
                <Filter size={15} />
              </button>
            </div>
            <label className="flex items-center gap-2 px-1 text-xs text-slate-400">
              <input
                checked={activeOnly}
                className="accent-cyan-400"
                onChange={(event) => setActiveOnly(event.target.checked)}
                type="checkbox"
              />
              仅显示启用账号
            </label>
          </div>
          {accounts.isLoading ? (
            <div className="flex items-center gap-2 py-8 text-sm text-slate-400">
              <Loader2 className="animate-spin" size={16} /> 加载账号…
            </div>
          ) : accounts.error ? (
            <StatePanel
              type="error"
              title="账号加载失败"
              detail={accounts.error.message}
              onRetry={() => accounts.refetch()}
            />
          ) : (
            <div className="mt-3 max-h-[55vh] overflow-y-auto pr-1">
              {filteredAccounts.length ? (
                <ul className="space-y-1">
                  {filteredAccounts.map((account) => {
                    const checked = selectedSet.has(account.id);
                    return (
                      <li key={account.id}>
                        <label
                          className={`flex min-w-0 cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition ${checked ? "bg-cyan-500/15 text-cyan-100" : "text-slate-300 hover:bg-slate-900"}`}
                        >
                          <span
                            className={`grid size-4 shrink-0 place-items-center rounded border ${checked ? "border-cyan-400 bg-cyan-400 text-slate-950" : "border-slate-600"}`}
                          >
                            {checked && <Check size={12} strokeWidth={3} />}
                          </span>
                          <input
                            checked={checked}
                            className="sr-only"
                            onChange={() => toggle(account.id)}
                            type="checkbox"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate">
                              {accountDisplayName({
                                ...account,
                                platform_name: account.platform?.name ?? account.platform?.key,
                              })}
                            </span>
                            <span className="mt-0.5 block truncate text-xs text-slate-500">
                              {platformLabel(account.platform?.key ?? "")} · {account.username ?? "未读取用户名"}
                            </span>
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="py-8 text-center text-sm text-slate-500">没有符合筛选条件的账号</p>
              )}
            </div>
          )}
          <div className="mt-4 border-t border-slate-800 pt-4">
            <button
              className={`w-full ${buttonClass} justify-center`}
              disabled={loading || selected.length < 2}
              onClick={runCompare}
              type="button"
            >
              {loading && <Loader2 className="animate-spin" size={15} />}
              {loading ? "正在生成对比…" : "生成对比快照"}
            </button>
            <p className="mt-2 text-center text-[11px] text-slate-600">{selected.length < 2 ? "至少选择 2 个账号" : "快照生成后可切换排名指标"}</p>
          </div>
        </Panel>

        <section className="min-w-0 space-y-4">
          {error && (
            <div className="rounded-xl border border-amber-700/50 bg-amber-950/30 px-4 py-3 text-sm text-amber-200">
              {error}
            </div>
          )}
          {!result && !error && (
            <Panel className="p-12 text-center">
              <BarChart3 className="mx-auto text-cyan-400" size={32} />
              <p className="mt-4 text-sm text-slate-300">选择至少 2 个账号生成对比快照</p>
              <p className="mt-1 text-xs text-slate-500">结果会按粉丝、播放、增长和互动率展示组内差异。</p>
            </Panel>
          )}
          {result && (
            <>
              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
                <SummaryCard icon={<UsersRound size={16} />} label="总粉丝" value={fmt(result.summary.total_followers)} hint="当前快照合计" />
                <SummaryCard icon={<Video size={16} />} label="累计播放" value={fmt(result.summary.total_views)} hint="当前快照合计" />
                <SummaryCard icon={<BarChart3 size={16} />} label="作品数量" value={fmt(result.summary.total_videos)} hint="可用字段合计" />
                <SummaryCard icon={<Trophy size={16} />} label="对比账号" value={`${result.summary.account_count} 个`} hint="组内基准样本" />
              </div>

              <div className="grid gap-4 2xl:grid-cols-[minmax(0,1.25fr)_minmax(300px,.75fr)]">
                <Panel className="min-w-0 p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="font-medium text-white">组内排名与基准</h2>
                      <p className="mt-1 text-xs text-slate-500">柱形长度代表组内相对值；百分比为相对组内中位数的差异。</p>
                    </div>
                    <div className="flex flex-wrap gap-1 rounded-lg border border-slate-800 p-1">
                      {(["growth", "followers", "views", "engagement"] as const).map((metric) => (
                        <button
                          className={`rounded-md px-2.5 py-1.5 text-xs transition ${rankingMetric === metric ? "bg-cyan-400/15 text-cyan-200" : "text-slate-500 hover:text-slate-200"}`}
                          key={metric}
                          onClick={() => setRankingMetric(metric)}
                          type="button"
                        >
                          {metricLabel(metric)}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="mt-5 space-y-4">
                    {rankingRows.map((row, index) => {
                      const value = metricValue(row, rankingMetric);
                      const width = rankingMax > 0 && value !== null ? Math.max((Math.max(value, 0) / rankingMax) * 100, 5) : 0;
                      return (
                        <div key={row.account_id}>
                          <div className="flex items-center justify-between gap-3 text-sm">
                            <div className="flex min-w-0 items-center gap-2">
                              <span className="w-5 text-xs tabular-nums text-slate-600">{index + 1}</span>
                              <span className="truncate text-slate-200">{row.display_name}</span>
                              <span className="shrink-0 text-[11px] text-slate-600">{platformLabel(row.platform_key)}</span>
                            </div>
                            <span className="shrink-0 tabular-nums text-slate-200">{metricText(value, rankingMetric)}</span>
                          </div>
                          <div className="mt-2 flex items-center gap-2">
                            <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-800">
                              <div className="h-full rounded-full bg-cyan-400 transition-all" style={{ width: `${width}%` }} />
                            </div>
                            <span className={`w-16 text-right text-xs tabular-nums ${value !== null && metricBaseline !== null && value >= metricBaseline ? "text-emerald-300" : "text-rose-300"}`}>
                              {relativeToBaseline(value, metricBaseline)}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </Panel>

                <Panel className="p-5">
                  <h2 className="font-medium text-white">对比结论</h2>
                  <p className="mt-1 text-xs text-slate-500">只根据当前选择的真实快照生成，不推断平台未提供的指标。</p>
                  <div className="mt-4 space-y-3">
                    <Insight icon={<UsersRound size={15} />} label="粉丝规模领先" value={leaderFollowers?.display_name ?? "暂无可用快照"} detail={leaderFollowers ? fmt(leaderFollowers.latest?.follower_count) : "—"} />
                    <Insight icon={<Video size={15} />} label="播放规模领先" value={leaderViews?.display_name ?? "暂无可用快照"} detail={leaderViews ? fmt(leaderViews.latest?.total_view_count) : "—"} />
                    <Insight icon={<Trophy size={15} />} label="互动率领先" value={leaderEngagement?.display_name ?? "暂无可用快照"} detail={leaderEngagement?.latest?.engagement_rate != null ? formatPercent(leaderEngagement.latest.engagement_rate) : "—"} />
                  </div>
                  <div className="mt-5 rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-xs leading-5 text-slate-500">
                    组内中位数仅用于横向基准，不等同于行业基准。跨平台的播放和互动定义可能不同，建议先在同平台账号之间比较，再结合平台来源说明解读。
                  </div>
                </Panel>
              </div>

              <Panel className="min-w-0 overflow-hidden p-0">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-5 py-4">
                  <div>
                    <h2 className="font-medium text-white">逐账号明细</h2>
                    <p className="mt-1 text-xs text-slate-500">含增量、快照时间、来源和同步状态，便于定位数据质量差异。</p>
                  </div>
                  <span className="text-xs text-slate-500">粉丝中位数：{fmt(median(resultRows.map((row) => row.latest?.follower_count)))}</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[1120px] text-left text-sm">
                    <caption className="sr-only">账号横向对比明细</caption>
                    <thead className="bg-slate-900/60 text-xs text-slate-400">
                      <tr>
                        <th className="px-5 py-3 font-medium">账号</th>
                        <th className="px-4 py-3 font-medium">平台 / 来源</th>
                        <th className="px-4 py-3 text-right font-medium">粉丝</th>
                        <th className="px-4 py-3 text-right font-medium">粉丝增量</th>
                        <th className="px-4 py-3 text-right font-medium">累计播放</th>
                        <th className="px-4 py-3 text-right font-medium">播放增量</th>
                        <th className="px-4 py-3 text-right font-medium">作品</th>
                        <th className="px-4 py-3 text-right font-medium">互动率</th>
                        <th className="px-4 py-3 font-medium">状态 / 快照</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                      {resultRows.map((row) => {
                        const followerMedian = median(resultRows.map((item) => item.latest?.follower_count));
                        return (
                          <tr className="hover:bg-slate-900/60" key={row.account_id}>
                            <td className="max-w-[240px] px-5 py-4">
                              <span className="block truncate text-slate-200" title={row.display_name}>{row.display_name}</span>
                              <span className="mt-1 block truncate text-xs text-slate-600">{row.username ?? "未读取用户名"}</span>
                            </td>
                            <td className="px-4 py-4">
                              <span className="block text-slate-300">{platformLabel(row.platform_key)}</span>
                              <span className="mt-1 block text-xs text-slate-500">{sourceKindLabel(row.latest?.source_kind ?? "")}</span>
                            </td>
                            <td className="px-4 py-4 text-right tabular-nums text-slate-200">{fmt(row.latest?.follower_count)}</td>
                            <td className={`px-4 py-4 text-right tabular-nums ${row.follower_delta != null && row.follower_delta > 0 ? "text-emerald-300" : row.follower_delta != null && row.follower_delta < 0 ? "text-rose-300" : "text-slate-400"}`}>
                              <span className="inline-flex items-center gap-1">
                                {row.follower_delta != null && row.follower_delta > 0 ? <ArrowUpRight size={13} /> : row.follower_delta != null && row.follower_delta < 0 ? <ArrowDownRight size={13} /> : null}
                                {delta(row.follower_delta)}
                              </span>
                              <span className="mt-1 block text-[11px] text-slate-600">中位数 {relativeToBaseline(row.latest?.follower_count ?? null, followerMedian)}</span>
                            </td>
                            <td className="px-4 py-4 text-right tabular-nums text-slate-200">{fmt(row.latest?.total_view_count)}</td>
                            <td className="px-4 py-4 text-right tabular-nums text-slate-300">{delta(row.view_delta)}</td>
                            <td className="px-4 py-4 text-right tabular-nums text-slate-300">{fmt(row.latest?.video_count)}</td>
                            <td className="px-4 py-4 text-right tabular-nums text-slate-300">{row.latest?.engagement_rate != null ? formatPercent(row.latest.engagement_rate) : "—"}</td>
                            <td className="whitespace-nowrap px-4 py-4">
                              <span className="block text-xs text-slate-300">{syncStatusLabel(row.sync_status)}</span>
                              <span className="mt-1 block text-[11px] text-slate-600">{row.latest ? new Date(row.latest.captured_at).toLocaleString("zh-CN") : "暂无快照"}</span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {resultRows.some((row) => row.latest?.source_kind === "mock") && (
                  <p className="border-t border-slate-800 px-5 py-3 text-xs text-amber-300">本次结果含 mock 来源，仅用于契约演示；请勿据此判断真实平台表现。</p>
                )}
              </Panel>
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function SummaryCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <Panel className="p-4">
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <span className="text-cyan-300">{icon}</span>
        {label}
      </div>
      <p className="mt-3 text-2xl font-semibold tabular-nums text-white">{value}</p>
      <p className="mt-1 text-xs text-slate-600">{hint}</p>
    </Panel>
  );
}

function Insight({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/40 p-3">
      <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-cyan-400/10 text-cyan-300">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-xs text-slate-500">{label}</span>
        <span className="mt-1 block truncate text-sm text-slate-200">{value}</span>
      </span>
      <span className="shrink-0 text-sm tabular-nums text-cyan-300">{detail}</span>
    </div>
  );
}
