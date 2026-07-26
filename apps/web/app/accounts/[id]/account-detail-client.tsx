"use client";

import type {
  AccountRecord,
  AccountSnapshotPage,
  AutomationRulePage,
  ContentRecordPage,
  SyncRunPage,
} from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, RefreshCw, Save } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import { TrendChart } from "@/components/trend-chart";
import {
  Badge,
  MetricCard,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { buildAccountDetailPaths } from "@/lib/admin-queries";
import {
  formatDate,
  formatNumber,
  formatPercent,
  sourceKindLabel,
} from "@/lib/format";

const tabs = [
  "概览",
  "作品",
  "数据趋势",
  "同步记录",
  "自动化",
  "设置",
] as const;
export function AccountDetailClient({ id }: { id: string }) {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState<(typeof tabs)[number]>("概览");
  const paths = buildAccountDetailPaths(id);
  const account = useQuery({
    queryKey: ["account", id, workspaceId],
    queryFn: () =>
      apiRequest<AccountRecord>(paths.account, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const snapshots = useQuery({
    queryKey: ["account-snapshots", id],
    queryFn: () =>
      apiRequest<AccountSnapshotPage>(paths.snapshots, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const contents = useQuery({
    queryKey: ["account-contents", id],
    queryFn: () =>
      apiRequest<ContentRecordPage>(paths.contents, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const runs = useQuery({
    queryKey: ["account-runs", id],
    queryFn: () =>
      apiRequest<SyncRunPage>(paths.syncRuns, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const automations = useQuery({
    queryKey: ["account-automations", workspaceId],
    queryFn: () =>
      apiRequest<AutomationRulePage>(paths.automations, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  async function sync() {
    if (!workspaceId) return;
    try {
      await apiRequest(`/accounts/${id}/sync`, {
        method: "POST",
        workspaceId,
        csrf: true,
      });
      notify("同步任务已排队");
      await qc.invalidateQueries({ queryKey: ["account"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "同步失败", "error");
    }
  }
  async function save(form: FormData) {
    if (!workspaceId) return;
    try {
      await apiRequest(`/accounts/${id}`, {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          display_name: form.get("display_name"),
          sync_interval_seconds: Number(form.get("sync_interval_seconds")),
          is_active: form.get("is_active") === "on",
        }),
      });
      notify("账号设置已保存");
      await qc.invalidateQueries({ queryKey: ["account"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "保存失败", "error");
    }
  }
  if (account.isLoading)
    return (
      <main className="p-8">
        <SkeletonRows />
      </main>
    );
  if (account.error || !account.data)
    return (
      <main className="p-8">
        <StatePanel
          type="error"
          title="账号详情加载失败"
          detail={account.error?.message}
          onRetry={() => account.refetch()}
        />
      </main>
    );
  const item = account.data;
  const snapshot = item.latest_snapshot;
  const trend = [...(snapshots.data?.items ?? [])].reverse().map((point) => ({
    name: new Date(point.captured_at).toLocaleDateString("zh-CN", {
      month: "numeric",
      day: "numeric",
    }),
    value: point.follower_count ?? 0,
  }));
  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow={`${item.platform.name} · ${sourceKindLabel(item.source_kind)}`}
        title={item.display_name}
        description={item.description ?? `外部 ID：${item.external_id}`}
        actions={
          <>
            {item.profile_url && (
              <a
                className={secondaryButtonClass}
                href={item.profile_url}
                target="_blank"
                rel="noreferrer"
              >
                平台主页
                <ExternalLink size={15} />
              </a>
            )}
            <button
              className={buttonClass}
              onClick={sync}
              disabled={["queued", "syncing"].includes(item.sync_status)}
            >
              <RefreshCw size={15} />
              立即同步
            </button>
          </>
        }
      />
      {item.source_kind === "mock" && (
        <div className="rounded-xl border border-amber-800 bg-amber-950/30 p-3 text-sm text-amber-200">
          此账号来自 Mock Adapter，仅用于开发与契约测试，不代表真实平台数据。
        </div>
      )}
      <div className="flex gap-1 overflow-x-auto border-b border-slate-800">
        {tabs.map((name) => (
          <button
            key={name}
            onClick={() => setTab(name)}
            className={`whitespace-nowrap border-b-2 px-4 py-3 text-sm ${tab === name ? "border-cyan-400 text-cyan-300" : "border-transparent text-slate-500"}`}
          >
            {name}
          </button>
        ))}
      </div>
      {tab === "概览" && (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="粉丝数"
              value={formatNumber(snapshot?.follower_count)}
              hint={`24h ${formatNumber(item.follower_growth_24h)}`}
            />
            <MetricCard
              label="总播放量"
              value={formatNumber(snapshot?.total_view_count)}
            />
            <MetricCard
              label="作品数"
              value={formatNumber(snapshot?.video_count)}
            />
            <MetricCard
              label="互动率"
              value={formatPercent(snapshot?.engagement_rate)}
            />
          </div>
          <Panel className="p-5">
            <h2 className="font-medium text-white">粉丝趋势</h2>
            <TrendChart data={trend} />
          </Panel>
        </>
      )}
      {tab === "作品" && (
        <Panel>
          <div className="border-b border-slate-800 p-5">
            <h2 className="font-medium text-white">最近作品</h2>
          </div>
          {contents.data?.items.length ? (
            <div className="divide-y divide-slate-800">
              {contents.data.items.map((content) => (
                <Link
                  href={`/contents/${content.id}`}
                  className="flex items-center justify-between gap-4 p-4 hover:bg-slate-900/50"
                  key={content.id}
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm text-slate-200">
                      {content.title}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {formatDate(content.published_at)}
                    </p>
                  </div>
                  <span className="text-sm text-slate-400">
                    {formatNumber(content.latest_snapshot?.view_count)} 播放
                  </span>
                </Link>
              ))}
            </div>
          ) : (
            <StatePanel
              type="empty"
              title="尚无作品"
              detail="运行账号同步后，Adapter 返回的作品会出现在这里。"
            />
          )}
        </Panel>
      )}
      {tab === "数据趋势" && (
        <Panel className="p-5">
          <h2 className="font-medium text-white">
            账号历史快照（{snapshots.data?.total ?? 0}）
          </h2>
          <TrendChart data={trend} />
        </Panel>
      )}
      {tab === "同步记录" && (
        <Panel>
          <div className="divide-y divide-slate-800">
            {runs.data?.items.map((run) => (
              <div
                className="grid gap-2 p-4 text-sm md:grid-cols-4"
                key={run.id}
              >
                <span>{formatDate(run.started_at)}</span>
                <Badge
                  tone={
                    run.status === "success"
                      ? "success"
                      : run.status === "error"
                        ? "danger"
                        : "info"
                  }
                >
                  {run.status}
                </Badge>
                <span>
                  新增 {run.records_created} · 更新 {run.records_updated}
                </span>
                <span className="text-rose-300">{run.error_message}</span>
              </div>
            ))}
          </div>
          {!runs.data?.items.length && (
            <StatePanel type="empty" title="暂无同步记录" />
          )}
        </Panel>
      )}
      {tab === "自动化" && (
        <Panel>
          <div className="divide-y divide-slate-800">
            {automations.data?.items.map((rule) => (
              <Link
                href={`/automations/${rule.id}`}
                className="flex justify-between p-4 hover:bg-slate-900/50"
                key={rule.id}
              >
                <span>{rule.name}</span>
                <Badge tone={rule.enabled ? "success" : "neutral"}>
                  {rule.enabled ? "启用" : "停用"}
                </Badge>
              </Link>
            ))}
          </div>
          {!automations.data?.items.length && (
            <StatePanel
              type="empty"
              title="暂无账号自动化"
              detail="规则适用于同类型实体，具体账号可在条件中限定。"
            />
          )}
        </Panel>
      )}
      {tab === "设置" && (
        <form
          action={save}
          className="max-w-2xl space-y-4 rounded-2xl border border-slate-800 bg-slate-950/70 p-6"
        >
          <label className="grid gap-2 text-sm">
            显示名称
            <input
              name="display_name"
              defaultValue={item.display_name}
              className={inputClass}
              disabled={!["owner", "admin", "editor"].includes(role ?? "")}
            />
          </label>
          <label className="grid gap-2 text-sm">
            同步周期（秒）
            <input
              name="sync_interval_seconds"
              type="number"
              min="300"
              max="604800"
              defaultValue={item.sync_interval_seconds}
              className={inputClass}
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              name="is_active"
              type="checkbox"
              defaultChecked={item.is_active}
            />
            启用监控
          </label>
          <button className={buttonClass}>
            <Save size={15} />
            保存设置
          </button>
        </form>
      )}
    </main>
  );
}
