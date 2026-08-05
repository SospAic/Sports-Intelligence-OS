"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { StatePanel, secondaryButtonClass } from "@/components/ui";
import { useWorkspace } from "@/components/app-shell";
import { accountDisplayName } from "@/lib/account-label";
import { apiRequest } from "@/lib/browser-api";
import { BackButton } from "@/components/back-button";
import type { AccountRecord } from "@sio/shared-types";

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

function fmt(n: number | null): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("zh-CN");
}

function delta(n: number | null): string {
  if (n === null || n === undefined) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toLocaleString("zh-CN")}`;
}

export function AccountCompare() {
  const { workspaceId } = useWorkspace();
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState<ComparisonResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const accounts = useQuery({
    queryKey: ["accounts-all", workspaceId],
    queryFn: () =>
      apiRequest<{ items: AccountRecord[] }>("/accounts?page_size=100", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });

  const items = accounts.data?.items ?? [];
  const selectedSet = useMemo(() => new Set(selected), [selected]);

  function toggle(id: string) {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 5) return prev; // keep comparisons readable
      return [...prev, id];
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
      const qs = selected.map((id) => `account_ids=${id}`).join("&");
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

  return (
    <main className="mx-auto min-w-0 max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <BackButton label="返回账号监控" />

      <div>
        <h1 className="text-2xl font-semibold text-white">账号横向对比</h1>
        <p className="mt-1 text-sm text-slate-400">
          选择 2–5
          个账号，对比粉丝、播放、互动与增长。仅基于真实同步观测（live/imported），不合成数据。
        </p>
      </div>

      <div className="grid min-w-0 gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="min-w-0 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium text-slate-200">选择账号</h2>
            <span className="text-xs text-slate-500">
              已选 {selected.length}/5
            </span>
          </div>
          {accounts.isLoading ? (
            <div className="flex items-center gap-2 py-6 text-sm text-slate-400">
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
            <ul className="max-h-[60vh] space-y-1 overflow-auto">
              {items.map((acc) => {
                const checked = selectedSet.has(acc.id);
                return (
                  <li key={acc.id}>
                    <label
                      className={`flex min-w-0 cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm ${
                        checked
                          ? "bg-cyan-500/15 text-cyan-100"
                          : "text-slate-300 hover:bg-slate-800"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(acc.id)}
                        className="accent-cyan-500"
                      />
                      <span className="min-w-0 flex-1 truncate">
                        {accountDisplayName({
                          ...acc,
                          platform_name:
                            acc.platform?.name ?? acc.platform?.key,
                        })}
                        <span className="ml-1 shrink-0 text-xs text-slate-500">
                          · {acc.platform?.name ?? acc.platform?.key ?? ""}
                        </span>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          <button
            className={`mt-4 w-full ${secondaryButtonClass} h-9`}
            disabled={loading || selected.length < 2}
            onClick={runCompare}
          >
            {loading && <Loader2 className="animate-spin" size={15} />}
            对比所选账号
          </button>
        </aside>

        <section className="min-w-0 space-y-4">
          {error && (
            <div className="rounded-xl border border-amber-700/50 bg-amber-950/30 px-4 py-3 text-sm text-amber-200">
              {error}
            </div>
          )}
          {!result && !error && (
            <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-10 text-center text-sm text-slate-500">
              选择账号后点击「对比所选账号」查看横向对比。
            </div>
          )}
          {result && (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                <SummaryCard
                  label="总粉丝"
                  value={fmt(result.summary.total_followers)}
                />
                <SummaryCard
                  label="总播放"
                  value={fmt(result.summary.total_views)}
                />
                <SummaryCard
                  label="对比账号数"
                  value={String(result.summary.account_count)}
                />
              </div>
              <div className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-950/70">
                <table className="w-full min-w-[900px] text-left text-sm">
                  <caption className="sr-only">账号对比表</caption>
                  <thead className="border-b border-slate-800 bg-slate-900/60 text-xs text-slate-400">
                    <tr>
                      <th className="whitespace-nowrap px-4 py-3 font-medium">
                        账号
                      </th>
                      <th className="px-4 py-3 font-medium">平台</th>
                      <th className="px-4 py-3 text-right font-medium">粉丝</th>
                      <th className="px-4 py-3 text-right font-medium">
                        粉丝增量
                      </th>
                      <th className="px-4 py-3 text-right font-medium">
                        总播放
                      </th>
                      <th className="px-4 py-3 text-right font-medium">
                        播放增量
                      </th>
                      <th className="px-4 py-3 text-right font-medium">
                        互动率
                      </th>
                      <th className="px-4 py-3 font-medium">同步状态</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800">
                    {result.rows.map((row) => (
                      <tr
                        key={row.account_id}
                        className="hover:bg-slate-900/60"
                      >
                        <td className="max-w-[260px] px-4 py-3 text-slate-200">
                          <span
                            className="block truncate"
                            title={row.display_name}
                          >
                            {accountDisplayName({
                              ...row,
                              platform_name: row.platform_key,
                            })}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-slate-400">
                          {row.platform_key}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-200">
                          {fmt(row.latest?.follower_count ?? null)}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-300">
                          {delta(row.follower_delta)}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-200">
                          {fmt(row.latest?.total_view_count ?? null)}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-300">
                          {delta(row.view_delta)}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-300">
                          {(() => {
                            const er = row.latest?.engagement_rate;
                            return er != null ? `${er.toFixed(2)}%` : "—";
                          })()}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-slate-400">
                          {row.sync_status}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {result.rows.some((r) => r.latest?.source_kind === "mock") && (
                <p className="text-xs text-slate-500">
                  注：含 mock 来源账号，对比仅供演示，不参与真实性判断。
                </p>
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
      <div className="text-xs text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-white">
        {value}
      </div>
    </div>
  );
}
