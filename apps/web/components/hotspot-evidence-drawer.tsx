"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  Clock3,
  ExternalLink,
  Info,
  LoaderCircle,
  MessageCircle,
  Newspaper,
  Play,
  Share2,
  ThumbsUp,
  Video,
  X,
} from "lucide-react";
import { useEffect } from "react";

import { ExternalImage } from "@/components/external-image";
import { ScoreExplanationPanel } from "@/components/score-explanation";
import { Badge, StatePanel, secondaryButtonClass } from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatNumber } from "@/lib/format";

export interface EvidenceTopic {
  id: string;
  title: string;
  platform: string;
  category: string;
  heat_score: number;
  growth_rate: number | null;
  rank: number;
  sample_size: number;
  observed_at: string;
  metadata?: Record<string, unknown> & {
    source_kind?: string;
    provider?: string;
    confidence_score?: number;
  };
}

interface EvidenceNews {
  id: string | null;
  title: string;
  summary: string | null;
  url: string;
  source_name: string;
  source_kind: string;
  provider: string;
  published_at: string | null;
  reliability_score: number | null;
  matched_by: string;
}

interface EvidenceVideo {
  id: string;
  platform: string;
  external_id: string;
  title: string;
  author_name: string | null;
  cover_url: string | null;
  video_url: string | null;
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
  share_count: number | null;
  breakout_score: number | null;
  category: string | null;
  source_kind: string;
  provider: string;
  observed_at: string;
  matched_by: string;
}

interface TopicEvidenceResponse {
  topic: EvidenceTopic;
  news: EvidenceNews[];
  videos: EvidenceVideo[];
  coverage: {
    window_hours?: number;
    news_count?: number;
    video_count?: number;
    exact_reference_news?: number;
    exact_reference_videos?: number;
    notes?: string[];
  };
}

const PLATFORM_LABELS: Record<string, string> = {
  youtube: "YouTube",
  tiktok: "TikTok",
  douyin: "抖音",
  bilibili: "Bilibili",
  web: "全网新闻",
};

function relativeTime(value: string | null): string {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  const hours = Math.floor((Date.now() - date.getTime()) / 3_600_000);
  if (hours < 1) return "刚刚";
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

function Stat({
  icon,
  value,
  label,
}: {
  icon: React.ReactNode;
  value: number | null;
  label: string;
}) {
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-slate-400" title={label}>
      {icon}
      {formatNumber(value)}
    </span>
  );
}

