"use client";
import type { TopicEventDetail } from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, Sparkles } from "lucide-react";
import Link from "next/link";
import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import {
  Badge,
  MetricCard,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  buttonClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate, sportLabel } from "@/lib/format";
import {
  eventRecommendationScore,
  isEventScoreAvailable,
} from "@/lib/news-metrics";
export function EventDetailClient({ id }: { id: string }) {
  const { workspaceId } = useWorkspace();
  const { notify } = useToast();
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["event", id],
    queryFn: () =>
      apiRequest<TopicEventDetail>(`/news/events/${id}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  async function bookmark() {
    if (!workspaceId || !query.data) return;
    try {
      await apiRequest(`/news/events/${id}/bookmark`, {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ bookmarked: !query.data.is_bookmarked }),
      });
      notify(query.data.is_bookmarked ? "已取消收藏" : "已加入选题库");
      await qc.invalidateQueries({ queryKey: ["event", id] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "收藏失败", "error");
    }
  }
  if (query.isLoading)
    return (
      <main className="p-8">
        <SkeletonRows />
      </main>
    );
  if (!query.data || query.error)
    return (
      <main className="p-8">
        <StatePanel
          type="error"
          title="事件详情加载失败"
          detail={query.error?.message}
        />
      </main>
    );
  const item = query.data;
  const storyAvailable = isEventScoreAvailable(item.metadata, "story_score");
  const recommendationScore = eventRecommendationScore(item.metadata);
  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow={`${sportLabel(item.sport)} · ${
          { active: "活跃", developing: "发展中", closed: "已结束" }[
            item.status
          ] ?? item.status
        }`}
        title={item.title}
        description={item.summary ?? "暂无事件摘要"}
        actions={
          <>
            <button className={secondaryButtonClass} onClick={bookmark}>
              <Bookmark
                size={15}
                fill={item.is_bookmarked ? "currentColor" : "none"}
              />
              {item.is_bookmarked ? "已收藏" : "收藏选题"}
            </button>
            <Link
              className={buttonClass}
              href={`/generate?input_type=event&input_id=${id}`}
            >
              <Sparkles size={15} />
              生成完整包
            </Link>
          </>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard
          label="客观热度"
          value={item.heat_score}
          hint="不含收藏偏好"
        />
        <MetricCard label="来源可靠度均值" value={item.reliability_score} />
        <MetricCard
          label="来源数"
          value={item.source_count}
          hint={
            item.source_count < 2 ? "单一来源，尚未交叉验证" : "已覆盖多个来源"
          }
        />
        <MetricCard label="报道数" value={item.article_count} />
        <MetricCard
          label="故事价值"
          value={storyAvailable ? item.story_score : "—"}
          hint={storyAvailable ? "来自文章元数据" : "数据源未提供，不按 0 分"}
        />
      </div>
      {recommendationScore !== null &&
        recommendationScore !== item.heat_score && (
          <p className="text-xs text-slate-500">
            个性化推荐分 {recommendationScore.toFixed(1)}
            ，其中包含当前用户的收藏偏好；客观热度保持独立。
          </p>
        )}
      <Panel>
        <div className="border-b border-slate-800 p-5">
          <h2 className="font-medium text-white">事件时间线与来源</h2>
        </div>
        <div className="relative ml-8 border-l border-slate-800 py-3">
          {item.articles.map((article) => (
            <div className="relative p-5" key={article.id}>
              <span className="absolute top-7 -left-[5px] size-2 rounded-full bg-cyan-400" />
              <p className="text-xs text-slate-500">
                {formatDate(article.event_time || article.published_at)} ·{" "}
                {article.source.name}
              </p>
              <Link href={`/news/${article.id}`}>
                <h3 className="mt-2 font-medium text-slate-200 hover:text-cyan-300">
                  {article.title}
                </h3>
              </Link>
              <p className="mt-2 line-clamp-2 text-sm text-slate-400">
                {article.summary}
              </p>
              <div className="mt-2">
                <Badge tone={article.is_duplicate ? "warning" : "neutral"}>
                  {article.is_duplicate ? "重复报道" : article.source_kind}
                </Badge>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </main>
  );
}
