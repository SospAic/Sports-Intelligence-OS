"use client";

import { useQuery } from "@tanstack/react-query";
import { Clock3, ExternalLink, LoaderCircle, Newspaper, X } from "lucide-react";
import { useEffect } from "react";

import { Badge, StatePanel } from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";

interface NewsArticle {
  id: string;
  title: string;
  summary: string | null;
  canonical_url: string;
  published_at: string | null;
  source: { name: string; reliability_score: number };
  source_kind: string;
  source_provider: string;
}

interface NewsEventDetail {
  title: string;
  summary: string | null;
  sport: string | null;
  league: string | null;
  last_update_time: string;
  article_count: number;
  source_count: number;
  heat_score: number;
  reliability_score: number;
  controversy_score: number;
  visual_score: number;
  story_score: number;
  status: string;
  articles: NewsArticle[];
}

function relativeTime(value: string | null): string {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  const hours = Math.floor((Date.now() - date.getTime()) / 3_600_000);
  if (hours < 1) return "刚刚";
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

export function HotNewsDetailDrawer({
  event,
  workspaceId,
  onClose,
}: {
  event: {
    id: string;
    title: string;
    summary: string | null;
    last_update_time: string;
    article_count: number;
    source_count: number;
    heat_score: number;
    reliability_score: number;
  } | null;
  workspaceId: string | null;
  onClose: () => void;
}) {
  const detail = useQuery({
    queryKey: ["hot-news-event-detail", workspaceId, event?.id],
    queryFn: () => apiRequest<NewsEventDetail>(`/news/events/${event!.id}`, { workspaceId: workspaceId! }),
    enabled: Boolean(event && workspaceId),
  });

  useEffect(() => {
    if (!event) return;
    const onKeyDown = (keyboardEvent: KeyboardEvent) => {
      if (keyboardEvent.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [event, onClose]);

  if (!event) return null;
  const data = detail.data;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-slate-950/70 backdrop-blur-sm"
      role="presentation"
      onMouseDown={(mouseEvent) => {
        if (mouseEvent.target === mouseEvent.currentTarget) onClose();
      }}
    >
      <aside className="flex h-full w-full max-w-2xl flex-col overflow-hidden border-l border-slate-700 bg-slate-950 shadow-2xl" role="dialog" aria-modal="true" aria-label={`${event.title} 新闻详情`}>
        <header className="shrink-0 border-b border-slate-800 px-5 py-4 sm:px-7">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-xs font-semibold tracking-[.18em] text-violet-300 uppercase">News cluster</p>
              <h2 className="mt-1 text-xl font-semibold leading-7 text-white">{event.title}</h2>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span>近 {relativeTime(event.last_update_time)}更新</span>
                <span>·</span>
                <span>{event.article_count} 篇报道</span>
                <span>·</span>
                <span>{event.source_count} 个来源</span>
              </div>
            </div>
            <button type="button" onClick={onClose} className="grid size-9 shrink-0 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-800 hover:text-white" aria-label="关闭新闻详情">
              <X size={18} />
            </button>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-2">
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2"><p className="text-[11px] text-slate-500">事件热度</p><p className="mt-1 text-lg font-semibold text-amber-300">{event.heat_score.toFixed(1)}</p></div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2"><p className="text-[11px] text-slate-500">来源可信度</p><p className="mt-1 text-lg font-semibold text-emerald-300">{event.reliability_score.toFixed(0)}</p></div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2"><p className="text-[11px] text-slate-500">可核验报道</p><p className="mt-1 text-lg font-semibold text-violet-300">{data?.articles.length ?? "—"}</p></div>
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-7">
          {detail.isLoading && <div className="grid min-h-56 place-items-center text-sm text-slate-400"><span className="inline-flex items-center gap-2"><LoaderCircle size={17} className="animate-spin text-cyan-400" />正在展开事件报道…</span></div>}
          {detail.isError && <StatePanel type="error" title="新闻详情加载失败" detail={String(detail.error ?? "请求失败")} onRetry={() => detail.refetch()} />}
          {data && (
            <div className="space-y-5">
              <section className="rounded-xl border border-violet-900/50 bg-violet-950/10 p-4">
                <div className="flex items-start gap-3"><Newspaper size={17} className="mt-0.5 shrink-0 text-violet-300" /><div><p className="text-sm font-medium text-violet-200">事件摘要</p><p className="mt-1 text-xs leading-5 text-slate-300">{data.summary || event.summary || "暂无事件摘要"}</p></div></div>
              </section>
              <section>
                <div className="mb-3 flex items-center gap-2"><Newspaper size={17} className="text-violet-300" /><h3 className="font-semibold text-white">报道与原文</h3><span className="text-xs text-slate-500">{data.articles.length} 条</span></div>
                <div className="space-y-2">
                  {data.articles.map((article) => (
                    <article key={article.id} className="rounded-xl border border-slate-800 bg-slate-900/45 p-4 transition hover:border-violet-700/60">
                      <div className="flex items-start justify-between gap-3"><a href={article.canonical_url} target="_blank" rel="noreferrer" className="line-clamp-2 text-sm font-medium leading-5 text-slate-100 hover:text-cyan-300">{article.title}</a><ExternalLink size={14} className="mt-0.5 shrink-0 text-slate-600" /></div>
                      {article.summary && <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-400">{article.summary}</p>}
                      <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500"><span className="font-medium text-violet-300">{article.source.name}</span><span>·</span><span className="inline-flex items-center gap-1"><Clock3 size={12} />{relativeTime(article.published_at)}</span><Badge tone={article.source_kind === "live" ? "success" : "warning"}>{article.source_kind === "live" ? "实时" : "导入"}</Badge><span>可信度 {article.source.reliability_score.toFixed(0)}</span></div>
                    </article>
                  ))}
                </div>
              </section>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
