"use client";

import type {
  ContentRecord,
  ContentSnapshotPage,
  DerivedMetricPage,
} from "@sio/shared-types";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Captions, ExternalLink, FileJson, Film, Sparkles } from "lucide-react";
import Link from "next/link";
import { useWorkspace } from "@/components/app-shell";
import { BackButton } from "@/components/back-button";
import { ExternalImage } from "@/components/external-image";
import { SubtitleVideoPlayer } from "@/components/subtitle-video-player";
import { contentCoverUrl } from "@/lib/media";
import { TrendChart } from "@/components/trend-chart";
import {
  MetricCard,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  secondaryButtonClass,
} from "@/components/ui";
import {
  InteractionBreakdown,
  TrafficSourceBreakdown,
  metricCardNode,
} from "@/components/metric-availability";
import { apiRequest, downloadApiFile } from "@/lib/browser-api";
import {
  DERIVED_METRIC_LABELS,
  formatDerivedMetricValue,
  metricQualityLabel,
} from "@/lib/metric-definitions";
import {
  formatDate,
  formatNumber,
  formatPercent,
  sourceKindLabel,
} from "@/lib/format";
import { buildChartSeries, latestObservedValue } from "@/lib/time-series";
function formatWatchTime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const total = Math.round(seconds);
  if (total < 60) return `${total}秒`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return rest ? `${minutes}分${rest}秒` : `${minutes}分`;
}

/** One asset slot in the media panel. Collapses to a "未下载" stub when empty. */
function MediaCard({
  title,
  icon,
  present,
  notDownloadedHint,
  action,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  present: boolean;
  notDownloadedHint: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  if (!present) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-700 px-4 py-6 text-center">
        <div className="flex items-center gap-2 text-slate-400">
          {icon}
          <span className="text-sm">{title}</span>
        </div>
        <p className="mt-2 text-xs text-slate-500">{notDownloadedHint}</p>
        {action && <div className="mt-3">{action}</div>}
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-xl border border-slate-800">
      <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-2 text-sm font-medium text-white">
        {icon}
        <span>{title}</span>
        {action && <span className="ml-auto">{action}</span>}
      </div>
      <div className="p-3">{children}</div>
    </div>
  );
}

// ---- per-item on-demand download (yt-dlp) -------------------------------

interface DownloadRead {
  id: string;
  status: string;
  error: string | null;
  media: {
    base: string;
    thumbnail?: string | null;
    video?: string | null;
    audio?: string | null;
    info_json?: string | null;
    subtitles?: { lang: string; file: string }[] | null;
  } | null;
}

interface DownloadForm {
  download_video: boolean;
  video_quality: string;
  video_format: string;
  audio_format: string;
  bitrate: string;
  naming_rule: string;
  write_subtitles: boolean;
  write_auto_subtitles: boolean;
  subtitle_langs: string;
  write_thumbnail: boolean;
  write_info_json: boolean;
}

const QUALITY_OPTIONS = ["best", "2160p", "1440p", "1080p", "720p", "480p", "audio"];
const VIDEO_FORMAT_OPTIONS = ["best", "mp4", "webm", "mkv"];
const AUDIO_FORMAT_OPTIONS = ["best", "mp3", "m4a", "aac", "opus", "wav", "flac"];
const BITRATE_OPTIONS = ["", "320K", "256K", "192K", "128K"];
const NAMING_OPTIONS = ["id", "title", "uploader", "date_title"];

// Default form factory per media type — each modal is focused on one asset.
function baseForm(): DownloadForm {
  return {
    download_video: true,
    video_quality: "best",
    video_format: "best",
    audio_format: "best",
    bitrate: "",
    naming_rule: "id",
    write_subtitles: true,
    write_auto_subtitles: false,
    subtitle_langs: "zh.*,en.*",
    write_thumbnail: false,
    write_info_json: false,
  };
}
function videoDefaultForm(): DownloadForm {
  return { ...baseForm(), download_video: true };
}
function subtitleDefaultForm(): DownloadForm {
  return { ...baseForm(), download_video: false, write_subtitles: true };
}
function metadataDefaultForm(): DownloadForm {
  return {
    ...baseForm(),
    download_video: false,
    write_subtitles: false,
    write_info_json: true,
  };
}

