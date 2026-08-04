export type SortOrder = "asc" | "desc";

function withQuery(path: string, params: URLSearchParams): string {
  return `${path}?${params.toString()}`;
}

export function buildAccountListPath(input: {
  page: number;
  query?: string;
  platform?: string;
  activeState?: "active" | "inactive" | "all";
}): string {
  const params = new URLSearchParams({
    page: String(input.page),
    page_size: "20",
    sort: "follower_count",
    order: "desc",
  });
  if (input.query) params.set("query", input.query);
  if (input.platform) params.set("platform", input.platform);
  if (input.activeState !== "all") {
    params.set("is_active", String(input.activeState !== "inactive"));
  }
  return withQuery("/accounts", params);
}

export function buildAccountExportPath(input: {
  query?: string;
  platform?: string;
  activeState?: "active" | "inactive" | "all";
}): string {
  const params = new URLSearchParams();
  if (input.query) params.set("query", input.query);
  if (input.platform) params.set("platform", input.platform);
  if (input.activeState !== "all") {
    params.set("is_active", String(input.activeState !== "inactive"));
  }
  return withQuery("/accounts/export.csv", params);
}

export function buildAccountDetailPaths(
  accountId: string,
  options: {
    sort?: string;
    order?: SortOrder;
    publishedFrom?: string | null;
    page?: number;
    pageSize?: number;
  } = {},
) {
  const encoded = encodeURIComponent(accountId);
  const contentsParams = new URLSearchParams({
    page: String(options.page ?? 1),
    page_size: String(options.pageSize ?? 20),
    sort: options.sort ?? "published_at",
    order: options.order ?? "desc",
  });
  if (options.publishedFrom) {
    contentsParams.set("published_from", options.publishedFrom);
  }
  return {
    account: `/accounts/${encoded}`,
    snapshots: `/accounts/${encoded}/snapshots?page=1&page_size=100`,
    contents: `/accounts/${encoded}/contents?${contentsParams.toString()}`,
    syncRuns: `/accounts/${encoded}/sync-runs?page=1&page_size=20`,
    syncRunDetail: (runId: string) =>
      `/accounts/${encoded}/sync-runs/${encodeURIComponent(runId)}`,
    automations: "/automations?page=1&page_size=100&entity_type=account",
  } as const;
}

export function buildContentListPath(input: {
  page: number;
  query?: string;
  platform?: string;
  minViews?: string;
  publishedFrom?: string;
  sort?: string;
  order?: SortOrder;
}): string {
  const params = new URLSearchParams({
    page: String(input.page),
    page_size: "20",
    sort: input.sort ?? "view_count",
    order: input.order ?? "desc",
  });
  if (input.query) params.set("query", input.query);
  if (input.platform) params.set("platform", input.platform);
  if (input.minViews) params.set("min_views", input.minViews);
  if (input.publishedFrom) {
    params.set(
      "published_from",
      new Date(`${input.publishedFrom}T00:00:00Z`).toISOString(),
    );
  }
  return withQuery("/contents", params);
}

export function buildNewsListPath(input: {
  page: number;
  query?: string;
  sport?: string;
  language?: string;
  bookmarked?: boolean;
  source?: string;
  league?: string;
  country?: string;
  publishedFrom?: string;
  publishedTo?: string;
  minHeat?: string;
}): string {
  const params = new URLSearchParams({
    page: String(input.page),
    page_size: "20",
    sort: "published_at",
    order: "desc",
  });
  if (input.query) params.set("query", input.query);
  if (input.sport) params.set("sport", input.sport);
  if (input.language) params.set("language", input.language);
  if (input.bookmarked) params.set("is_bookmarked", "true");
  if (input.source) params.set("source", input.source);
  if (input.league) params.set("league", input.league);
  if (input.country) params.set("country", input.country);
  if (input.publishedFrom) {
    params.set(
      "published_from",
      new Date(`${input.publishedFrom}T00:00:00Z`).toISOString(),
    );
  }
  if (input.publishedTo) {
    params.set(
      "published_to",
      new Date(`${input.publishedTo}T23:59:59Z`).toISOString(),
    );
  }
  if (input.minHeat) params.set("min_heat", input.minHeat);
  return withQuery("/news/articles", params);
}
