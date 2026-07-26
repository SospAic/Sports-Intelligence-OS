"use client";

import type { NewsSourceRecord } from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Database,
  HeartPulse,
  Newspaper,
  RefreshCw,
  Send,
  Sparkles,
} from "lucide-react";
import { useState } from "react";
import { NotificationChannelsClient } from "@/app/notification-channels/notification-channels-client";
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
import { LLMSettingsPanel } from "./llm-settings-panel";
import { RuntimeSettingsPanel } from "./runtime-settings-panel";

type SourcePage = {
  items: NewsSourceRecord[];
  page: number;
  page_size: number;
  total: number;
};
type SettingsTab = "overview" | "runtime" | "llm" | "notifications" | "sources";

const TABS: Array<{ key: SettingsTab; label: string; icon: typeof Database }> =
  [
    { key: "overview", label: "概览", icon: HeartPulse },
    { key: "runtime", label: "数据库与 Redis", icon: Database },
    { key: "llm", label: "LLM API", icon: Sparkles },
    { key: "notifications", label: "通知 Provider", icon: Send },
    { key: "sources", label: "新闻源", icon: Newspaper },
  ];

export function SettingsClient() {
  const { workspaceId, currentUser, role } = useWorkspace();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<SettingsTab>("overview");
  const health = useQuery({
    queryKey: ["health"],
    queryFn: fetchReadyHealth,
    refetchInterval: 30000,
  });
  const sources = useQuery({
    queryKey: ["news-sources", workspaceId],
    queryFn: () =>
      apiRequest<SourcePage>("/news/sources?page=1&page_size=100", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && (tab === "sources" || tab === "overview"),
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
      await queryClient.invalidateQueries({ queryKey: ["news-sources"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "同步失败", "error");
    }
  }

  return (
    <main className="mx-auto max-w-[1400px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Configuration"
        title="设置"
        description="集中管理部署参数、工作区 LLM、通知渠道与数据源。密钥只在后端加密保存，部署级连接参数需通过环境变量和重启生效。"
      />
      <nav
        aria-label="设置分类"
        className="flex gap-2 overflow-x-auto border-b border-slate-800 pb-3"
      >
        {TABS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              className={`inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm transition ${
                tab === item.key
                  ? "bg-cyan-950 text-cyan-200 ring-1 ring-cyan-800"
                  : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
              }`}
              key={item.key}
              onClick={() => setTab(item.key)}
              type="button"
            >
              <Icon size={14} />
              {item.label}
            </button>
          );
        })}
      </nav>

      {tab === "overview" && (
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
                onRetry={() => health.refetch()}
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
                {Object.entries(health.data?.checks ?? {}).map(
                  ([key, value]) => (
                    <div className="flex justify-between text-sm" key={key}>
                      <span className="text-slate-400">{key}</span>
                      <Badge tone={value === "ok" ? "success" : "danger"}>
                        {value}
                      </Badge>
                    </div>
                  ),
                )}
              </div>
            )}
          </Panel>
          <Panel className="p-5 xl:col-span-2">
            <h2 className="font-medium text-white">配置边界</h2>
            <div className="mt-4 grid gap-4 text-sm md:grid-cols-3">
              <SummaryCard
                title="数据库与 Redis"
                detail="查看脱敏连接拓扑、连接池、超时、重试与任务参数，复制环境变量草稿。"
              />
              <SummaryCard
                title="LLM API"
                detail="工作区级加密配置、默认模型与采样参数、成本、超时、重试和真实连接测试。"
              />
              <SummaryCard
                title="通知 Provider"
                detail="Email、Webhook、Telegram、Discord、飞书、钉钉、企业微信的专属字段与投递记录。"
              />
            </div>
          </Panel>
        </div>
      )}
      {tab === "runtime" && <RuntimeSettingsPanel />}
      {tab === "llm" && <LLMSettingsPanel />}
      {tab === "notifications" && <NotificationChannelsClient embedded />}
      {tab === "sources" && (
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
                    !["owner", "admin", "editor", "analyst"].includes(
                      role ?? "",
                    )
                  }
                  onClick={() => syncSource(source.id)}
                  type="button"
                >
                  <RefreshCw size={13} />
                  同步
                </button>
              </div>
            ))}
          </div>
          {sources.isLoading && (
            <div className="p-5 text-sm text-slate-500">正在加载新闻源…</div>
          )}
          {sources.error && (
            <StatePanel
              type="error"
              title="新闻源加载失败"
              detail={sources.error.message}
              onRetry={() => sources.refetch()}
            />
          )}
          {!sources.isLoading && !sources.data?.items.length && (
            <StatePanel type="empty" title="暂无新闻源" />
          )}
        </Panel>
      )}
    </main>
  );
}

function SummaryCard({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <h3 className="font-medium text-slate-200">{title}</h3>
      <p className="mt-2 text-xs leading-5 text-slate-500">{detail}</p>
    </div>
  );
}
