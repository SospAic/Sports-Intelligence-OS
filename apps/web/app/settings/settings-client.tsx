"use client";
import type {
  LLMProviderDescriptor,
  NewsSourceRecord,
  NotificationProviderDescriptor,
} from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import {
  Badge,
  PageHeader,
  Panel,
  StatePanel,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";
import { fetchReadyHealth } from "@/lib/health";
type SourcePage = {
  items: NewsSourceRecord[];
  page: number;
  page_size: number;
  total: number;
};
export function SettingsClient() {
  const { workspaceId, currentUser, role } = useWorkspace();
  const { notify } = useToast();
  const qc = useQueryClient();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: fetchReadyHealth,
    refetchInterval: 30000,
  });
  const llm = useQuery({
    queryKey: ["llm-providers"],
    queryFn: () =>
      apiRequest<LLMProviderDescriptor[]>("/llm/providers", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const notifications = useQuery({
    queryKey: ["notification-providers"],
    queryFn: () =>
      apiRequest<NotificationProviderDescriptor[]>("/notification-providers", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const sources = useQuery({
    queryKey: ["news-sources", workspaceId],
    queryFn: () =>
      apiRequest<SourcePage>("/news/sources?page=1&page_size=100", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  async function syncSource(id: string) {
    if (!workspaceId) return;
    try {
      await apiRequest(`/news/sources/${id}/sync`, {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({}),
      });
      notify("新闻源同步已排队");
      await qc.invalidateQueries({ queryKey: ["news-sources"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "同步失败", "error");
    }
  }
  return (
    <main className="mx-auto max-w-[1300px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Configuration"
        title="设置"
        description="查看当前工作区、服务健康、模型配置状态和新闻源；API Key 永远不会发送到前端。"
      />
      <div className="grid gap-5 xl:grid-cols-2">
        <Panel className="p-5">
          <h2 className="font-medium text-white">用户与工作区</h2>
          <dl className="mt-4 grid grid-cols-[8rem_1fr] gap-y-3 text-sm">
            <dt className="text-slate-500">用户</dt>
            <dd>{currentUser?.user.email}</dd>
            <dt className="text-slate-500">显示名称</dt>
            <dd>{currentUser?.user.display_name || "—"}</dd>
            <dt className="text-slate-500">工作区</dt>
            <dd>{currentUser?.memberships[0]?.workspace_name}</dd>
            <dt className="text-slate-500">权限</dt>
            <dd>
              <Badge tone="info">{role}</Badge>
            </dd>
            <dt className="text-slate-500">时区</dt>
            <dd>{currentUser?.user.timezone}</dd>
          </dl>
        </Panel>
        <Panel className="p-5">
          <h2 className="font-medium text-white">服务健康</h2>
          {health.error ? (
            <StatePanel
              type="error"
              title="健康检查失败"
              detail={health.error.message}
            />
          ) : (
            <div className="mt-4 space-y-3">
              <div className="flex justify-between">
                <span>API</span>
                <Badge
                  tone={health.data?.status === "ok" ? "success" : "warning"}
                >
                  {health.data?.status ?? "checking"}
                </Badge>
              </div>
              {Object.entries(health.data?.checks ?? {}).map(([key, value]) => (
                <div className="flex justify-between text-sm" key={key}>
                  <span className="text-slate-400">{key}</span>
                  <Badge tone={value === "ok" ? "success" : "danger"}>
                    {value}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </Panel>
        <Panel className="p-5">
          <h2 className="font-medium text-white">LLM Provider</h2>
          <div className="mt-3 divide-y divide-slate-800">
            {llm.data?.map((item) => (
              <div
                className="flex items-center justify-between py-3 text-sm"
                key={item.key}
              >
                <div>
                  <p>{item.name}</p>
                  <p className="mt-1 text-xs text-slate-500">{item.detail}</p>
                </div>
                <Badge tone={item.configured ? "success" : "warning"}>
                  {item.is_mock
                    ? "Mock"
                    : item.configured
                      ? "已配置"
                      : "缺少后端 Key"}
                </Badge>
              </div>
            ))}
          </div>
        </Panel>
        <Panel className="p-5">
          <h2 className="font-medium text-white">通知 Provider</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {notifications.data?.map((item) => (
              <Badge tone={item.is_mock ? "warning" : "neutral"} key={item.key}>
                {item.name}
                {item.is_mock ? " · Mock" : ""}
              </Badge>
            ))}
          </div>
        </Panel>
      </div>
      <Panel>
        <div className="border-b border-slate-800 p-5">
          <h2 className="font-medium text-white">新闻数据源</h2>
          <p className="mt-1 text-xs text-slate-500">
            仅对已启用并获授权的公开源执行同步。
          </p>
        </div>
        <div className="divide-y divide-slate-800">
          {sources.data?.items.map((source) => (
            <div
              className="grid gap-3 p-4 text-sm md:grid-cols-[1.5fr_1fr_1fr_auto] md:items-center"
              key={source.id}
            >
              <div>
                <p className="text-slate-200">{source.name}</p>
                <p className="mt-1 truncate text-xs text-slate-500">
                  {source.url || "手动录入源"}
                </p>
              </div>
              <span>
                {source.provider_key} · 可靠度 {source.reliability_score}
              </span>
              <div>
                <Badge tone={source.enabled ? "success" : "neutral"}>
                  {source.enabled ? "启用" : "停用"}
                </Badge>
                <p className="mt-1 text-xs text-slate-500">
                  {formatDate(source.last_synced_at)}
                </p>
              </div>
              <button
                className={`${secondaryButtonClass} h-8 px-2`}
                disabled={
                  !source.enabled ||
                  !["owner", "admin", "editor", "analyst"].includes(role ?? "")
                }
                onClick={() => syncSource(source.id)}
              >
                <RefreshCw size={13} />
                同步
              </button>
            </div>
          ))}
        </div>
        {!sources.data?.items.length && (
          <StatePanel type="empty" title="暂无新闻源" />
        )}
      </Panel>
    </main>
  );
}
