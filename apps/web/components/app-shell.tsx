"use client";

import type {
  CurrentUserResponse,
  HealthResponse,
  MonitoringAccountPage,
  NotificationDeliveryPage,
  SyncRunPage,
} from "@sio/shared-types";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Bell,
  BookMarked,
  Bot,
  ChevronDown,
  CircleUserRound,
  FileText,
  Gauge,
  GitBranch,
  ListChecks,
  Menu,
  Newspaper,
  PanelLeftClose,
  Plus,
  ScrollText,
  Search,
  Settings,
  Sparkles,
  TrendingUp,
  UsersRound,
  Video,
  Webhook,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { apiRequest } from "@/lib/browser-api";
import { fetchReadyHealth, queueHealthPresentation } from "@/lib/health";
import { Tooltip } from "@/components/ui";

type WorkspaceValue = {
  currentUser: CurrentUserResponse | null;
  workspaceId: string | null;
  role: string | null;
  loading: boolean;
};
type GlobalSearchPage = {
  items: Array<{
    entity_type: string;
    entity_id: string;
    title: string;
    subtitle: string;
    url: string;
  }>;
  total: number;
};

const searchSubtitleLabels: Record<string, string> = {
  video: "视频",
  article: "新闻",
  event: "事件",
  account: "账号",
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
  enabled: "已启用",
  disabled: "已停用",
  pending: "待处理",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
  error: "错误",
  healthy: "正常",
  degraded: "降级",
};

function localizeSearchSubtitle(value: string, entityType: string): string {
  const source = value || entityType;
  return source
    .split(" · ")
    .map((part) => searchSubtitleLabels[part] ?? part)
    .join(" · ");
}
const WorkspaceContext = createContext<WorkspaceValue>({
  currentUser: null,
  workspaceId: null,
  role: null,
  loading: true,
});
export function useWorkspace(): WorkspaceValue {
  return useContext(WorkspaceContext);
}