interface ModalProps {
  open: boolean;
  onClose: () => void;
  content: ContentRecord;
  workspaceId: string;
}

/** Shared submit + poll + file-save lifecycle for the focused download modals. */
function useDownloadModal(content: ContentRecord, workspaceId: string) {
  const [download, setDownload] = useState<DownloadRead | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(
    async (form: DownloadForm) => {
      setSubmitting(true);
      setError(null);
      try {
        const rec = await apiRequest<DownloadRead>("/downloads", {
          method: "POST",
          workspaceId,
          csrf: true,
          body: JSON.stringify({ url: content.canonical_url, ...form }),
        });
        setDownload(rec);
      } catch (e) {
        setError(e instanceof Error ? e.message : "提交下载失败");
      } finally {
        setSubmitting(false);
      }
    },
    [content, workspaceId],
  );

  useEffect(() => {
    if (!download || ["done", "empty", "failed"].includes(download.status)) return;
    const timer = setInterval(async () => {
      try {
        const rec = await apiRequest<DownloadRead>(`/downloads/${download.id}`, {
          workspaceId,
        });
        setDownload(rec);
        if (["done", "empty", "failed"].includes(rec.status)) clearInterval(timer);
      } catch {
        /* transient polling errors are non-fatal */
      }
    }, 2500);
    return () => clearInterval(timer);
  }, [download, workspaceId]);

  const saveFile = useCallback(
    (file: string) => {
      if (!download) return;
      downloadApiFile(
        `/downloads/${download.id}/file/${encodeURIComponent(file)}`,
        workspaceId,
        file,
      );
    },
    [download, workspaceId],
  );

  const busy =
    download != null && !["done", "empty", "failed"].includes(download.status);
  const mediaFiles = useMemo(() => {
    const media = download?.media;
    if (!media) return [] as { label: string; file: string }[];
    const files: { label: string; file: string }[] = [];
    if (media.video) files.push({ label: `视频 · ${media.video}`, file: media.video });
    if (media.audio) files.push({ label: `音频 · ${media.audio}`, file: media.audio });
    if (media.thumbnail)
      files.push({ label: `封面 · ${media.thumbnail}`, file: media.thumbnail });
    if (media.info_json)
      files.push({ label: `信息 · ${media.info_json}`, file: media.info_json });
    for (const s of media.subtitles ?? []) {
      files.push({ label: `字幕 · ${s.lang || "未知"}`, file: s.file });
    }
    return files;
  }, [download]);

  return { download, submitting, error, submit, saveFile, busy, mediaFiles };
}

