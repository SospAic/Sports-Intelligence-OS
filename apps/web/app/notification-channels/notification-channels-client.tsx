"use client";
import type {
  NotificationChannelRecord,
  NotificationDeliveryPage,
  NotificationProviderDescriptor,
} from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Send, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { DataTable } from "@/components/data-table";
import { useToast } from "@/components/toast";
import {
  Badge,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";
import { normalizeNotificationConfig } from "@/lib/notification-config";
const labels: Record<string, string> = {
  host: "SMTP 主机",
  port: "端口",
  username: "用户名",
  password: "密码",
  from_email: "发件人",
  to_emails: "收件人（逗号分隔）",
  use_tls: "使用 STARTTLS",
  use_ssl: "使用 SSL",
  url: "Webhook URL",
  headers: "附加请求头（JSON）",
  signing_secret: "签名密钥",
  bot_token: "Bot Token",
  chat_id: "Chat ID",
  webhook_url: "Webhook URL",
  secret: "签名密钥",
  simulate_error: "模拟错误",
};
export function NotificationChannelsClient() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [providerKey, setProviderKey] = useState("");
  const [config, setConfig] = useState<Record<string, string | boolean>>({});
  const [name, setName] = useState("");
  const providers = useQuery({
    queryKey: ["notification-providers"],
    queryFn: () =>
      apiRequest<NotificationProviderDescriptor[]>("/notification-providers", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const channels = useQuery({
    queryKey: ["notification-channels", workspaceId],
    queryFn: () =>
      apiRequest<NotificationChannelRecord[]>("/notification-channels", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const deliveries = useQuery({
    queryKey: ["notification-deliveries", workspaceId],
    queryFn: () =>
      apiRequest<NotificationDeliveryPage>(
        "/notification-deliveries?page=1&page_size=50",
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });
  const provider = providers.data?.find((item) => item.key === providerKey);
  const canAdmin = ["owner", "admin"].includes(role ?? "");
  async function create() {
    if (!workspaceId) return;
    try {
      const normalized = normalizeNotificationConfig(config);
      await apiRequest("/notification-channels", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          provider_key: providerKey,
          name,
          config: normalized,
          enabled: true,
        }),
      });
      notify("通知渠道已加密保存；API 不会返回明文密钥。");
      setCreating(false);
      setConfig({});
      setName("");
      await qc.invalidateQueries({ queryKey: ["notification-channels"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "创建失败", "error");
    }
  }
  async function toggle(channel: NotificationChannelRecord) {
    if (!workspaceId) return;
    try {
      await apiRequest(`/notification-channels/${channel.id}`, {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ enabled: !channel.enabled }),
      });
      notify(channel.enabled ? "渠道已停用" : "渠道已启用");
      await qc.invalidateQueries({ queryKey: ["notification-channels"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "更新失败", "error");
    }
  }
  async function test(channel: NotificationChannelRecord) {
    if (
      !workspaceId ||
      !window.confirm(
        channel.provider_key === "mock_notification"
          ? "发送 Mock 测试通知？"
          : "这将向真实外部渠道发送一条测试通知，是否继续？",
      )
    )
      return;
    try {
      const result = await apiRequest<{
        status: string;
        error?: { detail?: string };
      }>(`/notification-channels/${channel.id}/test`, {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          title: "Sports Intelligence OS 测试通知",
          body: "通知渠道配置测试。",
        }),
      });
      notify(
        result.status === "delivered"
          ? "测试通知已投递"
          : (result.error?.detail ?? `投递状态：${result.status}`),
        result.status === "delivered" ? "success" : "error",
      );
      await qc.invalidateQueries({ queryKey: ["notification-deliveries"] });
      await qc.invalidateQueries({ queryKey: ["notification-channels"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "测试失败", "error");
    }
  }
  async function remove(channel: NotificationChannelRecord) {
    if (
      !workspaceId ||
      !window.confirm("确定删除此渠道？有投递历史的渠道只会被停用。")
    )
      return;
    try {
      await apiRequest(`/notification-channels/${channel.id}`, {
        method: "DELETE",
        workspaceId,
        csrf: true,
      });
      notify("渠道已删除");
      await qc.invalidateQueries({ queryKey: ["notification-channels"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "删除失败", "error");
    }
  }
  const columns: ColumnDef<
    NotificationDeliveryPage["items"][number],
    unknown
  >[] = [
    {
      accessorKey: "created_at",
      header: "时间",
      cell: ({ row }) => formatDate(row.original.created_at),
    },
    { accessorKey: "entity_type", header: "实体" },
    {
      accessorKey: "status",
      header: "状态",
      cell: ({ row }) => (
        <Badge
          tone={
            row.original.status === "delivered"
              ? "success"
              : row.original.status === "failed"
                ? "danger"
                : "info"
          }
        >
          {row.original.status}
        </Badge>
      ),
    },
    { accessorKey: "attempts", header: "尝试次数" },
    {
      accessorKey: "error",
      header: "失败原因",
      cell: ({ row }) => (
        <span className="line-clamp-2 max-w-96 text-rose-300">
          {(row.original.error?.detail as string) ?? "—"}
        </span>
      ),
    },
  ];
  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Notifications"
        title="通知渠道"
        description="渠道密钥只在后端加密保存；此页面仅展示脱敏配置，测试真实渠道前会再次确认。"
        actions={
          canAdmin && (
            <button
              className={buttonClass}
              onClick={() => setCreating((v) => !v)}
            >
              <Plus size={15} />
              添加渠道
            </button>
          )
        }
      />
      {creating && (
        <Panel className="space-y-4 p-5">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-2 text-sm">
              Provider
              <select
                className={inputClass}
                value={providerKey}
                onChange={(e) => {
                  setProviderKey(e.target.value);
                  setConfig({});
                }}
              >
                <option value="">选择 Provider</option>
                {providers.data?.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.name}
                    {item.is_mock ? "（Mock）" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-2 text-sm">
              渠道名称
              <input
                className={inputClass}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            {provider?.config_fields.map((field) =>
              field.startsWith("use_") || field === "simulate_error" ? (
                <label
                  className="flex items-center gap-2 pt-7 text-sm"
                  key={field}
                >
                  <input
                    type="checkbox"
                    checked={Boolean(config[field])}
                    onChange={(e) =>
                      setConfig((value) => ({
                        ...value,
                        [field]: e.target.checked,
                      }))
                    }
                  />
                  {labels[field] ?? field}
                </label>
              ) : (
                <label className="grid gap-2 text-sm" key={field}>
                  {labels[field] ?? field}
                  {field === "headers" ? (
                    <textarea
                      className={`${inputClass} h-20 py-2 font-mono`}
                      value={String(config[field] ?? "")}
                      onChange={(e) =>
                        setConfig((value) => ({
                          ...value,
                          [field]: e.target.value,
                        }))
                      }
                    />
                  ) : (
                    <input
                      className={inputClass}
                      type={
                        /password|secret|token/.test(field)
                          ? "password"
                          : field === "port"
                            ? "number"
                            : "text"
                      }
                      autoComplete="off"
                      value={String(config[field] ?? "")}
                      onChange={(e) =>
                        setConfig((value) => ({
                          ...value,
                          [field]: e.target.value,
                        }))
                      }
                    />
                  )}
                </label>
              ),
            )}
          </div>
          <div className="flex gap-2">
            <button
              className={buttonClass}
              disabled={!providerKey || !name}
              onClick={create}
            >
              <ShieldCheck size={15} />
              验证并加密保存
            </button>
            <button
              className={secondaryButtonClass}
              onClick={() => setCreating(false)}
            >
              取消
            </button>
          </div>
        </Panel>
      )}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {channels.isLoading ? (
          <Panel>
            <SkeletonRows count={3} />
          </Panel>
        ) : (
          channels.data?.map((channel) => (
            <Panel className="p-5" key={channel.id}>
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="font-medium text-white">{channel.name}</h2>
                  <p className="mt-1 text-xs text-slate-500">
                    {channel.provider_key}
                  </p>
                </div>
                <Badge
                  tone={
                    channel.health_status === "healthy"
                      ? "success"
                      : channel.health_status === "unhealthy"
                        ? "danger"
                        : "neutral"
                  }
                >
                  {channel.health_status}
                </Badge>
              </div>
              <pre className="mt-4 max-h-32 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-400">
                {JSON.stringify(channel.config_masked, null, 2)}
              </pre>
              <p className="mt-3 text-xs text-slate-500">
                上次测试：{formatDate(channel.last_tested_at)}
              </p>
              <div className="mt-4 flex gap-2">
                <button
                  className={`${secondaryButtonClass} h-8 px-2`}
                  disabled={!channel.enabled}
                  onClick={() => test(channel)}
                >
                  <Send size={13} />
                  测试
                </button>
                <button
                  className={`${secondaryButtonClass} h-8 px-2`}
                  onClick={() => toggle(channel)}
                >
                  {channel.enabled ? "停用" : "启用"}
                </button>
                <button
                  className="ml-auto text-rose-300"
                  onClick={() => remove(channel)}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </Panel>
          ))
        )}
      </div>
      {!channels.isLoading && !channels.data?.length && (
        <StatePanel type="empty" title="尚未配置通知渠道" />
      )}
      <div id="deliveries">
        <h2 className="mb-3 text-lg font-medium text-white">投递历史</h2>
        {deliveries.error ? (
          <StatePanel
            type="error"
            title="投递记录加载失败"
            detail={deliveries.error.message}
          />
        ) : (
          <DataTable
            data={deliveries.data?.items ?? []}
            columns={columns}
            total={deliveries.data?.total ?? 0}
            page={1}
            pageSize={50}
            empty="暂无投递记录"
            getRowId={(row) => row.id}
          />
        )}
      </div>
    </main>
  );
}