export function HotspotEvidenceDrawer({
  topic,
  workspaceId,
  onClose,
}: {
  topic: EvidenceTopic | null;
  workspaceId: string | null;
  onClose: () => void;
}) {
  const evidence = useQuery({
    queryKey: ["trend-topic-evidence", workspaceId, topic?.id],
    queryFn: () =>
      apiRequest<TopicEvidenceResponse>(`/trends/topics/${topic!.id}/evidence`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(topic && workspaceId),
  });

  useEffect(() => {
    if (!topic) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose, topic]);

  if (!topic) return null;

  const data = evidence.data;
  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-slate-950/70 backdrop-blur-sm"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        aria-label={`${topic.title} 话题证据`}
        className="flex h-full w-full max-w-3xl flex-col overflow-hidden border-l border-slate-700 bg-slate-950 shadow-2xl"
        role="dialog"
        aria-modal="true"
      >
        <header className="shrink-0 border-b border-slate-800 bg-slate-950/95 px-5 py-4 sm:px-7">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
                Hotspot evidence
              </p>
              <h2 className="mt-1 text-xl font-semibold leading-7 text-white">{topic.title}</h2>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Badge tone="info">{PLATFORM_LABELS[topic.platform] ?? topic.platform}</Badge>
                <Badge tone={topic.metadata?.source_kind === "live" ? "success" : "warning"}>
                  {topic.metadata?.source_kind === "live" ? "实时来源" : "来源待确认"}
                </Badge>
                <span className="text-xs text-slate-500">
                  观测于 {relativeTime(topic.observed_at)} · 样本 {formatNumber(topic.sample_size)}
                </span>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="grid size-9 shrink-0 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-800 hover:text-white"
              aria-label="关闭话题证据"
            >
              <X size={18} />
            </button>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-2 sm:max-w-lg">
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
              <p className="text-[11px] text-slate-500">派生热度</p>
              <p className="mt-1 text-lg font-semibold tabular-nums text-amber-300">
                {topic.heat_score.toFixed(1)}
              </p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
              <p className="text-[11px] text-slate-500">新闻证据</p>
              <p className="mt-1 text-lg font-semibold tabular-nums text-violet-300">
                {data?.coverage.news_count ?? "—"}
              </p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
              <p className="text-[11px] text-slate-500">视频样本</p>
              <p className="mt-1 text-lg font-semibold tabular-nums text-cyan-300">
                {data?.coverage.video_count ?? "—"}
              </p>
            </div>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-7">
          {evidence.isLoading && (
            <div className="grid min-h-72 place-items-center text-sm text-slate-400">
              <span className="inline-flex items-center gap-2">
                <LoaderCircle size={17} className="animate-spin text-cyan-400" />
                正在整理新闻与视频证据…
              </span>
            </div>
          )}
          {evidence.isError && (
            <StatePanel
              type="error"
              title="证据加载失败"
              detail={String(evidence.error ?? "接口暂时不可用")}
              onRetry={() => evidence.refetch()}
            />
          )}
          {data && (
            <div className="space-y-6">
              <section className="rounded-xl border border-cyan-900/60 bg-cyan-950/10 p-4">
                <div className="flex items-start gap-3">
                  <Info size={17} className="mt-0.5 shrink-0 text-cyan-300" />
                  <div className="min-w-0 text-xs leading-5 text-slate-300">
                    <p className="font-medium text-cyan-200">证据覆盖说明</p>
                    <p className="mt-1">
                      当前窗口 {data.coverage.window_hours ?? 72} 小时；其中新闻直接引用 {data.coverage.exact_reference_news ?? 0} 条，视频直接引用 {data.coverage.exact_reference_videos ?? 0} 条，其余为标题/实体匹配。
                    </p>
                    {data.coverage.notes?.map((note) => (
                      <p key={note} className="mt-1 text-slate-400">{note}</p>
                    ))}
                  </div>
                </div>
                {workspaceId && (
                  <ScoreExplanationPanel
                    entityType="topic"
                    entityId={topic.id}
                    apiPath={`/trends/topics/${topic.id}/explain`}
                    workspaceId={workspaceId}
                  />
                )}
              </section>

              <section>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Newspaper size={17} className="text-violet-300" />
                    <h3 className="font-semibold text-white">新闻证据</h3>
                    <span className="text-xs text-slate-500">{data.news.length} 条</span>
                  </div>
                  <Link href="/news" className="text-xs text-cyan-400 hover:text-cyan-300">进入新闻中心 →</Link>
                </div>
                {data.news.length > 0 ? (
                  <div className="space-y-2">
                    {data.news.map((news) => (
                      <article key={`${news.url}-${news.id ?? "fallback"}`} className="rounded-xl border border-slate-800 bg-slate-900/45 p-4 transition hover:border-violet-700/60">
                        <div className="flex items-start justify-between gap-3">
                          <a href={news.url} target="_blank" rel="noreferrer" className="line-clamp-2 text-sm font-medium leading-5 text-slate-100 hover:text-cyan-300">
                            {news.title}
                          </a>
                          <ExternalLink size={14} className="mt-0.5 shrink-0 text-slate-600" />
                        </div>
                        {news.summary && <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-400">{news.summary}</p>}
                        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                          <span className="font-medium text-violet-300">{news.source_name}</span>
                          <span>·</span>
                          <span className="inline-flex items-center gap-1"><Clock3 size={12} />{relativeTime(news.published_at)}</span>
                          <Badge tone={news.matched_by === "采集引用" ? "success" : "neutral"}>{news.matched_by}</Badge>
                          {news.reliability_score != null && <span>来源可信度 {news.reliability_score.toFixed(0)}</span>}
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-slate-800 p-7 text-center text-sm text-slate-500">暂无可验证新闻链接</div>
                )}
              </section>

              <section>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Video size={17} className="text-cyan-300" />
                    <h3 className="font-semibold text-white">相关视频</h3>
                    <span className="text-xs text-slate-500">{data.videos.length} 条</span>
                  </div>
                </div>
                {data.videos.length > 0 ? (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {data.videos.map((video) => (
                      <article key={video.id} className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/45">
                        {video.video_url ? (
                          <a href={video.video_url} target="_blank" rel="noreferrer" className="block">
                            <div className="relative aspect-video bg-slate-900">
                              {video.cover_url ? <ExternalImage src={video.cover_url} alt={video.title} className="size-full object-cover" containerClassName="size-full" /> : <div className="grid size-full place-items-center"><Video size={22} className="text-slate-700" /></div>}
                              {video.breakout_score != null && <span className="absolute bottom-2 right-2 rounded bg-amber-500 px-1.5 py-0.5 text-[10px] font-semibold text-white">潜力 {video.breakout_score.toFixed(1)}</span>}
                            </div>
                          </a>
                        ) : <div className="grid aspect-video place-items-center bg-slate-900"><Video size={22} className="text-slate-700" /></div>}
                        <div className="p-3">
                          <a href={video.video_url ?? "#"} target={video.video_url ? "_blank" : undefined} rel={video.video_url ? "noreferrer" : undefined} className="line-clamp-2 text-sm font-medium leading-5 text-slate-100 hover:text-cyan-300">{video.title}</a>
                          <p className="mt-1 truncate text-xs text-slate-500">{video.author_name ?? "未知作者"} · {PLATFORM_LABELS[video.platform] ?? video.platform}</p>
                          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                            <Stat icon={<Play size={12} />} value={video.view_count} label="播放量" />
                            <Stat icon={<ThumbsUp size={12} />} value={video.like_count} label="点赞" />
                            <Stat icon={<MessageCircle size={12} />} value={video.comment_count} label="评论" />
                            <Stat icon={<Share2 size={12} />} value={video.share_count} label="分享" />
                          </div>
                          <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-slate-600">
                            <span>{relativeTime(video.observed_at)}</span>
                            <Badge tone={video.matched_by === "采集引用" ? "success" : "neutral"}>{video.matched_by}</Badge>
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-slate-800 p-7 text-center text-sm text-slate-500">暂无可验证相关视频；不以估算播放或互动数填充。</div>
                )}
              </section>

              <div className="border-t border-slate-800 pt-4 text-xs leading-5 text-slate-500">
                证据链只展示 live / imported 来源中适配器实际返回的字段。没有平台私有分析权限时，不会把完播率、流量来源或变现指标伪装成热点证据。
              </div>
              <button type="button" className={secondaryButtonClass} onClick={onClose}>返回热点工作台</button>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
