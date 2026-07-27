"use client";

import type {
  CurrentUserResponse,
  HealthResponse,
  MonitoringAccountPage,
  NotificationDeliveryPage,
} from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Bell,
  BookMarked,
  Bot,
  ChevronDown,
  CircleUserRound,
  Gauge,
  GitBranch,
  ListChecks,
  Menu,
  Moon,
  Newspaper,
  PanelLeftClose,
  Plus,
  Search,
  Settings,
  Sparkles,
  Sun,
  UsersRound,
  Video,
  Webhook,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { apiRequest } from "@/lib/browser-api";
import { fetchReadyHealth, queueHealthPresentation } from "@/lib/health";

type WorkspaceValue = {
  currentUser: CurrentUserResponse | null;
  workspaceId: string | null;
  role: string | null;
  loading: boolean;
};
const WorkspaceContext = createContext<WorkspaceValue>({
  currentUser: null,
  workspaceId: null,
  role: null,
  loading: true,
});
export function useWorkspace(): WorkspaceValue {
  return useContext(WorkspaceContext);
}

const navigation = [
  ["仪表盘", "/dashboard", Gauge],
  ["账号监控", "/accounts", UsersRound],
  ["作品数据", "/contents", Video],
  ["新闻热点", "/news", Newspaper],
  ["事件中心", "/events", Activity],
  ["选题库", "/topics", BookMarked],
  ["内容创作", "/generate", Sparkles],
  ["规则中心", "/rules", GitBranch],
  ["自动化", "/automations", Bot],
  ["通知渠道", "/notification-channels", Webhook],
  ["任务记录", "/tasks", ListChecks],
  ["系统日志", "/logs", Activity],
  ["设置", "/settings", Settings],
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const authPage = pathname === "/login";
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [search, setSearch] = useState("");
  const [userOpen, setUserOpen] = useState(false);
  const [quickOpen, setQuickOpen] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">(() =>
    typeof window !== "undefined" &&
    window.localStorage.getItem("sio-theme") === "light"
      ? "light"
      : "dark",
  );
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
    refetchInterval: 30_000,
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

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
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
  const failedDeliveries =
    deliveryQuery.data?.items.filter((item) => item.status === "failed")
      .length ?? 0;
  const syncing =
    syncQuery.data?.items.filter(
      (item) => item.sync_status === "queued" || item.sync_status === "syncing",
    ).length ?? 0;
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

  async function logout() {
    try {
      await apiRequest<void>("/auth/logout", { method: "POST", csrf: true });
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }
  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    window.localStorage.setItem("sio-theme", next);
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
        {navigation.map(([label, href, Icon]) => {
          const active =
            pathname === href ||
            (href !== "/dashboard" && pathname.startsWith(`${href}/`));
          return (
            <Link
              key={href}
              href={href}
              onClick={() => setMobileOpen(false)}
              title={collapsed ? label : undefined}
              className={`mb-1 flex h-10 items-center gap-3 rounded-lg px-3 text-sm transition ${active ? "bg-cyan-400/12 text-cyan-300" : "text-slate-400 hover:bg-slate-900 hover:text-slate-100"}`}
            >
              <Icon size={17} className="shrink-0" />
              {!collapsed && <span>{label}</span>}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-slate-800 p-3">
        <button
          className="hidden w-full items-center gap-3 rounded-lg px-2 py-2 text-left text-sm text-slate-400 hover:bg-slate-900 lg:flex"
          onClick={() => setCollapsed((value) => !value)}
        >
          <PanelLeftClose size={17} className={collapsed ? "rotate-180" : ""} />
          {!collapsed && "收起导航"}
        </button>
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
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索页面或功能…"
                className="h-10 w-full rounded-lg border border-slate-800 bg-slate-950/80 pr-3 pl-9 text-sm outline-none focus:border-cyan-600"
              />
              {search && (
                <div className="absolute top-12 left-0 z-50 w-full rounded-xl border border-slate-700 bg-slate-950 p-2 shadow-2xl">
                  {filteredNavigation.length ? (
                    filteredNavigation.map(([label, href, Icon]) => (
                      <Link
                        className="flex items-center gap-3 rounded-lg p-3 text-sm hover:bg-slate-900"
                        href={href}
                        key={href}
                        onClick={() => setSearch("")}
                      >
                        <Icon size={16} />
                        {label}
                      </Link>
                    ))
                  ) : (
                    <p className="p-3 text-sm text-slate-500">未找到匹配功能</p>
                  )}
                </div>
              )}
            </div>
            <div className="hidden items-center gap-2 text-xs text-slate-400 md:flex">
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
            </div>
            <div className="relative">
              <button
                aria-label="快速创建"
                className="grid size-9 place-items-center rounded-lg border border-slate-700 hover:bg-slate-900"
                onClick={() => setQuickOpen((value) => !value)}
              >
                <Plus size={18} />
              </button>
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
            <button
              aria-label="切换主题"
              className="grid size-9 place-items-center rounded-lg border border-slate-700 hover:bg-slate-900"
              onClick={toggleTheme}
            >
              {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
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
          <div className="min-h-[calc(100vh-4rem)]">{children}</div>
        </div>
      </div>
    </WorkspaceContext.Provider>
  );
}
