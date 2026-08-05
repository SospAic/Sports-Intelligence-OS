"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Captions,
  Download as DownloadIcon,
  FileJson,
  Film,
  Link2,
  Loader2,
} from "lucide-react";
import { useWorkspace } from "@/components/app-shell";
import { ExternalImage } from "@/components/external-image";
import { apiRequest } from "@/lib/browser-api";
import {
  Badge,
  PageHeader,
  Panel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { formatDate } from "@/lib/format";

interface DownloadMedia {
  base: string;
  video?: string | null;
  thumbnail?: string | null;
  info_json?: string | null;
  subtitles?: { lang: string; file: string }[] | null;
}

interface DownloadRecord {
  id: string;
  workspace_id: string;
  url: string;
  platform: string | null;
  status: "pending" | "running" | "done" | "empty" | "failed";
  error: string | null;
  media: DownloadMedia | null;
  created_at: string;
  updated_at: string;
}

interface DownloadPreview {
  url: string;
  platform: string | null;
  external_id: string | null;
  title: string | null;
  uploader: string | null;
  thumbnail: string | null;
  duration_seconds: number | null;
  description: string | null;
  subtitle_languages: string[];
}

function statusBadge(status: string) {
  if (status === "done")
    return <Badge tone="success">已完成</Badge>;
  if (status === "running" || status === "pending")
    return <Badge tone="info">{status === "running" ? "下载中" : "排队中"}</Badge>;
  if (status === "failed") return <Badge tone="danger">失败</Badge>;
  return <Badge tone="neutral">无结果</Badge>;
}

export default function DownloadPage() {
  const { workspaceId } = useWorkspace();
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<DownloadPreview | null>(null);
  const [downloadVideo, setDownloadVideo] = useState(true);
  const [videoFormat, setVideoFormat] = useState("best");
  const [writeSubtitles, setWriteSubtitles] = useState(true);
  const [writeAutoSubtitles, setWriteAutoSubtitles] = useState(false);
  const [subtitleLangs, setSubtitleLangs] = useState("zh.*,en.*");
  const [writeThumbnail, setWriteThumbnail] = useState(true);
  const [writeInfoJson, setWriteInfoJson] = useState(false);
  const [saveToWorks, setSaveToWorks] = useState(false);

  const list = useQuery({
    queryKey: ["downloads", workspaceId],
    queryFn: () =>
      apiRequest<{ items: DownloadRecord[]; total: number }>("/downloads", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
    refetchInterval: 4000,
  });

  const resolve = useMutation({
    mutationFn: async () =>
      apiRequest<DownloadPreview>("/downloads/preview", {
        method: "POST",
        workspaceId: workspaceId!,
        body: JSON.stringify({ url: url.trim() }),
      }),
    onSuccess: (result) => setPreview(result),
  });

  const create = useMutation({
    mutationFn: async () => {
      return apiRequest<DownloadRecord>("/downloads", {
        method: "POST",
        workspaceId: workspaceId!,
        csrf: true,
        body: JSON.stringify({
          url: url.trim(),
          download_video: downloadVideo,
          video_format: videoFormat,
          write_subtitles: writeSubtitles,
          write_auto_subtitles: writeAutoSubtitles,
          subtitle_langs: subtitleLangs,
          write_thumbnail: writeThumbnail,
          write_info_json: writeInfoJson,
          save_to_works: saveToWorks,
        }),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["downloads", workspaceId] });
      setUrl("");
      setPreview(null);
      resolve.reset();
    },
  });

  return (
    <main className="mx-auto max-w-[1280px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="MEDIA WORKSPACE"
        title="视频下载"
        description="先解析公开地址，再选择视频、字幕、封面和清晰度。任务提交后异步执行，页面不会被下载过程锁死。"
      />

      <Panel className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-medium text-white">解析视频地址</h2>
            <p className="mt-1 text-sm text-slate-500">先获取公开页面信息，再选择需要保存的媒体资源。</p>
          </div>
          {preview && <Badge tone="success">地址已解析</Badge>}
        </div>
        <div className="mt-4 space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row">
            <input
              className={`${inputClass} min-w-0 flex-1`}
              placeholder="粘贴视频链接，例如 https://www.youtube.com/watch?v=..."
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                setPreview(null);
                resolve.reset();
              }}
            />
            <button
              className={`${secondaryButtonClass} shrink-0 sm:min-w-28`}
              disabled={!url.trim() || resolve.isPending}
              onClick={() => resolve.mutate()}
              type="button"
            >
              {resolve.isPending ? <Loader2 size={15} className="animate-spin" /> : <Link2 size={15} />}
              {resolve.isPending ? "解析中…" : "解析地址"}
            </button>
          </div>
          {resolve.isError && (
            <p className="rounded-lg border border-rose-900/50 bg-rose-950/30 p-3 text-sm text-rose-300">
              {resolve.error instanceof Error ? resolve.error.message : "地址解析失败，请检查链接或稍后重试"}
            </p>
          )}
          {preview && (
            <div className="grid overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40 md:grid-cols-[minmax(220px,320px)_1fr]">
              <div className="aspect-video bg-slate-900 md:aspect-auto">
                {preview.thumbnail ? (
                  <ExternalImage
                    src={preview.thumbnail}
                    alt={preview.title ?? "视频封面"}
                    className="h-full min-h-44 w-full object-cover"
                  />
                ) : (
                  <div className="grid h-full min-h-44 place-items-center text-slate-600">
                    <Film size={38} />
                  </div>
                )}
              </div>
              <div className="min-w-0 p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="info">{preview.platform ?? "视频"}</Badge>
                  {preview.uploader && <span className="text-xs text-slate-500">{preview.uploader}</span>}
                </div>
                <h3 className="mt-2 line-clamp-2 text-lg font-semibold text-white">
                  {preview.title || "未读取到标题"}
                </h3>
                <p className="mt-2 line-clamp-3 text-sm leading-6 text-slate-400">
                  {preview.description || "源站未提供简介。"}
                </p>
                <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
                  {preview.duration_seconds != null && <span>时长 {Math.round(preview.duration_seconds)} 秒</span>}
                  {preview.subtitle_languages.length > 0 && (
                    <span>字幕 {preview.subtitle_languages.slice(0, 6).join("、")}</span>
                  )}
                </div>
              </div>
            </div>
          )}
          <div className={preview ? "grid gap-4 md:grid-cols-2 xl:grid-cols-3" : "hidden"}>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={downloadVideo}
                onChange={(e) => setDownloadVideo(e.target.checked)}
              />
              下载视频
            </label>
            <label className="flex flex-col gap-1 text-sm text-slate-400">
              视频格式
              <select
                className={inputClass}
                value={videoFormat}
                onChange={(e) => setVideoFormat(e.target.value)}
                disabled={!downloadVideo}
              >
                <option value="best">最佳</option>
                <option value="bestvideo+bestaudio">最佳（分离音视频）</option>
                <option value="1080">1080p</option>
                <option value="720">720p</option>
                <option value="480">480p</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={writeSubtitles}
                onChange={(e) => setWriteSubtitles(e.target.checked)}
              />
              下载字幕
            </label>
            <label className="flex flex-col gap-1 text-sm text-slate-400">
              字幕语言
              <input
                className={inputClass}
                value={subtitleLangs}
                onChange={(e) => setSubtitleLangs(e.target.value)}
                placeholder="zh.*,en.*"
                disabled={!writeSubtitles}
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={writeAutoSubtitles}
                onChange={(e) => setWriteAutoSubtitles(e.target.checked)}
              />
              含自动生成字幕
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={writeThumbnail}
                onChange={(e) => setWriteThumbnail(e.target.checked)}
              />
              下载封面
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={writeInfoJson}
                onChange={(e) => setWriteInfoJson(e.target.checked)}
              />
              下载 info.json
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={saveToWorks}
                onChange={(e) => setSaveToWorks(e.target.checked)}
              />
              下载后保存至作品列表
            </label>
          </div>
          <button
            className={`${buttonClass} w-full sm:w-auto`}
            disabled={!url.trim() || !preview}
            onClick={() => create.mutate()}
            type="button"
          >
            <DownloadIcon size={16} />
            {create.isPending ? "任务已提交，可继续添加" : "提交异步下载"}
          </button>
          {!preview && <p className="text-sm text-slate-500">解析成功后才能提交下载任务。</p>}
          {create.isError && (
            <p className="text-sm text-rose-300">
              {create.error instanceof Error ? create.error.message : "提交失败"}
            </p>
          )}
        </div>
      </Panel>

      <Panel className="p-5">
        <h2 className="font-medium text-white">下载记录</h2>
        <div className="mt-4 space-y-3">
          {list.isLoading ? (
            <p className="text-sm text-slate-500">加载中…</p>
          ) : (list.data?.items?.length ?? 0) === 0 ? (
            <p className="text-sm text-slate-500">暂无下载记录</p>
          ) : (
            list.data?.items?.map((item) => (
              <div
                key={item.id}
                className="rounded-xl border border-slate-800 bg-slate-950/60 p-4"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noreferrer"
                    className="max-w-[70%] truncate text-sm text-sky-400 hover:text-sky-300"
                  >
                    {item.url}
                  </a>
                  <div className="flex items-center gap-2">
                    {statusBadge(item.status)}
                    {item.platform && (
                      <span className="text-xs text-slate-500">
                        {item.platform}
                      </span>
                    )}
                  </div>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  提交于 {formatDate(item.created_at)}
                </p>
                {item.status === "failed" && item.error && (
                  <p className="mt-2 text-xs text-rose-300">{item.error}</p>
                )}
                {item.media && (
                  <div className="mt-3 flex flex-wrap gap-3">
                    {item.media.video && (
                      <a
                        className="inline-flex items-center gap-1 text-sm text-sky-400 hover:text-sky-300"
                        href={`/api/v1/downloads/${item.id}/file/${encodeURIComponent(item.media.video)}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <Film size={14} /> 视频
                      </a>
                    )}
                    {item.media.subtitles?.map((s) => (
                      <a
                        key={s.file}
                        className="inline-flex items-center gap-1 text-sm text-sky-400 hover:text-sky-300"
                        href={`/api/v1/downloads/${item.id}/file/${encodeURIComponent(s.file)}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <Captions size={14} /> {s.lang || "字幕"}
                      </a>
                    ))}
                    {item.media.info_json && (
                      <a
                        className="inline-flex items-center gap-1 text-sm text-sky-400 hover:text-sky-300"
                        href={`/api/v1/downloads/${item.id}/file/${encodeURIComponent(item.media.info_json)}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <FileJson size={14} /> info.json
                      </a>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </Panel>
    </main>
  );
}
