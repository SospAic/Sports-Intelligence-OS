"use client";

import type {
  AdapterDescriptorRead,
  LLMProviderSettingRecord,
  NewsSourceRecord,
  PlatformRecord,
  ReadinessReportRead,
  RuntimeSettingsRecord,
  YtDlpRuntimeRecord,
} from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  HeartPulse,
  KeyRound,
  Newspaper,
  Pencil,
  Plug,
  Plus,
  RefreshCw,
  Save,
  Send,
  Sparkles,
  Trash2,
  Pause,
  Play,
  Square,
  Database,
  Languages,
  HardDrive,
  ShieldCheck,
  Bell,
} from "lucide-react";
import { type ReactNode, useState } from "react";
import { useSearchParams } from "next/navigation";
import { NotificationChannelsClient } from "@/app/notification-channels/notification-channels-client";
import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import {
  Badge,
  PageHeader,
  Panel,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";
import { fetchReadyHealth } from "@/lib/health";
import { LLMSettingsPanel } from "./llm-settings-panel";
import { RuntimeSettingsPanel } from "./runtime-settings-panel";
import { SyncSettingsPanel } from "./sync-settings-panel";
import { SemanticSearchSettingsPanel } from "./semantic-search-settings-panel";
import { StorageLifecyclePanel } from "./storage-lifecycle-panel";
import { SubscriptionsPanel } from "./subscriptions-panel";
import { AccountAccessPanel } from "./account-access-panel";

type SourcePage = {
  items: NewsSourceRecord[];
  page: number;
  page_size: number;
  total: number;
};
type PlatformCredential = {
  platform_key: string;
  mode: "api" | "public_page" | "authorized_login" | "authorized_session";
  source: "database" | "environment" | "default";
  enabled: boolean;
  configured: boolean;
  configured_fields: string[];
  config_masked: Record<string, unknown>;
  updated_at: string | null;
};
type NotificationHealthSummary = {
  channels: Array<{
    enabled: boolean;
    health_status: string;
    success_rate: number | null;
  }>;
  deliveries: number;
  delivered: number;
  failed: number;
  generated_at: string;
};
type StorageHealthRecord = {
  quota_percent: number | null;
  media_file_count: number;
  tracked_artifact_count: number;
  warnings: string[];
  scan_truncated: boolean;
};
type SemanticSearchStatusRecord = {
  enabled: boolean;
  backend: string;
  model: string;
  embedded_items: number;
  pending_items: number;
  freshness: "fresh" | "stale" | "empty";
  freshness_detail: string;
};
type OverviewCheckState = "ready" | "checking" | "attention" | "blocked" | "error";
type OverviewCheck = {
  key: string;
  title: string;
  state: OverviewCheckState;
  detail: string;
  nextAction: string;
  tab: SettingsTab;
  icon: ReactNode;
};
type SettingsTab =
  | "overview"
  | "llm"
  | "notifications"
  | "sources"
  | "platforms"
  | "sync"
  | "search"
  | "subtitles"
  | "storage"
  | "subscriptions"
  | "access";

const TABS: Array<{
  key: SettingsTab;
  label: string;
  icon: typeof HeartPulse;
}> = [
  { key: "overview", label: "概览", icon: HeartPulse },
  { key: "platforms", label: "平台管理", icon: Plug },
  { key: "sync", label: "同步设置", icon: RefreshCw },
  { key: "subtitles", label: "字幕翻译", icon: Languages },
  { key: "llm", label: "LLM API", icon: Sparkles },
  { key: "search", label: "语义检索", icon: Database },
  { key: "storage", label: "存储治理", icon: HardDrive },
  { key: "subscriptions", label: "订阅告警", icon: Bell },
  { key: "access", label: "账号授权", icon: KeyRound },
  { key: "notifications", label: "通知 Provider", icon: Send },
  { key: "sources", label: "新闻源", icon: Newspaper },
];

export function SettingsClient() {
  const { workspaceId, currentUser, role } = useWorkspace();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const initialTab = (searchParams.get("tab") as SettingsTab) || "overview";
  const [tab, setTab] = useState<SettingsTab>(
    [
      "overview",
      "llm",
      "notifications",
      "sources",
      "platforms",
      "sync",
      "search",
      "subtitles",
      "storage",
      "subscriptions",
      "access",
    ].includes(initialTab)
      ? initialTab
      : "overview",
  );
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
    refetchInterval: 30_000,
  });
  const platforms = useQuery({
    queryKey: ["platforms"],
    queryFn: () => apiRequest<PlatformRecord[]>("/platforms?enabled=true"),
    enabled: Boolean(workspaceId) && tab === "platforms",
  });
  const platformCredentials = useQuery({
    queryKey: ["platform-credentials", workspaceId],
    queryFn: () =>
      apiRequest<PlatformCredential[]>("/settings/platform-credentials", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && tab === "platforms",
  });
  const platformAdapters = useQuery({
    queryKey: ["platform-adapters"],
    queryFn: () =>
      apiRequest<AdapterDescriptorRead[]>("/settings/platform-adapters"),
    enabled: Boolean(workspaceId) && tab === "platforms",
  });
  const readiness = useQuery({
    queryKey: ["platform-readiness", workspaceId],
    queryFn: () =>
      apiRequest<ReadinessReportRead>("/settings/readiness", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && (tab === "platforms" || tab === "overview"),
    refetchInterval: 60_000,
  });
  const overviewRuntime = useQuery<RuntimeSettingsRecord>({
    queryKey: ["runtime-settings", workspaceId],
    queryFn: () =>
      apiRequest<RuntimeSettingsRecord>("/settings/runtime", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && tab === "overview",
  });
  const overviewYtdlp = useQuery<YtDlpRuntimeRecord>({
    queryKey: ["ytdlp-runtime", workspaceId],
    queryFn: () =>
      apiRequest<YtDlpRuntimeRecord>("/downloads/runtime", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && tab === "overview",
  });
  const overviewLlm = useQuery<LLMProviderSettingRecord>({
    queryKey: ["llm-setting", workspaceId],
    queryFn: () =>
      apiRequest<LLMProviderSettingRecord>("/settings/llm/openai-compatible", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && tab === "overview",
  });
  const overviewSemantic = useQuery<SemanticSearchStatusRecord>({
    queryKey: ["semantic-search-status", workspaceId],
    queryFn: () =>
      apiRequest<SemanticSearchStatusRecord>("/semantic-search/status", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && tab === "overview",
    refetchInterval: 15_000,
  });
  const overviewStorage = useQuery<StorageHealthRecord>({
    queryKey: ["storage-health", workspaceId],
    queryFn: () =>
      apiRequest<StorageHealthRecord>("/storage/health", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && tab === "overview",
  });
  const overviewNotifications = useQuery<NotificationHealthSummary>({
    queryKey: ["notification-health", workspaceId],
    queryFn: () =>
      apiRequest<NotificationHealthSummary>("/notification-health", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && tab === "overview",
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

  async function toggleSource(source: NewsSourceRecord) {
    if (!workspaceId) return;
    setSourcePending(true);
    try {
      await apiRequest(
        `/news/sources/${source.id}/${source.enabled ? "disable" : "enable"}`,
        {
          method: "POST",
          workspaceId,
          csrf: true,
          body: JSON.stringify({}),
        },
      );
      notify(source.enabled ? "新闻源已停用" : "新闻源已启用");
      await queryClient.invalidateQueries({ queryKey: ["news-sources"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "状态更新失败", "error");
    } finally {
      setSourcePending(false);
    }
  }

  async function cancelSourceSync(source: NewsSourceRecord) {
    if (!workspaceId || !source.active_sync_run_id) return;
    setSourcePending(true);
    try {
      await apiRequest(
        `/news/sources/${source.id}/sync/${source.active_sync_run_id}/cancel`,
        { method: "POST", workspaceId, csrf: true, body: JSON.stringify({}) },
      );
      notify("同步已停止，历史文章已保留");
      await queryClient.invalidateQueries({ queryKey: ["news-sources"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "停止同步失败", "error");
    } finally {
      setSourcePending(false);
    }
  }

  const canEdit = ["owner", "admin", "editor"].includes(role ?? "");
  const [creatingSource, setCreatingSource] = useState(false);
  const [editingSourceId, setEditingSourceId] = useState<string | null>(null);
  const [editSourceForm, setEditSourceForm] = useState({
    name: "",
    url: "",
    reliability_score: "50",
  });
  const [sourcePending, setSourcePending] = useState(false);

  async function refreshOverview() {
    const results = await Promise.all([
      health.refetch(),
      sources.refetch(),
      readiness.refetch(),
      overviewRuntime.refetch(),
      overviewYtdlp.refetch(),
      overviewLlm.refetch(),
      overviewSemantic.refetch(),
      overviewStorage.refetch(),
      overviewNotifications.refetch(),
    ]);
    if (results.some((result) => result.error)) {
      notify("配置检查完成，但有检查项返回错误", "error");
    } else {
      notify("配置检查已完成", "success");
    }
  }

  const platformItems = readiness.data?.platforms ?? [];
  const readyPlatformCount = platformItems.filter(
    (item) => item.status === "ready",
  ).length;
  const platformAttentionCount = platformItems.filter(
    (item) => item.status !== "ready",
  ).length;
  const configuredLlm = overviewLlm.data;
  const enabledNotificationChannels =
    overviewNotifications.data?.channels.filter((channel) => channel.enabled) ?? [];
  const unhealthyNotificationChannels = enabledNotificationChannels.filter(
    (channel) => channel.health_status !== "healthy",
  ).length;
  const overviewChecks: OverviewCheck[] = [
    {
      key: "services",
      title: "核心服务",
      state: health.isLoading
        ? "checking"
        : health.error
          ? "error"
          : health.data?.status === "ok"
            ? "ready"
            : "attention",
      detail: health.error
        ? health.error.message
        : health.data
          ? `API 已响应；${Object.entries(health.data.checks ?? {})
              .map(([key, value]) => `${key} ${value}`)
              .join("，")}`
          : "正在读取 API、数据库与 Redis 状态。",
      nextAction: health.error ? "检查容器日志与就绪探针" : "核心服务可用",
      tab: "overview",
      icon: <HeartPulse size={17} />,
    },
    {
      key: "platforms",
      title: "平台凭证与采集能力",
      state: readiness.isLoading
        ? "checking"
        : readiness.error
          ? "error"
          : platformItems.length === 0
            ? "blocked"
            : platformAttentionCount === 0
              ? "ready"
              : "attention",
      detail: readiness.error
        ? readiness.error.message
        : readiness.data
          ? `${readyPlatformCount} 个平台已通过就绪检查，${platformAttentionCount} 个平台需要配置、探针或授权。`
          : "正在检查平台适配器、凭证来源和公开/API 能力。",
      nextAction:
        platformAttentionCount > 0 ? "打开平台管理查看下一动作" : "平台采集能力正常",
      tab: "platforms",
      icon: <Plug size={17} />,
    },
    {
      key: "llm",
      title: "LLM Provider",
      state: overviewLlm.isLoading
        ? "checking"
        : overviewLlm.error
          ? "error"
          : configuredLlm?.effective && configuredLlm.health_status === "healthy"
            ? "ready"
            : configuredLlm?.effective
              ? "attention"
              : "blocked",
      detail: overviewLlm.error
        ? overviewLlm.error.message
        : configuredLlm?.effective
          ? `${configuredLlm.name} · ${configuredLlm.effective_scope === "workspace" ? "工作区生效" : "环境回退"} · 默认模型 ${configuredLlm.default_model || "未设置"}`
          : "尚未形成可生效的 LLM 配置；需要 Base URL、模型及对应凭证。",
      nextAction:
        configuredLlm?.health_status === "healthy"
          ? "已通过最近一次连接检查"
          : "进入 LLM API 测试配置并检查模型",
      tab: "llm",
      icon: <Sparkles size={17} />,
    },
    {
      key: "video-runtime",
      title: "视频解析运行时",
      state: overviewYtdlp.isLoading
        ? "checking"
        : overviewYtdlp.error
          ? "error"
          : overviewYtdlp.data?.status === "ready"
            ? "ready"
            : "attention",
      detail: overviewYtdlp.error
        ? overviewYtdlp.error.message
        : overviewYtdlp.data
          ? `${overviewYtdlp.data.detail} · yt-dlp ${overviewYtdlp.data.yt_dlp_version ?? "未发现"}`
          : "正在检查 Node.js、yt-dlp 与 EJS 组件。",
      nextAction:
        overviewYtdlp.data?.status === "ready"
          ? "运行时已就绪"
          : "进入同步设置重新检查运行时",
      tab: "sync",
      icon: <RefreshCw size={17} />,
    },
    {
      key: "runtime-config",
      title: "部署参数与字幕翻译",
      state: overviewRuntime.isLoading
        ? "checking"
        : overviewRuntime.error
          ? "error"
          : overviewRuntime.data
            ? "ready"
            : "blocked",
      detail: overviewRuntime.error
        ? overviewRuntime.error.message
        : overviewRuntime.data
          ? `已读取 ${overviewRuntime.data.sections.length} 组部署参数；修改环境变量后需重启服务。`
          : "尚未读取部署级运行参数。",
      nextAction: "查看同步、字幕与翻译运行参数",
      tab: "subtitles",
      icon: <Languages size={17} />,
    },
    {
      key: "semantic-search",
      title: "语义检索索引",
      state: overviewSemantic.isLoading
        ? "checking"
        : overviewSemantic.error
          ? "error"
          : !overviewSemantic.data?.enabled
            ? "blocked"
            : overviewSemantic.data.freshness === "fresh"
              ? "ready"
              : "attention",
      detail: overviewSemantic.error
        ? overviewSemantic.error.message
        : overviewSemantic.data?.enabled
          ? `${overviewSemantic.data.freshness_detail} · 已索引 ${overviewSemantic.data.embedded_items} 条，待处理 ${overviewSemantic.data.pending_items} 条。`
          : "Embedding 后端或语义检索开关未启用。",
      nextAction: overviewSemantic.data?.enabled
        ? "打开语义检索查看索引与重建"
        : "配置 embedding 后端后启用",
      tab: "search",
      icon: <Database size={17} />,
    },
    {
      key: "notifications",
      title: "通知渠道",
      state: overviewNotifications.isLoading
        ? "checking"
        : overviewNotifications.error
          ? "error"
          : enabledNotificationChannels.length === 0
            ? "blocked"
            : unhealthyNotificationChannels === 0
              ? "ready"
              : "attention",
      detail: overviewNotifications.error
        ? overviewNotifications.error.message
        : overviewNotifications.data
          ? enabledNotificationChannels.length === 0
            ? "尚未启用通知渠道，系统只会保留内部事件。"
            : `${enabledNotificationChannels.length} 个渠道已启用，${unhealthyNotificationChannels} 个渠道需要测试或修复。近 24 小时投递 ${overviewNotifications.data.deliveries} 次。`
          : "正在读取通知渠道健康与投递摘要。",
      nextAction:
        enabledNotificationChannels.length === 0
          ? "配置并测试一个通知渠道"
          : "打开通知 Provider 查看投递记录",
      tab: "notifications",
      icon: <Send size={17} />,
    },
    {
      key: "storage",
      title: "媒体存储",
      state: overviewStorage.isLoading
        ? "checking"
        : overviewStorage.error
          ? "error"
          : overviewStorage.data &&
              (overviewStorage.data.warnings.length > 0 ||
                overviewStorage.data.scan_truncated ||
                (overviewStorage.data.quota_percent ?? 0) >= 90)
            ? "attention"
            : overviewStorage.data
              ? "ready"
              : "blocked",
      detail: overviewStorage.error
        ? overviewStorage.error.message
        : overviewStorage.data
          ? `${overviewStorage.data.media_file_count} 个媒体文件、${overviewStorage.data.tracked_artifact_count} 个已登记资源。${overviewStorage.data.warnings[0] ?? "未发现存储告警。"}`
          : "正在检查媒体目录、资源登记和配额。",
      nextAction: "查看存储治理与生命周期策略",
      tab: "storage",
      icon: <HardDrive size={17} />,
    },
    {
      key: "news-sources",
      title: "新闻源",
      state: sources.isLoading
        ? "checking"
        : sources.error
          ? "error"
          : (sources.data?.items.filter((item) => item.enabled).length ?? 0) > 0
            ? "ready"
            : "attention",
      detail: sources.error
        ? sources.error.message
        : sources.data
          ? `${sources.data.items.filter((item) => item.enabled).length} 个启用源 / ${sources.data.total} 个已登记源。`
          : "正在读取新闻源配置。",
      nextAction: "查看新闻源同步与失败状态",
      tab: "sources",
      icon: <Newspaper size={17} />,
    },
  ];
  const overviewReadyCount = overviewChecks.filter((item) => item.state === "ready").length;
  const overviewAttentionCount = overviewChecks.filter(
    (item) => item.state === "attention" || item.state === "error",
  ).length;
  const overviewBlockedCount = overviewChecks.filter(
    (item) => item.state === "blocked",
  ).length;
  const overviewRefreshing = [
    health,
    sources,
    readiness,
    overviewRuntime,
    overviewYtdlp,
    overviewLlm,
    overviewSemantic,
    overviewStorage,
    overviewNotifications,
  ].some((query) => query.isFetching);

  async function createSource(form: FormData) {
    if (!workspaceId) return;
    setSourcePending(true);
    try {
      await apiRequest("/news/sources", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          name: form.get("name"),
          source_type: form.get("source_type") || "rss",
          url: form.get("url") || null,
          category: form.get("category") || "general",
          language: form.get("language") || null,
          country: (form.get("country") as string)?.toUpperCase() || null,
          reliability_score: Number(form.get("reliability_score") || 50),
          enabled: true,
        }),
      });
      notify("新闻源已添加");
      setCreatingSource(false);
      await queryClient.invalidateQueries({ queryKey: ["news-sources"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "添加失败", "error");
    } finally {
      setSourcePending(false);
    }
  }

  async function updateSource(id: string) {
    if (!workspaceId) return;
    setSourcePending(true);
    try {
      const body: Record<string, unknown> = {};
      if (editSourceForm.name.trim()) body.name = editSourceForm.name.trim();
      if (editSourceForm.url.trim()) body.url = editSourceForm.url.trim();
      body.reliability_score = Number(editSourceForm.reliability_score);
      await apiRequest(`/news/sources/${id}`, {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify(body),
      });
      notify("新闻源已更新");
      setEditingSourceId(null);
      await queryClient.invalidateQueries({ queryKey: ["news-sources"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "更新失败", "error");
    } finally {
      setSourcePending(false);
    }
  }

  async function deleteSource(id: string) {
    if (!workspaceId) return;
    if (!window.confirm("确定删除该新闻源？")) return;
    try {
      await apiRequest<void>(`/news/sources/${id}`, {
        method: "DELETE",
        workspaceId,
        csrf: true,
      });
      notify("新闻源已删除");
      await queryClient.invalidateQueries({ queryKey: ["news-sources"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "删除失败", "error");
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
        {TABS.filter((item) => item.key !== "access" || ["owner", "admin"].includes(role ?? "")).map((item) => {
          const Icon = item.icon;
          return (
            <button
              className={`inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm transition ${
                tab === item.key
                  ? "bg-cyan-900 text-cyan-100 ring-1 ring-cyan-700"
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
        <div className="space-y-5">
          <div className="grid gap-5 xl:grid-cols-[1.35fr_0.65fr]">
            <Panel className="p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <ShieldCheck size={19} className="text-cyan-300" />
                    <h2 className="font-medium text-white">配置检查</h2>
                    <Badge tone="info">实时诊断</Badge>
                  </div>
                  <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
                    集中检查服务、平台凭证、模型、解析运行时、索引、通知、存储和新闻源。配置已填写不等于真实可用；每项都显示当前证据和下一步。
                  </p>
                </div>
                <button
                  className={secondaryButtonClass}
                  disabled={overviewRefreshing}
                  onClick={() => void refreshOverview()}
                  type="button"
                >
                  <RefreshCw
                    size={14}
                    className={overviewRefreshing ? "animate-spin" : ""}
                  />
                  {overviewRefreshing ? "检查中…" : "重新检查全部"}
                </button>
              </div>
              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                <OverviewMetric label="已就绪" value={overviewReadyCount} tone="success" />
                <OverviewMetric label="需要关注" value={overviewAttentionCount} tone="warning" />
                <OverviewMetric label="未启用/受限" value={overviewBlockedCount} tone="danger" />
              </div>
            </Panel>
            <Panel className="p-5">
              <h2 className="font-medium text-white">用户与工作区</h2>
              <dl className="mt-4 grid grid-cols-[6rem_1fr] gap-y-3 text-sm">
                <dt className="text-slate-500">用户</dt>
                <dd>{currentUser?.user.email}</dd>
                <dt className="text-slate-500">工作区</dt>
                <dd>{currentUser?.memberships[0]?.workspace_name}</dd>
                <dt className="text-slate-500">权限</dt>
                <dd><Badge tone="info">{role}</Badge></dd>
                <dt className="text-slate-500">时区</dt>
                <dd>{currentUser?.user.timezone}</dd>
              </dl>
            </Panel>
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {overviewChecks.map((item) => (
              <ConfigurationCheckCard
                key={item.key}
                check={item}
                onOpen={() => setTab(item.tab)}
              />
            ))}
          </div>

          <Panel className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-medium text-white">服务健康明细</h2>
                <p className="mt-1 text-xs text-slate-500">
                  这里显示基础设施探针；业务配置检查见上方卡片，不再把“接口能访问”当成“功能已可用”。
                </p>
              </div>
              {health.data?.version && (
                <span className="text-xs text-slate-600">
                  API {health.data.version}
                </span>
              )}
            </div>
            {health.error ? (
              <StatePanel
                type="error"
                title="健康检查失败"
                detail={health.error.message}
                onRetry={() => health.refetch()}
              />
            ) : (
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <ServiceHealthRow label="API" value={health.data?.status ?? "checking"} />
                {Object.entries(health.data?.checks ?? {}).map(([key, value]) => (
                  <ServiceHealthRow key={key} label={key} value={value} />
                ))}
              </div>
            )}
          </Panel>
        </div>
      )}
      {tab === "llm" && <LLMSettingsPanel />}
      {tab === "notifications" && <NotificationChannelsClient embedded />}
      {tab === "sources" && (
        <Panel>
          <div className="flex items-center justify-between border-b border-slate-800 p-5">
            <div>
              <h2 className="font-medium text-white">新闻数据源</h2>
              <p className="mt-1 text-xs text-slate-500">
                管理 RSS、Atom、JSON Feed 或手动录入的新闻源。
              </p>
            </div>
            {canEdit && (
              <button
                className={buttonClass}
                onClick={() => setCreatingSource((v) => !v)}
              >
                <Plus size={16} />
                添加新闻源
              </button>
            )}
          </div>
          {creatingSource && (
            <form
              action={createSource}
              className="m-4 grid gap-3 rounded-xl border border-cyan-900/70 bg-cyan-950/10 p-4 md:grid-cols-2 xl:grid-cols-3"
            >
              <input
                name="name"
                required
                className={inputClass}
                placeholder="源名称"
              />
              <select
                name="source_type"
                className={inputClass}
                defaultValue="rss"
              >
                <option value="rss">RSS</option>
                <option value="atom">Atom</option>
                <option value="json">JSON Feed</option>
                <option value="web">公开网页（浏览器采集）</option>
                <option value="manual">手动录入</option>
              </select>
              <input
                name="url"
                type="url"
                className={inputClass}
                placeholder="Feed URL（手动源可留空）"
              />
              <input
                name="category"
                className={inputClass}
                placeholder="分类（如 basketball）"
                defaultValue="general"
              />
              <input
                name="language"
                className={inputClass}
                placeholder="语言（如 en）"
              />
              <input
                name="country"
                className={inputClass}
                placeholder="国家代码（如 US）"
                maxLength={2}
              />
              <input
                name="reliability_score"
                type="number"
                min="0"
                max="100"
                defaultValue="50"
                className={inputClass}
                placeholder="可靠度 0-100"
              />
              <div className="flex gap-2 md:col-span-2 xl:col-span-3">
                <button disabled={sourcePending} className={buttonClass}>
                  {sourcePending ? "保存中…" : "保存新闻源"}
                </button>
                <button
                  type="button"
                  className={secondaryButtonClass}
                  onClick={() => setCreatingSource(false)}
                >
                  取消
                </button>
              </div>
            </form>
          )}
          <div className="divide-y divide-slate-800">
            {sources.data?.items.map((source) => (
              <div key={source.id}>
                {editingSourceId === source.id ? (
                  <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-4">
                    <input
                      className={inputClass}
                      value={editSourceForm.name}
                      onChange={(e) =>
                        setEditSourceForm({
                          ...editSourceForm,
                          name: e.target.value,
                        })
                      }
                      placeholder="名称"
                    />
                    <input
                      className={inputClass}
                      value={editSourceForm.url}
                      onChange={(e) =>
                        setEditSourceForm({
                          ...editSourceForm,
                          url: e.target.value,
                        })
                      }
                      placeholder="URL"
                    />
                    <input
                      className={inputClass}
                      type="number"
                      min="0"
                      max="100"
                      value={editSourceForm.reliability_score}
                      onChange={(e) =>
                        setEditSourceForm({
                          ...editSourceForm,
                          reliability_score: e.target.value,
                        })
                      }
                      placeholder="可靠度"
                    />
                    <div className="flex items-center gap-3">
                      <button
                        className="text-cyan-300 disabled:text-slate-600 text-sm"
                        disabled={sourcePending}
                        onClick={() => updateSource(source.id)}
                      >
                        保存
                      </button>
                      <button
                        className="text-slate-500 text-sm"
                        onClick={() => setEditingSourceId(null)}
                      >
                        取消
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="grid gap-3 p-4 text-sm md:grid-cols-[1.5fr_1fr_1fr_auto] md:items-center">
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
                      <Badge
                        tone={
                          !source.enabled
                            ? "neutral"
                            : source.last_error_code
                              ? "danger"
                              : source.last_synced_at
                                ? "success"
                                : "warning"
                        }
                      >
                        {!source.enabled
                          ? "停用"
                          : source.last_error_code
                            ? `异常 · ${Math.max(1, source.consecutive_failures)} 次`
                            : source.last_synced_at
                              ? "正常"
                              : "待首次同步"}
                      </Badge>
                      <p className="mt-1 text-xs text-slate-500">
                        最近尝试 {formatDate(source.last_attempt_at)}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        最近成功 {formatDate(source.last_synced_at)}
                      </p>
                      {source.next_sync_at && (
                        <p className="mt-1 text-xs text-slate-600">
                          下次尝试 {formatDate(source.next_sync_at)}
                        </p>
                      )}
                      {source.last_error_message && (
                        <p
                          className="mt-1 max-w-72 truncate text-xs text-rose-400"
                          title={source.last_error_message}
                        >
                          {source.last_error_code
                            ? `[${source.last_error_code}] `
                            : ""}
                          {source.last_error_message}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        className={`${secondaryButtonClass} h-8 px-2`}
                        disabled={
                          sourcePending ||
                          (!source.active_sync_run_id && !source.enabled) ||
                          !["owner", "admin", "editor", "analyst"].includes(
                            role ?? "",
                          )
                        }
                        onClick={() =>
                          source.active_sync_run_id
                            ? cancelSourceSync(source)
                            : syncSource(source.id)
                        }
                        type="button"
                      >
                        {source.active_sync_run_id ? (
                          <Square size={13} />
                        ) : (
                          <RefreshCw size={13} />
                        )}
                        {source.active_sync_run_id ? "停止" : "同步"}
                      </button>
                      {canEdit && (
                        <>
                          <button
                            className={`inline-flex items-center gap-1 text-xs ${source.enabled ? "text-amber-300 hover:text-amber-200" : "text-emerald-300 hover:text-emerald-200"}`}
                            disabled={sourcePending}
                            onClick={() => toggleSource(source)}
                            type="button"
                          >
                            {source.enabled ? (
                              <Pause size={13} />
                            ) : (
                              <Play size={13} />
                            )}
                            {source.enabled ? "停用" : "启用"}
                          </button>
                          <button
                            className="inline-flex items-center gap-1 text-cyan-300 hover:text-cyan-200 text-xs"
                            onClick={() => {
                              setEditingSourceId(source.id);
                              setEditSourceForm({
                                name: source.name,
                                url: source.url ?? "",
                                reliability_score: String(
                                  source.reliability_score,
                                ),
                              });
                            }}
                          >
                            <Pencil size={13} />
                            编辑
                          </button>
                          {["owner", "admin"].includes(role ?? "") && (
                            <button
                              className="inline-flex items-center gap-1 text-red-400 hover:text-red-300 text-xs"
                              onClick={() => deleteSource(source.id)}
                            >
                              <Trash2 size={13} />
                              删除
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                )}
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
      {tab === "platforms" && (
        <div className="space-y-5">
          <Panel className="p-5">
            <h2 className="font-medium text-white">平台数据获取策略</h2>
            <p className="mt-1 text-xs text-slate-500">
              官方 API
              优先；公开页只有在逐项确认许可、robots、字段必要性、采样频率和来源审计后才能启用。
            </p>
          </Panel>
          {readiness.isLoading && (
            <Panel className="p-5 text-sm text-slate-500">
              正在生成能力就绪度诊断…
            </Panel>
          )}
          {readiness.error && (
            <StatePanel
              type="error"
              title="能力就绪度诊断加载失败"
              detail={readiness.error.message}
              onRetry={() => readiness.refetch()}
            />
          )}
          {readiness.data && (
            <ReadinessPanel
              report={readiness.data}
              workspaceId={workspaceId!}
              canProbe={["owner", "admin"].includes(role ?? "")}
              onProbed={() =>
                queryClient.invalidateQueries({
                  queryKey: ["platform-readiness", workspaceId],
                })
              }
            />
          )}
          {platforms.isLoading && (
            <Panel className="p-5 text-sm text-slate-500">正在加载平台…</Panel>
          )}
          <div className="grid gap-5 md:grid-cols-2">
            {platforms.data?.map((platform) => (
              <SecurePlatformCredentialCard
                key={`${platform.id}:${platformCredentials.data?.find((item) => item.platform_key === platform.key)?.updated_at ?? "default"}`}
                platform={platform}
                setting={platformCredentials.data?.find(
                  (item) => item.platform_key === platform.key,
                )}
                workspaceId={workspaceId!}
                canEdit={canEdit}
                onSaved={() => {
                  queryClient.invalidateQueries({
                    queryKey: ["platform-credentials"],
                  });
                  queryClient.invalidateQueries({
                    queryKey: ["platform-readiness", workspaceId],
                  });
                  queryClient.invalidateQueries({ queryKey: ["accounts"] });
                }}
              />
            ))}
          </div>
          {platformAdapters.isLoading && (
            <Panel className="p-5 text-sm text-slate-500">
              正在加载适配器能力…
            </Panel>
          )}
          {platformAdapters.data && platformAdapters.data.length > 0 && (
            <PlatformAdapterMatrix
              adapters={platformAdapters.data}
              activeKeys={
                new Set(
                  (platforms.data ?? []).map(
                    (platform) => platform.adapter_key,
                  ),
                )
              }
            />
          )}
        </div>
      )}
      {tab === "sync" && (
        <>
          <SyncSettingsPanel />
          <RuntimeSettingsPanel sectionKeys={["media_runtime"]} />
        </>
      )}
      {tab === "subtitles" && (
        <RuntimeSettingsPanel sectionKeys={["subtitle_runtime"]} />
      )}
      {tab === "search" && <SemanticSearchSettingsPanel />}
      {tab === "storage" && workspaceId && (
        <StorageLifecyclePanel workspaceId={workspaceId} role={role} />
      )}
      {tab === "subscriptions" && <SubscriptionsPanel />}
      {tab === "access" && workspaceId && ["owner", "admin"].includes(role ?? "") && (
        <AccountAccessPanel workspaceId={workspaceId} />
      )}
    </main>
  );
}

const CAPABILITY_LABELS: Record<string, string> = {
  PUBLIC_PROFILE: "公开资料",
  ACCOUNT_ANALYTICS: "账号分析",
  CONTENT_LIST: "内容列表",
  CONTENT_ANALYTICS: "内容分析",
  TRAFFIC_SOURCES: "流量来源",
  RETENTION: "留存",
  REVENUE: "收益",
  COMMENTS: "评论",
  SEARCH_TERMS: "搜索词",
};

const READINESS_STATUS_LABELS: Record<
  ReadinessReportRead["platforms"][number]["status"],
  string
> = {
  ready: "已就绪",
  unverified: "已配置·待探针",
  degraded: "部分可用",
  needs_setup: "待配置",
  blocked: "当前受限",
};

function readinessTone(
  status: ReadinessReportRead["platforms"][number]["status"],
): "success" | "warning" | "danger" | "info" {
  if (status === "ready") return "success";
  if (status === "unverified") return "info";
  if (status === "degraded") return "warning";
  if (status === "needs_setup") return "warning";
  return "danger";
}

function ReadinessPanel({
  report,
  workspaceId,
  canProbe,
  onProbed,
}: {
  report: ReadinessReportRead;
  workspaceId: string;
  canProbe: boolean;
  onProbed: () => void;
}) {
  const { notify } = useToast();
  const [probing, setProbing] = useState<string | null>(null);

  async function probe(platformKey: string) {
    setProbing(platformKey);
    try {
      const result = await apiRequest<{ status: string; detail: string }>(
        `/settings/readiness/${platformKey}/probe`,
        { method: "POST", workspaceId, csrf: true, body: JSON.stringify({}) },
      );
      notify(
        result.status === "passed"
          ? "平台探针通过"
          : `平台探针结果：${result.status}`,
        result.status === "passed" ? "success" : "error",
      );
      onProbed();
    } catch (error) {
      notify(error instanceof Error ? error.message : "平台探针失败", "error");
    } finally {
      setProbing(null);
    }
  }

  return (
    <Panel className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-medium text-white">能力就绪度诊断</h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-500">
            “已配置”不等于“实时验证成功”。这里把适配器、凭证、数据来源和产品能力拆开显示，避免把公开指标、私有 Analytics 和发布权限混为一谈。
          </p>
        </div>
        <span className="text-xs text-slate-600">
          生成于 {formatDate(report.generated_at)}
        </span>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        {report.platforms.map((item) => (
          <div
            key={item.key}
            className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="font-medium text-slate-200">{item.platform_name}</h3>
                <p className="mt-1 text-xs text-slate-600">
                  {item.adapter_key} · {item.credential_source === "environment" ? "环境凭证" : item.credential_source === "database" ? "工作区凭证" : "未配置"}
                </p>
              </div>
              <Badge tone={readinessTone(item.status)}>
                {READINESS_STATUS_LABELS[item.status]}
              </Badge>
            </div>
            <p className="mt-3 text-xs leading-5 text-slate-400">{item.detail}</p>
            {item.last_probe && (
              <div className="mt-3 rounded-lg border border-slate-800/80 bg-slate-900/40 p-3 text-xs leading-5">
                <div className="flex flex-wrap items-center justify-between gap-2 text-slate-500">
                  <span>
                    最近{item.last_probe.trigger === "scheduled" ? "自动" : "手动"}探针 · {formatDate(item.last_probe.checked_at)}
                  </span>
                  <span className={item.last_probe.status === "passed" ? "text-emerald-300" : "text-amber-300"}>
                    {item.last_probe.status}
                  </span>
                </div>
                <p className="mt-1 text-slate-400">{item.last_probe.detail}</p>
                {item.last_probe.error_code && (
                  <p className="mt-1 text-rose-300">错误码：{item.last_probe.error_code}</p>
                )}
              </div>
            )}
            {item.conditions.length > 0 && (
              <ul className="mt-3 space-y-1 text-xs leading-5 text-slate-500">
                {item.conditions.slice(0, 3).map((condition) => (
                  <li key={condition}>· {condition}</li>
                ))}
              </ul>
            )}
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-cyan-300">下一步：{item.next_action}</p>
              {canProbe && (
                <button
                  type="button"
                  className={secondaryButtonClass}
                  disabled={probing === item.platform_key}
                  onClick={() => probe(item.platform_key)}
                >
                  {probing === item.platform_key ? "探针执行中…" : "运行探针"}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-5 border-t border-slate-800 pt-4">
        <h3 className="text-sm font-medium text-slate-200">跨平台能力边界</h3>
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          {report.features.map((item) => (
            <div
              key={item.key}
              className="rounded-xl border border-slate-800/80 bg-slate-900/30 p-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-sm text-slate-300">{item.title}</h4>
                <Badge tone={readinessTone(item.status)}>
                  {READINESS_STATUS_LABELS[item.status]}
                </Badge>
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-500">{item.detail}</p>
              {item.conditions.length > 0 && (
                <p className="mt-2 text-xs leading-5 text-slate-600">
                  条件：{item.conditions.join("；")}
                </p>
              )}
              <p className="mt-2 text-xs text-cyan-300">下一步：{item.next_action}</p>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  );
}

function sourceKindLabel(kind: string): string {
  if (kind === "live") return "实时";
  if (kind === "imported") return "导入";
  return kind;
}

function PlatformAdapterMatrix({
  adapters,
  activeKeys,
}: {
  adapters: AdapterDescriptorRead[];
  activeKeys: Set<string>;
}) {
  return (
    <Panel className="p-5">
      <h2 className="font-medium text-white">适配器能力矩阵</h2>
      <p className="mt-1 text-xs text-slate-500">
        各平台的数据采集能力由适配器声明，能力差异集中在适配器而非业务逻辑中。
      </p>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {adapters.map((adapter) => (
          <div
            key={adapter.key}
            className="rounded-xl border border-slate-800 bg-slate-900/40 p-4"
          >
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-medium text-slate-200">{adapter.name}</h3>
              <Badge
                tone={
                  adapter.implementation_status === "implemented"
                    ? "success"
                    : "neutral"
                }
              >
                {adapter.implementation_status === "implemented"
                  ? "已实现"
                  : "骨架"}
              </Badge>
              {activeKeys.has(adapter.key) && (
                <Badge tone="info">已接入平台</Badge>
              )}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              数据来源：
              {adapter.source_kinds.map(sourceKindLabel).join("、") || "—"}
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {Object.entries(adapter.capabilities).map(([cap, supported]) => (
                <span
                  key={cap}
                  title={supported ? "支持" : "不支持"}
                  className={
                    "rounded-md px-2 py-0.5 text-xs " +
                    (supported
                      ? "bg-cyan-500/15 text-cyan-300"
                      : "bg-slate-800 text-slate-600 line-through")
                  }
                >
                  {CAPABILITY_LABELS[cap] ?? cap}
                </span>
              ))}
            </div>
            {adapter.config_fields.length > 0 && (
              <div className="mt-3 text-xs text-slate-500">
                所需配置：
                {adapter.config_fields.map((field) => field.label).join("、")}
              </div>
            )}
          </div>
        ))}
      </div>
    </Panel>
  );
}

const OVERVIEW_STATE_LABELS: Record<OverviewCheckState, string> = {
  ready: "已就绪",
  checking: "检查中",
  attention: "需要关注",
  blocked: "未启用 / 受限",
  error: "检查失败",
};

function overviewTone(
  state: OverviewCheckState,
): "success" | "warning" | "danger" | "info" {
  if (state === "ready") return "success";
  if (state === "checking") return "info";
  if (state === "blocked") return "danger";
  return "warning";
}

function ConfigurationCheckCard({
  check,
  onOpen,
}: {
  check: OverviewCheck;
  onOpen: () => void;
}) {
  return (
    <div className="flex min-h-[194px] flex-col rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 text-slate-200">
          <span className="text-cyan-300">{check.icon}</span>
          <h3 className="font-medium">{check.title}</h3>
        </div>
        <Badge tone={overviewTone(check.state)}>
          {OVERVIEW_STATE_LABELS[check.state]}
        </Badge>
      </div>
      <p className="mt-3 flex-1 text-xs leading-5 text-slate-400">
        {check.detail}
      </p>
      <div className="mt-4 flex items-center justify-between gap-3 border-t border-slate-800/80 pt-3">
        <span className="text-xs text-cyan-300">{check.nextAction}</span>
        <button
          type="button"
          className="shrink-0 text-xs text-slate-400 transition hover:text-white"
          onClick={onOpen}
        >
          查看详情 →
        </button>
      </div>
    </div>
  );
}

function OverviewMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "success" | "warning" | "danger";
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-slate-500">{label}</span>
        <Badge tone={tone}>{value}</Badge>
      </div>
    </div>
  );
}

function ServiceHealthRow({ label, value }: { label: string; value: string }) {
  const ok = value === "ok";
  return (
    <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm">
      <span className="text-slate-400">{label}</span>
      <Badge tone={ok ? "success" : value === "checking" ? "info" : "danger"}>
        {value}
      </Badge>
    </div>
  );
}

const PLATFORM_API_FIELDS: Record<
  string,
  Array<{
    key: string;
    label: string;
    secret: boolean;
    required: boolean;
    placeholder: string;
  }>
> = {
  youtube: [
    {
      key: "api_key",
      label: "YouTube Data API Key",
      secret: true,
      required: true,
      placeholder: "Google Cloud API Key",
    },
  ],
  tiktok: [
    {
      key: "client_key",
      label: "Client Key",
      secret: false,
      required: true,
      placeholder: "TikTok 应用 Client Key",
    },
    {
      key: "client_secret",
      label: "Client Secret",
      secret: true,
      required: true,
      placeholder: "TikTok 应用 Client Secret",
    },
    {
      key: "access_token",
      label: "Access Token",
      secret: true,
      required: true,
      placeholder: "OAuth Access Token",
    },
    {
      key: "refresh_token",
      label: "Refresh Token",
      secret: true,
      required: false,
      placeholder: "用于自动续期（可选）",
    },
  ],
  douyin: [
    {
      key: "client_key",
      label: "Client Key",
      secret: false,
      required: true,
      placeholder: "抖音开放平台 Client Key",
    },
    {
      key: "client_secret",
      label: "Client Secret",
      secret: true,
      required: true,
      placeholder: "抖音开放平台 Client Secret",
    },
    {
      key: "access_token",
      label: "Access Token",
      secret: true,
      required: true,
      placeholder: "OAuth Access Token",
    },
    {
      key: "refresh_token",
      label: "Refresh Token",
      secret: true,
      required: false,
      placeholder: "用于自动续期（可选）",
    },
  ],
};

const PLATFORM_LOGIN_FIELDS = [
  {
    key: "username",
    label: "登录账号 / 手机号 / 邮箱",
    secret: true,
    required: true,
    placeholder: "仅发送到后端加密保存",
  },
  {
    key: "password",
    label: "登录密码",
    secret: true,
    required: true,
    placeholder: "仅发送到后端加密保存",
  },
];

const DEFAULT_SESSION_EXPIRY = (() => {
  const d = new Date();
  d.setDate(d.getDate() + 30);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
})();

function SecurePlatformCredentialCard({
  platform,
  setting,
  workspaceId,
  canEdit,
  onSaved,
}: {
  platform: PlatformRecord;
  setting?: PlatformCredential;
  workspaceId: string;
  canEdit: boolean;
  onSaved: () => void;
}) {
  const { notify } = useToast();
  const [saving, setSaving] = useState(false);
  const apiAvailable = Boolean(PLATFORM_API_FIELDS[platform.key]);
  const [mode, setMode] = useState<
    "api" | "public_page" | "authorized_login" | "authorized_session"
  >(
    setting?.mode === "api" && !apiAvailable
      ? "public_page"
      : (setting?.mode ?? "public_page"),
  );
  const fields =
    mode === "api"
      ? (PLATFORM_API_FIELDS[platform.key] ?? [])
      : mode === "authorized_login"
        ? PLATFORM_LOGIN_FIELDS
        : [];

  async function saveCredentials(form: FormData) {
    setSaving(true);
    const config: Record<string, string> = {};
    for (const field of fields) {
      const value = String(form.get(field.key) ?? "").trim();
      if (value) config[field.key] = value;
    }
    if (mode === "public_page") {
      for (const key of [
        "terms_permission_confirmed",
        "robots_reviewed",
        "fields_minimized",
        "source_audit_enabled",
      ]) {
        config[key] = form.get(key) === "on" ? "true" : "false";
      }
      config.sample_interval_seconds = String(
        Math.max(300, Number(form.get("sample_interval_seconds") ?? 300)),
      );
    }
    if (mode === "authorized_login") {
      for (const key of [
        "account_authorization_confirmed",
        "platform_login_allowed",
        "oauth_unavailable_or_insufficient",
      ]) {
        config[key] = form.get(key) === "on" ? "true" : "false";
      }
    }
    if (mode === "authorized_session") {
      for (const key of [
        "storage_state_json",
        "cookies_netscape",
        "session_label",
        "session_expires_at",
        "cdp_endpoint",
      ]) {
        const value = String(form.get(key) ?? "").trim();
        if (value)
          config[key] =
            key === "session_expires_at"
              ? new Date(value).toISOString()
              : value;
      }
      for (const key of [
        "account_authorization_confirmed",
        "platform_session_allowed",
        "oauth_unavailable_or_insufficient",
      ]) {
        config[key] = form.get(key) === "on" ? "true" : "false";
      }
    }
    try {
      await apiRequest(`/settings/platform-credentials/${platform.key}`, {
        method: "PUT",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ mode, config, clear_fields: [], enabled: true }),
      });
      notify(`${platform.name} 数据获取设置已保存`);
      onSaved();
    } catch (error) {
      notify(
        error instanceof Error ? error.message : "平台设置保存失败",
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  async function openManualLogin(form: HTMLFormElement | null) {
    if (!form) return;
    const cdpEndpoint =
      String(new FormData(form).get("cdp_endpoint") ?? "").trim() ||
      "http://browser:9222";
    if (!cdpEndpoint) {
      notify("请先填写本地浏览器 CDP 地址", "error");
      return;
    }
    const browserWindow = window.open("about:blank", "sio-docker-browser");
    if (browserWindow) browserWindow.opener = null;
    setSaving(true);
    try {
      const response = await apiRequest<{
        detail: string;
        browser_view_url?: string | null;
      }>(
        `/settings/platform-credentials/${platform.key}/session-capture/open`,
        {
          method: "POST",
          workspaceId,
          csrf: true,
          body: JSON.stringify({ cdp_endpoint: cdpEndpoint }),
        },
      );
      if (response.browser_view_url && browserWindow) {
        browserWindow.location.href = response.browser_view_url;
      } else if (browserWindow) {
        browserWindow.close();
      }
      notify(response.detail);
    } catch (error) {
      browserWindow?.close();
      notify(error instanceof Error ? error.message : "打开人工登录页失败", "error");
    } finally {
      setSaving(false);
    }
  }

  async function captureManualLogin(form: HTMLFormElement | null) {
    if (!form) return;
    const data = new FormData(form);
    const cdpEndpoint =
      String(data.get("cdp_endpoint") ?? "").trim() || "http://browser:9222";
    if (!cdpEndpoint) {
      notify("请先填写本地浏览器 CDP 地址", "error");
      return;
    }
    const confirmations = {
      account_authorization_confirmed:
        data.get("account_authorization_confirmed") === "on",
      platform_session_allowed: data.get("platform_session_allowed") === "on",
      oauth_unavailable_or_insufficient:
        data.get("oauth_unavailable_or_insufficient") === "on",
    };
    if (!Object.values(confirmations).every(Boolean)) {
      notify("请完成授权、平台许可和 API 条件确认后再保存", "error");
      return;
    }
    setSaving(true);
    try {
      await apiRequest(
        `/settings/platform-credentials/${platform.key}/session-capture/save`,
        {
          method: "POST",
          workspaceId,
          csrf: true,
          body: JSON.stringify({ cdp_endpoint: cdpEndpoint, ...confirmations }),
        },
      );
      notify(`${platform.name} 已从人工登录浏览器中加密保存 Cookie 和会话`);
      onSaved();
    } catch (error) {
      notify(error instanceof Error ? error.message : "保存浏览器登录会话失败", "error");
    } finally {
      setSaving(false);
    }
  }

  async function revokeLoginAccess() {
    if (!window.confirm(`确定清除 ${platform.name} 的加密登录凭据和会话状态？`))
      return;
    setSaving(true);
    try {
      await apiRequest(
        `/settings/platform-credentials/${platform.key}/revoke-login`,
        { method: "POST", workspaceId, csrf: true, body: JSON.stringify({}) },
      );
      notify(`${platform.name} 登录授权已撤销`);
      onSaved();
    } catch (error) {
      notify(
        error instanceof Error ? error.message : "撤销登录授权失败",
        "error",
      );
    } finally {
      setSaving(false);
    }
  }

  const hasLoginAccess = Boolean(
    setting?.configured_fields.some((field) =>
      ["username", "password", "storage_state_json", "cookies_netscape"].includes(field),
    ),
  );

  // 会话过期时间默认 +30 天（仅在从未保存过有效期时给出），避免误选成临近此刻导致保存后立刻失效。
  const defaultSessionExpiry = setting?.config_masked?.session_expires_at
    ? undefined
    : DEFAULT_SESSION_EXPIRY;

  return (
    <Panel className="p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <KeyRound size={16} className="text-cyan-400" />
          <h3 className="font-medium text-cyan-400">{platform.name}</h3>
        </div>
        <Badge tone={setting?.configured ? "success" : "warning"}>
          {setting?.configured ? "已配置" : "待配置"}
        </Badge>
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-500">
        设置作用于当前工作区的全部账号。密钥只发送至后端加密保存，页面仅显示已配置字段。
      </p>
      <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <button
          type="button"
          disabled={!canEdit || !apiAvailable}
          onClick={() => setMode("api")}
          className={`rounded-lg border px-3 py-2 text-xs font-medium transition ${
            mode === "api"
              ? "border-cyan-700 bg-cyan-950/60 text-cyan-200"
              : "border-slate-700 bg-slate-900/40 text-slate-400"
          }`}
        >
          {apiAvailable ? "官方 API / 获准接口" : "暂无官方 API Provider"}
        </button>
        <button
          type="button"
          disabled={!canEdit}
          onClick={() => setMode("public_page")}
          className={`rounded-lg border px-3 py-2 text-xs font-medium transition ${
            mode === "public_page"
              ? "border-cyan-700 bg-cyan-950/60 text-cyan-200"
              : "border-slate-700 bg-slate-900/40 text-slate-400"
          }`}
        >
          合规公开页抽样
        </button>
        <button
          type="button"
          disabled={!canEdit}
          onClick={() => setMode("authorized_login")}
          className={`rounded-lg border px-3 py-2 text-xs font-medium transition ${
            mode === "authorized_login"
              ? "border-cyan-700 bg-cyan-950/60 text-cyan-200"
              : "border-slate-700 bg-slate-900/40 text-slate-400"
          }`}
        >
          加密账号登录
        </button>
        <button
          type="button"
          disabled={!canEdit}
          onClick={() => setMode("authorized_session")}
          className={`rounded-lg border px-3 py-2 text-xs font-medium transition ${
            mode === "authorized_session"
              ? "border-cyan-700 bg-cyan-950/60 text-cyan-200"
              : "border-slate-700 bg-slate-900/40 text-slate-400"
          }`}
        >
          加密会话状态
        </button>
      </div>
      <p className="mt-2 text-[11px] leading-5 text-slate-500">
        {mode === "api"
          ? "官方能力存在且权限足够时必须选择此项。留空字段会保留已加密值。"
          : mode === "public_page"
            ? "仅适用于无需登录且通过平台条款、robots/许可、字段必要性、采样频率、限流和来源审计的页面。"
            : mode === "authorized_login"
              ? "凭据加密保存且不回显；只执行平台允许的常规登录，验证码、2FA 或风控出现时立即停止。"
              : "导入已授权浏览器的 Playwright storage_state JSON；状态加密保存、隔离使用且永不回显。"}
      </p>
      <form action={saveCredentials} className="mt-4 space-y-3">
        {fields.map((field) => (
          <label className="grid gap-1 text-sm" key={field.key}>
            <span className="text-xs font-medium text-slate-300">
              {field.label}
              {field.required ? " *" : ""}
            </span>
            <input
              name={field.key}
              type={field.secret ? "password" : "text"}
              className={inputClass}
              placeholder={
                setting?.configured_fields.includes(field.key)
                  ? "已配置；留空保持不变"
                  : field.placeholder
              }
              autoComplete="new-password"
              disabled={!canEdit}
            />
          </label>
        ))}
        {mode === "public_page" && (
          <fieldset className="space-y-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3">
            <legend className="px-1 text-xs font-medium text-slate-300">
              启用前的强制条件
            </legend>
            {[
              ["terms_permission_confirmed", "已确认平台条款或获得许可"],
              ["robots_reviewed", "已检查 robots/页面许可范围"],
              ["fields_minimized", "仅采集实现用途所必需字段"],
              ["source_audit_enabled", "保留来源、采集时间和审计记录"],
            ].map(([key, label]) => (
              <label
                key={key}
                className="flex items-start gap-2 text-xs leading-5 text-slate-400"
              >
                <input
                  className="mt-1"
                  name={key}
                  type="checkbox"
                  defaultChecked={setting?.configured_fields.includes(
                    key ?? "",
                  )}
                  disabled={!canEdit}
                />
                <span>{label}</span>
              </label>
            ))}
            <label className="grid gap-1 text-xs text-slate-400">
              最小采样间隔（秒，至少 300）
              <input
                className={inputClass}
                name="sample_interval_seconds"
                type="number"
                min={300}
                defaultValue={300}
                disabled={!canEdit}
              />
            </label>
          </fieldset>
        )}
        {mode === "authorized_login" && (
          <fieldset className="space-y-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3">
            <legend className="px-1 text-xs font-medium text-slate-300">
              启用前的强制条件
            </legend>
            {[
              [
                "account_authorization_confirmed",
                "账号由我所有或已获得账号所有者明确授权",
              ],
              [
                "platform_login_allowed",
                "已确认平台允许此账号采用自动化浏览器登录",
              ],
              [
                "oauth_unavailable_or_insufficient",
                "OAuth/API 不可用或权限不足",
              ],
            ].map(([key, label]) => (
              <label
                key={key}
                className="flex items-start gap-2 text-xs leading-5 text-slate-400"
              >
                <input
                  className="mt-1"
                  name={key}
                  type="checkbox"
                  defaultChecked={setting?.configured_fields.includes(
                    key ?? "",
                  )}
                  disabled={!canEdit}
                />
                <span>{label}</span>
              </label>
            ))}
          </fieldset>
        )}
        {mode === "authorized_session" && (
          <div className="space-y-3">
            <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
              <p className="text-xs font-medium text-violet-300">人工登录并保存 Cookie</p>
              <p className="mt-1 text-xs leading-5 text-slate-400">
                默认使用 Docker 内置的可视化 Chromium。系统不会代填密码、绕过验证码或二次验证，
                只读取当前平台 Cookie 并在后端加密保存。
              </p>
              <ol className="mt-2 list-decimal space-y-1 pl-4 text-[11px] leading-5 text-slate-500">
                <li>点击打开平台登录页，系统会打开 Docker 内置浏览器窗口。</li>
                <li>在 noVNC 浏览器窗口中人工完成登录、验证码和二次验证。</li>
                <li>回到此页，确认授权项后点击保存已登录 Cookie。</li>
              </ol>
              <p className="text-xs leading-5 text-slate-400">
                如需改用宿主机 Chrome/Edge，可将 CDP 地址替换为
                <code className="mx-1 rounded bg-slate-800 px-1">http://host.docker.internal:9222</code>。
              </p>
              <p className="text-xs leading-5 text-slate-400">
                住宅/轮换代理是绕过 TikTok、抖音等数据中心 IP
                反爬封锁的关键。配合下方已授权的登录会话（storage_state），即可在「账号监控」中正常抓取到真实作品与播放数据。仅作用于当前工作区该平台的全部账号。
              </p>
              <div className="mt-3 grid gap-3 sm:grid-cols-1">
                <label className="grid gap-1 text-xs text-slate-300">
                  代理服务器（必填，如 http://host:port 或 socks5://host:port）
                  <input
                    name="proxy_server"
                    className={inputClass}
                    placeholder="住宅代理出口地址"
                    disabled={!canEdit}
                  />
                </label>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="grid gap-1 text-xs text-slate-300">
                    代理用户名（可选）
                    <input
                      name="proxy_username"
                      className={inputClass}
                      placeholder="可选"
                      disabled={!canEdit}
                    />
                  </label>
                  <label className="grid gap-1 text-xs text-slate-300">
                    代理密码（可选）
                    <input
                      name="proxy_password"
                      type="password"
                      className={inputClass}
                      placeholder="可选"
                      disabled={!canEdit}
                    />
                  </label>
                </div>
              </div>
            </div>
            <label className="grid gap-1 text-xs text-slate-300">
              Playwright storage_state JSON *
              <textarea
                className={`${inputClass} min-h-28 font-mono text-xs`}
                name="storage_state_json"
                placeholder={
                  setting?.configured_fields.includes("storage_state_json")
                    ? "已加密保存；留空保持不变"
                    : '{"cookies": [], "origins": []}'
                }
                disabled={!canEdit}
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-1 text-xs text-slate-300">
                会话标签
                <input
                  className={inputClass}
                  name="session_label"
                  disabled={!canEdit}
                />
              </label>
              <label className="grid gap-1 text-xs text-slate-300">
                过期时间 *（默认 +30 天）
                <input
                  className={inputClass}
                  name="session_expires_at"
                  type="datetime-local"
                  defaultValue={defaultSessionExpiry}
                  disabled={!canEdit}
                />
              </label>
            </div>
            {[
              [
                "account_authorization_confirmed",
                "账号由我所有或已获得账号所有者明确授权",
              ],
              ["platform_session_allowed", "已确认平台允许使用该登录会话"],
              [
                "oauth_unavailable_or_insufficient",
                "OAuth/API 不可用或权限不足",
              ],
            ].map(([key, label]) => (
              <label
                key={key}
                className="flex items-start gap-2 text-xs leading-5 text-slate-400"
              >
                <input
                  className="mt-1"
                  name={key}
                  type="checkbox"
                  defaultChecked={setting?.configured_fields.includes(
                    key ?? "",
                  )}
                  disabled={!canEdit}
                />
                <span>{label}</span>
              </label>
            ))}
          </div>
        )}
        <div className="rounded-lg border border-slate-800 bg-emerald-950/30 p-3">
          <p className="text-xs font-medium text-emerald-300">
            Docker 内置浏览器（推荐）
          </p>
          <p className="mt-1 text-xs leading-5 text-slate-400">
            默认填写 Docker 内置 Chromium 的私有 CDP 地址；如果改用本机真实浏览器，需用专用 profile
            并带
            <code className="mx-1 rounded bg-slate-800 px-1">--remote-debugging-port=9222</code>
            启动。若 worker 运行在 Docker 内，请填
            <code className="mx-1 rounded bg-slate-800 px-1">
              http://host.docker.internal:9222
            </code>
            ，否则保留
            <code className="mx-1 rounded bg-slate-800 px-1">
              http://browser:9222
            </code>
            。
          </p>
          <label className="mt-3 grid gap-1 text-xs text-slate-300">
            本地浏览器 CDP 地址
            <input
              name="cdp_endpoint"
              className={inputClass}
              defaultValue={
                String(setting?.config_masked?.cdp_endpoint ?? "").trim() ||
                "http://browser:9222"
              }
              placeholder="Docker 内置浏览器：http://browser:9222"
              disabled={!canEdit}
            />
          </label>
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              type="button"
              className={secondaryButtonClass}
              disabled={saving || !canEdit}
              onClick={(event) => {
                void openManualLogin(event.currentTarget.form);
              }}
            >
              打开平台登录页
            </button>
            <button
              type="button"
              className={`${buttonClass} justify-center`}
              disabled={saving || !canEdit}
              onClick={(event) => {
                void captureManualLogin(event.currentTarget.form);
              }}
            >
              保存已登录 Cookie
            </button>
          </div>
        </div>
        <button
          className={`${buttonClass} w-full justify-center`}
          disabled={saving || !canEdit}
        >
          <Save size={14} />
          {saving
            ? "保存中…"
            : mode === "api"
              ? "保存 API 配置"
              : mode === "authorized_login"
                ? "保存加密登录凭据"
                : mode === "authorized_session"
                  ? "保存加密会话状态"
                  : "启用公开页抽样"}
        </button>
        {hasLoginAccess && (
          <button
            type="button"
            className="w-full rounded-lg border border-rose-900/70 px-3 py-2 text-xs text-rose-300"
            onClick={revokeLoginAccess}
            disabled={saving || !canEdit}
          >
            一键撤销登录授权
          </button>
        )}
      </form>
    </Panel>
  );
}
