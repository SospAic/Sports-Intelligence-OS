import type { HealthResponse } from "@sio/shared-types";

export type QueueHealthState =
  | "checking"
  | "healthy"
  | "busy"
  | "degraded"
  | "unreachable";

export async function fetchReadyHealth(): Promise<HealthResponse> {
  const response = await fetch("/health/ready", { cache: "no-store" });
  const payload = (await response
    .json()
    .catch(() => null)) as HealthResponse | null;
  if (!payload || !["ok", "degraded"].includes(payload.status)) {
    throw new Error(`健康检查返回无效响应（HTTP ${response.status}）`);
  }
  if (!response.ok && payload.status !== "degraded") {
    throw new Error(`健康检查失败（HTTP ${response.status}）`);
  }
  return payload;
}

export function queueHealthPresentation(options: {
  health: HealthResponse | undefined;
  syncing: number;
  isPending: boolean;
  isError: boolean;
}): { label: string; state: QueueHealthState } {
  if (options.isError) {
    return { label: "后台服务不可达", state: "unreachable" };
  }
  if (options.isPending || !options.health) {
    return { label: "正在检查后台服务", state: "checking" };
  }
  if (options.health.status === "degraded") {
    return { label: "后台任务服务降级", state: "degraded" };
  }
  if (options.syncing > 0) {
    return { label: `${options.syncing} 个同步中`, state: "busy" };
  }
  return { label: "同步队列正常", state: "healthy" };
}
