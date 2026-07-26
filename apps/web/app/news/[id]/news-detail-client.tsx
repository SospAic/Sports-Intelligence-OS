"use client";
import type { ArticleRecord } from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Sparkles } from "lucide-react";
import Link from "next/link";
import { useWorkspace } from "@/components/app-shell";
import {
  Badge,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";
export function NewsDetailClient({ id }: { id: string }) {
  const { workspaceId } = useWorkspace();
  const query = useQuery({
    queryKey: ["article", id],
    queryFn: () =>
      apiRequest<ArticleRecord>(`/news/articles/${id}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
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
          title="新闻详情加载失败"
          detail={query.error?.message}
        />
      </main>
    );
  const item = query.data;
  return (
    <main className="mx-auto max-w-5xl space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow={`${item.source.name} · ${item.source_kind === "live" ? "实时来源" : "用户录入"}`}
        title={item.title}
        description={`发布 ${formatDate(item.published_at)} · 抓取 ${formatDate(item.fetched_at)}`}
        actions={
          <>
            <Link
              className={secondaryButtonClass}
              href={`/generate?input_type=news&input_id=${id}`}
            >
              <Sparkles size={15} />
              生成短视频内容
            </Link>
            <a
              className={secondaryButtonClass}
              href={item.canonical_url}
              target="_blank"
              rel="noreferrer"
            >
              原始链接
              <ExternalLink size={15} />
            </a>
          </>
        }
      />
      <div className="flex flex-wrap gap-2">
        <Badge tone="info">{item.sport || "综合体育"}</Badge>
        {item.league && <Badge>{item.league}</Badge>}
        {item.is_duplicate && <Badge tone="warning">重复报道组</Badge>}
        {item.event_id && (
          <Link
            className="text-sm text-cyan-300"
            href={`/events/${item.event_id}`}
          >
            所属事件 →
          </Link>
        )}
      </div>
      <Panel className="p-6">
        <h2 className="font-medium text-white">摘要</h2>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-300">
          {item.summary || "来源未提供摘要"}
        </p>
      </Panel>
      <Panel className="p-6">
        <h2 className="font-medium text-white">已保存正文</h2>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-400">
          {item.content ||
            "出于授权与版权边界，当前来源未保存全文。请通过原始链接查看。"}
        </p>
      </Panel>
    </main>
  );
}
