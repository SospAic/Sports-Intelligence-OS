"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Clock3,
  Flame,
  Heart,
  MessageCircle,
  Play,
  RefreshCw,
  Share2,
  ThumbsUp,
  TrendingUp,
  Video,
  Zap,
} from "lucide-react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

import { useUrlState } from "@/lib/use-persisted-state";

import { useWorkspace } from "@/components/app-shell";
import { ExternalImage } from "@/components/external-image";
import { ScoreExplanationPanel } from "@/components/score-explanation";
import { useToast } from "@/components/toast";
import { DerivativesPanel } from "@/components/derivatives-panel";
import { SearchPanel } from "@/components/search-panel";
import { AnalyticsClient } from "./analytics/analytics-client";
import {
  Badge,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  buttonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatNumber } from "@/lib/format";

// ─── Types ───────────────────────────────────────────────────────────────────

type Platform = "all" | "youtube" | "tiktok" | "douyin" | "bilibili";

interface PlatformSummary {
  platform: string;
  topic_count: number;
  video_count: number;
  avg_heat_score: number;
  max_breakout_score: number | null;
  total_views: number | null;
}

interface TrendingTopic {
  id: string;
  rank: number;
  title: string;
  platform: string;
  heat_score: number;
  growth_rate: number | null;
  category: string;
  sample_size: number;
  observed_at: string;
  metadata?: Record<string, unknown> & {
    source_kind?: string;
    confidence_score?: number;
  };
}

interface BreakoutVideo {
  id: string;
  title: string;
  author_name: string | null;
  platform: string;
  cover_url: string | null;
  video_url: string | null;
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
  share_count: number | null;
  breakout_score: number | null;
  category?: string;
  observed_at: string;
  metadata?: Record<string, unknown> & {
    source_kind?: string;
    confidence_score?: number;
    duration?: string;
    danmaku_count?: number;
    coin_count?: number;
    favorite_count?: number;
    forward_count?: number;
    digg_count?: number;
  };
}

interface KeywordStat {
  keyword: string;
  platform: string;
  heat_index: number | null;
  observed_at: string;
  metadata?: Record<string, unknown> & { confidence_score?: number };
  video_count: number | null;
  total_views: number | null;
}

interface DashboardResponse {
  top_topics: TrendingTopic[];
  breakout_videos: BreakoutVideo[];
  platform_summary: PlatformSummary[];
}

interface TopicsPageResponse {
  items: TrendingTopic[];
  total: number;
  page: number;
  page_size: number;
}

interface VideosPageResponse {
  items: BreakoutVideo[];
  total: number;
  page: number;
  page_size: number;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const PLATFORM_TABS: { key: Platform; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "youtube", label: "YouTube" },
  { key: "tiktok", label: "TikTok" },
  { key: "douyin", label: "抖音" },
  { key: "bilibili", label: "Bilibili" },
];

const PLATFORM_LABELS: Record<string, string> = Object.fromEntries(
  PLATFORM_TABS.filter((item) => item.key !== "all").map((item) => [
    item.key,
    item.label,
  ]),
);

const PLATFORM_COLORS: Record<string, string> = {
  youtube: "#EF4444",
  tiktok: "#EC4899",
  douyin: "#06B6D4",
  bilibili: "#3B82F6",
};

const PLATFORM_BG: Record<string, string> = {
  youtube: "bg-red-500/10 border-red-500/30",
  tiktok: "bg-pink-500/10 border-pink-500/30",
  douyin: "bg-cyan-500/10 border-cyan-500/30",
  bilibili: "bg-blue-500/10 border-blue-500/30",
};

const PLATFORM_TEXT: Record<string, string> = {
  youtube: "text-red-400",
  tiktok: "text-pink-400",
  douyin: "text-cyan-400",
  bilibili: "text-blue-400",
};

const PLATFORM_ACCENT: Record<string, string> = {
  youtube: "from-red-500/20 to-transparent",
  tiktok: "from-pink-500/20 to-transparent",
  douyin: "from-cyan-500/20 to-transparent",
  bilibili: "from-blue-500/20 to-transparent",
};

/** Platform-specific sort options mapped to backend sort_by fields */
const PLATFORM_SORT_OPTIONS: Record<
  Platform,
  { value: string; label: string }[]
> = {
  all: [
    { value: "breakout_score", label: "热度" },
    { value: "view_count", label: "播放量" },
    { value: "observed_at", label: "发布时间" },
  ],
  youtube: [
    { value: "breakout_score", label: "热度" },
    { value: "view_count", label: "播放量" },
    { value: "observed_at", label: "发布时间" },
    { value: "like_count", label: "增长率" },
  ],
  tiktok: [
    { value: "breakout_score", label: "热度" },
    { value: "view_count", label: "播放量" },
    { value: "comment_count", label: "互动率" },
  ],
  douyin: [
    { value: "breakout_score", label: "热度" },
    { value: "view_count", label: "播放量" },
    { value: "like_count", label: "点赞量" },
  ],
  bilibili: [
    { value: "breakout_score", label: "热度" },
    { value: "view_count", label: "播放量" },
    { value: "comment_count", label: "弹幕数" },
  ],
};

const PAGE_SIZE = 20;

const CATEGORIES = [
  "全部",
  "sports",
  "basketball",
  "football",
  "olympics",
  "esports",
  "fitness",
  "mma",
  "motorsport",
  "baseball",
  "american_football",
  "ice_hockey",
  "golf",
  "volleyball",
  "swimming",
  "athletics",
  "tennis",
  "badminton",
  "table_tennis",
];

