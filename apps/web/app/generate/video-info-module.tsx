"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { MessageSquare, Tag } from "lucide-react";
import type { ContentRecord } from "@sio/shared-types";
import { apiRequest } from "@/lib/browser-api";
import { useWorkspace } from "@/components/app-shell";

export interface VideoComment {
  id: string;
  author_name: string;
  text: string;
  like_count: number | null;
  reply_count: number | null;
}

export interface VideoContext {
  name?: string;
  tags?: string[];
  subtitleLangs?: string[];
  comments?: VideoComment[];
}

interface VideoInfoModuleProps {
  inputId: string;
  inputType: string;
  onChange: (ctx: VideoContext | null) => void;
}

/**
 * "视频信息" module for one-click creation. Assembles the pieces of a video
 * that should be fed to the LLM (name / tags / subtitles / hot comments), with
 * live plain-text preview. Defaults check name + tags + subtitles; hot comments
 * are opt-in and, when enabled, expose a multi-select of the top comments.
 */
export function VideoInfoModule({
  inputId,
  inputType,
  onChange,
}: VideoInfoModuleProps) {
  const { workspaceId } = useWorkspace();
  const [includeName, setIncludeName] = useState(true);
  const [includeTags, setIncludeTags] = useState(true);
  const [includeSubtitles, setIncludeSubtitles] = useState(true);
  const [includeComments, setIncludeComments] = useState(false);
  const [selectedCommentIds, setSelectedCommentIds] = useState<string[]>([]);

  const content = useQuery({
    queryKey: ["content-for-generation", inputId],
    queryFn: () =>
      apiRequest<ContentRecord>(`/contents/${inputId}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(inputId) && inputType === "content",
  });

  const comments = useQuery({
    queryKey: ["content-comments-for-generation", inputId],
    queryFn: () =>
      apiRequest<VideoComment[]>(`/contents/${inputId}/comments`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(inputId) && inputType === "content" && includeComments,
  });

  const data = content.data;
  const subtitleLangs =
    data?.media?.subtitles?.map((s) => s.lang).filter(Boolean) ?? [];
  const commentList = comments.data ?? [];

  const selectedComments = commentList.filter((c) =>
    selectedCommentIds.includes(c.id),
  );
  const selectedCommentKey = selectedCommentIds.join("|");
  const tagsKey = data?.tags?.join("|");
  const subtitleLangsKey = subtitleLangs.join("|");

  useEffect(() => {
    if (inputType !== "content" || !inputId) {
      onChange(null);
      return;
    }
    const ctx: VideoContext = {};
    if (includeName && data?.title) ctx.name = data.title;
    if (includeTags && data?.tags?.length) ctx.tags = data.tags;
    if (includeSubtitles && subtitleLangs.length)
      ctx.subtitleLangs = subtitleLangs;
    if (includeComments && selectedComments.length)
      ctx.comments = selectedComments;
    const empty =
      !ctx.name && !ctx.tags && !ctx.subtitleLangs && !ctx.comments;
    onChange(empty ? null : ctx);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    includeName,
    includeTags,
    includeSubtitles,
    includeComments,
    selectedCommentKey,
    data?.title,
    tagsKey,
    subtitleLangsKey,
    inputType,
    inputId,
  ]);

  if (inputType !== "content") {
    return (
      <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-5 lg:p-6">
        <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
          02 · 视频信息
        </p>
        <p className="mt-3 text-sm text-slate-400">
          该模块用于「视频素材」来源：选择一条视频后，可将其名称、标签、字幕与热门评论作为素材提交给内容引擎。当前素材类型无需视频信息。
        </p>
      </section>
    );
  }

  if (!inputId) {
    return (
      <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-5 lg:p-6">
        <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
          02 · 视频信息
        </p>
        <p className="mt-3 text-sm text-slate-400">
          请先在「01 · 选择素材」中选择一条视频素材，这里会显示其名称、标签与字幕等信息。
        </p>
      </section>
    );
  }

  function toggleComment(id: string) {
    setSelectedCommentIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-5 lg:p-6">
      <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
        02 · 视频信息
      </p>
      <h2 className="mt-2 text-xl font-semibold text-white">
        选择要提交给内容引擎的视频素材
      </h2>
      <p className="mt-2 text-sm text-slate-400">
        勾选后，对应内容会以纯文本形式拼接到素材中；默认包含视频名称、标签与字幕语种。
      </p>

      {content.isLoading ? (
        <p className="mt-4 text-sm text-slate-500">加载视频信息…</p>
      ) : content.isError ? (
        <p className="mt-4 text-sm text-rose-300">无法加载该视频信息。</p>
      ) : (
        <div className="mt-5 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <CheckboxPill
              checked={includeName}
              onChange={setIncludeName}
              label="视频名称"
              detail={data?.title}
            />
            <CheckboxPill
              checked={includeTags}
              onChange={setIncludeTags}
              label="视频标签"
              detail={
                data?.tags?.length ? data.tags.slice(0, 4).join("、") : "无"
              }
              icon={<Tag size={13} />}
            />
            <CheckboxPill
              checked={includeSubtitles}
              onChange={setIncludeSubtitles}
              label="视频字幕"
              detail={
                subtitleLangs.length ? subtitleLangs.join("、") : "无已下载字幕"
              }
            />
            <CheckboxPill
              checked={includeComments}
              onChange={(v) => {
                setIncludeComments(v);
                if (!v) setSelectedCommentIds([]);
              }}
              label="热门评论"
              detail={
                commentList.length ? `共 ${commentList.length} 条` : "暂无"
              }
              icon={<MessageSquare size={13} />}
            />
          </div>

          {includeComments && (
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
              <p className="mb-2 text-xs text-slate-400">
                选择要纳入的热门评论（可多选）：
              </p>
              {commentList.length === 0 ? (
                <p className="text-sm text-slate-500">
                  该视频暂未采集到评论。可在「系统 → 视频下载 / 评论采集」中开启评论抓取。
                </p>
              ) : (
                <ul className="max-h-56 space-y-1.5 overflow-auto">
                  {commentList.map((c) => {
                    const checked = selectedCommentIds.includes(c.id);
                    return (
                      <li key={c.id}>
                        <button
                          type="button"
                          onClick={() => toggleComment(c.id)}
                          className={`flex w-full items-start gap-2 rounded-lg border px-3 py-2 text-left text-sm ${
                            checked
                              ? "border-cyan-700 bg-cyan-950/40"
                              : "border-slate-800 hover:border-slate-700"
                          }`}
                        >
                          <span
                            className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                              checked
                                ? "border-cyan-400 bg-cyan-500/20 text-cyan-300"
                                : "border-slate-600"
                            }`}
                          >
                            {checked ? "✓" : ""}
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate text-slate-200">
                              {c.author_name}
                            </span>
                            <span className="block line-clamp-2 text-xs text-slate-400">
                              {c.text}
                            </span>
                            <span className="mt-0.5 block text-[11px] text-slate-500">
                              赞 {c.like_count ?? "?"} · 回 {c.reply_count ?? "?"}
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          )}

          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <p className="mb-2 text-xs font-medium text-slate-400">
              素材预览（将提交给内容引擎的纯文本）
            </p>
            <pre className="whitespace-pre-wrap break-words text-xs leading-6 text-slate-300">
              {buildPreview()}
            </pre>
          </div>
        </div>
      )}
    </section>
  );

  function buildPreview(): string {
    const lines: string[] = [];
    if (includeName && data?.title) lines.push(`视频名称：${data.title}`);
    if (includeTags && data?.tags?.length)
      lines.push(`视频标签：${data.tags.join(", ")}`);
    if (includeSubtitles && subtitleLangs.length)
      lines.push(`视频字幕语种：${subtitleLangs.join(", ")}`);
    if (includeComments && selectedComments.length) {
      lines.push("热门评论：");
      for (const c of selectedComments) {
        lines.push(
          `- （${c.author_name} · 赞 ${c.like_count ?? "?"} / 回 ${c.reply_count ?? "?"}）${c.text}`,
        );
      }
    }
    return lines.length ? lines.join("\n") : "（未选择任何素材）";
  }
}

function CheckboxPill({
  checked,
  onChange,
  label,
  detail,
  icon,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  detail?: string;
  icon?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 text-left ${
        checked
          ? "border-cyan-700 bg-cyan-950/40"
          : "border-slate-800 hover:border-slate-700"
      }`}
    >
      <span
        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
          checked
            ? "border-cyan-400 bg-cyan-500/20 text-cyan-300"
            : "border-slate-600"
        }`}
      >
        {checked ? "✓" : ""}
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-1 text-sm text-slate-200">
          {icon}
          {label}
        </span>
        {detail && (
          <span className="block truncate text-xs text-slate-500">{detail}</span>
        )}
      </span>
    </button>
  );
}
