"use client";

import type {
  NotificationDeliveryPage,
  OperationTaskPage,
} from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import { Activity, Bell, CheckCheck, ListChecks } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useWorkspace } from "@/components/app-shell";
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

type KindFilter = "all" | "sync" | "notification" | "task";

export function NotificationsClient() {
  const { workspaceId } = useWorkspace();
  const [kind, setKind] = useState<KindFilter>("all");
  const [status, setStatus] = useState("");
  const [readIds, setReadIds] = useState<Set<string>>(() => new Set());
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

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem("sio-read-inbox-items");
      const ids = raw ? JSON.parse(raw) : [];
      if (Array.isArray(ids)) {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate the optional browser-only read marker
        setReadIds(
          new Set(ids.filter((id): id is string => typeof id === "string")),
        );
      }
    } catch {
      // History remains usable without local read persistence.
    }
  }, []);

  const items = useMemo(
    () =>
      buildInboxItems(tasks.data?.items ?? [], deliveries.data?.items ?? []),
    [deliveries.data?.items, tasks.data?.items],
  );
  const filtered = items.filter(
    (item) => (kind === "all" || item.kind === kind) && (!status || item.status === status),
  );
  const unreadCount = items.filter((item) => !readIds.has(item.id)).length;

  function markRead(id: string) {
    setReadIds((previous) => {
      const next = new Set(previous);
      next.add(id);
      try {
        window.localStorage.setItem(
          "sio-read-inbox-items",
          JSON.stringify(Array.from(next)),
        );
      } catch {
        // Continue without local persistence when browser storage is blocked.
      }
      return next;
    });
  }

  function markAllRead() {
    setReadIds((previous) => {
      const next = new Set(previous);
      items.forEach((item) => next.add(item.id));
      try {
        window.localStorage.setItem(
          "sio-read-inbox-items",
          JSON.stringify(Array.from(next)),
        );
      } catch {
        // Continue without local persistence when browser storage is blocked.
      }
      return next;
    });
  }

  const error = tasks.error ?? deliveries.error;
  return (
    <main className="mx-auto min-w-0 max-w-[1100px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="OPERATIONS INBOX"
        title="信息历史"
        description="集中查看同步、通知投递和后台任务；数据来自已持久化的真实运行记录，未读标记保存在当前浏览器。"
        actions={
          <button
            className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 transition hover:bg-slate-900 disabled:cursor-not-allowed disabled:text-slate-600"
            disabled={!unreadCount}
            onClick={markAllRead}
            type="button"
          >
            <CheckCheck size={15} /> 全部标为已读
          </button>
        }
      />

      <Panel className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          {(["all", "sync", "notification", "task"] as const).map((value) => (
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
        </div>
      </Panel>

      {tasks.isLoading || deliveries.isLoading ? (
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
          }}
        />
      ) : (
        <Panel className="overflow-hidden p-0">
          {filtered.length ? (
            <div className="divide-y divide-slate-800">
              {filtered.map((item) => (
                <Link
                  className="flex items-start gap-3 px-5 py-4 transition hover:bg-slate-900/70"
                  href={item.href}
                  key={item.id}
                  onClick={() => markRead(item.id)}
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
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-slate-200">
                        {item.title}
                      </span>
                      <Badge tone={item.kind === "notification" ? "info" : "neutral"}>
                        {inboxKindLabel(item.kind)}
                      </Badge>
                      {!readIds.has(item.id) && <Badge tone="warning">未读</Badge>}
                    </span>
                    <span className="mt-1 block truncate text-sm text-slate-400">
                      {item.detail}
                    </span>
                    <span className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                      <span>{formatDate(item.timestamp)}</span>
                      <span>{inboxStatusLabel(item.status)}</span>
                    </span>
                  </span>
                </Link>
              ))}
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