/** Shared overlay chrome + status / result rendering for the focused modals. */
function DownloadModalFrame({
  open,
  onClose,
  title,
  subtitle,
  error,
  download,
  mediaFiles,
  saveFile,
  submitDisabled,
  onSubmit,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle: string;
  error: string | null;
  download: DownloadRead | null;
  mediaFiles: { label: string; file: string }[];
  saveFile: (file: string) => void;
  submitDisabled: boolean;
  onSubmit: () => void;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/60 p-4"
      role="presentation"
      onClick={onClose}
    >
      <div
        className="my-auto max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-base font-semibold text-white">{title}</h3>
            <p className="mt-1 text-xs text-slate-500">{subtitle}</p>
          </div>
          <button
            className="text-slate-500 hover:text-white"
            onClick={onClose}
            aria-label="关闭"
          >
            ✕
          </button>
        </div>

        <div className="mt-4 space-y-3">{children}</div>

        {error && (
          <p className="mt-3 rounded-md border border-red-900/60 bg-red-950/40 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}

        <div className="mt-4 flex items-center gap-2">
          <button
            className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
            onClick={onSubmit}
            disabled={submitDisabled}
          >
            开始下载
          </button>
          {download && (
            <span className="text-xs text-slate-400">
              状态：{download.status}
              {(download.status === "running" || download.status === "pending") &&
                "（拉取中…）"}
            </span>
          )}
        </div>

        {download && mediaFiles.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 text-xs text-slate-400">下载完成，点击保存到本地：</p>
            <ul className="flex flex-wrap gap-2">
              {mediaFiles.map((m) => (
                <li key={m.file}>
                  <button
                    className="rounded-md border border-slate-700 px-2 py-1 text-xs text-sky-400 hover:text-sky-300"
                    onClick={() => saveFile(m.file)}
                  >
                    {m.label}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {download && download.status === "failed" && (
          <p className="mt-3 text-xs text-red-400">
            下载失败：{download.error || "未知错误"}
          </p>
        )}
        {download && download.status === "empty" && (
          <p className="mt-3 rounded-md border border-amber-900/60 bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
            {download.error ||
              "已拉取，但未生成任何媒体文件（请检查清晰度 / 开关设置）。"}
          </p>
        )}
      </div>
    </div>
  );
}

const selectClass =
  "rounded-md border border-slate-700 bg-slate-800 px-2 py-1 text-sm text-white";
const labelClass = "text-xs text-slate-400";
const fieldClass = "flex flex-col gap-1";

function VideoDownloadModal({ open, onClose, content, workspaceId }: ModalProps) {
  const { download, submitting, error, submit, saveFile, busy, mediaFiles } =
    useDownloadModal(content, workspaceId);
  const [form, setForm] = useState<DownloadForm>(() => videoDefaultForm());
  const isAudio = form.video_quality === "audio";
  return (
    <DownloadModalFrame
      open={open}
      onClose={onClose}
      title="下载视频"
      subtitle={`仅对当前作品（${content.title.slice(0, 28) || "该作品"}）生效，使用 yt-dlp 从源站重新拉取。`}
      error={error}
      download={download}
      mediaFiles={mediaFiles}
      saveFile={saveFile}
      submitDisabled={submitting || busy}
      onSubmit={() => submit(form)}
    >
      <div className={fieldClass}>
        <span className={labelClass}>视频清晰度</span>
        <select
          className={selectClass}
          value={form.video_quality}
          onChange={(e) => setForm({ ...form, video_quality: e.target.value })}
        >
          {QUALITY_OPTIONS.map((o) => (
            <option key={o} value={o}>
              {o === "audio" ? "仅音频" : o}
            </option>
          ))}
        </select>
      </div>
      <div className={fieldClass}>
        <span className={labelClass}>视频格式（容器）</span>
        <select
          className={selectClass}
          value={form.video_format}
          onChange={(e) => setForm({ ...form, video_format: e.target.value })}
        >
          {VIDEO_FORMAT_OPTIONS.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </div>
      {isAudio && (
        <div className="grid grid-cols-2 gap-3">
          <div className={fieldClass}>
            <span className={labelClass}>音频格式</span>
            <select
              className={selectClass}
              value={form.audio_format}
              onChange={(e) => setForm({ ...form, audio_format: e.target.value })}
            >
              {AUDIO_FORMAT_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </div>
          <div className={fieldClass}>
            <span className={labelClass}>码率（仅音频提取）</span>
            <select
              className={selectClass}
              value={form.bitrate}
              onChange={(e) => setForm({ ...form, bitrate: e.target.value })}
            >
              {BITRATE_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o || "默认"}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
      <div className={fieldClass}>
        <span className={labelClass}>命名规则</span>
        <select
          className={selectClass}
          value={form.naming_rule}
          onChange={(e) => setForm({ ...form, naming_rule: e.target.value })}
        >
          {NAMING_OPTIONS.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </div>
    </DownloadModalFrame>
  );
}

function SubtitleDownloadModal({ open, onClose, content, workspaceId }: ModalProps) {
  const { download, submitting, error, submit, saveFile, busy, mediaFiles } =
    useDownloadModal(content, workspaceId);
  const [form, setForm] = useState<DownloadForm>(() => subtitleDefaultForm());
  return (
    <DownloadModalFrame
      open={open}
      onClose={onClose}
      title="下载字幕"
      subtitle={`仅对当前作品（${content.title.slice(0, 28) || "该作品"}）生效，使用 yt-dlp 从源站重新拉取字幕。`}
      error={error}
      download={download}
      mediaFiles={mediaFiles}
      saveFile={saveFile}
      submitDisabled={submitting || busy}
      onSubmit={() => submit(form)}
    >
      <label className="flex items-center gap-2 text-sm text-slate-300">
        <input
          type="checkbox"
          className="rounded border-slate-600 bg-slate-800"
          checked={form.write_subtitles}
          onChange={(e) => setForm({ ...form, write_subtitles: e.target.checked })}
        />
        下载字幕（人工字幕）
      </label>
      <label className="flex items-center gap-2 text-sm text-slate-300">
        <input
          type="checkbox"
          className="rounded border-slate-600 bg-slate-800"
          checked={form.write_auto_subtitles}
          onChange={(e) =>
            setForm({ ...form, write_auto_subtitles: e.target.checked })
          }
        />
        下载自动生成字幕（语音识别，质量较低）
      </label>
      <div className={fieldClass}>
        <span className={labelClass}>字幕语言（如 zh.*,en.*）</span>
        <input
          className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1 text-sm text-white"
          value={form.subtitle_langs}
          onChange={(e) => setForm({ ...form, subtitle_langs: e.target.value })}
        />
      </div>
    </DownloadModalFrame>
  );
}

function MetadataDownloadModal({ open, onClose, content, workspaceId }: ModalProps) {
  const { download, submitting, error, submit, saveFile, busy, mediaFiles } =
    useDownloadModal(content, workspaceId);
  const [form, setForm] = useState<DownloadForm>(() => metadataDefaultForm());
  return (
    <DownloadModalFrame
      open={open}
      onClose={onClose}
      title="下载原始信息 (info.json)"
      subtitle={`仅对当前作品（${content.title.slice(0, 28) || "该作品"}）生效，使用 yt-dlp 抓取原始元数据。`}
      error={error}
      download={download}
      mediaFiles={mediaFiles}
      saveFile={saveFile}
      submitDisabled={submitting || busy}
      onSubmit={() => submit(form)}
    >
      <label className="flex items-center gap-2 text-sm text-slate-300">
        <input
          type="checkbox"
          className="rounded border-slate-600 bg-slate-800"
          checked={form.write_info_json}
          onChange={(e) => setForm({ ...form, write_info_json: e.target.checked })}
        />
        下载 info.json（原始抓取元数据）
      </label>
    </DownloadModalFrame>
  );
}

export function ContentDetailClient({ id }: { id: string }) {
  const { workspaceId, loading: workspaceLoading } = useWorkspace();
  const item = useQuery({
    queryKey: ["content", id],
    queryFn: () =>
      apiRequest<ContentRecord>(`/contents/${id}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const snapshots = useQuery({
    queryKey: ["content-snapshots", id],
    queryFn: () =>
      apiRequest<ContentSnapshotPage>(
        `/contents/${id}/snapshots?page=1&page_size=100`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });
  const metrics = useQuery({
    queryKey: ["content-metrics", id],
    queryFn: () =>
      apiRequest<DerivedMetricPage>(
        `/contents/${id}/metrics?page=1&page_size=100`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });
  const [dlVideo, setDlVideo] = useState(false);
  const [dlSubtitle, setDlSubtitle] = useState(false);
  const [dlMetadata, setDlMetadata] = useState(false);
  if (workspaceLoading || !workspaceId || item.isLoading)
    return (
      <main className="p-8">
        <SkeletonRows />
      </main>
    );
  if (!item.data || item.error)
    return (
      <main className="p-8">
        <StatePanel
          type="error"
          title="作品详情加载失败"
          detail={item.error?.message}
        />
      </main>
    );
  const data = item.data;
  const history = snapshots.data?.items ?? [];
  const snapshot = data.latest_snapshot;
  const latestMetrics = Array.from(
    (metrics.data?.items ?? []).reduce((latest, metric) => {
      const key = `${metric.metric_key}:${metric.window}`;
      // The API is newest-first. Keep the first observation instead of letting
      // an older historical calculation overwrite it in the UI.
      if (!latest.has(key)) latest.set(key, metric);
      return latest;
    }, new Map<string, NonNullable<typeof metrics.data>["items"][number]>()),
  ).map(([, metric]) => metric);
  const trend = buildChartSeries(history, (point) => point.view_count);
  const media = data.media;
  const mediaUrl = (file: string) => `/api/v1/media/${id}/${encodeURIComponent(file)}`;
  const subs = media?.subtitles?.filter((s) => s?.file) ?? [];
  const hasSubtitles = subs.length > 0;
  const assetLinkClass =
    "inline-flex items-center gap-1 text-sm text-sky-400 hover:text-sky-300";
  const dlBtn = (kind: "video" | "subtitle" | "metadata") => (
    <button
      type="button"
      onClick={() => {
        if (kind === "video") setDlVideo(true);
        else if (kind === "subtitle") setDlSubtitle(true);
        else setDlMetadata(true);
      }}
      className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-slate-500 hover:text-white"
    >
      下载
    </button>
  );
  return (
    <main className="mx-auto max-w-[1400px] space-y-6 px-4 py-7 lg:px-8">
      <BackButton />
      <PageHeader
        eyebrow={`${data.platform.name} · ${sourceKindLabel(data.source_kind)}`}
        title={data.title}
        description={`发布于 ${formatDate(data.published_at)} · 最近观测 ${formatDate(data.last_seen_at)}`}
        actions={
          <>
            <Link
              className={`${secondaryButtonClass} whitespace-nowrap`}
              href={`/generate?input_type=content&input_id=${id}`}
            >
              <Sparkles size={15} />
              生成内容
            </Link>
            <a
              className={`${secondaryButtonClass} whitespace-nowrap`}
              href={data.canonical_url}
              target="_blank"
              rel="noreferrer"
            >
              查看原作品
              <ExternalLink size={15} />
            </a>
          </>
        }
      />
      {contentCoverUrl(data) && (
        <ExternalImage
          src={contentCoverUrl(data)}
          alt={data.title}
          className="max-h-72 w-full rounded-2xl border border-slate-800 object-cover"
        />
      )}
      <Panel className="p-5">
        <h2 className="font-medium text-white">媒体资源</h2>
        <p className="mt-1 text-xs text-slate-500">
          同步时按「设置 → 同步设置 → 媒体下载」中的开关归档的本地文件；未开启的项显示「未下载」。封面已在上方预览。
        </p>
        <div className="mt-4 flex flex-col gap-4">
          <MediaCard
            title="视频"
            icon={<Film size={15} />}
            present={true}
            notDownloadedHint="未下载 · 点击「下载」用 yt-dlp 从源站重新拉取"
            action={dlBtn("video")}
          >
            <SubtitleVideoPlayer
              contentId={id}
              videoFile={media?.video}
              subtitles={subs}
            />
          </MediaCard>
          <MediaCard
            title="字幕文件"
            icon={<Captions size={15} />}
            present={hasSubtitles}
            notDownloadedHint="未下载 · 点击「下载」用 yt-dlp 从源站重新拉取"
            action={dlBtn("subtitle")}
          >
            {hasSubtitles ? (
              <ul className="flex flex-wrap gap-2">
                {subs.map((s) => (
                  <li key={s.file}>
                    <a
                      href={mediaUrl(s.file)}
                      target="_blank"
                      rel="noreferrer"
                      className={assetLinkClass}
                    >
                      {s.lang || "未知语言"}
                      <ExternalLink size={12} />
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-slate-500">
                该作品尚未归档任何字幕文件。
              </p>
            )}
          </MediaCard>
          <MediaCard
            title="原始信息 (info.json)"
            icon={<FileJson size={15} />}
            present={Boolean(media?.info_json)}
            notDownloadedHint="未下载 · 点击「下载」用 yt-dlp 从源站重新拉取"
            action={dlBtn("metadata")}
          >
            {media?.info_json && (
              <a
                href={mediaUrl(media.info_json)}
                target="_blank"
                rel="noreferrer"
                className={assetLinkClass}
              >
                查看 / 下载 JSON
                <ExternalLink size={12} />
              </a>
            )}
          </MediaCard>
        </div>
      </Panel>
      <VideoDownloadModal
        key={dlVideo ? "open" : "closed"}
        open={dlVideo}
        onClose={() => setDlVideo(false)}
        content={data}
        workspaceId={workspaceId!}
      />
      <SubtitleDownloadModal
        key={dlSubtitle ? "open" : "closed"}
        open={dlSubtitle}
        onClose={() => setDlSubtitle(false)}
        content={data}
        workspaceId={workspaceId!}
      />
      <MetadataDownloadModal
        key={dlMetadata ? "open" : "closed"}
        open={dlMetadata}
        onClose={() => setDlMetadata(false)}
        content={data}
        workspaceId={workspaceId!}
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="播放量"
          value={formatNumber(
            latestObservedValue(history, (point) => point.view_count) ??
              snapshot?.view_count,
          )}
          hint={`24h ${formatNumber(data.view_growth_24h)}`}
        />
        <MetricCard
          label="点赞"
          value={formatNumber(
            latestObservedValue(history, (point) => point.like_count) ??
              snapshot?.like_count,
          )}
        />
        <MetricCard
          label="评论"
          value={formatNumber(
            latestObservedValue(history, (point) => point.comment_count) ??
              snapshot?.comment_count,
          )}
        />
        <MetricCard
          label="分享"
          value={formatNumber(
            latestObservedValue(history, (point) => point.share_count) ??
              snapshot?.share_count,
          )}
        />
        <MetricCard
          label="收藏"
          value={formatNumber(
            latestObservedValue(history, (point) => point.favorite_count) ??
              snapshot?.favorite_count,
          )}
        />
        <MetricCard
          label="完播率"
          value={metricCardNode(
            "completion_rate",
            latestObservedValue(history, (point) => point.completion_rate) ??
              snapshot?.completion_rate,
            formatPercent,
          )}
          hint="需官方 API / 私有分析授权"
        />
        <MetricCard
          label="平均观看时长"
          value={metricCardNode(
            "average_watch_time",
            snapshot?.average_watch_time,
            formatWatchTime,
          )}
          hint="需官方 API / 私有分析授权"
        />
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <Panel className="p-5">
          <h2 className="font-medium text-white">互动拆解</h2>
          <p className="mt-1 text-xs text-slate-500">
            点赞 / 评论 / 收藏 /
            分享各占播放量的比例（基于最新快照；公开可获取字段）。
          </p>
          <InteractionBreakdown snapshot={snapshot} format={formatPercent} />
        </Panel>
        <Panel className="p-5">
          <h2 className="font-medium text-white">流量来源占比</h2>
          <p className="mt-1 text-xs text-slate-500">
            推荐 / 搜索 / 关注流量占比；需要配置该平台官方 API
            或流量来源授权后返回真实值。
          </p>
          <TrafficSourceBreakdown
            split={{
              recommendation_traffic_rate:
                snapshot?.recommendation_traffic_rate ?? null,
              search_traffic_rate: snapshot?.search_traffic_rate ?? null,
              profile_traffic_rate: snapshot?.profile_traffic_rate ?? null,
            }}
            format={formatPercent}
          />
        </Panel>
      </div>
      <div className="grid gap-5 xl:grid-cols-[2fr_1fr]">
        <Panel className="p-5">
          <h2 className="font-medium text-white">播放趋势</h2>
          <TrendChart data={trend} />
        </Panel>
        <Panel className="p-5">
          <h2 className="font-medium text-white">派生指标</h2>
          <div className="mt-3 divide-y divide-slate-800">
            {latestMetrics.map((metric) => (
              <div
                className="flex justify-between py-3 text-sm"
                key={metric.id}
              >
                <span className="text-slate-400">
                  {DERIVED_METRIC_LABELS[metric.metric_key] ??
                    metric.metric_key}{" "}
                  · {metric.window}
                </span>
                <span className="text-right">
                  <span className="block">
                    {formatDerivedMetricValue(metric.metric_key, metric.value)}
                  </span>
                  <span className="text-[10px] text-slate-500">
                    {metricQualityLabel(metric.metadata)}
                  </span>
                </span>
              </div>
            ))}
          </div>
          {!latestMetrics.length && (
            <p className="mt-4 text-sm text-slate-500">暂无已计算指标</p>
          )}
        </Panel>
      </div>
      <Panel className="p-5">
        <h2 className="font-medium text-white">作品说明</h2>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-400">
          {data.description || "平台未提供说明"}
        </p>
      </Panel>
    </main>
  );
}
