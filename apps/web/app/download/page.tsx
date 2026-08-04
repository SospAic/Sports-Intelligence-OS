"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download as DownloadIcon, Film, FileJson, Captions } from "lucide-react";
import { useWorkspace } from "@/components/app-shell";
import { apiRequest } from "@/lib/browser-api";
import { Badge, buttonClass, inputClass, Panel } from "@/components/ui";
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
  const [downloadVideo, setDownloadVideo] = useState(true);
  const [videoFormat, setVideoFormat] = useState("best");
  const [writeSubtitles, setWriteSubtitles] = useState(true);
  const [writeAutoSubtitles, setWriteAutoSubtitles] = useState(false);
  const [subtitleLangs, setSubtitleLangs] = useState("zh.*,en.*");
  const [writeThumbnail, setWriteThumbnail] = useState(true);
  const [writeInfoJson, setWriteInfoJson] = useState(false);

  const list = useQuery({
    queryKey: ["downloads", workspaceId],
    queryFn: () =>
      apiRequest<{ items: DownloadRecord[]; total: number }>("/downloads", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
    refetchInterval: 4000,
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
        }),
      });
    },
    onSuccess: () => {
      setUrl("");
      queryClient.invalidateQueries({ queryKey: ["downloads", workspaceId] });
    },
  });

  return (
    <main className="mx-auto max-w-[1100px] space-y-6 px-4 py-7 lg:px-8">
      <div>
        <h1 className="text-2xl font-semibold text-white">视频 / 字幕下载</h1>
        <p className="mt-1 text-sm text-slate-400">
          复用系统 yt-dlp 能力，支持尽可能多的视频网站（YouTube、TikTok、抖音、B站等）。
          提交链接后在后台下载视频与字幕，完成后可在此直接预览与下载。
        </p>
      </div>

      <Panel className="p-5">
        <h2 className="font-medium text-white">新建下载任务</h2>
        <div className="mt-4 space-y-4">
          <input
            className={`${inputClass} w-full`}
            placeholder="粘贴视频链接，例如 https://www.youtube.com/watch?v=..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
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
          </div>
          <button
            className={`${buttonClass} w-full sm:w-auto`}
            disabled={!url.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            <DownloadIcon size={16} />
            {create.isPending ? "提交中…" : "开始下载"}
          </button>
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
