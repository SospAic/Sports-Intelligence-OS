import { describe, expect, it } from "vitest";

import { queueHealthPresentation } from "./health";

const healthy = { status: "ok", service: "api", version: "test" } as const;
const degraded = {
  status: "degraded",
  service: "api",
  version: "test",
  checks: { database: "ok", redis: "error" },
} as const;

describe("queueHealthPresentation", () => {
  it("does not claim the queue is healthy while readiness is loading", () => {
    expect(
      queueHealthPresentation({
        health: undefined,
        syncing: 0,
        isPending: true,
        isError: false,
      }),
    ).toEqual({ label: "正在检查后台服务", state: "checking" });
  });

  it("surfaces degraded dependencies before account sync counts", () => {
    expect(
      queueHealthPresentation({
        health: degraded,
        syncing: 1,
        isPending: false,
        isError: false,
      }),
    ).toEqual({ label: "后台任务服务降级", state: "degraded" });
  });

  it("shows active synchronization only when readiness is healthy", () => {
    expect(
      queueHealthPresentation({
        health: healthy,
        syncing: 2,
        isPending: false,
        isError: false,
      }),
    ).toEqual({ label: "2 个同步中", state: "busy" });
  });

  it("distinguishes an unreachable health endpoint", () => {
    expect(
      queueHealthPresentation({
        health: undefined,
        syncing: 0,
        isPending: false,
        isError: true,
      }),
    ).toEqual({ label: "后台服务不可达", state: "unreachable" });
  });
});
