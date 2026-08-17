import type {
  InboxExtendedItemRecord,
  NotificationDeliveryRecord,
  OperationTaskRecord,
} from "@sio/shared-types";

import { operationTaskLabel } from "@/lib/operation-labels";

export type InboxItemKind =
  | "sync"
  | "notification"
  | "task"
  | "editorial_comment"
  | "subscription_event"
  | "dead_letter";

export interface InboxItem {
  id: string;
  kind: InboxItemKind;
  title: string;
  detail: string;
  status: string;
  timestamp: string | null;
  href: string;
}

const ENTITY_LABELS: Record<string, string> = {
  account: "账号",
  content: "作品",
  event: "事件",
  article: "新闻",
  rule: "规则",
  system: "系统",
};

export function inboxKindLabel(kind: InboxItemKind): string {
  if (kind === "sync") return "同步";
  if (kind === "notification") return "通知";
  if (kind === "editorial_comment") return "审核评论";
  if (kind === "subscription_event") return "订阅告警";
  if (kind === "dead_letter") return "死信";
  return "任务";
}

export function inboxStatusLabel(status: string): string {
  return (
    {
      queued: "排队中",
      pending: "等待中",
      sending: "发送中",
      running: "执行中",
      syncing: "同步中",
      retrying: "等待重试",
      delivered: "已送达",
      success: "成功",
      completed: "完成",
      degraded: "部分完成",
      failed: "失败",
      error: "错误",
      cancelled: "已取消",
    }[status] ?? status
  );
}

function taskItem(task: OperationTaskRecord): InboxItem {
  const isSync = task.category === "platform_sync";
  return {
    id: `task:${task.id}`,
    kind: isSync ? "sync" : "task",
    title: isSync ? "账号同步" : "后台任务",
    detail: operationTaskLabel(task.task_type || task.category),
    status: task.status,
    timestamp: task.finished_at ?? task.started_at,
    href: isSync ? "/tasks?category=platform_sync" : "/tasks",
  };
}

function deliveryItem(delivery: NotificationDeliveryRecord): InboxItem {
  return {
    id: `notification:${delivery.id}`,
    kind: "notification",
    title: "通知投递",
    detail: `${ENTITY_LABELS[delivery.entity_type] ?? delivery.entity_type} · ${delivery.channel_id.slice(0, 8)}`,
    status: delivery.status,
    timestamp: delivery.updated_at || delivery.created_at,
    href: "/notification-channels#deliveries",
  };
}

/** Build one chronologically sorted stream from persisted operational records. */
export function buildInboxItems(
  tasks: OperationTaskRecord[],
  deliveries: NotificationDeliveryRecord[],
  extended: InboxExtendedItemRecord[] = [],
): InboxItem[] {
  const extendedItems: InboxItem[] = extended.map((item) => ({
    id: item.item_key,
    kind: item.item_kind,
    title: item.title,
    detail: item.detail,
    status: item.status,
    timestamp: item.timestamp,
    href: item.href,
  }));
  return [...tasks.map(taskItem), ...deliveries.map(deliveryItem), ...extendedItems].sort(
    (a, b) => {
      const aTime = a.timestamp ? new Date(a.timestamp).getTime() : 0;
      const bTime = b.timestamp ? new Date(b.timestamp).getTime() : 0;
      return bTime - aTime;
    },
  );
}
