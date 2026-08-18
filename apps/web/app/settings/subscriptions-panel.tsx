"use client";

import type {
  AccountRecord,
  AccountRecordPage,
  PlatformRecord,
} from "@sio/shared-types";
import { Bell, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import {
  Badge,
  Panel,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";

type NotificationChannel = {
  id: string;
  name: string;
  provider_key: string;
  enabled: boolean;
};

type Subscription = {
  id: string;
  name: string;
  description: string | null;
  trigger_type: "new_content" | "keyword_match" | "metric_spike";
  platform_id: string | null;
  account_id: string | null;
  keywords: string[];
  thresholds: Record<string, unknown>;
  channel_ids: string[];
  cooldown_seconds: number;
  enabled: boolean;
  last_triggered_at: string | null;
  created_at: string;
};

type SubscriptionPage = {
  items: Subscription[];
  total: number;
};

const triggerLabels = {
  new_content: "新作品",
  keyword_match: "关键词命中",
  metric_spike: "指标突变",
} as const;

export function SubscriptionsPanel() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const canEdit = ["owner", "admin", "editor"].includes(role ?? "");
  const canDelete = ["owner", "admin"].includes(role ?? "");
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState(false);
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);

  const subscriptions = useQuery({
    queryKey: ["subscriptions", workspaceId],
    queryFn: () =>
      apiRequest<SubscriptionPage>("/subscriptions?page=1&page_size=100", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const channels = useQuery({
    queryKey: ["notification-channels", workspaceId],
    queryFn: () =>
      apiRequest<NotificationChannel[]>("/notification-channels", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && creating,
  });
  const platforms = useQuery({
    queryKey: ["platforms"],
    queryFn: () => apiRequest<PlatformRecord[]>("/platforms?enabled=true"),
    enabled: Boolean(workspaceId) && creating,
  });
  const accounts = useQuery({
    queryKey: ["subscription-accounts", workspaceId],
    queryFn: () =>
      apiRequest<AccountRecordPage>("/accounts?page=1&page_size=100&is_active=true", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId) && creating,
  });

  async function createSubscription(form: HTMLFormElement) {
    if (!workspaceId) return;
    const data = new FormData(form);
    const triggerType = String(data.get("trigger_type") || "new_content") as Subscription["trigger_type"];
    const accountId = String(data.get("account_id") || "").trim();
    const platformId = String(data.get("platform_id") || "").trim();
    const keywords = String(data.get("keywords") || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    const metric = String(data.get("metric") || "view_count").trim();
    const threshold = Number(data.get("threshold") || 0);
    setPending(true);
    try {
      await apiRequest("/subscriptions", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          name: String(data.get("name") || "").trim(),
          trigger_type: triggerType,
          account_id: accountId || null,
          platform_id: platformId || null,
          keywords,
          thresholds: triggerType === "metric_spike" ? { [metric]: { increase: threshold } } : {},
          channel_ids: selectedChannels,
          cooldown_seconds: Number(data.get("cooldown_seconds") || 3600),
          enabled: true,
        }),
      });
      notify("订阅告警已创建");
      setCreating(false);
      setSelectedChannels([]);
      await queryClient.invalidateQueries({ queryKey: ["subscriptions"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "订阅创建失败", "error");
    } finally {
      setPending(false);
    }
  }

  async function toggleSubscription(subscription: Subscription) {
    if (!workspaceId) return;
    setPending(true);
    try {
      await apiRequest(`/subscriptions/${subscription.id}`, {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ enabled: !subscription.enabled }),
      });
      notify(subscription.enabled ? "订阅已停用" : "订阅已启用");
      await queryClient.invalidateQueries({ queryKey: ["subscriptions"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "订阅状态更新失败", "error");
    } finally {
      setPending(false);
    }
  }

  async function deleteSubscription(subscription: Subscription) {
    if (!workspaceId || !window.confirm(`确定删除订阅「${subscription.name}」？`)) return;
    setPending(true);
    try {
      await apiRequest(`/subscriptions/${subscription.id}`, {
        method: "DELETE",
        workspaceId,
        csrf: true,
      });
      notify("订阅已删除");
      await queryClient.invalidateQueries({ queryKey: ["subscriptions"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "订阅删除失败", "error");
    } finally {
      setPending(false);
    }
  }

  if (subscriptions.error) {
    return (
      <StatePanel
        type="error"
        title="订阅告警加载失败"
        detail={subscriptions.error.message}
        onRetry={() => subscriptions.refetch()}
      />
    );
  }

  return (
    <Panel>
      <div className="flex items-center justify-between gap-3 border-b border-slate-800 p-5">
        <div>
          <div className="flex items-center gap-2">
            <Bell size={16} className="text-cyan-300" />
            <h2 className="font-medium text-white">订阅告警</h2>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            订阅新作品、关键词和指标突变；命中后进入统一通知队列，并保留事件审计。
          </p>
        </div>
        {canEdit && (
          <button className={buttonClass} onClick={() => setCreating((value) => !value)} type="button">
            <Plus size={15} /> 新建订阅
          </button>
        )}
      </div>
      {creating && (
        <form
          className="m-4 grid gap-3 rounded-xl border border-cyan-900/70 bg-cyan-950/10 p-4 md:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            void createSubscription(event.currentTarget);
          }}
        >
          <input className={inputClass} name="name" placeholder="订阅名称" required />
          <select className={inputClass} defaultValue="new_content" name="trigger_type">
            {Object.entries(triggerLabels).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <select className={inputClass} defaultValue="" name="platform_id">
            <option value="">全部平台</option>
            {platforms.data?.map((platform) => (
              <option key={platform.id} value={platform.id}>{platform.name}</option>
            ))}
          </select>
          <select className={inputClass} defaultValue="" name="account_id">
            <option value="">全部账号</option>
            {accounts.data?.items.map((account: AccountRecord) => (
              <option key={account.id} value={account.id}>
                {account.display_name || account.username || account.external_id}
              </option>
            ))}
          </select>
          <input className={inputClass} name="keywords" placeholder="关键词，逗号分隔（关键词订阅必填）" />
          <div className="grid grid-cols-2 gap-2">
            <input className={inputClass} defaultValue="view_count" name="metric" placeholder="指标键" />
            <input className={inputClass} defaultValue="1000" min="1" name="threshold" type="number" />
          </div>
          <input className={inputClass} defaultValue="3600" min="0" name="cooldown_seconds" type="number" />
          <div className="space-y-2 rounded-lg border border-slate-800 p-3 text-xs text-slate-400">
            <p className="font-medium text-slate-200">通知渠道</p>
            {channels.data?.filter((channel) => channel.enabled).map((channel) => (
              <label className="flex items-center gap-2" key={channel.id}>
                <input
                  checked={selectedChannels.includes(channel.id)}
                  onChange={() =>
                    setSelectedChannels((current) =>
                      current.includes(channel.id)
                        ? current.filter((id) => id !== channel.id)
                        : [...current, channel.id],
                    )
                  }
                  type="checkbox"
                />
                {channel.name} · {channel.provider_key}
              </label>
            ))}
            {!channels.data?.some((channel) => channel.enabled) && <p>暂无启用的通知渠道</p>}
          </div>
          <div className="flex gap-2 md:col-span-2">
            <button className={buttonClass} disabled={pending} type="submit">{pending ? "保存中…" : "保存订阅"}</button>
            <button className={secondaryButtonClass} onClick={() => setCreating(false)} type="button">取消</button>
          </div>
        </form>
      )}
      <div className="divide-y divide-slate-800">
        {subscriptions.data?.items.map((subscription) => (
          <div className="flex flex-wrap items-center justify-between gap-3 p-4" key={subscription.id}>
            <div className="min-w-0">
              <p className="font-medium text-slate-200">{subscription.name}</p>
              <p className="mt-1 text-xs text-slate-500">
                {triggerLabels[subscription.trigger_type]} · {subscription.keywords.join(", ") || "无关键词"} · {subscription.channel_ids.length} 个通知渠道
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Badge tone={subscription.enabled ? "success" : "neutral"}>
                {subscription.enabled ? "运行中" : "已停用"}
              </Badge>
              {canEdit && (
                <button className="text-xs text-cyan-300" disabled={pending} onClick={() => void toggleSubscription(subscription)} type="button">
                  {subscription.enabled ? "停用" : "启用"}
                </button>
              )}
              {canDelete && (
                <button className="text-rose-300" disabled={pending} onClick={() => void deleteSubscription(subscription)} type="button" aria-label={`删除${subscription.name}`}>
                  <Trash2 size={15} />
                </button>
              )}
            </div>
          </div>
        ))}
        {!subscriptions.isLoading && !subscriptions.data?.items.length && (
          <div className="p-8 text-center text-sm text-slate-500">暂无订阅。创建后，后台扫描器会按实时或导入来源触发告警。</div>
        )}
      </div>
    </Panel>
  );
}
