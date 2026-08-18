"use client";

import type {
  InboxExtendedItemRecord,
  InboxReadStateRecord,
  InboxQueueStateRecord,
  InboxSavedViewRecord,
  InboxSlaSummaryRecord,
  NotificationDeliveryPage,
  OperationTaskPage,
} from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import { Activity, Bell, CheckCheck, ListChecks, Save, Tag } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import {
  Badge,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  inputClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import {
  buildInboxItems,
  inboxKindLabel,
  inboxStatusLabel,
} from "@/lib/inbox";
import { formatDate } from "@/lib/format";

type KindFilter =
  | "all"
  | "sync"
  | "notification"
  | "task"
  | "editorial_comment"
  | "subscription_event"
  | "dead_letter";

export function NotificationsClient() {
  const { workspaceId } = useWorkspace();
  const { notify } = useToast();
  const [kind, setKind] = useState<KindFilter>("all");
  const [status, setStatus] = useState("");
  const [queueState, setQueueState] = useState("");
  const [activeView, setActiveView] = useState("");
  const [labelInputs, setLabelInputs] = useState<Record<string, string>>({});
  const [optimisticReadIds, setOptimisticReadIds] = useState<Set<string>>(
    () => new Set(),
  );
  const tasks = useQuery({
    queryKey: ["notification-history-tasks", workspaceId],
    queryFn: () =>
      apiRequest<OperationTaskPage>(
        "/operations/tasks?page=1&page_size=100",
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });
  const deliveries = useQuery({
    queryKey: ["notification-history-deliveries", workspaceId],
    queryFn: () =>
      apiRequest<NotificationDeliveryPage>(
        "/notification-deliveries?page=1&page_size=100",
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });
  const extendedItems = useQuery<InboxExtendedItemRecord[]>({
    queryKey: ["notification-history-extended-items", workspaceId],
    queryFn: () =>
      apiRequest<InboxExtendedItemRecord[]>("/inbox/items?limit=100", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const sla = useQuery<InboxSlaSummaryRecord>({
    queryKey: ["notification-history-sla", workspaceId],
    queryFn: () => apiRequest<InboxSlaSummaryRecord>("/inbox/sla?window_minutes=60&limit=100", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId),
    refetchInterval: 60_000,
  });

  const items = useMemo(
    () =>
      buildInboxItems(
        tasks.data?.items ?? [],
        deliveries.data?.items ?? [],
        extendedItems.data ?? [],
      ),
    [deliveries.data?.items, extendedItems.data, tasks.data?.items],
  );
  const readStateQuery = useQuery<InboxReadStateRecord[]>({
    queryKey: [
      "notification-history-read-states",
      workspaceId,
      items.map((item) => item.id).join(","),
    ],
    queryFn: () => {
      const params = new URLSearchParams();
      items.forEach((item) => params.append("item_key", item.id));
      return apiRequest<InboxReadStateRecord[]>(
        `/inbox/read-states?${params.toString()}`,
        { workspaceId: workspaceId! },
      );
    },
    enabled: Boolean(workspaceId) && items.length > 0,
    staleTime: 10_000,
  });
  const queueStateQuery = useQuery<InboxQueueStateRecord[]>({
    queryKey: [
      "notification-history-queue-states",
      workspaceId,
      items.map((item) => item.id).join(","),
    ],
    queryFn: () => {
      const params = new URLSearchParams();
      items.forEach((item) => params.append("item_key", item.id));
      return apiRequest<InboxQueueStateRecord[]>(
        `/inbox/queue-states?${params.toString()}`,
        { workspaceId: workspaceId! },
      );
    },
    enabled: Boolean(workspaceId) && items.length > 0,
    staleTime: 10_000,
  });
  const views = useQuery<InboxSavedViewRecord[]>({
    queryKey: ["notification-history-views", workspaceId],
    queryFn: () =>
      apiRequest<InboxSavedViewRecord[]>("/inbox/views", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const readIds = useMemo(
    () =>
      new Set([
        ...(readStateQuery.data ?? []).map((state) => state.item_key),
        ...optimisticReadIds,
      ]),
    [optimisticReadIds, readStateQuery.data],
  );
  const queueStates = useMemo(
    () => new Map((queueStateQuery.data ?? []).map((state) => [state.item_key, state])),
    [queueStateQuery.data],
  );
  const filtered = items.filter(
    (item) =>
      (kind === "all" || item.kind === kind) &&
      (!status || item.status === status) &&
      (!queueState || (queueStates.get(item.id)?.state ?? "open") === queueState),
  );
  const unreadCount = items.filter((item) => !readIds.has(item.id)).length;

  async function markRead(id: string) {
    setOptimisticReadIds((previous) => {
      const next = new Set(previous);
      next.add(id);
      return next;
    });
    try {
      await apiRequest("/inbox/read-states", {
        method: "POST",
        body: JSON.stringify({ item_key: id }),
        workspaceId: workspaceId!,
        csrf: true,
      });
      await readStateQuery.refetch();
    } catch {
      setOptimisticReadIds((previous) => {
        const next = new Set(previous);
        next.delete(id);
        return next;
      });
    }
  }

  async function markAllRead() {
    const ids = items.map((item) => item.id);
    if (!ids.length) return;
    setOptimisticReadIds((previous) => {
      const next = new Set(previous);
      ids.forEach((id) => next.add(id));
      return next;
    });
    try {
      await apiRequest("/inbox/read-states/bulk", {
        method: "POST",
        body: JSON.stringify({ item_keys: ids }),
        workspaceId: workspaceId!,
        csrf: true,
      });
      await readStateQuery.refetch();
    } catch {
      setOptimisticReadIds((previous) => {
        const next = new Set(previous);
        ids.forEach((id) => next.delete(id));
        return next;
      });
    }
  }

  async function updateQueueState(
    itemKeys: string[],
    patch: { state?: "open" | "in_progress" | "completed"; labels?: string[] },
  ) {
    if (!workspaceId || !itemKeys.length) return;
    try {
      await apiRequest("/inbox/queue-states/bulk", {
        method: "PATCH",
        body: JSON.stringify({ item_keys: itemKeys, ...patch }),
        workspaceId,
        csrf: true,
      });
      await queueStateQuery.refetch();
    } catch (error) {
      notify(error instanceof Error ? error.message : "队列状态更新失败", "error");
    }
  }

  async function addLabel(itemId: string) {
    const label = labelInputs[itemId]?.trim().toLowerCase();
    if (!label) return;
    const current = queueStates.get(itemId)?.labels ?? [];
    await updateQueueState([itemId], { labels: [...current, label] });
    setLabelInputs((previous) => ({ ...previous, [itemId]: "" }));
  }

  function applyView(view: InboxSavedViewRecord) {
    const filters = view.filters;
    const nextKind = filters.kind;
    const nextStatus = filters.status;
    const nextQueueState = filters.queue_state;
    if (
      nextKind === "all" ||
      nextKind === "sync" ||
      nextKind === "notification" ||
      nextKind === "task" ||
      nextKind === "editorial_comment" ||
      nextKind === "subscription_event" ||
      nextKind === "dead_letter"
    ) {
      setKind(nextKind);
    }
    setStatus(typeof nextStatus === "string" ? nextStatus : "");
    setQueueState(typeof nextQueueState === "string" ? nextQueueState : "");
    setActiveView(view.id);
  }

  async function saveCurrentView() {
    if (!workspaceId) return;
    const name = window.prompt("保存视图名称");
    if (!name?.trim()) return;
    try {
      await apiRequest("/inbox/views", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          filters: { kind, status, queue_state: queueState },
        }),
        workspaceId,
        csrf: true,
      });
      await views.refetch();
      notify("运营队列视图已保存");
    } catch (error) {
      notify(error instanceof Error ? error.message : "保存视图失败", "error");
    }
  }

  const error =
    tasks.error ??
    deliveries.error ??
    extendedItems.error ??
    sla.error ??
    queueStateQuery.error ??
    views.error;
  return (
    <main className="mx-auto min-w-0 max-w-[1100px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="OPERATIONS INBOX"
        title="信息历史"
        description="集中查看同步、通知投递、后台任务、审核评论、订阅告警和待重放死信；数据来自真实运行记录，已读状态按工作区和用户持久化。"
        actions={
          <button
            className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 transition hover:bg-slate-900 disabled:cursor-not-allowed disabled:text-slate-600"
            disabled={!unreadCount}
            onClick={() => void markAllRead()}
            type="button"
          >
            <CheckCheck size={15} /> 全部标为已读
          </button>
        }
      />

      {sla.data && (
        <Panel className="p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-200">队列 SLA</h2>
              <p className="mt-1 text-xs text-slate-500">截止时间来自共享队列状态；逾期项由 Beat 加标签并写入审计事件，不改变原业务状态。</p>
            </div>
            <span className="text-xs text-slate-600">未来 {sla.data.window_minutes} 分钟</span>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-4">
            <SlaMetric label="已逾期" value={sla.data.overdue_count} tone="danger" />
            <SlaMetric label="即将到期" value={sla.data.due_soon_count} tone="warning" />
            <SlaMetric label="按计划" value={sla.data.on_track_count} tone="success" />
            <SlaMetric label="已完成" value={sla.data.completed_count} tone="neutral" />
          </div>
        </Panel>
      )}

      <Panel className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          {([
            "all",
            "sync",
            "notification",
            "task",
            "editorial_comment",
            "subscription_event",
            "dead_letter",
          ] as const).map((value) => (
            <button
              className={`rounded-lg px-3 py-2 text-xs transition ${kind === value ? "bg-cyan-400/15 text-cyan-200" : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"}`}
              key={value}
              onClick={() => setKind(value)}
              type="button"
            >
              {value === "all" ? "全部" : inboxKindLabel(value)}
            </button>
          ))}
          <select
            aria-label="按状态筛选"
            className={`${inputClass} ml-auto h-9 w-36 text-xs`}
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="">全部状态</option>
            <option value="queued">排队中</option>
            <option value="running">执行中</option>
            <option value="success">成功</option>
            <option value="delivered">已送达</option>
            <option value="failed">失败</option>
            <option value="error">错误</option>
          </select>
          <select
            aria-label="按处理状态筛选"
            className={`${inputClass} h-9 w-36 text-xs`}
            value={queueState}
            onChange={(event) => {
              setQueueState(event.target.value);
              setActiveView("");
            }}
          >
            <option value="">全部处理状态</option>
            <option value="open">待处理</option>
            <option value="in_progress">处理中</option>
            <option value="completed">已完成</option>
          </select>
          <select
            aria-label="应用保存视图"
            className={`${inputClass} h-9 w-44 text-xs`}
            value={activeView}
            onChange={(event) => {
              const view = views.data?.find((item) => item.id === event.target.value);
              if (view) applyView(view);
            }}
          >
            <option value="">保存视图</option>
            {(views.data ?? []).map((view) => (
              <option key={view.id} value={view.id}>{view.name}</option>
            ))}
          </select>
          <button
            className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:border-cyan-400 hover:text-cyan-200"
            onClick={() => void saveCurrentView()}
            type="button"
          >
            <Save size={14} /> 保存当前视图
          </button>
        </div>
      </Panel>

      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
        <span>当前显示 {filtered.length} 条；处理状态和标签对工作区成员共享。</span>
        <button
          className="rounded-lg border border-slate-700 px-3 py-2 text-slate-300 hover:border-cyan-400 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!filtered.length}
          onClick={() => void updateQueueState(filtered.map((item) => item.id), { state: "completed" })}
          type="button"
        >
          批量标记当前筛选为已完成
        </button>
      </div>

      {tasks.isLoading || deliveries.isLoading || extendedItems.isLoading || sla.isLoading ? (
        <Panel className="p-4">
          <SkeletonRows />
        </Panel>
      ) : error ? (
        <StatePanel
          type="error"
          title="信息历史加载失败"
          detail={error instanceof Error ? error.message : "请稍后重试"}
          onRetry={() => {
            void tasks.refetch();
            void deliveries.refetch();
            void extendedItems.refetch();
            void sla.refetch();
          }}
        />
      ) : (
        <Panel className="overflow-hidden p-0">
          {filtered.length ? (
            <div className="divide-y divide-slate-800">
              {filtered.map((item) => {
                const state = queueStates.get(item.id);
                const currentQueueState = state?.state ?? "open";
                return (
                <div
                  className="flex items-start gap-3 px-5 py-4 transition hover:bg-slate-900/70"
                  key={item.id}
                >
                  <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-slate-900 text-cyan-300">
                    {item.kind === "sync" ? (
                      <Activity size={16} />
                    ) : item.kind === "notification" ? (
                      <Bell size={16} />
                    ) : (
                      <ListChecks size={16} />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <Link
                      className="block rounded-md focus:outline-none focus:ring-2 focus:ring-cyan-400"
                      href={item.href}
                      onClick={() => void markRead(item.id)}
                    >
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-slate-200">
                        {item.title}
                      </span>
                      <Badge tone={item.kind === "notification" ? "info" : "neutral"}>
                        {inboxKindLabel(item.kind)}
                      </Badge>
                      {!readIds.has(item.id) && <Badge tone="warning">未读</Badge>}
                      {state?.labels.includes("sla_overdue") && <Badge tone="danger">SLA逾期</Badge>}
                    </span>
                    <span className="mt-1 block truncate text-sm text-slate-400">
                      {item.detail}
                    </span>
                    <span className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                      <span>{formatDate(item.timestamp)}</span>
                      <span>{inboxStatusLabel(item.status)}</span>
                    </span>
                    </Link>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <label className="sr-only" htmlFor={`queue-state-${item.id}`}>
                        {item.title}处理状态
                      </label>
                      <select
                        id={`queue-state-${item.id}`}
                        aria-label={`${item.title}处理状态`}
                        className={`${inputClass} h-8 w-28 text-xs`}
                        value={currentQueueState}
                        onChange={(event) =>
                          void updateQueueState([item.id], {
                            state: event.target.value as "open" | "in_progress" | "completed",
                          })
                        }
                      >
                        <option value="open">待处理</option>
                        <option value="in_progress">处理中</option>
                        <option value="completed">已完成</option>
                      </select>
                      {state?.labels.map((label) => (
                        <Badge key={label} tone="info"><Tag size={12} /> {label}</Badge>
                      ))}
                      <input
                        aria-label={`${item.title}新增标签`}
                        className={`${inputClass} h-8 w-28 text-xs`}
                        placeholder="新增标签"
                        value={labelInputs[item.id] ?? ""}
                        onChange={(event) =>
                          setLabelInputs((previous) => ({
                            ...previous,
                            [item.id]: event.target.value,
                          }))
                        }
                        onKeyDown={(event) => {
                          if (event.key === "Enter") void addLabel(item.id);
                        }}
                      />
                      <button
                        className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-400 hover:border-cyan-400 hover:text-cyan-200"
                        onClick={() => void addLabel(item.id)}
                        type="button"
                      >
                        添加标签
                      </button>
                    </div>
                  </span>
                </div>
                );
              })}
            </div>
          ) : (
            <div className="p-12 text-center text-sm text-slate-500">
              当前筛选下暂无信息记录
            </div>
          )}
        </Panel>
      )}
    </main>
  );
}

function SlaMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "danger" | "warning" | "success" | "neutral";
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2">
      <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
        <span>{label}</span>
        <Badge tone={tone}>{value}</Badge>
      </div>
    </div>
  );
}