const CATEGORY_LABELS: Record<string, string> = {
  全部: "全部",
  sports: "综合体育",
  basketball: "篮球",
  football: "足球",
  olympics: "奥运",
  esports: "电竞",
  fitness: "健身",
  mma: "格斗",
  motorsport: "赛车",
  baseball: "棒球",
  american_football: "橄榄球",
  ice_hockey: "冰球",
  golf: "高尔夫",
  volleyball: "排球",
  swimming: "游泳",
  athletics: "田径",
  tennis: "网球",
  badminton: "羽毛球",
  table_tennis: "乒乓球",
};

// ─── Helper Functions ────────────────────────────────────────────────────────

function getPlatformBadgeTone(
  platform: string,
): "neutral" | "success" | "warning" | "danger" | "info" {
  switch (platform.toLowerCase()) {
    case "youtube":
      return "danger";
    case "tiktok":
      return "warning";
    case "douyin":
      return "info";
    case "bilibili":
      return "success";
    default:
      return "neutral";
  }
}

function formatGrowthRate(rate: number): string {
  const percent = (rate * 100).toFixed(1);
  return rate >= 0 ? `+${percent}%` : `${percent}%`;
}

function confidenceLabel(value: unknown): string {
  if (typeof value !== "number") return "置信度未提供";
  const score = value;
  if (score >= 0.75) return `高置信度 ${Math.round(score * 100)}%`;
  if (score >= 0.45) return `中置信度 ${Math.round(score * 100)}%`;
  return `低置信度 ${Math.round(score * 100)}%`;
}

function formatDuration(duration: string | undefined): string {
  if (!duration) return "";
  // Handle ISO 8601 duration (PT1H2M3S) or plain seconds
  const isoMatch = duration.match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
  if (isoMatch) {
    const hours = parseInt(isoMatch[1] || "0", 10);
    const minutes = parseInt(isoMatch[2] || "0", 10);
    const seconds = parseInt(isoMatch[3] || "0", 10);
    if (hours > 0)
      return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }
  const totalSeconds = parseInt(duration, 10);
  if (!Number.isNaN(totalSeconds)) {
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    if (h > 0)
      return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    return `${m}:${String(s).padStart(2, "0")}`;
  }
  return duration;
}

