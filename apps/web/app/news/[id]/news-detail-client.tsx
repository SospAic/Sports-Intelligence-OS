"use client";
import type { ArticleRecord } from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Pencil, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import {
  Badge,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { BackButton } from "@/components/back-button";
import { useToast } from "@/components/toast";
import { apiRequest } from "@/lib/browser-api";
import { formatDate, sportLabel } from "@/lib/format";

export function NewsDetailClient({ id }: { id: string }) {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const router = useRouter();
  const queryClient = useQueryClient();
  const canEdit = ["owner", "admin", "editor"].includes(role ?? "");
  const canDelete = ["owner", "admin"].includes(role ?? "");
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState(false);
  const [form, setForm] = useState({
    title: "",
    summary: "",
    content: "",
    author: "",
    sport: "",
    league: "",
    country: "",
    canonical_url: "",
    controversy_score: "",
    visual_score: "",
    story_score: "",
  });
  const query = useQuery({
    queryKey: ["article", id],
    queryFn: () =>
      apiRequest<ArticleRecord>(`/news/articles/${id}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });

  function startEdit(item: ArticleRecord) {
    setForm({
      title: item.title,
      summary: item.summary ?? "",
      content: item.content ?? "",
      author: item.author ?? "",
      sport: item.sport ?? "",
      league: item.league ?? "",
      country: item.country ?? "",
      canonical_url: item.canonical_url ?? "",
      controversy_score: "",
      visual_score: "",
      story_score: "",
    });
    setEditing(true);
  }

  async function saveEdit() {
    if (!workspaceId) return;
    setPending(true);
    try {
      const body: Record<string, unknown> = {};
      if (form.title.trim()) body.title = form.title.trim();
      if (form.summary.trim()) body.summary = form.summary.trim();
      if (form.content.trim()) body.content = form.content.trim();
      if (form.author.trim()) body.author = form.author.trim();
      if (form.sport.trim()) body.sport = form.sport.trim();
      if (form.league.trim()) body.league = form.league.trim();
      if (form.country.trim()) body.country = form.country.trim().toUpperCase();
      if (form.canonical_url.trim())
        body.canonical_url = form.canonical_url.trim();
      if (form.controversy_score)
        body.controversy_score = Number(form.controversy_score);
      if (form.visual_score) body.visual_score = Number(form.visual_score);
      if (form.story_score) body.story_score = Number(form.story_score);
      await apiRequest<ArticleRecord>(`/news/articles/${id}`, {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify(body),
      });
      notify("文章已更新");
      setEditing(false);
      await queryClient.invalidateQueries({ queryKey: ["article", id] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "更新失败", "error");
    } finally {
      setPending(false);
    }
  }

  async function deleteArticle() {
    if (!workspaceId) return;
    if (!window.confirm("确定删除该文章？此操作不可撤销。")) return;
    try {
      await apiRequest<void>(`/news/articles/${id}`, {
        method: "DELETE",
        workspaceId,
        csrf: true,
      });
      notify("文章已删除");
      router.push("/news");
    } catch (error) {
      notify(error instanceof Error ? error.message : "删除失败", "error");
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
          title="新闻详情加载失败"
          detail={query.error?.message}
        />
      </main>
    );
  const item = query.data;
  return (
    <main className="mx-auto max-w-5xl space-y-6 px-4 py-7 lg:px-8">
      <BackButton />
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
            {canEdit && (
              <button
                className={secondaryButtonClass}
                onClick={() => (editing ? setEditing(false) : startEdit(item))}
              >
                <Pencil size={15} />
                {editing ? "取消编辑" : "编辑"}
              </button>
            )}
            {canDelete && (
              <button
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-red-900/60 bg-slate-950 px-4 text-sm font-medium text-red-400 transition hover:bg-red-950/40 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={deleteArticle}
              >
                <Trash2 size={15} />
                删除
              </button>
            )}
          </>
        }
      />
      <div className="flex flex-wrap gap-2">
        <Badge tone="info">{sportLabel(item.sport)}</Badge>
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
      {editing ? (
        <Panel className="space-y-4 p-6">
          <h2 className="font-medium text-white">编辑文章</h2>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">标题</span>
              <input
                className={`${inputClass} w-full`}
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">作者</span>
              <input
                className={`${inputClass} w-full`}
                value={form.author}
                onChange={(e) => setForm({ ...form, author: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">运动</span>
              <input
                className={`${inputClass} w-full`}
                value={form.sport}
                onChange={(e) => setForm({ ...form, sport: e.target.value })}
                placeholder="如 basketball"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">联赛</span>
              <input
                className={`${inputClass} w-full`}
                value={form.league}
                onChange={(e) => setForm({ ...form, league: e.target.value })}
                placeholder="如 NBA"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">
                国家 (ISO)
              </span>
              <input
                className={`${inputClass} w-full`}
                value={form.country}
                onChange={(e) => setForm({ ...form, country: e.target.value })}
                placeholder="如 US"
                maxLength={2}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">
                原始链接
              </span>
              <input
                className={`${inputClass} w-full`}
                value={form.canonical_url}
                onChange={(e) =>
                  setForm({ ...form, canonical_url: e.target.value })
                }
              />
            </label>
          </div>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">摘要</span>
            <textarea
              className={`${inputClass} h-24 w-full resize-none`}
              value={form.summary}
              onChange={(e) => setForm({ ...form, summary: e.target.value })}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">正文</span>
            <textarea
              className={`${inputClass} h-40 w-full resize-none`}
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
            />
          </label>
          <div className="grid gap-3 md:grid-cols-3">
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">
                争议度 (0-100)
              </span>
              <input
                className={`${inputClass} w-full`}
                type="number"
                min="0"
                max="100"
                value={form.controversy_score}
                onChange={(e) =>
                  setForm({ ...form, controversy_score: e.target.value })
                }
                placeholder="保持不变"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">
                视觉度 (0-100)
              </span>
              <input
                className={`${inputClass} w-full`}
                type="number"
                min="0"
                max="100"
                value={form.visual_score}
                onChange={(e) =>
                  setForm({ ...form, visual_score: e.target.value })
                }
                placeholder="保持不变"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-slate-500">
                故事度 (0-100)
              </span>
              <input
                className={`${inputClass} w-full`}
                type="number"
                min="0"
                max="100"
                value={form.story_score}
                onChange={(e) =>
                  setForm({ ...form, story_score: e.target.value })
                }
                placeholder="保持不变"
              />
            </label>
          </div>
          <div className="flex gap-2">
            <button
              disabled={pending}
              className={buttonClass}
              onClick={saveEdit}
            >
              {pending ? "保存中…" : "保存修改"}
            </button>
            <button
              className={secondaryButtonClass}
              onClick={() => setEditing(false)}
            >
              取消
            </button>
          </div>
        </Panel>
      ) : (
        <>
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
        </>
      )}
    </main>
  );
}
