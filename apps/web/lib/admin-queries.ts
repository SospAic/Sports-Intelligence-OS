export type SortOrder = "asc" | "desc";

function withQuery(path: string, params: URLSearchParams): string {
  return `${path}?${params.toString()}`;
}

export function buildAccountListPath(input: {
  page: number;
  query?: string;
  platform?: string;
}): string {
  const params = new URLSearchParams({
    page: String(input.page),
    page_size: "20",
    sort: "follower_count",
    order: "desc",
  });
  if (input.query) params.set("query", input.query);
  if (input.platform) params.set("platform", input.platform);
  return withQuery("/accounts", params);
}

export function buildAccountDetailPaths(accountId: string) {
  const encoded = encodeURIComponent(accountId);
  return {
    account: `/accounts/${encoded}`,
    snapshots: `/accounts/${encoded}/snapshots?page=1&page_size=100`,
    contents: `/accounts/${encoded}/contents?page=1&page_size=20`,
    syncRuns: `/accounts/${encoded}/sync-runs?page=1&page_size=50`,
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
  return withQuery("/news/articles", params);
}