type NavigationItem = readonly [string, string, LucideIcon];
const navigationGroups: ReadonlyArray<{
  label: string;
  items: ReadonlyArray<NavigationItem>;
}> = [
  {
    label: "洞察",
    items: [
      ["仪表盘", "/dashboard", Gauge],
      ["趋势中心", "/trends", TrendingUp],
      ["账号监控", "/accounts", UsersRound],
      ["作品数据", "/contents", Video],
      ["新闻热点", "/news", Newspaper],
      ["事件中心", "/events", Activity],
    ],
  },
  {
    label: "创作",
    items: [
      ["选题库", "/topics", BookMarked],
      ["内容创作", "/generate", Sparkles],
      ["规则中心", "/rules", GitBranch],
    ],
  },
  {
    label: "自动化",
    items: [
      ["自动化规则", "/automations", Bot],
      ["通知模板", "/notification-templates", FileText],
      ["通知渠道", "/notification-channels", Webhook],
    ],
  },
  {
    label: "运维",
    items: [
      ["任务记录", "/tasks", ListChecks],
      ["调用记录", "/operations/external-calls", ScrollText],
      ["死信管理", "/operations/dead-letters", AlertTriangle],
      ["系统日志", "/logs", Activity],
      ["设置", "/settings", Settings],
    ],
  },
];
const navigation: NavigationItem[] = navigationGroups.flatMap(
  (group) => group.items,
);

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const authPage = pathname === "/login";
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [activeSearchIndex, setActiveSearchIndex] = useState(-1);
  const searchListRef = useRef<HTMLDivElement>(null);
  const [userOpen, setUserOpen] = useState(false);
  const [quickOpen, setQuickOpen] = useState(false);
  const [syncPopoverOpen, setSyncPopoverOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const userQuery = useQuery({
    queryKey: ["current-user"],
    queryFn: () => apiRequest<CurrentUserResponse>("/me"),
    enabled: !authPage,
    retry: false,
  });
  const currentUser = userQuery.data ?? null;
  const membership = currentUser?.memberships[0] ?? null;
  const workspaceId = membership?.workspace_id ?? null;
  const syncQuery = useQuery({
    queryKey: ["shell-sync", workspaceId],
    queryFn: () =>
      apiRequest<MonitoringAccountPage>(
        "/accounts?page=1&page_size=20&sort=last_synced_at&order=desc",
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
    refetchInterval: (query) => {
      const items = query.state.data?.items;
      if (!items) return 30_000;
      return items.some(
        (item) =>
          item.sync_status === "queued" || item.sync_status === "syncing",
      )
        ? 5_000
        : 30_000;
    },
  });
  const deliveryQuery = useQuery({
    queryKey: ["shell-deliveries", workspaceId],
    queryFn: () =>
      apiRequest<NotificationDeliveryPage>(
        "/notification-deliveries?page=1&page_size=20",
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
    refetchInterval: 30_000,
  });
  const healthQuery = useQuery<HealthResponse>({
    queryKey: ["shell-health"],
    queryFn: fetchReadyHealth,
    enabled: !authPage,
    refetchInterval: 30_000,
    retry: false,
  });
  const globalSearchQuery = useQuery({
    queryKey: ["global-search", workspaceId, debouncedSearch],
    queryFn: () =>
      apiRequest<GlobalSearchPage>(
        `/search?q=${encodeURIComponent(debouncedSearch)}&page=1&page_size=8`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId) && debouncedSearch.length >= 2,
    staleTime: 30_000,
  });

  // Fetch latest sync run for each syncing account (for header popover progress)
  const syncingAccountItems = useMemo(
    () =>
      (syncQuery.data?.items ?? []).filter(
        (item) =>
          item.sync_status === "queued" || item.sync_status === "syncing",
      ),
    [syncQuery.data],
  );
  const shellSyncRunQueries = useQueries({
    queries: syncingAccountItems.map((account) => ({
      queryKey: ["shell-account-run", account.id],
      queryFn: () =>
        apiRequest<SyncRunPage>(
          `/accounts/${encodeURIComponent(account.id)}/sync-runs?page=1&page_size=1`,
          { workspaceId: workspaceId! },
        ),
      enabled: Boolean(workspaceId),
      refetchInterval: 5_000,
    })),
  });

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedSearch(search.trim()),
      300,
    );
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (activeSearchIndex < 0 || !searchListRef.current) return;
    const activeEl = searchListRef.current.querySelector(
      `#global-search-option-${activeSearchIndex}`,
    );
    activeEl?.scrollIntoView({ block: "nearest" });
  }, [activeSearchIndex]);

  useEffect(() => {
    if (authPage) return;
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing =
        !!target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable);
      if (event.key === "/" && !typing && !shortcutsOpen) {
        event.preventDefault();
        searchInputRef.current?.focus();
        return;
      }
      if (event.key === "?" && !typing) {
        event.preventDefault();
        setShortcutsOpen((value) => !value);
        return;
      }
      if (event.key === "Escape" && shortcutsOpen) {
        setShortcutsOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [authPage, shortcutsOpen]);

  const context = useMemo(
    () => ({
      currentUser,
      workspaceId,
      role: membership?.role ?? null,
      loading: userQuery.isLoading,
    }),
    [currentUser, workspaceId, membership?.role, userQuery.isLoading],
  );
  if (authPage)
    return (
      <WorkspaceContext.Provider value={context}>
        {children}
      </WorkspaceContext.Provider>
    );
  if (userQuery.isLoading) {
    return (
      <WorkspaceContext.Provider value={context}>
        <div
          className="grid min-h-screen place-items-center px-6"
          aria-busy="true"
          aria-label="正在加载工作区"
        >
          <div className="w-full max-w-sm text-center">
            <div className="mx-auto grid size-12 place-items-center rounded-2xl bg-cyan-400 font-black text-slate-950 shadow-lg shadow-cyan-950/40">
              SI
            </div>
            <p className="mt-4 text-sm text-slate-300">正在加载工作区…</p>
            <div className="mx-auto mt-4 h-1 w-40 overflow-hidden rounded-full bg-slate-800">
              <span className="block h-full w-1/2 animate-pulse rounded-full bg-cyan-400" />
            </div>
          </div>
        </div>
      </WorkspaceContext.Provider>
    );
  }
  const failedDeliveries =
    deliveryQuery.data?.items.filter((item) => item.status === "failed")
      .length ?? 0;
  const syncing =
    syncQuery.data?.items.filter(
      (item) => item.sync_status === "queued" || item.sync_status === "syncing",
    ).length ?? 0;
  const syncingAccounts = syncingAccountItems;
  const shellSyncRunMap = new Map<
    string,
    { progress_percent: number; progress_stage: string } | undefined
  >();
  syncingAccountItems.forEach((account, index) => {
    const run = shellSyncRunQueries[index]?.data?.items[0];
    if (run) {
      shellSyncRunMap.set(account.id, {
        progress_percent: run.progress_percent,
        progress_stage: run.progress_stage,
      });
    }
  });
  const queueHealth = queueHealthPresentation({
    health: healthQuery.data,
    syncing,
    isPending: healthQuery.isPending,
    isError: healthQuery.isError,
  });
  const filteredNavigation = search.trim()
    ? navigation.filter(([label]) =>
        label.toLowerCase().includes(search.trim().toLowerCase()),
      )
    : [];
  const searchResults = [
    ...(globalSearchQuery.data?.items ?? []).map((item) => ({
      id: `${item.entity_type}:${item.entity_id}`,
      title: item.title,
      subtitle: localizeSearchSubtitle(item.subtitle, item.entity_type),
      url: item.url,
      icon: null,
    })),
    ...filteredNavigation.map(([label, url, icon]) => ({
      id: `navigation:${url}`,
      title: label,
      subtitle: "页面功能",
      url,
      icon,
    })),
  ];

  async function logout() {
    try {
      await apiRequest<void>("/auth/logout", { method: "POST", csrf: true });
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }
  const side = (
    <>
      <div className="flex h-16 items-center gap-3 border-b border-slate-800 px-4">
        <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-cyan-400 font-black text-slate-950">
          SI
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-white">
              Sports Intelligence OS
            </p>
            <p className="text-[11px] text-slate-500">体育内容情报工作台</p>
          </div>
        )}
        <button
          aria-label="关闭导航"
          className="ml-auto lg:hidden"
          onClick={() => setMobileOpen(false)}
        >
          <X size={20} />
        </button>
      </div>
      <nav className="flex-1 overflow-y-auto p-2" aria-label="主导航">
        {navigationGroups.map((group) => (
          <div className="mb-3" key={group.label}>
            {!collapsed && (
              <p className="px-3 py-2 text-[10px] font-semibold tracking-[.18em] text-slate-600 uppercase">
                {group.label}
              </p>
            )}
            {group.items.map(([label, href, Icon]) => {
              const active =
                pathname === href ||
                (href !== "/dashboard" && pathname.startsWith(`${href}/`));
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  onClick={() => setMobileOpen(false)}
                  title={collapsed ? label : undefined}
                  className={`mb-1 flex h-10 items-center gap-3 rounded-lg px-3 text-sm transition ${active ? "bg-cyan-400/12 text-cyan-300" : "text-slate-400 hover:bg-slate-900 hover:text-slate-100"}`}
                >
                  <Icon size={17} className="shrink-0" />
                  {!collapsed && <span>{label}</span>}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="border-t border-slate-800 p-3">
        <Tooltip label={collapsed ? "展开导航" : "收起导航"}>
          <button
            className="hidden w-full items-center gap-3 rounded-lg px-2 py-2 text-left text-sm text-slate-400 hover:bg-slate-900 lg:flex"
            onClick={() => setCollapsed((value) => !value)}
          >
            <PanelLeftClose size={17} className={collapsed ? "rotate-180" : ""} />
            {!collapsed && "收起导航"}
          </button>
        </Tooltip>
      </div>
    </>
  );

  return (
    <WorkspaceContext.Provider value={context}>
      <div className="min-h-screen bg-transparent text-slate-100">
        {mobileOpen && (
          <button
            aria-label="关闭导航遮罩"
            className="fixed inset-0 z-40 bg-black/60 lg:hidden"
            onClick={() => setMobileOpen(false)}
          />
        )}
        <aside
          className={`fixed inset-y-0 left-0 z-50 flex border-r border-slate-800 bg-slate-950/95 backdrop-blur transition-all ${mobileOpen ? "translate-x-0" : "-translate-x-full"} ${collapsed ? "lg:w-[4.25rem]" : "lg:w-60"} w-60 lg:translate-x-0`}
        >
          <div className="flex w-full flex-col">{side}</div>
        </aside>
        <div
          className={`transition-[padding] ${collapsed ? "lg:pl-[4.25rem]" : "lg:pl-60"}`}
        >
          <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-slate-800 bg-[#07101c]/90 px-4 backdrop-blur lg:px-6">
            <button
              aria-label="打开导航"
              className="lg:hidden"
              onClick={() => setMobileOpen(true)}
            >
              <Menu size={21} />
            </button>
            <div className="relative min-w-0 max-w-xl flex-1">
              <Search
                className="absolute top-1/2 left-3 -translate-y-1/2 text-slate-500"
                size={16}
              />
              <input
                aria-label="全局搜索"
                role="combobox"
                aria-autocomplete="list"
                aria-expanded={Boolean(search)}
                aria-controls="global-search-results"
                aria-activedescendant={
                  activeSearchIndex >= 0
                    ? `global-search-option-${activeSearchIndex}`
                    : undefined
                }
                ref={searchInputRef}
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setActiveSearchIndex(-1);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    setSearch("");
                    return;
                  }
                  if (!searchResults.length) return;
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    setActiveSearchIndex(
                      (index) => (index + 1) % searchResults.length,
                    );
                    return;
                  }
                  if (event.key === "ArrowUp") {
                    event.preventDefault();
                    setActiveSearchIndex((index) =>
                      index <= 0
                        ? searchResults.length - 1
                        : index - 1,
                    );
                    return;
                  }
                  const selectedResult = searchResults[activeSearchIndex];
                  if (event.key === "Enter" && selectedResult) {
                    event.preventDefault();
                    router.push(selectedResult.url);
                    setSearch("");
                  }
                }}
                placeholder="搜索页面或功能…"
                className="h-10 w-full rounded-lg border border-slate-800 bg-slate-950/80 pr-3 pl-9 text-sm outline-none focus:border-cyan-600"
              />
              {search && (
                <div
                  id="global-search-results"
                  ref={searchListRef}
                  className="absolute top-12 left-0 z-50 w-full rounded-xl border border-slate-700 bg-slate-950 p-2 shadow-2xl"
                  aria-live="polite"
                  role="listbox"
                >
                  {globalSearchQuery.data?.items.map((item) => (
                    <Link
                      aria-selected={
                        searchResults[activeSearchIndex]?.id ===
                        `${item.entity_type}:${item.entity_id}`
                      }
                      className={`block rounded-lg p-3 text-sm hover:bg-slate-900 ${searchResults[activeSearchIndex]?.id === `${item.entity_type}:${item.entity_id}` ? "bg-cyan-400/10 text-cyan-100" : ""}`}
                      href={item.url}
                      key={`${item.entity_type}:${item.entity_id}`}
                      id={`global-search-option-${searchResults.findIndex((result) => result.id === `${item.entity_type}:${item.entity_id}`)}`}
                      onClick={() => setSearch("")}
                      role="option"
                    >
                      <span className="block truncate text-slate-200">
                        {item.title}
                      </span>
                      <span className="mt-1 block truncate text-xs text-slate-500">
                        {localizeSearchSubtitle(
                          item.subtitle,
                          item.entity_type,
                        )}
                      </span>
                    </Link>
                  ))}
                  {!!globalSearchQuery.data?.items.length &&
                    filteredNavigation.length > 0 && (
                      <div className="my-1 border-t border-slate-800" />
                    )}
                  {filteredNavigation.length ? (
                    filteredNavigation.map(([label, href, Icon]) => (
                      <Link
                        aria-selected={
                          searchResults[activeSearchIndex]?.id ===
                          `navigation:${href}`
                        }
                        className={`flex items-center gap-3 rounded-lg p-3 text-sm hover:bg-slate-900 ${searchResults[activeSearchIndex]?.id === `navigation:${href}` ? "bg-cyan-400/10 text-cyan-100" : ""}`}
                        href={href}
                        key={href}
                        id={`global-search-option-${searchResults.findIndex((result) => result.id === `navigation:${href}`)}`}
                        onClick={() => setSearch("")}
                        role="option"
                      >
                        <Icon size={16} />
                        {label}
                      </Link>
                    ))
                  ) : search.trim().length < 2 ? (
                    <p className="p-3 text-sm text-slate-500">
                      至少输入 2 个字符
                    </p>
                  ) : globalSearchQuery.isFetching ? (
                    <p className="animate-pulse p-3 text-sm text-cyan-300">
                      正在搜索…
                    </p>
                  ) : globalSearchQuery.isError ? (
                    <button
                      className="w-full rounded-lg p-3 text-left text-sm text-rose-300 hover:bg-slate-900"
                      onClick={() => globalSearchQuery.refetch()}
                    >
                      搜索失败，点击重试
                    </button>
                  ) : globalSearchQuery.data?.items.length ? null : (
                    <p className="p-3 text-sm text-slate-500">未找到匹配结果</p>
                  )}
                </div>
              )}
            </div>
            <div className="relative hidden md:block">
              <button
                aria-label={`同步状态：${queueHealth.label}`}
                title={queueHealth.label}
                className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-slate-400 transition hover:bg-slate-900 hover:text-slate-200"
                onClick={() => setSyncPopoverOpen((value) => !value)}
              >
                <Activity
                  size={15}
                  className={
                    {
                      checking: "animate-pulse text-slate-400",
                      healthy: "text-emerald-400",
                      busy: "animate-pulse text-cyan-400",
                      degraded: "text-amber-400",
                      unreachable: "text-rose-400",
                    }[queueHealth.state]
                  }
                />
                {queueHealth.label}
                {syncing > 0 && (
                  <span className="min-w-4 rounded-full bg-cyan-500/20 px-1.5 text-center text-[10px] font-semibold text-cyan-300">
                    {syncing}
                  </span>
                )}
              </button>
              {syncPopoverOpen && (
                <div className="absolute top-11 right-0 z-50 w-80 rounded-xl border border-slate-700 bg-slate-950 shadow-2xl">
                  <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
                    <p className="text-sm font-medium text-white">同步状态</p>
                    <button
                      aria-label="关闭"
                      className="grid size-6 place-items-center rounded text-slate-500 hover:bg-slate-800 hover:text-white"
                      onClick={() => setSyncPopoverOpen(false)}
                    >
                      <X size={14} />
                    </button>
                  </div>
                  <div className="max-h-72 overflow-y-auto p-3">
                    {syncingAccounts.length === 0 ? (
                      <p className="py-4 text-center text-sm text-slate-500">
                        当前没有正在同步的账号
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {syncingAccounts.map((account) => {
                          const run = shellSyncRunMap.get(account.id);
                          return (
                            <Link
                              href={`/accounts/${account.id}`}
                              className="block rounded-lg border border-slate-800 p-3 transition hover:border-slate-700 hover:bg-slate-900"
                              key={account.id}
                              onClick={() => setSyncPopoverOpen(false)}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="truncate text-sm text-slate-200">
                                  {account.display_name}
                                </span>
                                <span className="shrink-0 text-[11px] text-slate-500">
                                  {account.platform.name}
                                </span>
                              </div>
                              <div className="mt-2 flex items-center gap-2">
                                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-800">
                                  <div
                                    className="h-full rounded-full bg-cyan-400 transition-all duration-700"
                                    style={{
                                      width: `${Math.max(run?.progress_percent ?? 0, 2)}%`,
                                    }}
                                  />
                                </div>
                                <span className="shrink-0 text-[11px] tabular-nums text-cyan-300">
                                  {run?.progress_percent ?? 0}%
                                </span>
                              </div>
                              {run?.progress_stage && (
                                <p className="mt-1.5 text-[11px] text-slate-500">
                                  {
                                    {
                                      queued: "排队",
                                      validating: "校验",
                                      account_profile: "账号资料",
                                      content_list: "作品列表",
                                      content_metrics: "指标",
                                      derived_metrics: "派生",
                                      completed: "完成",
                                    }[run.progress_stage] ??
                                      run.progress_stage
                                  }
                                  {account.sync_status === "queued"
                                    ? " · 排队中"
                                    : ""}
                                </p>
                              )}
                            </Link>
                          );
                        })}
                      </div>
                    )}
                  </div>
                  <div className="border-t border-slate-800 p-3">
                    <Link
                      className="block text-center text-xs text-cyan-300 hover:text-cyan-200"
                      href="/accounts"
                      onClick={() => setSyncPopoverOpen(false)}
                    >
                      查看全部
                    </Link>
                  </div>
                </div>
              )}
            </div>
            <div className="relative">
              <Tooltip label="快速创建">
                <button
                  aria-label="快速创建"
                  className="grid size-9 place-items-center rounded-lg border border-slate-700 hover:bg-slate-900"
                  onClick={() => setQuickOpen((value) => !value)}
                >
                  <Plus size={18} />
                </button>
              </Tooltip>
              {quickOpen && (
                <div className="absolute top-11 right-0 w-44 rounded-xl border border-slate-700 bg-slate-950 p-2 shadow-2xl">
                  <Link
                    className="block rounded-lg p-2 text-sm hover:bg-slate-900"
                    href="/accounts?create=1"
                  >
                    添加账号
                  </Link>
                  <Link
                    className="block rounded-lg p-2 text-sm hover:bg-slate-900"
                    href="/generate"
                  >
                    创建内容
                  </Link>
                  <Link
                    className="block rounded-lg p-2 text-sm hover:bg-slate-900"
                    href="/automations/new"
                  >
                    新建自动化
                  </Link>
                </div>
              )}
            </div>
            <Tooltip label="通知中心">
              <Link
                aria-label={`通知中心，${failedDeliveries} 条失败`}
                href="/notification-channels#deliveries"
                className="relative grid size-9 place-items-center rounded-lg border border-slate-700 hover:bg-slate-900"
              >
                <Bell size={18} />
                {failedDeliveries > 0 && (
                  <span className="absolute -top-1 -right-1 min-w-4 rounded-full bg-rose-500 px-1 text-center text-[10px] text-white">
                    {failedDeliveries}
                  </span>
                )}
              </Link>
            </Tooltip>
            <div className="relative">
              <button
                className="flex h-9 items-center gap-2 rounded-lg border border-slate-700 px-2 text-sm hover:bg-slate-900"
                onClick={() => setUserOpen((value) => !value)}
              >
                <CircleUserRound size={18} />
                <span className="hidden max-w-28 truncate xl:inline">
                  {currentUser?.user.display_name ||
                    currentUser?.user.email ||
                    "用户"}
                </span>
                <ChevronDown size={14} />
              </button>
              {userOpen && (
                <div className="absolute top-11 right-0 w-56 rounded-xl border border-slate-700 bg-slate-950 p-2 shadow-2xl">
                  <div className="border-b border-slate-800 p-2">
                    <p className="truncate text-sm text-white">
                      {currentUser?.user.email}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {membership?.workspace_name} · {membership?.role}
                    </p>
                  </div>
                  <Link
                    className="mt-1 block rounded-lg p-2 text-sm hover:bg-slate-900"
                    href="/settings"
                  >
                    个人与工作区设置
                  </Link>
                  <button
                    className="w-full rounded-lg p-2 text-left text-sm text-rose-300 hover:bg-slate-900"
                    onClick={logout}
                  >
                    退出登录
                  </button>
                </div>
              )}
            </div>
          </header>
          <div className="page-enter min-h-[calc(100vh-4rem)]" key={pathname}>
            {children}
          </div>
        </div>
        {shortcutsOpen && (
          <ShortcutsHelp onClose={() => setShortcutsOpen(false)} />
        )}
      </div>
    </WorkspaceContext.Provider>
  );
}

/* ------------------------------------------------------------------ */
/*  Keyboard shortcuts help dialog                                    */
/* ------------------------------------------------------------------ */
const SHORTCUT_ITEMS: Array<[string, string]> = [
  ["/", "聚焦全局搜索"],
  ["?", "打开 / 关闭本帮助"],
  ["Esc", "关闭弹窗 / 清空搜索"],
];

function ShortcutsHelp({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="键盘快捷键"
    >
      <button
        aria-label="关闭快捷键帮助"
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
        tabIndex={-1}
      />
      <div className="relative w-full max-w-md rounded-2xl border border-slate-700 bg-slate-950 p-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">键盘快捷键</h2>
          <button
            aria-label="关闭"
            className="grid size-8 place-items-center rounded-lg border border-slate-700 text-slate-400 hover:bg-slate-800"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>
        <ul className="mt-4 space-y-2">
          {SHORTCUT_ITEMS.map(([key, label]) => (
            <li
              key={key}
              className="flex items-center justify-between gap-4 text-sm"
            >
              <span className="text-slate-300">{label}</span>
              <kbd className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-xs text-cyan-300">
                {key}
              </kbd>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-xs text-slate-500">
          在输入框中按键时快捷键不会触发，便于正常输入。
        </p>
      </div>
    </div>
  );
}