function formatRelativeDate(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  if (diffHours < 1) return "刚刚";
  if (diffHours < 24) return `${diffHours}小时前`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays}天前`;
  return date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
}

// ─── Platform-Specific Video Stat Components ─────────────────────────────────

function VideoStatItem({
  icon,
  value,
  label,
}: {
  icon: React.ReactNode;
  value: number | null | undefined;
  label: string;
}) {
  return (
    <span
      className="inline-flex items-center gap-1 text-xs text-slate-400"
      title={label}
    >
      {icon}
      <span>{formatNumber(value)}</span>
    </span>
  );
}

function YouTubeVideoStats({ video }: { video: BreakoutVideo }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <VideoStatItem
        icon={<Play size={12} />}
        value={video.view_count}
        label="播放量"
      />
      <VideoStatItem
        icon={<ThumbsUp size={12} />}
        value={video.like_count}
        label="点赞"
      />
      <VideoStatItem
        icon={<MessageCircle size={12} />}
        value={video.comment_count}
        label="评论"
      />
      {video.metadata?.duration && (
        <span className="text-xs text-slate-500">
          {formatDuration(video.metadata.duration as string)}
        </span>
      )}
      <span className="text-xs text-slate-500">
        {formatRelativeDate(video.observed_at)}
      </span>
    </div>
  );
}

function TikTokVideoStats({ video }: { video: BreakoutVideo }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <VideoStatItem
        icon={<Play size={12} />}
        value={video.view_count}
        label="播放量"
      />
      <VideoStatItem
        icon={<Heart size={12} />}
        value={video.like_count}
        label="点赞"
      />
      <VideoStatItem
        icon={<Share2 size={12} />}
        value={video.share_count}
        label="分享"
      />
      <VideoStatItem
        icon={<MessageCircle size={12} />}
        value={video.comment_count}
        label="评论"
      />
    </div>
  );
}

function DouyinVideoStats({ video }: { video: BreakoutVideo }) {
  const diggCount = video.metadata?.digg_count ?? video.like_count;
  const forwardCount = video.metadata?.forward_count ?? video.share_count;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <VideoStatItem
        icon={<Play size={12} />}
        value={video.view_count}
        label="播放量"
      />
      <VideoStatItem
        icon={<Heart size={12} />}
        value={diggCount}
        label="点赞"
      />
      <VideoStatItem
        icon={<Share2 size={12} />}
        value={forwardCount}
        label="转发"
      />
    </div>
  );
}

function BilibiliVideoStats({ video }: { video: BreakoutVideo }) {
  const danmakuCount = video.metadata?.danmaku_count ?? video.comment_count;
  const coinCount = video.metadata?.coin_count;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <VideoStatItem
        icon={<Play size={12} />}
        value={video.view_count}
        label="播放量"
      />
      <VideoStatItem
        icon={<MessageCircle size={12} />}
        value={danmakuCount}
        label="弹幕"
      />
      <VideoStatItem
        icon={<ThumbsUp size={12} />}
        value={video.like_count}
        label="点赞"
      />
      {coinCount != null && (
        <VideoStatItem
          icon={<Zap size={12} />}
          value={coinCount}
          label="投币"
        />
      )}
    </div>
  );
}

function PlatformVideoStats({
  video,
  platform,
}: {
  video: BreakoutVideo;
  platform: Platform;
}) {
  const effectivePlatform =
    platform === "all" ? video.platform.toLowerCase() : platform;
  switch (effectivePlatform) {
    case "youtube":
      return <YouTubeVideoStats video={video} />;
    case "tiktok":
      return <TikTokVideoStats video={video} />;
    case "douyin":
      return <DouyinVideoStats video={video} />;
    case "bilibili":
      return <BilibiliVideoStats video={video} />;
    default:
      return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <VideoStatItem
            icon={<Play size={12} />}
            value={video.view_count}
            label="播放量"
          />
          <VideoStatItem
            icon={<ThumbsUp size={12} />}
            value={video.like_count}
            label="点赞"
          />
        </div>
      );
  }
}

// ─── Video Card Component ────────────────────────────────────────────────────

function VideoCard({
  video,
  platform,
  workspaceId,
}: {
  video: BreakoutVideo;
  platform: Platform;
  workspaceId: string | null;
}) {
  return (
    <div className="group flex gap-3 rounded-xl border border-slate-800/60 bg-slate-900/40 p-3 transition hover:border-slate-700 hover:bg-slate-900/70">
      {/* Thumbnail / Cover */}
      <div className="relative aspect-video w-28 shrink-0 overflow-hidden rounded-lg bg-slate-800 sm:w-36">
        {video.cover_url ? (
          <ExternalImage
            src={video.cover_url}
            alt={video.title}
            className="size-full object-cover transition-transform duration-200 group-hover:scale-105"
            containerClassName="size-full"
          />
        ) : (
          <div className="grid size-full place-items-center">
            <Video size={20} className="text-slate-600" />
          </div>
        )}
        {/* Breakout score badge */}
        {video.breakout_score != null && (
          <div
            title={`多信号高潜分；${confidenceLabel(video.metadata?.confidence_score)}`}
            className={`absolute bottom-1 right-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold shadow ${
              video.breakout_score >= 80
                ? "bg-amber-500 text-white"
                : video.breakout_score >= 60
                  ? "bg-emerald-500 text-white"
                  : "bg-slate-600/90 text-white"
            }`}
          >
            {video.breakout_score.toFixed(1)}
          </div>
        )}
        {/* Duration badge for YouTube */}
        {(platform === "youtube" ||
          (platform === "all" && video.platform.toLowerCase() === "youtube")) &&
          video.metadata?.duration && (
            <div className="absolute bottom-1 left-1 rounded bg-black/80 px-1 py-0.5 text-[10px] font-medium text-white">
              {formatDuration(video.metadata.duration as string)}
            </div>
          )}
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <h3 className="line-clamp-2 text-sm font-medium leading-5 text-slate-100 transition group-hover:text-white">
          {video.title}
        </h3>
        <p className="mt-1 truncate text-xs text-slate-500">
          {video.author_name ?? "未知作者"}
        </p>
        <div className="mt-2">
          <PlatformVideoStats video={video} platform={platform} />
        </div>
        <div className="mt-1.5 flex items-center gap-2 text-[11px] text-slate-600">
          {platform === "all" && (
            <Badge tone={getPlatformBadgeTone(video.platform)}>
              {PLATFORM_LABELS[video.platform.toLowerCase()] ?? video.platform}
            </Badge>
          )}
          {video.metadata?.source_kind === "live" && (
            <span className="inline-flex items-center gap-1 text-emerald-400">
              <span className="size-1.5 rounded-full bg-emerald-400" />
              实时
            </span>
          )}
        </div>
        {workspaceId && (
          <ScoreExplanationPanel
            entityType="video"
            entityId={video.id}
            apiPath={`/trends/videos/${video.id}/explain`}
            workspaceId={workspaceId}
          />
        )}
      </div>
    </div>
  );
}

// ─── Pagination Component ────────────────────────────────────────────────────

function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onLoadMore,
  isLoading,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onLoadMore: () => void;
  isLoading: boolean;
}) {
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) return null;

  // Generate page numbers to display (max 5 visible)
  const getPageNumbers = (): (number | "...")[] => {
    const pages: (number | "...")[] = [];
    if (totalPages <= 5) {
      for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
      pages.push(1);
      if (page > 3) pages.push("...");
      const start = Math.max(2, page - 1);
      const end = Math.min(totalPages - 1, page + 1);
      for (let i = start; i <= end; i++) pages.push(i);
      if (page < totalPages - 2) pages.push("...");
      pages.push(totalPages);
    }
    return pages;
  };

  const hasMore = page < totalPages;

  return (
    <div className="flex flex-col items-center gap-3 border-t border-slate-800/60 px-5 py-4">
      {/* Load More Button */}
      {hasMore && (
        <button
          onClick={onLoadMore}
          disabled={isLoading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-4 py-2 text-sm font-medium text-slate-200 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoading ? (
            <RefreshCw size={14} className="animate-spin" />
          ) : (
            <ChevronRight size={14} />
          )}
          {isLoading ? "加载中…" : "加载更多"}
        </button>
      )}

      {/* Page Numbers */}
      <div className="flex items-center gap-1">
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1 || isLoading}
          className="grid size-8 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-800 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-30"
          aria-label="上一页"
        >
          <ChevronLeft size={16} />
        </button>

        {getPageNumbers().map((pageNum, idx) =>
          pageNum === "..." ? (
            <span
              key={`ellipsis-${idx}`}
              className="px-1 text-sm text-slate-600"
            >
              …
            </span>
          ) : (
            <button
              key={pageNum}
              onClick={() => onPageChange(pageNum)}
              disabled={isLoading}
              className={`grid size-8 place-items-center rounded-lg text-sm font-medium transition ${
                page === pageNum
                  ? "bg-cyan-500 text-slate-950"
                  : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              } disabled:cursor-not-allowed disabled:opacity-50`}
            >
              {pageNum}
            </button>
          ),
        )}

        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages || isLoading}
          className="grid size-8 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-800 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-30"
          aria-label="下一页"
        >
          <ChevronRight size={16} />
        </button>
      </div>

      {/* Total info */}
      <p className="text-xs text-slate-500">
        共 {formatNumber(total)} 条 · 第 {page}/{totalPages} 页
      </p>
    </div>
  );
}

// ─── Sort Dropdown Component ─────────────────────────────────────────────────

function SortDropdown({
  options,
  value,
  onChange,
}: {
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-slate-500">排序</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 rounded-lg border border-slate-700 bg-slate-950 px-2.5 text-xs text-slate-200 outline-none focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

const MODULE_TABS: {
  key: "trends" | "derivatives" | "search" | "analytics";
  label: string;
}[] = [
  { key: "trends", label: "趋势榜单" },
  { key: "derivatives", label: "衍生话题" },
  { key: "search", label: "智能搜索" },
  { key: "analytics", label: "情报分析" },
];

export function TrendsClient() {
  const { workspaceId } = useWorkspace();
  const { notify } = useToast();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const [liveConnected, setLiveConnected] = useState(false);

  const [platformRaw] = useUrlState("platform", "all");
  const platform = platformRaw as Platform;
  const [collecting, setCollecting] = useState(false);
  const [category, setCategory] = useUrlState("category", "全部");
  const [tab, setTab] = useState<"trends" | "derivatives" | "search" | "analytics">("trends");

  // Pagination & sort state for videos
  const [videoPage, setVideoPage] = useState(1);
  const [videoSort, setVideoSortParam] = useUrlState("sort", "breakout_score");
  // Accumulated videos for "load more" pattern
  const [accumulatedVideos, setAccumulatedVideos] = useState<BreakoutVideo[]>(
    [],
  );
  const [isLoadMore, setIsLoadMore] = useState(false);

  // Pagination state for topics
  const [topicPage, setTopicPage] = useState(1);

  const platformParam = platform === "all" ? "" : platform;

  // Reset pagination when platform or sort changes
  const handlePlatformChange = useCallback(
    (newPlatform: Platform) => {
      // Combined URL update for platform + sort to avoid race conditions
      const params = new URLSearchParams(searchParams.toString());
      if (newPlatform === "all") {
        params.delete("platform");
      } else {
        params.set("platform", newPlatform);
      }
      // Reset sort to first option for the new platform
      const opts = PLATFORM_SORT_OPTIONS[newPlatform];
      const newSort = opts[0]?.value ?? "breakout_score";
      if (newSort === "breakout_score") {
        params.delete("sort");
      } else {
        params.set("sort", newSort);
      }
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });

      setVideoPage(1);
      setTopicPage(1);
      setAccumulatedVideos([]);
      setIsLoadMore(false);
    },
    [searchParams, router, pathname],
  );

  const handleSortChange = useCallback(
    (newSort: string) => {
      setVideoSortParam(newSort);
      setVideoPage(1);
      setAccumulatedVideos([]);
      setIsLoadMore(false);
    },
    [setVideoSortParam],
  );

  const handleVideoPageChange = useCallback((newPage: number) => {
    setVideoPage(newPage);
    setAccumulatedVideos([]);
    setIsLoadMore(false);
  }, []);

  const handleLoadMore = useCallback(() => {
    setIsLoadMore(true);
    setVideoPage((prev) => prev + 1);
  }, []);

  // ─── Queries ─────────────────────────────────────────────────────────────

  const dashboard = useQuery({
    queryKey: ["trends-dashboard", workspaceId],
    queryFn: () =>
      apiRequest<DashboardResponse>("/trends/dashboard", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });

  const topics = useQuery({
    queryKey: ["trends-topics", workspaceId, platformParam, topicPage],
    queryFn: () =>
      apiRequest<TopicsPageResponse>(
        `/trends/topics?platform=${platformParam}&page=${topicPage}&page_size=${PAGE_SIZE}`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });

  const videos = useQuery({
    queryKey: [
      "trends-videos",
      workspaceId,
      platformParam,
      videoSort,
      videoPage,
    ],
    queryFn: () =>
      apiRequest<VideosPageResponse>(
        `/trends/videos?platform=${platformParam}&sort_by=${videoSort}&page=${videoPage}&page_size=${PAGE_SIZE}`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });

  const keywords = useQuery({
    queryKey: ["trends-keywords", workspaceId, platformParam],
    queryFn: () =>
      apiRequest<KeywordStat[]>(`/trends/keywords?platform=${platformParam}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });

  // Merge accumulated videos with new page results for display
  const currentVideoItems = videos.data?.items ?? [];
  const displayVideos = isLoadMore
    ? [...accumulatedVideos, ...currentVideoItems]
    : currentVideoItems;
  // Extract error messages before JSX to avoid TS narrowing to 'never'
  const videosErrorMsg = videos.isError
    ? String((videos as { error?: unknown }).error ?? "请求失败")
    : "";
  const topicsErrorMsg = topics.isError
    ? String((topics as { error?: unknown }).error ?? "请求失败")
    : "";
  // Pre-extract refetch to avoid 'never' type in JSX && guards
  const refetchVideos = videos.refetch;
  const refetchTopics = topics.refetch;
  const refetchDashboard = dashboard.refetch;
  const refetchKeywords = keywords.refetch;
  const videosIsFetching = videos.isFetching;
  const topicsIsFetching = topics.isFetching;

  // Track previous video page to detect load-more completion
  const prevVideoPageRef = useRef(videoPage);
  useEffect(() => {
    const items = videos.data?.items;
    if (
      isLoadMore &&
      videos.isSuccess &&
      items &&
      items.length > 0 &&
      prevVideoPageRef.current === videoPage
    ) {
      setAccumulatedVideos((prev) => {
        const newItems = items.filter((v) => !prev.some((p) => p.id === v.id));
        return newItems.length > 0 ? [...prev, ...newItems] : prev;
      });
      setIsLoadMore(false);
    }
    prevVideoPageRef.current = videoPage;
  }, [isLoadMore, videos.isSuccess, videos.data, videoPage]);

  // ─── Real-time dashboard stream (SSE) ──────────────────────────────────────
  // Subscribes to /trends/stream and merges each pushed dashboard snapshot into
  // the react-query cache, so the platform-overview cards update live without
  // polling. Replaces the previously static dashboard view (STATUS.md known
  // limitation: 趋势分析实时更新). The browser auto-reconnects on error.
  useEffect(() => {
    if (!workspaceId) return;
    const source = new EventSource(
      `/api/v1/trends/stream?interval=5`,
    );
    source.onopen = () => setLiveConnected(true);
    source.onmessage = (event) => {
      try {
        const snapshot = JSON.parse(event.data) as DashboardResponse;
        queryClient.setQueryData(
          ["trends-dashboard", workspaceId],
          snapshot,
        );
      } catch {
        // Ignore malformed frames; the next tick will refresh.
      }
    };
    source.onerror = () => setLiveConnected(false);
    return () => {
      source.close();
      setLiveConnected(false);
    };
  }, [workspaceId, queryClient]);

  // ─── Actions ─────────────────────────────────────────────────────────────

  async function collectData() {
    if (!workspaceId) return;
    setCollecting(true);
    try {
      const result = await apiRequest<{ status: string; task_id: string }>(
        "/trends/collect",
        {
          method: "POST",
          workspaceId,
          csrf: true,
          body: JSON.stringify({}),
        },
      );
      notify(`真实数据采集任务已排队（${result.task_id.slice(0, 8)}）`);
      for (const delay of [5000, 15000])
        setTimeout(() => {
          refetchDashboard();
          refetchTopics();
          refetchVideos();
          refetchKeywords();
        }, delay);
    } catch (error) {
      notify(error instanceof Error ? error.message : "采集失败", "error");
    } finally {
      setCollecting(false);
    }
  }

  // ─── Data Processing ─────────────────────────────────────────────────────

  const platformStats = dashboard.data?.platform_summary ?? [];
  const visibleTopics = (topics.data?.items ?? []).filter(
    (topic) => category === "全部" || topic.category === category,
  );
  const visibleVideos = displayVideos.filter(
    (video) => category === "全部" || video.category === category,
  );

  const videoTotal = videos.data?.total ?? 0;
  const topicTotal = topics.data?.total ?? 0;

  // Prepare chart data: group keywords by keyword name, split by platform
  const chartData = (() => {
    const items = keywords.data ?? [];
    const grouped = new Map<string, Record<string, number>>();

    for (const item of items) {
      const existing = grouped.get(item.keyword) ?? {};
      if (item.heat_index != null) existing[item.platform] = item.heat_index;
      grouped.set(item.keyword, existing);
    }

    return Array.from(grouped.entries()).map(([keyword, platforms]) => ({
      keyword,
      ...platforms,
    }));
  })();

  const chartPlatforms = Array.from(
    new Set((keywords.data ?? []).map((k) => k.platform)),
  );

  // Fixed platform order for the bottom "各平台派生话题与视频样本" module.
  // Includes Douyin so it always renders a card even when no data is collected yet.
  const OVERVIEW_PLATFORMS = PLATFORM_TABS.filter((t) => t.key !== "all");

  // ─── Loading State ───────────────────────────────────────────────────────

  const isLoading =
    dashboard.isLoading ||
    topics.isLoading ||
    videos.isLoading ||
    keywords.isLoading;
  const hasError =
    dashboard.isError || topics.isError || videos.isError || keywords.isError;

  const sortOptions = PLATFORM_SORT_OPTIONS[platform];

  // ─── Render ──────────────────────────────────────────────────────────────

  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      {/* Header */}
      <PageHeader
        eyebrow="Hotspot Intelligence"
        title="热点情报中心"
        description="跨平台真实视频样本、热点衍生话题与智能搜索分析"
        actions={
          <div className="flex items-center gap-2">
            {liveConnected && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2.5 py-1 text-xs font-medium text-emerald-300 ring-1 ring-emerald-500/30">
                <span className="size-1.5 animate-pulse rounded-full bg-emerald-400" />
                实时
              </span>
            )}
            <button
              className={buttonClass}
              onClick={collectData}
              disabled={collecting}
            >
              <RefreshCw
                size={15}
                className={collecting ? "animate-spin" : ""}
              />
              {collecting ? "采集中…" : "开始采集"}
            </button>
          </div>
        }
      />

      {/* Module Tabs: 趋势榜单 / 衍生话题 / 智能搜索 */}
      <div className="flex gap-2 rounded-xl border border-slate-800 bg-slate-950/50 p-1.5">
        {MODULE_TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
              tab === t.key
                ? "bg-cyan-500 text-slate-950"
                : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "trends" && (
        <>
          {/* 趋势榜单 标题与副标题（与其他页签区块风格一致） */}
          <div className="mb-1 flex items-center gap-2">
            <TrendingUp size={18} className="text-cyan-400" />
            <h2 className="font-semibold text-white">趋势榜单</h2>
          </div>
          <p className="mb-4 text-sm text-slate-500">
            跨平台真实视频样本与热点话题排行，可按平台、分类筛选，并查看赛道趋势图表与各平台派生话题。
          </p>

          {/* Platform Filter Tabs */}
          <div className="flex gap-2 overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/50 p-2">
        {PLATFORM_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handlePlatformChange(tab.key)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
              platform === tab.key
                ? "bg-cyan-500 text-slate-950"
                : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Category Filter Chips */}
      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => setCategory(cat)}
            className={`shrink-0 rounded-full px-3 py-1 text-xs font-medium transition ${
              category === cat
                ? "bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/40"
                : "bg-slate-800/60 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            }`}
          >
            {CATEGORY_LABELS[cat] ?? cat}
          </button>
        ))}
      </div>

      <Panel className="p-4">
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-slate-200">
            <CircleHelp size={16} className="text-cyan-400" />
            指标口径与可信度
            <span className="ml-auto text-xs font-normal text-slate-500 group-open:hidden">
              最近 24 小时 · 仅 live 样本
            </span>
          </summary>
          <div className="mt-3 grid gap-3 text-xs leading-6 text-slate-400 md:grid-cols-3">
            <p>
              <strong className="text-slate-200">话题热度</strong>
              <br />
              样本量 15%、样本总播放百分位 45%、平均播放百分位 30%、来源广度
              10%；小样本向 50 分收缩。
            </p>
            <p>
              <strong className="text-slate-200">高潜分</strong>
              <br />
              播放百分位 30%、观测窗口播放速度 35%、互动率 20%、新鲜度
              15%；缺失项不按 0 分处理。
            </p>
            <p>
              <strong className="text-slate-200">增长率</strong>
              <br />
              同关键词相邻采集批次的样本总播放变化，不是平台官方趋势；置信度随有效样本数与字段覆盖度变化。
            </p>
          </div>
        </details>
      </Panel>

      {/* Loading */}
      {isLoading && (
        <Panel>
          <SkeletonRows count={8} />
        </Panel>
      )}

      {/* Error */}
      {hasError && !isLoading && (
        <StatePanel
          type="error"
          title="数据加载失败"
          detail={videosErrorMsg || topicsErrorMsg || "数据加载失败，请重试"}
          onRetry={() => {
            refetchDashboard();
            refetchTopics();
            refetchVideos();
            refetchKeywords();
          }}
        />
      )}

      {/* Content */}
      {!isLoading && !hasError && (
        <>
          {/* Section 3: Hot Topics with Pagination */}
          <Panel>
            <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
              <div className="flex items-center gap-2">
                <TrendingUp size={18} className="text-cyan-400" />
                <h2 className="font-semibold text-white">
                  {platform === "all"
                    ? "热门话题排行"
                    : `${PLATFORM_LABELS[platform] ?? platform} 热门话题`}
                </h2>
                <span className="text-xs text-slate-500">
                  {formatNumber(topicTotal)} 条
                </span>
              </div>
            </div>

            <div className="max-h-[520px] overflow-y-auto">
              {topics.isLoading && <SkeletonRows count={5} />}
              {!topics.isLoading && topics.isError && (
                <StatePanel
                  type="error"
                  title="话题加载失败"
                  detail={topicsErrorMsg}
                  onRetry={() => refetchTopics()}
                />
              )}
              {!topics.isLoading &&
                !topics.isError &&
                visibleTopics.length > 0 && (
                  <div className="divide-y divide-slate-800/50">
                    {visibleTopics.map((topic, index) => (
                      <div
                        key={topic.id}
                        className="flex items-center gap-4 px-5 py-3 transition hover:bg-slate-900/50"
                      >
                        {/* Rank */}
                        <div
                          className={`grid size-8 shrink-0 place-items-center rounded-lg text-sm font-bold ${
                            index < 3
                              ? "bg-gradient-to-br from-amber-500 to-orange-600 text-white"
                              : "bg-slate-800 text-slate-400"
                          }`}
                        >
                          {topic.rank || index + 1}
                        </div>

                        {/* Content */}
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <h3 className="truncate text-sm font-medium text-slate-100">
                              {topic.title}
                            </h3>
                          </div>
                          <div className="mt-1 flex items-center gap-2 text-xs">
                            <Badge tone={getPlatformBadgeTone(topic.platform)}>
                              {PLATFORM_LABELS[topic.platform.toLowerCase()] ??
                                topic.platform}
                            </Badge>
                            {topic.metadata?.source_kind === "live" && (
                              <span className="inline-flex items-center gap-1 text-emerald-400">
                                <span className="size-1.5 rounded-full bg-emerald-400" />
                                实时
                              </span>
                            )}
                            <span
                              title="按样本规模与字段覆盖度计算"
                              className="text-slate-500"
                            >
                              {confidenceLabel(
                                topic.metadata?.confidence_score,
                              )}
                            </span>
                            <span className="text-slate-500">
                              {CATEGORY_LABELS[topic.category] ??
                                topic.category}
                            </span>
                          </div>
                          {workspaceId && (
                            <ScoreExplanationPanel
                              entityType="topic"
                              entityId={topic.id}
                              apiPath={`/trends/topics/${topic.id}/explain`}
                              workspaceId={workspaceId}
                            />
                          )}
                        </div>

                        {/* Heat Score Bar */}
                        <div className="hidden w-32 sm:block">
                          <div className="mb-1 flex justify-between text-xs">
                            <span className="text-slate-500">派生热度</span>
                            <span className="font-medium text-slate-300">
                              {formatNumber(topic.heat_score)}
                            </span>
                          </div>
                          <div className="h-1.5 rounded-full bg-slate-800">
                            <div
                              className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-emerald-400"
                              style={{
                                width: `${Math.min((topic.heat_score / 100) * 100, 100)}%`,
                              }}
                            />
                          </div>
                        </div>

                        {/* Growth Rate */}
                        <div className="flex items-center gap-1 text-xs">
                          {topic.growth_rate != null ? (
                            <>
                              {topic.growth_rate >= 0 ? (
                                <ArrowUp
                                  size={12}
                                  className="text-emerald-400"
                                />
                              ) : (
                                <ArrowDown
                                  size={12}
                                  className="text-rose-400"
                                />
                              )}
                              <span
                                className={
                                  topic.growth_rate >= 0
                                    ? "font-medium text-emerald-400"
                                    : "font-medium text-rose-400"
                                }
                              >
                                {formatGrowthRate(topic.growth_rate)}
                              </span>
                            </>
                          ) : (
                            <span className="text-slate-600">--</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              {!topics.isLoading &&
                !topics.isError &&
                visibleTopics.length === 0 && (
                  <div className="p-8 text-center text-sm text-slate-500">
                    {category === "全部"
                      ? "暂无热门话题数据"
                      : "当前分类暂无话题样本"}
                  </div>
                )}
            </div>

            {/* Topic Pagination */}
            {!topics.isLoading && !topics.isError && topicTotal > PAGE_SIZE && (
              <Pagination
                page={topicPage}
                pageSize={PAGE_SIZE}
                total={topicTotal}
                onPageChange={setTopicPage}
                onLoadMore={() => setTopicPage((p) => p + 1)}
                isLoading={topicsIsFetching}
              />
            )}
          </Panel>

          {/* Section 4: Keyword Trend Chart */}
          <Panel className="p-5">
            <div className="mb-4 flex items-center gap-2">
              <BarChart3 size={18} className="text-cyan-400" />
              <h2 className="font-semibold text-white">赛道趋势图表</h2>
              <span className="text-xs text-slate-500">
                关键词派生热度指数跨平台对比
              </span>
              {keywords.data?.[0]?.observed_at && (
                <span className="ml-auto hidden items-center gap-1 text-xs text-slate-500 sm:flex">
                  <Clock3 size={13} />
                  更新于{" "}
                  {new Date(keywords.data[0].observed_at).toLocaleString(
                    "zh-CN",
                  )}
                </span>
              )}
            </div>

            {chartData.length > 0 ? (
              <>
                {/* Bar Chart */}
                <div className="h-[320px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={chartData}
                      margin={{ top: 10, right: 10, left: 0, bottom: 20 }}
                    >
                      <XAxis
                        dataKey="keyword"
                        tick={{ fill: "#94A3B8", fontSize: 12 }}
                        axisLine={{ stroke: "#334155" }}
                        tickLine={false}
                      />
                      <YAxis
                        tick={{ fill: "#94A3B8", fontSize: 12 }}
                        axisLine={{ stroke: "#334155" }}
                        tickLine={false}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#0F172A",
                          border: "1px solid #334155",
                          borderRadius: "8px",
                          color: "#E2E8F0",
                        }}
                        labelStyle={{ color: "#94A3B8" }}
                      />
                      {chartPlatforms.map((plat) => (
                        <Bar
                          key={plat}
                          dataKey={plat}
                          fill={
                            PLATFORM_COLORS[plat.toLowerCase()] ?? "#6366F1"
                          }
                          radius={[4, 4, 0, 0]}
                        />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                </div>

                {/* Keyword Stats Table */}
                <div className="mt-6 overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-800">
                        <th className="pb-3 text-left font-medium text-slate-400">
                          关键词
                        </th>
                        <th className="pb-3 text-left font-medium text-slate-400">
                          平台
                        </th>
                        <th className="pb-3 text-right font-medium text-slate-400">
                          视频数
                        </th>
                        <th className="pb-3 text-right font-medium text-slate-400">
                          总播放
                        </th>
                        <th className="pb-3 text-right font-medium text-slate-400">
                          热度指数
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/50">
                      {(keywords.data ?? []).slice(0, 10).map((kw, idx) => (
                        <tr
                          key={`${kw.keyword}-${kw.platform}-${idx}`}
                          className="hover:bg-slate-900/30"
                        >
                          <td className="py-3 font-medium text-slate-200">
                            {kw.keyword}
                          </td>
                          <td className="py-3">
                            <Badge tone={getPlatformBadgeTone(kw.platform)}>
                              {kw.platform}
                            </Badge>
                          </td>
                          <td className="py-3 text-right text-slate-300">
                            {formatNumber(kw.video_count)}
                          </td>
                          <td className="py-3 text-right text-slate-300">
                            {formatNumber(kw.total_views)}
                          </td>
                          <td className="py-3 text-right">
                            <span
                              className={`font-medium ${
                                (kw.heat_index ?? 0) >= 80
                                  ? "text-amber-400"
                                  : (kw.heat_index ?? 0) >= 60
                                    ? "text-emerald-400"
                                    : "text-slate-300"
                              }`}
                            >
                              {kw.heat_index != null
                                ? kw.heat_index.toFixed(1)
                                : "--"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <div className="grid h-[200px] place-items-center text-sm text-slate-500">
                暂无关键词趋势数据
              </div>
            )}
          </Panel>

          {/* Section 2: Trending Videos with Platform-Specific Content & Pagination — moved to second-to-last */}
          <Panel>
            <div className="flex flex-col gap-3 border-b border-slate-800 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <Zap size={18} className="text-amber-400" />
                <h2 className="font-semibold text-white">
                  {platform === "all"
                    ? "热门视频"
                    : `${PLATFORM_LABELS[platform] ?? platform} 热门视频`}
                </h2>
                <span className="text-xs text-slate-500">
                  {formatNumber(videoTotal)} 条结果
                </span>
              </div>
              <SortDropdown
                options={sortOptions}
                value={videoSort}
                onChange={handleSortChange}
              />
            </div>

            {/* Video Grid - responsive: single column mobile, grid on desktop */}
            <div className="p-4">
              {videos.isLoading && <SkeletonRows count={6} />}
              {!videos.isLoading && videos.isError && (
                <StatePanel
                  type="error"
                  title="视频加载失败"
                  detail={videosErrorMsg}
                  onRetry={() => refetchVideos()}
                />
              )}
              {!videos.isLoading &&
                !videos.isError &&
                visibleVideos.length > 0 && (
                  <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                    {visibleVideos.map((video) => (
                      <VideoCard
                        key={video.id}
                        video={video}
                        platform={platform}
                        workspaceId={workspaceId}
                      />
                    ))}
                  </div>
                )}
              {!videos.isLoading &&
                !videos.isError &&
                visibleVideos.length === 0 && (
                  <div className="grid min-h-40 place-items-center text-sm text-slate-500">
                    {category === "全部"
                      ? "暂无热门视频数据"
                      : "当前分类暂无视频样本"}
                  </div>
                )}
            </div>

            {/* Pagination */}
            {!videos.isLoading && !videos.isError && videoTotal > 0 && (
              <Pagination
                page={videoPage}
                pageSize={PAGE_SIZE}
                total={videoTotal}
                onPageChange={handleVideoPageChange}
                onLoadMore={handleLoadMore}
                isLoading={videosIsFetching}
              />
            )}
          </Panel>

          {/* Section 1: Platform Overview Cards — moved to bottom; always includes Douyin */}
          <Panel className="p-5">
            <div className="mb-4 flex items-center gap-2">
              <BarChart3 size={18} className="text-cyan-400" />
              <h2 className="font-semibold text-white">各平台派生话题与视频样本</h2>
              <span className="text-xs text-slate-500">
                按平台汇总的派生话题数与视频样本数（含抖音）
              </span>
            </div>
            <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {OVERVIEW_PLATFORMS.map((p) => {
                const stats = platformStats.find(
                  (s) => s.platform.toLowerCase() === p.key,
                );
                return (
                  <Panel
                    key={p.key}
                    className={`relative overflow-hidden p-5 ${PLATFORM_BG[p.key] ?? ""}`}
                  >
                    <div
                      className={`absolute inset-x-0 top-0 h-1 bg-gradient-to-b ${PLATFORM_ACCENT[p.key] ?? ""}`}
                    />
                    <div className="flex items-center gap-3">
                      <div
                        className={`grid size-10 place-items-center rounded-lg ${PLATFORM_BG[p.key] ?? "bg-slate-800"}`}
                      >
                        <Video
                          size={18}
                          className={PLATFORM_TEXT[p.key] ?? "text-slate-400"}
                        />
                      </div>
                      <h3 className="font-semibold text-white">{p.label}</h3>
                    </div>
                    <div className="mt-4 grid grid-cols-2 gap-3">
                      <div>
                        <p className="text-xs text-slate-500">派生话题</p>
                        <p className="mt-1 text-lg font-semibold text-white">
                          {formatNumber(stats?.topic_count ?? 0)}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">视频样本</p>
                        <p className="mt-1 text-lg font-semibold text-white">
                          {formatNumber(stats?.video_count ?? 0)}
                        </p>
                      </div>
                    </div>
                    <div className="mt-3 flex items-center gap-2 text-xs">
                      <Flame size={12} className="text-amber-400" />
                      <span className="text-slate-400">
                        平均派生热度{" "}
                        <span className="font-medium text-amber-300">
                          {stats?.avg_heat_score != null
                            ? stats.avg_heat_score.toFixed(1)
                            : "0.0"}
                        </span>
                      </span>
                    </div>
                  </Panel>
                );
              })}
            </section>
          </Panel>
        </>
      )}

      {/* Empty State when no data at all */}
      {!isLoading &&
        !hasError &&
        !platformStats.length &&
        !topics.data?.items?.length &&
        !videos.data?.items?.length && (
          <StatePanel
            type="empty"
            title="暂无趋势数据"
            detail="请先配置官方 API，或完成公开页面采集条件确认并添加监控账号，然后点击「开始采集」。"
          />
        )}
        </>
      )}

      {tab === "derivatives" && <DerivativesPanel workspaceId={workspaceId!} />}

      {tab === "search" && <SearchPanel workspaceId={workspaceId!} />}

      {tab === "analytics" && <AnalyticsClient />}
    </main>
  );
}
