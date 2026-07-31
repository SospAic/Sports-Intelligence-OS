"use client";
import type {
  AccountRecordPage,
  AccountSnapshotPage,
  ArticleRecordPage,
  ContentRecordPage,
  OperationTaskPage,
} from "@sio/shared-types";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  Activity,
  BellRing,
  Newspaper,
  Radio,
  UsersRound,
  Video,
} from "lucide-react";
import Link from "next/link";
import { useWorkspace } from "@/components/app-shell";
import { TrendChart } from "@/components/trend-chart";
import {
  Badge,
  MetricCard,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate, formatNumber, sourceKindLabel } from "@/lib/format";
import { buildChartSeries } from "@/lib/time-series";
import {
  OPERATION_STATUS_LABELS,
  operationTaskLabel,
} from "@/lib/operation-labels";

type DashboardStats = {
  stats: {
    account_counts?: {
      total: number;
      active: number;
      synced_24h: number;
      by_platform: Record<string, number>;
    };
    content_counts?: {
      total: number;
      new_24h: number;
      by_platform: Record<string, number>;
    };
    sync_stats?: {
      successful_24h: number;
      failed_24h: number;
      next_scheduled_at: string | null;
    };
    news_stats?: {
      total_articles: number;
      new_articles_24h: number;
      total_events: number;
      hot_events: number;
    };
    automation_stats?: {
      enabled_rules: number;
      evaluations_24h: number;
      matched_24h: number;
    };
    notification_stats?: {
      total_24h: number;
      delivered_24h: number;
      failed_24h: number;
    };
  };
};
export function DashboardClient() {
  const {
    workspaceId,
    currentUser,
    loading: workspaceLoading,
  } = useWorkspace();
  const results = useQueries({
    queries: [
      {
        queryKey: ["dashboard-stats", workspaceId],
        queryFn: () =>
          apiRequest<DashboardStats>("/dashboard/stats", {
            workspaceId: workspaceId!,
          }),
        enabled: Boolean(workspaceId),
      },
      {
        queryKey: ["dash-accounts", workspaceId],
        queryFn: () =>
          apiRequest<AccountRecordPage>(
            "/accounts?page=1&page_size=100&sort=follower_growth_24h&order=desc&is_active=true",
            { workspaceId: workspaceId! },
          ),
        enabled: Boolean(workspaceId),
      },
      {
        queryKey: ["dash-contents", workspaceId],
        queryFn: () =>
          apiRequest<ContentRecordPage>(
            "/contents?page=1&page_size=20&sort=view_count&order=desc",
            { workspaceId: workspaceId! },
          ),
        enabled: Boolean(workspaceId),
      },
      {
        queryKey: ["dash-news", workspaceId],
        queryFn: () =>
          apiRequest<ArticleRecordPage>(
            "/news/articles?page=1&page_size=10&sort=heat_score&order=desc",
            { workspaceId: workspaceId! },
          ),
        enabled: Boolean(workspaceId),
      },
      {
        queryKey: ["dash-tasks", workspaceId],
        queryFn: () =>
          apiRequest<OperationTaskPage>(
            "/operations/tasks?page=1&page_size=8",
            { workspaceId: workspaceId! },
          ),
        enabled: Boolean(workspaceId),
      },
    ],
  });
  const [stats, accounts, contents, news, tasks] = results;
  const firstAccount = accounts.data?.items[0]?.id;
  const snapshots = useQuery({
    queryKey: ["dash-trend", firstAccount],
    queryFn: () =>
      apiRequest<AccountSnapshotPage>(
        `/accounts/${firstAccount}/snapshots?page=1&page_size=30`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId && firstAccount),
  });
  if (
    workspaceLoading ||
    !workspaceId ||
    results.some((result) => result.isLoading)
  )
    return (
      <main className="p-8">
        <SkeletonRows count={8} />
      </main>
    );
  const failed = results.find((result) => result.error)?.error;
  if (failed)
    return (
      <main className="p-8">
        <StatePanel
          type="error"
          title="仪表盘数据加载失败"
          detail={failed.message}
        />
      </main>
    );
  const trend = buildChartSeries(
    snapshots.data?.items ?? [],
    (item) => item.follower_count,
  );
  const platformCounts = Object.entries(
    (accounts.data?.items ?? []).reduce<Record<string, number>>(
      (result, item) => {
        result[item.platform.name] = (result[item.platform.name] ?? 0) + 1;
        return result;
      },
      {},
    ),
  ).sort((left, right) => right[1] - left[1]);
  const largestPlatform = Math.max(
    1,
    ...platformCounts.map(([, count]) => count),
  );
  return (
    <main className="mx-auto max-w-[1600px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Overview"
        title={`早上好，${currentUser?.user.display_name || currentUser?.user.email || "创作者"}`}
        description="所有统计均来自当前工作区 API；空值表示尚未采集，不会用静态数字补齐。"
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
        <MetricCard
          label="监控账号"
          value={stats.data?.stats.account_counts?.active ?? 0}
          icon={<UsersRound size={18} />}
        />
        <MetricCard
          label="监控作品"
          value={stats.data?.stats.content_counts?.total ?? 0}
          icon={<Video size={18} />}
        />
        <MetricCard
          label="近 24 小时新增作品"
          value={stats.data?.stats.content_counts?.new_24h ?? 0}
        />
        <MetricCard
          label="近 24 小时新闻"
          value={stats.data?.stats.news_stats?.new_articles_24h ?? 0}
          icon={<Newspaper size={18} />}
        />
        <MetricCard
          label="近 24 小时热点事件"
          value={stats.data?.stats.news_stats?.hot_events ?? 0}
          icon={<Radio size={18} />}
        />
        <MetricCard
          label="同步成功/失败"
          value={`${stats.data?.stats.sync_stats?.successful_24h ?? 0}/${stats.data?.stats.sync_stats?.failed_24h ?? 0}`}
        />
        <MetricCard
          label="近 24 小时规则触发"
          value={stats.data?.stats.automation_stats?.matched_24h ?? 0}
          icon={<Activity size={18} />}
        />
        <MetricCard
          label="通知成功/失败"
          value={`${stats.data?.stats.notification_stats?.delivered_24h ?? 0}/${stats.data?.stats.notification_stats?.failed_24h ?? 0}`}
          icon={<BellRing size={18} />}
        />
      </div>
      <div className="grid gap-5 xl:grid-cols-[1.5fr_1fr]">
        <Panel className="p-5">
          <div>
            <h2 className="font-medium text-white">账号增长趋势</h2>
            <p className="mt-1 text-xs text-slate-500">
              {accounts.data?.items[0]?.display_name ?? "暂无账号"}
            </p>
          </div>
          <TrendChart data={trend} />
        </Panel>
        <Panel>
          <div className="border-b border-slate-800 p-5">
            <h2 className="font-medium text-white">最近任务</h2>
          </div>
          <div className="divide-y divide-slate-800">
            {tasks.data?.items.map((task) => (
              <Link
                href="/tasks"
                className="flex items-center justify-between gap-3 p-4 text-sm hover:bg-slate-900/60"
                key={task.id}
              >
                <div>
                  <p className="text-slate-200">
                    {operationTaskLabel(task.task_type)}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {formatDate(task.started_at)}
                  </p>
                </div>
                <Badge
                  tone={
                    task.status === "success" || task.status === "completed"
                      ? "success"
                      : task.status === "error" || task.status === "failed"
                        ? "danger"
                        : "info"
                  }
                >
                  {OPERATION_STATUS_LABELS[task.status] ?? task.status}
                </Badge>
              </Link>
            ))}
          </div>
          {!tasks.data?.items.length && (
            <StatePanel type="empty" title="暂无任务记录" />
          )}
        </Panel>
      </div>
      <div className="grid min-w-0 gap-5 xl:grid-cols-3">
        <Panel className="min-w-0 p-5">
          <h2 className="font-medium text-white">平台分布</h2>
          <div className="mt-5 space-y-4">
            {platformCounts.map(([name, count]) => (
              <div key={name}>
                <div className="mb-1 flex justify-between text-xs text-slate-400">
                  <span>{name}</span>
                  <span>{count}</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full rounded-full bg-cyan-400"
                    style={{ width: `${(count / largestPlatform) * 100}%` }}
                  />
                </div>
              </div>
            ))}
            {!platformCounts.length && (
              <p className="text-sm text-slate-500">暂无账号分布</p>
            )}
          </div>
          {(accounts.data?.total ?? 0) > 100 && (
            <p className="mt-4 text-xs text-amber-300">
              分布基于增长排序前 100 个账号。
            </p>
          )}
        </Panel>
        <Panel className="min-w-0">
          <div className="border-b border-slate-800 p-5">
            <h2 className="font-medium text-white">热门作品排行</h2>
          </div>
          <div className="divide-y divide-slate-800">
            {contents.data?.items.slice(0, 8).map((item, index) => (
              <Link
                className="flex items-center gap-3 p-4 hover:bg-slate-900/50"
                href={`/contents/${item.id}`}
                key={item.id}
              >
                <span className="w-5 text-sm text-slate-600">{index + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-slate-200">
                    {item.title}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {item.platform.name} · {sourceKindLabel(item.source_kind)}
                  </p>
                </div>
                <span className="text-sm">
                  {formatNumber(item.latest_snapshot?.view_count)}
                </span>
              </Link>
            ))}
          </div>
        </Panel>
        <Panel className="min-w-0">
          <div className="border-b border-slate-800 p-5">
            <h2 className="font-medium text-white">热门新闻排行</h2>
          </div>
          <div className="divide-y divide-slate-800">
            {news.data?.items.slice(0, 8).map((item, index) => (
              <Link
                className="flex items-center gap-3 p-4 hover:bg-slate-900/50"
                href={`/news/${item.id}`}
                key={item.id}
              >
                <span className="w-5 text-sm text-slate-600">{index + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-slate-200">
                    {item.title}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {item.source.name}
                  </p>
                </div>
                <Badge tone="warning">{formatNumber(item.heat_score)}</Badge>
              </Link>
            ))}
          </div>
        </Panel>
      </div>
    </main>
  );
}
