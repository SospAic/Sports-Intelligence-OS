import { describe, expect, it } from "vitest";

import { buildInboxItems } from "@/lib/inbox";

describe("buildInboxItems", () => {
  it("merges persisted task and notification records chronologically", () => {
    const items = buildInboxItems(
      [
        {
          id: "task-1",
          category: "platform_sync",
          task_type: "youtube:account",
          status: "running",
          started_at: "2026-08-16T08:00:00Z",
          finished_at: null,
          error_code: null,
          error_message: null,
          error_detail: null,
          error_hint: null,
          metadata: {},
        },
      ],
      [
        {
          id: "delivery-1",
          channel_id: "channel-123456",
          rule_id: null,
          entity_type: "content",
          entity_id: "content-1",
          payload: {},
          status: "failed",
          attempts: 1,
          sent_at: null,
          error: null,
          provider_message_id: null,
          created_at: "2026-08-16T09:00:00Z",
          updated_at: "2026-08-16T09:05:00Z",
        },
      ],
    );

    expect(items.map((item) => [item.kind, item.id])).toEqual([
      ["notification", "notification:delivery-1"],
      ["sync", "task:task-1"],
    ]);
    expect(items[0]?.detail).toContain("作品");
  });
});
