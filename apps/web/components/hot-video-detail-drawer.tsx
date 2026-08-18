"use client";

import { ExternalLink, Heart, MessageCircle, Play, Share2, Video, X } from "lucide-react";
import { useEffect } from "react";

import { ExternalImage } from "@/components/external-image";
import { Badge } from "@/components/ui";
import { formatNumber } from "@/lib/format";

interface VideoDetailRecord {
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
  metadata?: Record<string, unknown> & { source_kind?: string; provider?: string };
}

const PLATFORM_LABELS: Record<string, string> = {
  youtube: "YouTube",
  tiktok: "TikTok",
  douyin: "抖音",
  bilibili: "Bilibili",
  web: "全网新闻",
};

function relativeTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  const hours = Math.floor((Date.now() - date.getTime()) / 3_600_000);
  if (hours < 1) return "刚刚";
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: number | null }) {
  return <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3"><div className="flex items-center gap-1 text-xs text-slate-500">{icon}{label}</div><p className="mt-1 text-lg font-semibold tabular-nums text-slate-100">{formatNumber(value)}</p></div>;
}

export function HotVideoDetailDrawer({
  video,
  onClose,
}: {
  video: VideoDetailRecord | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!video) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose, video]);

  if (!video) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/70 backdrop-blur-sm" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className="flex h-full w-full max-w-xl flex-col overflow-hidden border-l border-slate-700 bg-slate-950 shadow-2xl" role="dialog" aria-modal="true" aria-label={`${video.title} 视频详情`}>
        <header className="shrink-0 border-b border-slate-800 px-5 py-4 sm:px-7">
          <div className="flex items-start justify-between gap-4"><div className="min-w-0"><p className="text-xs font-semibold tracking-[.18em] text-amber-300 uppercase">Video sample</p><h2 className="mt-1 text-xl font-semibold leading-7 text-white">{video.title}</h2><div className="mt-2 flex flex-wrap items-center gap-2"><Badge tone="info">{PLATFORM_LABELS[video.platform] ?? video.platform}</Badge><span className="text-xs text-slate-500">{video.author_name ?? "未知作者"} · {relativeTime(video.observed_at)}</span></div></div><button type="button" onClick={onClose} className="grid size-9 shrink-0 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-800 hover:text-white" aria-label="关闭视频详情"><X size={18} /></button></div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-7">
          <div className="space-y-5">
            <div className="relative aspect-video overflow-hidden rounded-xl border border-slate-800 bg-slate-900">{video.cover_url ? <ExternalImage src={video.cover_url} alt={video.title} className="size-full object-cover" containerClassName="size-full" /> : <div className="grid size-full place-items-center"><Video size={28} className="text-slate-700" /></div>}{video.breakout_score != null && <span className="absolute bottom-3 right-3 rounded bg-amber-500 px-2 py-1 text-xs font-semibold text-white">高潜分 {video.breakout_score.toFixed(1)}</span>}</div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4"><Stat icon={<Play size={13} />} label="播放" value={video.view_count} /><Stat icon={<Heart size={13} />} label="点赞" value={video.like_count} /><Stat icon={<MessageCircle size={13} />} label="评论" value={video.comment_count} /><Stat icon={<Share2 size={13} />} label="分享" value={video.share_count} /></div>
            <section className="rounded-xl border border-cyan-900/50 bg-cyan-950/10 p-4 text-xs leading-5 text-slate-300"><p className="font-medium text-cyan-200">数据口径</p><p className="mt-1">以上只显示该平台适配器实际返回的字段；潜力分是基于当前样本计算的派生指标，不等同于平台官方推荐。</p><div className="mt-2 flex flex-wrap gap-2"><Badge tone={video.metadata?.source_kind === "live" ? "success" : "warning"}>{video.metadata?.source_kind === "live" ? "实时来源" : "来源待确认"}</Badge>{video.category && <Badge>{video.category}</Badge>}{video.metadata?.provider && <span className="text-slate-500">Provider: {String(video.metadata.provider)}</span>}</div></section>
            {video.video_url ? <a href={video.video_url} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-cyan-300 px-4 text-sm font-medium text-slate-950 transition hover:bg-cyan-200"><ExternalLink size={15} />打开原视频</a> : <p className="text-sm text-slate-500">该样本未返回可打开的原视频链接。</p>}
          </div>
        </div>
      </aside>
    </div>
  );
}
