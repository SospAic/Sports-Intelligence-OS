"use client";

import type {
  ArticleRecord,
  ArticleRecordPage,
  ContentRecord,
  ContentRecordPage,
  TopicEventDetail,
  TopicEventPage,
  TopicEventRecord,
} from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import { FileText, Flame, Newspaper, Video } from "lucide-react";
import Link from "next/link";

import { Badge, SkeletonRows, StatePanel, inputClass } from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate, formatNumber, sourceKindLabel } from "@/lib/format";

export type CreationSourceType = "content" | "news" | "event" | "user_text";

type SourceCard = {
  id: string;
  title: string;
  detail: string;
  time: string | null;
  sourceKind: string;
};

const sourceTabs: Array<{
  key: CreationSourceType;
  label: string;
  icon: typeof Video;
}> = [
  { key: "content", label: "热门视频", icon: Video },
  { key: "news", label: "热点新闻", icon: Newspaper },
  { key: "event", label: "聚合事件", icon: Flame },
  { key: "user_text", label: "自定义材料", icon: FileText },
];

export function GenerationSourcePicker({
  workspaceId,
  inputType,
  inputId,
  title,
  text,
  onInputTypeChange,
  onInputIdChange,
  onTitleChange,
  onTextChange,
}: {
  workspaceId: string;
  inputType: CreationSourceType;
  inputId: string;
  title: string;
  text: string;
  onInputTypeChange: (value: CreationSourceType) => void;
  onInputIdChange: (value: string) => void;
  onTitleChange: (value: string) => void;
  onTextChange: (value: string) => void;
}) {
  const sourceQuery = useQuery({
    queryKey: ["generation-source-candidates", workspaceId, inputType],
    queryFn: () => sourceCandidates(workspaceId, inputType),
    enabled: Boolean(workspaceId && inputType !== "user_text"),
  });
  const selectedFromList = sourceQuery.data?.find(
    (item) => item.id === inputId,
  );
  const selectedQuery = useQuery({
    queryKey: ["generation-source", workspaceId, inputType, inputId],
    queryFn: () => sourceDetail(workspaceId, inputType, inputId),
    enabled: Boolean(
      workspaceId && inputType !== "user_text" && inputId && !selectedFromList,
    ),
  });
  const selected = selectedFromList ?? selectedQuery.data;

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-5 lg:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
            01 · 选择素材
          </p>
          <h2 className="mt-2 text-xl font-semibold text-white">
            从热点直接开始
          </h2>
          <p className="mt-2 text-sm text-slate-400">
            选择一条已采集的视频、新闻或事件；来源和事实会随生成记录冻结。
          </p>
        </div>
        {selected ? <Badge tone="success">已选择</Badge> : null}
      </div>

      <div className="mt-5 flex flex-wrap gap-2" role="tablist">
        {sourceTabs.map(({ key, label, icon: Icon }) => (
          <button
            aria-selected={inputType === key}
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition ${
              inputType === key
                ? "border-cyan-700 bg-cyan-950/60 text-cyan-200"
                : "border-slate-800 text-slate-400 hover:border-slate-700 hover:text-slate-200"
            }`}
            key={key}
            onClick={() => {
              onInputTypeChange(key);
              onInputIdChange("");
            }}
            role="tab"
            type="button"
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </div>

      {inputType === "user_text" ? (
        <div className="mt-5 space-y-4">
          <label className="grid gap-2 text-sm text-slate-300">
            事件标题
            <input
              className={inputClass}
              onChange={(event) => onTitleChange(event.target.value)}
              placeholder="例如：最后一圈发生的逆转"
              value={title}
            />
          </label>
          <label className="grid gap-2 text-sm text-slate-300">
            已知事实与来源
            <textarea
              className="min-h-48 rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm leading-6 text-slate-100 outline-none focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20"
              onChange={(event) => onTextChange(event.target.value)}
              placeholder="粘贴事件事实、比分、时间、人物和可核实来源。没有独立来源时，系统会保留‘核实未完成’标记。"
              value={text}
            />
          </label>
        </div>
      ) : sourceQuery.isPending ? (
        <div className="mt-5 overflow-hidden rounded-xl border border-slate-800">
          <SkeletonRows count={4} />
        </div>
      ) : sourceQuery.isError ? (
        <div className="mt-5 overflow-hidden rounded-xl border border-slate-800">
          <StatePanel
            detail={
              sourceQuery.error instanceof Error
                ? sourceQuery.error.message
                : "无法读取候选素材"
            }
            onRetry={() => sourceQuery.refetch()}
            title="候选素材加载失败"
            type="error"
          />
        </div>
      ) : sourceQuery.data?.length ? (
        <div className="mt-5 grid gap-3 lg:grid-cols-2">
          {sourceQuery.data.map((item) => (
            <button
              aria-pressed={inputId === item.id}
              className={`rounded-xl border p-4 text-left transition ${
                inputId === item.id
                  ? "border-cyan-600 bg-cyan-950/30"
                  : "border-slate-800 bg-slate-950 hover:border-slate-700"
              }`}
              key={item.id}
              onClick={() => onInputIdChange(item.id)}
              type="button"
            >
              <div className="flex items-start justify-between gap-3">
                <p className="line-clamp-2 text-sm font-medium leading-6 text-slate-100">
                  {item.title}
                </p>
                {inputId === item.id ? (
                  <span className="shrink-0 text-xs text-cyan-300">已选</span>
                ) : null}
              </div>
              <p className="mt-2 line-clamp-1 text-xs text-slate-400">
                {item.detail}
              </p>
              <div className="mt-3 flex items-center justify-between gap-3 text-[11px] text-slate-500">
                <span>{sourceLabel(item.sourceKind)}</span>
                <span>{formatDate(item.time)}</span>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <div className="mt-5 rounded-xl border border-slate-800">
          <StatePanel
            detail="先同步平台作品或添加新闻源，也可以切换到自定义材料。"
            title="当前没有可用素材"
            type="empty"
          />
        </div>
      )}

      {inputType !== "user_text" && inputId && selectedQuery.isError ? (
        <div className="mt-4 rounded-xl border border-rose-900/60 bg-rose-950/20 p-4 text-sm text-rose-200">
          无法确认从详情页带入的素材。
          <button
            className="ml-2 text-cyan-300 underline"
            onClick={() => selectedQuery.refetch()}
            type="button"
          >
            重试
          </button>
        </div>
      ) : inputType !== "user_text" && inputId && !selected ? (
        <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-sm text-slate-400">
          正在确认从详情页带入的素材…
        </div>
      ) : null}
      {selected &&
      !sourceQuery.data?.some((item) => item.id === selected.id) ? (
        <div className="mt-4 rounded-xl border border-cyan-900/70 bg-cyan-950/20 p-4">
          <p className="text-xs text-cyan-300">已从详情页带入</p>
          <p className="mt-1 text-sm font-medium text-slate-100">
            {selected.title}
          </p>
          <p className="mt-1 text-xs text-slate-400">{selected.detail}</p>
        </div>
      ) : null}

      {inputType !== "user_text" ? (
        <p className="mt-4 text-xs text-slate-500">
          找不到目标？前往
          <Link
            className="mx-1 text-cyan-300 hover:underline"
            href={
              inputType === "content"
                ? "/contents"
                : inputType === "news"
                  ? "/news"
                  : "/events"
            }
          >
            完整素材列表
          </Link>
          后点击“生成”。
        </p>
      ) : null}
    </section>
  );
}

async function sourceCandidates(
  workspaceId: string,
  inputType: CreationSourceType,
): Promise<SourceCard[]> {
  if (inputType === "user_text") return [];
  const path =
    inputType === "content"
      ? "/contents?page=1&page_size=12&sort=view_count&order=desc"
      : inputType === "news"
        ? "/news/articles?page=1&page_size=12&sort=heat_score&order=desc"
        : "/news/events?page=1&page_size=12&sort=heat_score&order=desc";
  const page = await apiRequest<
    ContentRecordPage | ArticleRecordPage | TopicEventPage
  >(path, { workspaceId });
  return page.items.map((item) => normalizeSource(inputType, item));
}

async function sourceDetail(
  workspaceId: string,
  inputType: CreationSourceType,
  inputId: string,
): Promise<SourceCard | null> {
  if (inputType === "user_text" || !inputId) return null;
  const path =
    inputType === "content"
      ? `/contents/${encodeURIComponent(inputId)}`
      : inputType === "news"
        ? `/news/articles/${encodeURIComponent(inputId)}`
        : `/news/events/${encodeURIComponent(inputId)}`;
  const item = await apiRequest<
    ContentRecord | ArticleRecord | TopicEventDetail
  >(path, { workspaceId });
  return normalizeSource(inputType, item);
}

function normalizeSource(
  inputType: Exclude<CreationSourceType, "user_text">,
  item: ContentRecord | ArticleRecord | TopicEventRecord,
): SourceCard {
  if (inputType === "content") {
    const content = item as ContentRecord;
    return {
      id: content.id,
      title: content.title,
      detail: `${content.platform.name} · ${formatNumber(content.latest_snapshot?.view_count)} 播放${content.view_growth_24h === null ? "" : ` · 24h +${formatNumber(content.view_growth_24h)}`}`,
      time: content.published_at,
      sourceKind: content.source_kind,
    };
  }
  if (inputType === "news") {
    const article = item as ArticleRecord;
    return {
      id: article.id,
      title: article.title,
      detail: `${article.source.name} · 热度 ${formatNumber(article.heat_score)}`,
      time: article.published_at,
      sourceKind: article.source_kind,
    };
  }
  const event = item as TopicEventRecord;
  return {
    id: event.id,
    title: event.title,
    detail: `${event.source_count} 个来源 · 热度 ${formatNumber(event.heat_score)} · 故事性 ${formatNumber(event.story_score)}`,
    time: event.last_update_time,
    sourceKind: "aggregated",
  };
}

function sourceLabel(value: string): string {
  return value === "aggregated" ? "多来源聚合" : sourceKindLabel(value);
}
