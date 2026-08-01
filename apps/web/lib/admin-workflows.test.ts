import { describe, expect, it } from "vitest";

import {
  serializeConditionNode,
  type Group,
} from "../app/automations/automation-editor";
import {
  buildAccountDetailPaths,
  buildAccountListPath,
  buildContentListPath,
  buildNewsListPath,
} from "./admin-queries";
import { normalizeNotificationConfig } from "./notification-config";

describe("管理后台 API 查询契约", () => {
  it("账号列表把搜索、平台、分页和真实排序传给后端", () => {
    const path = buildAccountListPath({
      page: 3,
      query: "Olympic creator",
      platform: "youtube",
    });
    const query = new URLSearchParams(path.split("?")[1]);
    expect(path.startsWith("/accounts?")).toBe(true);
    expect(Object.fromEntries(query)).toMatchObject({
      page: "3",
      page_size: "20",
      sort: "follower_count",
      order: "desc",
      query: "Olympic creator",
      platform: "youtube",
    });
  });

  it("账号详情使用同一账号 ID 请求详情、快照、作品和同步记录", () => {
    const paths = buildAccountDetailPaths("account / 42");
    expect(paths.account).toBe("/accounts/account%20%2F%2042");
    expect(paths.snapshots).toContain("/snapshots?page=1&page_size=100");
    expect(paths.contents).toContain("/contents?page=1&page_size=20");
    expect(paths.syncRuns).toContain("/sync-runs?page=1&page_size=20");
    expect(paths.automations).toContain("entity_type=account");
  });

  it("作品排序和高级筛选直接形成后端查询参数", () => {
    const path = buildContentListPath({
      page: 2,
      query: "final",
      platform: "youtube",
      minViews: "1000000",
      publishedFrom: "2026-07-01",
      sort: "view_growth_24h",
      order: "desc",
    });
    const query = new URLSearchParams(path.split("?")[1]);
    expect(query.get("sort")).toBe("view_growth_24h");
    expect(query.get("min_views")).toBe("1000000");
    expect(query.get("published_from")).toBe("2026-07-01T00:00:00.000Z");
  });

  it("新闻筛选保留项目、语言、关键词和收藏状态", () => {
    const path = buildNewsListPath({
      page: 1,
      query: "world record",
      sport: "athletics",
      language: "en",
      bookmarked: true,
    });
    const query = new URLSearchParams(path.split("?")[1]);
    expect(Object.fromEntries(query)).toMatchObject({
      query: "world record",
      sport: "athletics",
      language: "en",
      is_bookmarked: "true",
      sort: "published_at",
    });
  });
});

describe("可视化自动化与通知配置", () => {
  it("把嵌套 AND/NOT 条件构建器序列化为结构化 JSON", () => {
    const tree: Group = {
      id: "root",
      kind: "group",
      operator: "AND",
      conditions: [
        {
          id: "views",
          kind: "leaf",
          field: "view_count",
          operator: "gte",
          value: "1000000",
        },
        {
          id: "not-imported",
          kind: "group",
          operator: "NOT",
          conditions: [
            {
              id: "source",
              kind: "leaf",
              field: "source_kind",
              operator: "eq",
              value: "imported",
            },
          ],
        },
      ],
    };
    expect(serializeConditionNode(tree)).toEqual({
      operator: "AND",
      conditions: [
        { field: "view_count", operator: "gte", value: 1000000 },
        {
          operator: "NOT",
          conditions: [{ field: "source_kind", operator: "eq", value: "imported" }],
        },
      ],
    });
  });

  it("规范化邮件和 Webhook 表单但不改变密钥值", () => {
    expect(
      normalizeNotificationConfig({
        port: "587",
        to_emails: "ops@example.com, editor@example.com",
        headers: '{"X-Environment":"test"}',
        signing_secret: "backend-only-secret",
        use_tls: true,
      }),
    ).toEqual({
      port: 587,
      to_emails: ["ops@example.com", "editor@example.com"],
      headers: { "X-Environment": "test" },
      signing_secret: "backend-only-secret",
      use_tls: true,
    });
  });
});
