"use client";

import type {
  ContentRecord,
  ContentSnapshotPage,
  DerivedMetricPage,
} from "@sio/shared-types";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createPortal } from "react-dom";
import {
  Captions,
  Download,
  ExternalLink,
  FileJson,
  Film,
  Loader2,
  MessageCircle,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useWorkspace } from "@/components/app-shell";
import { BackButton } from "@/components/back-button";
import { ExternalImage } from "@/components/external-image";
import { SubtitleVideoPlayer } from "@/components/subtitle-video-player";
import {
  SubtitleGenerationOptions,
  missingSubtitleGenerationLanguages,
  existingSubtitleGenerationLanguages,
} from "@/components/subtitle-generation-options";
import { contentCoverUrl } from "@/lib/media";
import {
  parseSubtitles,
  subtitleDisplayText,
  type SubtitleCue,
  type SubtitleWord,
} from "@/lib/subtitles";
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
import { apiRequest, downloadApiFile, downloadApiPostFile } from "@/lib/browser-api";
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
import {
  defaultSubtitleLanguagePair,
  subtitleLanguageLabel,
} from "@/lib/language-options";
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
  headerAction,
  alwaysShowHeader = false,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  present: boolean;
  notDownloadedHint: string;
  action?: React.ReactNode;
  headerAction?: React.ReactNode;
  alwaysShowHeader?: boolean;
  children: React.ReactNode;
}) {
  if (!present && !alwaysShowHeader) {
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
    <div className="relative rounded-xl border border-slate-800">
      <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-2 text-sm font-medium text-white">
        {icon}
        <span className="shrink-0">{title}</span>
        {(headerAction ?? action) && (
          <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-2">
            {headerAction ?? action}
          </div>
        )}
      </div>
      <div className="p-3">
        {present ? children : <p className="text-xs text-slate-500">{notDownloadedHint}</p>}
      </div>
    </div>
  );
}

function SubtitleHeaderControls({
  subtitles,
  primaryLang,
  secondaryLang,
  showTimeline,
  onPrimaryChange,
  onSecondaryChange,
  onTimelineChange,
}: {
  subtitles: { lang: string; file: string }[];
  primaryLang: string;
  secondaryLang: string;
  showTimeline: boolean;
  onPrimaryChange: (value: string) => void;
  onSecondaryChange: (value: string) => void;
  onTimelineChange: (value: boolean) => void;
}) {
  const languages = Array.from(
    new Set(subtitles.map((subtitle) => subtitle.lang).filter(Boolean)),
  );
  const compactSelectClass =
    "h-7 max-w-[7rem] rounded-md border border-slate-700 bg-slate-900 px-1.5 text-[11px] text-slate-200";
  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5 text-[11px] font-normal text-slate-400">
      <label className="flex items-center gap-1" title="第一语言">
        <span className="hidden sm:inline">第一</span>
        <select
          aria-label="第一语言"
          className={compactSelectClass}
          value={primaryLang}
          disabled={languages.length === 0}
          onChange={(event) => onPrimaryChange(event.target.value)}
        >
          <option value="">关闭</option>
          {languages.map((language) => (
            <option key={language} value={language}>
              {subtitleLanguageLabel(language)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1" title="第二语言">
        <span className="hidden sm:inline">第二</span>
        <select
          aria-label="第二语言"
          className={compactSelectClass}
          value={secondaryLang}
          disabled={languages.length === 0}
          onChange={(event) => onSecondaryChange(event.target.value)}
        >
          <option value="">无</option>
          {languages.map((language) => (
            <option key={language} value={language} disabled={language === primaryLang}>
              {subtitleLanguageLabel(language)}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1 whitespace-nowrap" title="是否显示时间戳">
        <input
          type="checkbox"
          aria-label="显示时间戳"
          className="rounded border-slate-600 bg-slate-800"
          checked={showTimeline}
          disabled={languages.length === 0}
          onChange={(event) => onTimelineChange(event.target.checked)}
        />
        <span className="hidden sm:inline">时间戳</span>
      </label>
    </div>
  );
}

function formatSubtitleStamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function renderSubtitleDisplayText(cue: SubtitleCue, currentTime: number | null): ReactNode {
  if (!cue.words?.length || currentTime == null) return subtitleDisplayText(cue.text);
  return cue.words.map((word: SubtitleWord, index: number) => {
    const active = currentTime >= word.start && currentTime < word.end;
    return (
      <span
        key={`${word.start}-${index}`}
        className={active ? "rounded bg-cyan-300/40 px-0.5 font-extrabold text-white" : ""}
      >
        {word.text}{index < cue.words!.length - 1 ? " " : ""}
      </span>
    );
  });
}

function SubtitleDisplayBox({
  contentId,
  workspaceId,
  subtitles,
  primaryLang,
  secondaryLang,
  showTimeline,
  currentTime,
}: {
  contentId: string;
  workspaceId: string;
  subtitles: { lang: string; file: string }[];
  primaryLang: string;
  secondaryLang: string;
  showTimeline: boolean;
  currentTime: number | null;
}) {
  const [cuesByLang, setCuesByLang] = useState<Record<string, SubtitleCue[]>>({});
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const activeCueRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const languages = [primaryLang, secondaryLang].filter(Boolean);
    if (languages.length === 0) {
      // Clear the derived track cache when the user switches to single-line
      // mode before starting the next asynchronous track load.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCuesByLang({});
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    void Promise.all(
      languages.map(async (language) => {
        const track = subtitles.find((item) => item.lang === language);
        if (!track) return [language, []] as const;
        const response = await fetch(
          `/api/v1/media/${contentId}/${encodeURIComponent(track.file)}`,
          { headers: { "X-Workspace-Id": workspaceId }, credentials: "include" },
        );
        if (!response.ok) throw new Error(`字幕轨道 ${language} 加载失败`);
        return [language, parseSubtitles(await response.text())] as const;
      }),
    )
      .then((entries) => {
        if (!cancelled) setCuesByLang(Object.fromEntries(entries));
      })
      .catch((reason) => {
        if (!cancelled) setLoadError(reason instanceof Error ? reason.message : "字幕加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [contentId, primaryLang, secondaryLang, subtitles, workspaceId]);

  const primaryCues = cuesByLang[primaryLang] ?? [];
  const secondaryCues = cuesByLang[secondaryLang] ?? [];
  const rows = primaryCues.map((primary) => ({
    primary,
    secondary:
      secondaryLang === ""
        ? null
        : secondaryCues.find(
            (cue) => cue.start < primary.end && cue.end > primary.start,
          ) ?? null,
  }));
  const activeIndex =
    currentTime == null
      ? -1
      : rows.findIndex(
          ({ primary }) => currentTime >= primary.start && currentTime < primary.end,
        );

  useEffect(() => {
    if (activeIndex < 0 || !activeCueRef.current || !scrollRef.current) return;
    const container = scrollRef.current;
    const cue = activeCueRef.current;
    const containerRect = container.getBoundingClientRect();
    const cueRect = cue.getBoundingClientRect();
    if (cueRect.top < containerRect.top || cueRect.bottom > containerRect.bottom) {
      const offset = cueRect.top - containerRect.top - containerRect.height / 2 + cueRect.height / 2;
      container.scrollTo({ top: Math.max(0, container.scrollTop + offset), behavior: "smooth" });
    }
  }, [activeIndex]);

  return (
    <div className="rounded-lg border border-violet-900/50 bg-violet-950/10 p-3">
      <div className="mb-2 flex items-center justify-between gap-2 text-xs">
        <span className="font-medium text-violet-100">字幕展示</span>
        <span className="text-slate-500">
          {rows.length > 0 ? `${rows.length} 条` : loading ? "加载中…" : "纯文本"}
        </span>
      </div>
      {loadError && <p className="mb-2 text-xs text-rose-300">{loadError}</p>}
      <div
        ref={scrollRef}
        aria-label="字幕展示框"
        className="max-h-72 min-h-16 space-y-2 overflow-y-auto overscroll-contain rounded-md border border-slate-800 bg-slate-950/70 p-2"
      >
        {rows.length === 0 ? (
          <p className="p-2 text-xs leading-5 text-slate-500">
            {loading ? "正在加载字幕内容…" : "当前没有可展示的字幕文本。"}
          </p>
        ) : (
          rows.map(({ primary, secondary }, index) => {
            const active = index === activeIndex;
            return (
              <div
                key={`${primary.start}-${index}`}
                ref={active ? activeCueRef : undefined}
                className={`rounded-md px-2 py-1.5 text-xs leading-5 transition ${
                  active ? "bg-cyan-950/60 text-white ring-1 ring-cyan-500/60" : "text-slate-300"
                }`}
              >
                {showTimeline && (
                  <div className="mb-1 text-[10px] text-cyan-300/80">
                    {formatSubtitleStamp(primary.start)} → {formatSubtitleStamp(primary.end)}
                  </div>
                )}
                <div className="whitespace-normal break-words">
                  {renderSubtitleDisplayText(primary, currentTime)}
                </div>
                {secondary && (
                  <div className="mt-1 whitespace-normal break-words text-cyan-100">
                    {showTimeline && (
                      <span className="mr-1 text-[10px] text-cyan-300/70">
                        [{formatSubtitleStamp(secondary.start)}]
                      </span>
                    )}
                    {renderSubtitleDisplayText(secondary, currentTime)}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ---- per-item on-demand download (yt-dlp) -------------------------------

interface DownloadRead {
  id: string;
  status: string;
  error: string | null;
  progress?: {
    stage?: string;
    percent?: number | null;
    message?: string | null;
    updated_at?: string | null;
    log?: { at: string; level: "info" | "warn" | "error"; message: string }[];
    files?: Record<string, "pending" | "ready" | "missing" | "failed">;
  };
  media: {
    base: string;
    thumbnail?: string | null;
    video?: string | null;
    audio?: string | null;
    info_json?: string | null;
    subtitles?: { lang: string; file: string }[] | null;
  } | null;
}

interface SubtitleJobRead {
  id: string;
  status: "queued" | "running" | "succeeded" | "degraded" | "failed";
  asr_backend: string;
  source_language: string | null;
  target_languages: string[];
  progress?: {
    stage?: string;
    percent?: number;
    log?: { at: string; level: "info" | "warn" | "error"; message: string }[];
  };
  result?: {
    generated_tracks?: { lang: string; file: string }[];
  } | null;
  error_code?: string | null;
  error_detail?: string | null;
}

const SUBTITLE_JOB_STATUS_LABELS: Record<SubtitleJobRead["status"], string> = {
  queued: "排队中",
  running: "执行中",
  succeeded: "已完成",
  degraded: "部分完成",
  failed: "失败",
};

interface HotCommentRecord {
  id: string;
  platform_comment_id: string;
  author_name: string;
  author_url: string | null;
  author_avatar_url: string | null;
  text: string;
  like_count: number | null;
  reply_count: number | null;
  parent_comment_id: string | null;
  is_reply: boolean;
  published_at: string | null;
  fetched_at: string;
  source_kind: "live" | "imported";
  source_provider: string;
  source_url: string | null;
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
  subtitle_primary_lang: string;
  subtitle_secondary_lang: string;
  subtitle_show_timestamps: boolean;
  write_thumbnail: boolean;
  write_info_json: boolean;
}

const QUALITY_OPTIONS = ["best", "2160p", "1440p", "1080p", "720p", "480p", "audio"];
const VIDEO_FORMAT_OPTIONS = ["best", "mp4", "webm", "mkv"];
const AUDIO_FORMAT_OPTIONS = ["best", "mp3", "m4a", "aac", "opus", "wav", "flac"];
const BITRATE_OPTIONS = ["", "320K", "256K", "192K", "128K"];
const NAMING_OPTIONS = ["id", "title", "uploader", "date_title"];
const SUBTITLE_LANGUAGE_OPTIONS = [
  ["zh", "中文"],
  ["en", "English"],
  ["ja", "日本語"],
  ["ko", "한국어"],
  ["es", "Español"],
  ["fr", "Français"],
  ["de", "Deutsch"],
  ["pt", "Português"],
  ["it", "Italiano"],
  ["ru", "Русский"],
] as const;

function subtitleLanguageFromContent(language: string | null | undefined): string {
  const normalized = String(language || "").trim().toLowerCase();
  const base = normalized.split(/[-_]/)[0] ?? "";
  return SUBTITLE_LANGUAGE_OPTIONS.some(([value]) => value === base) ? base : "zh";
}

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
    subtitle_primary_lang: "zh",
    subtitle_secondary_lang: "en",
    subtitle_show_timestamps: false,
    write_thumbnail: false,
    write_info_json: false,
  };
}
function videoDefaultForm(): DownloadForm {
  return { ...baseForm(), download_video: true };
}
function subtitleDefaultForm(language?: string | null): DownloadForm {
  const primary = subtitleLanguageFromContent(language);
  return {
    ...baseForm(),
    download_video: false,
    write_subtitles: true,
    subtitle_primary_lang: primary,
    subtitle_secondary_lang: primary === "zh" ? "en" : "zh",
  };
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
  initialSubtitlePrimaryLang?: string;
  initialSubtitleSecondaryLang?: string;
  initialSubtitleShowTimeline?: boolean;
  onCompleted?: () => void;
  onJobChange?: (job: SubtitleJobRead | null) => void;
}

/** Shared submit + poll + file-save lifecycle for the focused download modals. */
function useDownloadModal(content: ContentRecord, workspaceId: string) {
  const queryClient = useQueryClient();
  const [download, setDownload] = useState<DownloadRead | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(
    async (form: DownloadForm): Promise<boolean> => {
      setSubmitting(true);
      setError(null);
      try {
        const rec = await apiRequest<DownloadRead>("/downloads", {
          method: "POST",
          workspaceId,
          csrf: true,
          body: JSON.stringify({
            url: content.canonical_url,
            content_id: content.id,
            save_to_works: true,
            ...form,
          }),
        });
        setDownload(rec);
        return true;
      } catch (e) {
        setError(e instanceof Error ? e.message : "提交下载失败");
        return false;
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
    }, 1200);
    return () => clearInterval(timer);
  }, [download?.id, download?.status, workspaceId]);

  useEffect(() => {
    if (download && ["done", "empty", "failed"].includes(download.status)) {
      void queryClient.invalidateQueries({ queryKey: ["content", content.id] });
    }
  }, [content.id, download, queryClient]);

  const saveFile = useCallback(
    async (file: string) => {
      if (!download) return;
      try {
        await downloadApiFile(
          `/downloads/${download.id}/file/${encodeURIComponent(file)}`,
          workspaceId,
          file,
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : "文件下载失败");
      }
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

const DOWNLOAD_STAGE_LABELS: Record<string, string> = {
  starting: "启动任务",
  processing: "处理任务",
  resolving: "解析作品",
  downloading: "下载媒体",
  subtitles: "获取字幕",
  finalizing: "整理文件",
  completed: "已完成",
  empty: "未生成文件",
  failed: "失败",
};
const DOWNLOAD_FILE_LABELS: Record<string, string> = {
  video: "视频",
  audio: "音频",
  subtitles: "字幕",
  thumbnail: "封面",
  info_json: "元信息",
};

function DownloadProgressLog({ download }: { download: DownloadRead }) {
  const logRef = useRef<HTMLDivElement>(null);
  const progress = download.progress ?? {};
  const log = progress.log ?? [];
  useEffect(() => {
    const node = logRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [log.length, progress.message]);
  const stage = DOWNLOAD_STAGE_LABELS[progress.stage ?? ""] ?? progress.stage ?? "等待任务";
  const status =
    download.status === "running"
      ? "执行中"
      : download.status === "pending"
        ? "排队中"
        : download.status === "done"
          ? "成功"
          : download.status === "empty"
            ? "无产物"
            : download.status === "failed"
              ? "失败"
              : download.status;
  return (
    <div className="mt-4 rounded-lg border border-cyan-900/60 bg-slate-950/70 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="font-medium text-slate-200">下载任务详情</span>
        <span className="text-cyan-300">
          {stage} · {status}
          {progress.percent != null ? ` · ${progress.percent}%` : ""}
        </span>
      </div>
      {progress.percent != null && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800">
          <div
            className="h-full rounded-full bg-cyan-400 transition-[width] duration-300"
            style={{ width: `${Math.min(100, Math.max(0, progress.percent))}%` }}
          />
        </div>
      )}
      {Object.keys(progress.files ?? {}).length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
          {Object.entries(progress.files ?? {}).map(([key, value]) => (
            <span
              key={key}
              className={`rounded border px-1.5 py-0.5 ${
                value === "ready"
                  ? "border-emerald-800 text-emerald-300"
                  : value === "failed"
                    ? "border-rose-800 text-rose-300"
                    : value === "missing"
                      ? "border-amber-800 text-amber-300"
                      : "border-slate-700 text-slate-400"
              }`}
            >
              {DOWNLOAD_FILE_LABELS[key] ?? key} · {value === "ready" ? "已生成" : value === "pending" ? "获取中" : value === "failed" ? "失败" : "未生成"}
            </span>
          ))}
        </div>
      )}
      <div
        ref={logRef}
        role="log"
        aria-live="polite"
        aria-label="下载滚动日志"
        className="mt-2 max-h-40 min-h-16 overflow-y-auto rounded border border-slate-800 bg-black/30 p-2 font-mono text-[10px] leading-relaxed"
      >
        {log.length === 0 ? (
          <p className="text-slate-500">等待后台任务输出第一条进度…</p>
        ) : (
          log.map((line, index) => (
            <p
              key={`${line.at}-${index}`}
              className={line.level === "error" ? "text-rose-300" : line.level === "warn" ? "text-amber-300" : "text-slate-400"}
            >
              <span className="mr-2 text-slate-600">
                {new Date(line.at).toLocaleTimeString("zh-CN", { hour12: false })}
              </span>
              {line.message}
            </p>
          ))
        )}
      </div>
    </div>
  );
}

function SubtitleDownloadDetails({
  download,
  submitting,
  busy,
  error,
}: {
  download: DownloadRead | null;
  submitting: boolean;
  busy: boolean;
  error: string | null;
}) {
  const active = submitting || busy;
  return (
    <div className="group relative shrink-0">
      <button
        type="button"
        aria-label="查看字幕下载详情"
        title={active ? "悬停查看字幕下载进度" : "查看最近一次字幕下载详情"}
        className={`flex h-5 w-5 items-center justify-center rounded-full border text-[11px] font-bold leading-none transition ${
          active
            ? "border-cyan-400/80 text-cyan-300"
            : error || download?.status === "failed"
              ? "border-rose-400/80 text-rose-300"
              : "border-amber-400/80 text-amber-300"
        }`}
      >
        !
      </button>
      <div className="pointer-events-none invisible absolute right-0 top-full z-50 mt-2 w-[min(28rem,calc(100vw-2rem))] translate-y-1 opacity-0 transition duration-150 group-hover:pointer-events-auto group-hover:visible group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:visible group-focus-within:translate-y-0 group-focus-within:opacity-100">
        <div className="rounded-lg border border-slate-700 bg-slate-950/95 p-3 text-left shadow-2xl backdrop-blur">
          <div className="mb-2 flex items-center justify-between gap-3 text-xs">
            <span className="font-medium text-slate-200">字幕下载详情</span>
            <span className={active ? "text-cyan-300" : "text-slate-500"}>
              {active ? "执行中" : download ? "已结束" : "未启动"}
            </span>
          </div>
          {download ? (
            <DownloadProgressLog download={download} />
          ) : (
            <p className="rounded border border-slate-800 bg-black/30 p-2 text-[10px] leading-5 text-slate-500">
              点击“下载”后，这里会显示解析、字幕获取和文件写入的实时滚动日志。
            </p>
          )}
          {error && <p className="mt-2 text-[10px] leading-5 text-rose-300">{error}</p>}
        </div>
      </div>
    </div>
  );
}

function SubtitleGenerationDetails({ job }: { job: SubtitleJobRead | null }) {
  const active = job != null && (job.status === "queued" || job.status === "running");
  const failed = job?.status === "failed";
  const progress = job?.progress ?? {};
  const logs = progress.log ?? [];
  const generatedTracks = job?.result?.generated_tracks ?? [];
  return (
    <div className="group relative shrink-0">
      <button
        type="button"
        aria-label="查看字幕生成详情"
        title={active ? "悬停查看字幕生成进度" : "查看最近一次字幕生成任务"}
        className={`flex h-5 w-5 items-center justify-center rounded-full border text-[11px] font-bold leading-none transition ${
          active
            ? "border-cyan-400/80 text-cyan-300"
            : failed
              ? "border-rose-400/80 text-rose-300"
              : "border-amber-400/80 text-amber-300"
        }`}
      >
        !
      </button>
      <div className="pointer-events-none invisible absolute right-0 top-full z-50 mt-2 w-[min(30rem,calc(100vw-2rem))] translate-y-1 opacity-0 transition duration-150 group-hover:pointer-events-auto group-hover:visible group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:visible group-focus-within:translate-y-0 group-focus-within:opacity-100">
        <div className="rounded-lg border border-slate-700 bg-slate-950/95 p-3 text-left shadow-2xl backdrop-blur">
          <div className="mb-2 flex items-center justify-between gap-3 text-xs">
            <span className="font-medium text-slate-200">字幕生成详情</span>
            <span className={active ? "text-cyan-300" : failed ? "text-rose-300" : "text-slate-400"}>
              {job ? SUBTITLE_JOB_STATUS_LABELS[job.status] : "未启动"}
            </span>
          </div>
          {job ? (
            <>
              <div className="flex items-center justify-between gap-2 text-[10px] text-slate-400">
                <span>{progress.stage || "等待任务"}</span>
                <span>{progress.percent ?? 0}% · {job.target_languages.length} 个目标语种</span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800">
                <div
                  className={`h-full rounded-full transition-[width] duration-300 ${failed ? "bg-rose-400" : "bg-cyan-400"}`}
                  style={{ width: `${Math.min(100, Math.max(0, progress.percent ?? 0))}%` }}
                />
              </div>
              <div role="log" aria-label="字幕生成滚动日志" className="mt-2 max-h-40 min-h-16 overflow-y-auto overscroll-contain rounded border border-slate-800 bg-black/30 p-2 font-mono text-[10px] leading-relaxed">
                {logs.length === 0 ? (
                  <p className="text-slate-500">等待后台任务输出第一条进度…</p>
                ) : (
                  logs.map((entry, index) => (
                    <p
                      key={`${entry.at}-${index}`}
                      className={entry.level === "error" ? "text-rose-300" : entry.level === "warn" ? "text-amber-300" : "text-slate-400"}
                    >
                      {entry.message}
                    </p>
                  ))
                )}
              </div>
              {job.error_detail && (
                <p className="mt-2 text-[10px] leading-5 text-rose-300">
                  {job.error_code}: {job.error_detail}
                </p>
              )}
              {generatedTracks.length > 0 && (
                <p className="mt-2 border-t border-slate-800 pt-2 text-[10px] text-emerald-300">
                  已生成 {generatedTracks.length} 条字幕轨道，可在字幕展示框中选择。
                </p>
              )}
            </>
          ) : (
            <p className="rounded border border-slate-800 bg-black/30 p-2 text-[10px] leading-5 text-slate-500">
              点击“生成字幕”并提交任务后，这里会显示 ASR、翻译和文件写入的实时进度。
            </p>
          )}
        </div>
      </div>
    </div>
  );
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
  submitLabel = "开始下载",
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
  saveFile: (file: string) => Promise<void>;
  submitDisabled: boolean;
  submitLabel?: string;
  onSubmit: () => void;
  children: React.ReactNode;
}) {
  if (!open) return null;
  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 pt-[10vh]"
      role="presentation"
    >
      <button
        aria-label="关闭"
        className="fixed inset-0 -z-10 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        className="relative flex max-h-[80vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-slate-700 bg-slate-950 shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-start justify-between border-b border-slate-800 px-5 py-4">
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

        <div className="flex-1 space-y-3 overflow-y-auto p-5">{children}</div>

        {error && (
          <p className="mx-5 mt-3 shrink-0 rounded-md border border-red-900/60 bg-red-950/40 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}

        <div className="flex shrink-0 items-center gap-2 border-t border-slate-800 px-5 py-4">
          <button
            className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
            onClick={onSubmit}
            disabled={submitDisabled}
          >
            {submitLabel}
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
          <div className="shrink-0 px-5 pb-3">
            <p className="mb-2 text-xs text-slate-400">下载完成，点击保存到本地：</p>
            <ul className="flex flex-wrap gap-2">
              {mediaFiles.map((m) => (
                <li key={m.file}>
                  <button
                    className="rounded-md border border-slate-700 px-2 py-1 text-xs text-sky-400 hover:text-sky-300"
                    onClick={() => void saveFile(m.file)}
                  >
                    {m.label}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {download && download.status === "failed" && (
          <p className="mx-5 mt-3 shrink-0 text-xs text-red-400">
            下载失败：{download.error || "未知错误"}
          </p>
        )}
        {download && download.status === "empty" && (
          <p className="mx-5 mt-3 shrink-0 rounded-md border border-amber-900/60 bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
            {download.error ||
              "已拉取，但未生成任何媒体文件（请检查清晰度 / 开关设置）。"}
          </p>
        )}
        {download && <div className="shrink-0 px-5 pb-5"><DownloadProgressLog download={download} /></div>}
      </div>
    </div>,
    document.body,
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

function SubtitleDownloadModal({
  open,
  onClose,
  content,
  workspaceId,
  onCompleted,
  onJobChange,
}: ModalProps) {
  const { download, error, saveFile, busy, mediaFiles } =
    useDownloadModal(content, workspaceId);
  const [generateMultilingual, setGenerateMultilingual] = useState(true);
  const existingSubtitleLanguages = useMemo(
    () => (content.media?.subtitles ?? []).map((track) => track.lang).filter(Boolean),
    [content.media?.subtitles],
  );
  const existingGeneratedLanguages = useMemo(
    () => existingSubtitleGenerationLanguages(existingSubtitleLanguages),
    [existingSubtitleLanguages],
  );
  const missingGeneratedLanguages = useMemo(
    () => missingSubtitleGenerationLanguages(existingSubtitleLanguages),
    [existingSubtitleLanguages],
  );
  const [generatedLanguages, setGeneratedLanguages] = useState<string[]>(() =>
    missingSubtitleGenerationLanguages(
      (content.media?.subtitles ?? []).map((track) => track.lang).filter(Boolean),
    ),
  );
  const [subtitleJob, setSubtitleJob] = useState<SubtitleJobRead | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const completionNotified = useRef<string | null>(null);

  const queueSubtitleGeneration = useCallback(async () => {
    const existing = new Set(existingGeneratedLanguages);
    const requestedLanguages = generatedLanguages.filter((language) => !existing.has(language));
    if (requestedLanguages.length === 0) {
      setGenerationError("请至少选择一种要生成的语种。");
      return false;
    }
    try {
      const created = await apiRequest<SubtitleJobRead>(
        `/media/${content.id}/subtitle-generate`,
        {
          method: "POST",
          workspaceId,
          csrf: true,
          body: JSON.stringify({
            source_language: content.language || null,
            target_languages: requestedLanguages,
          }),
        },
      );
      setSubtitleJob(created);
      onJobChange?.(created);
      return true;
    } catch (reason) {
      setGenerationError(
        reason instanceof Error ? reason.message : "多语言字幕任务启动失败",
      );
      return false;
    }
  }, [content.id, content.language, existingGeneratedLanguages, generatedLanguages, onJobChange, workspaceId]);

  useEffect(() => {
    if (!subtitleJob || !["queued", "running"].includes(subtitleJob.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await apiRequest<SubtitleJobRead | null>(
          `/media/${content.id}/subtitle-jobs/${subtitleJob.id}`,
          { workspaceId },
        );
        if (next) {
          setSubtitleJob(next);
          onJobChange?.(next);
        }
      } catch (reason) {
        setGenerationError(
          reason instanceof Error ? reason.message : "字幕任务状态读取失败",
        );
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [content.id, onJobChange, subtitleJob?.id, subtitleJob?.status, workspaceId]);

  useEffect(() => {
    if (
      subtitleJob &&
      (subtitleJob.status === "succeeded" || subtitleJob.status === "degraded") &&
      completionNotified.current !== subtitleJob.id
    ) {
      completionNotified.current = subtitleJob.id;
      onCompleted?.();
    }
  }, [onCompleted, subtitleJob?.status]);

  const submitSubtitleForm = async () => {
    setGenerationError(null);
    if (!generateMultilingual) {
      setGenerationError("请启用生成多语言字幕。");
      return;
    }
    await queueSubtitleGeneration();
  };

  const generatedTracks = subtitleJob?.result?.generated_tracks ?? [];
  const subtitleBusy =
    subtitleJob != null && ["queued", "running"].includes(subtitleJob.status);
  const allLanguagesGenerated = missingGeneratedLanguages.length === 0;

  return (
    <DownloadModalFrame
      open={open}
      onClose={onClose}
      title="生成字幕"
      subtitle={`仅对当前作品（${content.title.slice(0, 28) || "该作品"}）生成本地多语言字幕。`}
      error={error || generationError}
      download={download}
      mediaFiles={mediaFiles}
      saveFile={saveFile}
      submitDisabled={busy || subtitleBusy || allLanguagesGenerated}
      submitLabel={allLanguagesGenerated ? "已生成字幕" : "开始生成"}
      onSubmit={() => void submitSubtitleForm()}
    >
      <SubtitleGenerationOptions
        enabled={generateMultilingual}
        languages={generatedLanguages}
        existingLanguages={existingSubtitleLanguages}
        disabled={subtitleBusy || allLanguagesGenerated}
        onEnabledChange={setGenerateMultilingual}
        onLanguagesChange={setGeneratedLanguages}
      />
      {subtitleJob && (
        <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3 text-xs">
          <div className="flex items-center justify-between gap-2 text-slate-300">
            <span>多语言字幕任务</span>
            <span className="text-cyan-300">
              {subtitleJob.status} · {subtitleJob.progress?.percent ?? 0}%
            </span>
          </div>
          <div className="mt-2 max-h-32 space-y-1 overflow-y-auto overscroll-contain font-mono text-[10px] leading-4">
            {(subtitleJob.progress?.log ?? []).map((entry, index) => (
              <p
                key={`${entry.at}-${index}`}
                className={
                  entry.level === "error"
                    ? "text-rose-300"
                    : entry.level === "warn"
                      ? "text-amber-300"
                      : "text-slate-400"
                }
              >
                {entry.message}
              </p>
            ))}
            {subtitleJob.error_detail && (
              <p className="text-rose-300">
                {subtitleJob.error_code}: {subtitleJob.error_detail}
              </p>
            )}
          </div>
          {generatedTracks.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-800 pt-2">
              {generatedTracks.map((track) => (
                <a
                  key={track.file}
                  className="text-sky-400 hover:text-sky-300"
                  href={`/api/v1/media/${content.id}/${encodeURIComponent(track.file)}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  下载 {track.lang}
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </DownloadModalFrame>
  );
}

function SubtitleFileCard({
  content,
  workspaceId,
  subtitles,
  primaryLang,
  secondaryLang,
  showTimeline,
  currentTime,
  onPrimaryChange,
  onSecondaryChange,
  onTimelineChange,
  onCompleted,
}: {
  content: ContentRecord;
  workspaceId: string;
  subtitles: { lang: string; file: string }[];
  primaryLang: string;
  secondaryLang: string;
  showTimeline: boolean;
  currentTime: number | null;
  onPrimaryChange: (value: string) => void;
  onSecondaryChange: (value: string) => void;
  onTimelineChange: (value: boolean) => void;
  onCompleted: () => void;
}) {
  const { download, submit, submitting, busy, error } = useDownloadModal(content, workspaceId);
  const [generatorOpen, setGeneratorOpen] = useState(false);
  const [subtitleJob, setSubtitleJob] = useState<SubtitleJobRead | null>(null);
  const [exportFormat, setExportFormat] = useState<"srt" | "vtt" | "txt" | "json" | "ass">("srt");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const languages = Array.from(
    new Set(subtitles.map((subtitle) => subtitle.lang).filter(Boolean)),
  );
  const missingLanguages = missingSubtitleGenerationLanguages(languages);
  const allLanguagesGenerated = missingLanguages.length === 0;
  const subtitleJobBusy =
    subtitleJob != null && ["queued", "running"].includes(subtitleJob.status);
  useEffect(() => {
    let cancelled = false;
    void apiRequest<SubtitleJobRead | null>(
      `/media/${content.id}/subtitle-job`,
      { workspaceId },
    )
      .then((job) => {
        if (!cancelled && job) setSubtitleJob(job);
      })
      .catch(() => {
        // Historical job status is supplementary; it must not hide subtitles.
      });
    return () => {
      cancelled = true;
    };
  }, [content.id, workspaceId]);
  const downloadOriginal = async () => {
    const selected = [primaryLang, secondaryLang].filter(Boolean);
    const accepted = await submit({
      ...subtitleDefaultForm(content.language),
      subtitle_primary_lang: primaryLang,
      subtitle_secondary_lang: secondaryLang,
      subtitle_show_timestamps: showTimeline,
      subtitle_langs: selected.join(",") || subtitleDefaultForm(content.language).subtitle_langs,
      write_auto_subtitles: false,
    });
    if (accepted) onCompleted();
  };
  const exportSubtitle = async () => {
    if (!primaryLang) {
      setExportError("请先选择第一语言字幕轨道");
      return;
    }
    setExporting(true);
    setExportError(null);
    try {
      const safePart = (value: string) => value.replace(/[^a-zA-Z0-9._-]+/g, "-");
      const base = `${safePart(primaryLang)}${secondaryLang ? `-and-${safePart(secondaryLang)}-bilingual` : ""}.${exportFormat}`;
      await downloadApiPostFile(
        `/media/${content.id}/subtitle-export`,
        {
          primary_lang: primaryLang,
          secondary_lang: secondaryLang,
          format: exportFormat,
          show_timestamps: showTimeline,
        },
        workspaceId,
        base,
      );
      onCompleted();
    } catch (reason) {
      setExportError(reason instanceof Error ? reason.message : "字幕导出失败");
    } finally {
      setExporting(false);
    }
  };
  return (
    <>
      <MediaCard
        title="字幕文件"
        icon={<Captions size={15} />}
        present
        notDownloadedHint="暂无已归档字幕轨道"
        alwaysShowHeader
        headerAction={
          <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
            <SubtitleHeaderControls
              subtitles={subtitles}
              primaryLang={primaryLang}
              secondaryLang={secondaryLang}
              showTimeline={showTimeline}
              onPrimaryChange={onPrimaryChange}
              onSecondaryChange={onSecondaryChange}
              onTimelineChange={onTimelineChange}
            />
            <select
              aria-label="字幕导出格式"
              className="h-7 max-w-[7rem] rounded-md border border-slate-700 bg-slate-900 px-1.5 text-[11px] text-slate-200"
              value={exportFormat}
              disabled={exporting || languages.length === 0}
              onChange={(event) =>
                setExportFormat(event.target.value as typeof exportFormat)
              }
            >
              <option value="srt">SRT（通用）</option>
              <option value="vtt">WebVTT（网页）</option>
              <option value="txt">TXT（纯文本）</option>
              <option value="json">JSON（结构化）</option>
              <option value="ass">ASS（样式字幕）</option>
            </select>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md border border-violet-500/70 px-2 py-1 text-xs text-violet-100 hover:bg-violet-500/15 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => void exportSubtitle()}
              disabled={exporting || languages.length === 0 || !primaryLang}
            >
              {exporting ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
              {exporting ? "导出中…" : "导出"}
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => void downloadOriginal()}
              disabled={submitting || busy || languages.length === 0}
            >
              {submitting || busy ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
              {submitting || busy ? "下载中…" : languages.length > 0 ? "已下载" : "下载原字幕"}
            </button>
            <SubtitleDownloadDetails
              download={download}
              submitting={submitting}
              busy={busy}
              error={error}
            />
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md bg-violet-500 px-2 py-1 text-xs font-medium text-white hover:bg-violet-400 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => setGeneratorOpen(true)}
              disabled={allLanguagesGenerated || subtitleJobBusy}
            >
              {subtitleJobBusy ? <Loader2 size={13} className="animate-spin" /> : <Captions size={13} />}
              {subtitleJobBusy ? "生成中…" : allLanguagesGenerated ? "已生成字幕" : "生成字幕"}
            </button>
            <SubtitleGenerationDetails job={subtitleJob} />
          </div>
        }
      >
        <SubtitleDisplayBox
          contentId={content.id}
          workspaceId={workspaceId}
          subtitles={subtitles}
          primaryLang={primaryLang}
          secondaryLang={secondaryLang}
          showTimeline={showTimeline}
          currentTime={currentTime}
        />
        {error && (
          <p role="alert" className="text-xs text-rose-300">
            {error}
          </p>
        )}
        {exportError && (
          <p role="alert" className="text-xs text-rose-300">
            {exportError}
          </p>
        )}
        {!error && languages.length === 0 && (
          <p className="text-xs text-slate-500">暂无已归档字幕轨道</p>
        )}
      </MediaCard>
      <SubtitleDownloadModal
        open={generatorOpen}
        onClose={() => setGeneratorOpen(false)}
        content={content}
        workspaceId={workspaceId}
        onJobChange={setSubtitleJob}
        onCompleted={() => {
          setGeneratorOpen(false);
          onCompleted();
        }}
      />
    </>
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
  const comments = useQuery({
    queryKey: ["content-comments", id],
    queryFn: () =>
      apiRequest<HotCommentRecord[]>(`/contents/${id}/comments?limit=20`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const [collectingComments, setCollectingComments] = useState(false);
  const [commentActionError, setCommentActionError] = useState<string | null>(null);
  const commentSync =
    (item.data?.metadata?.comment_sync as
      | {
          status?: string;
          count?: number;
          fetched_at?: string;
          notice?: string | null;
          source_provider?: string;
        }
      | undefined) ?? undefined;
  useEffect(() => {
    if (!collectingComments) return;
    const timer = setInterval(async () => {
      const next = await item.refetch();
      await comments.refetch();
      const status = (next.data?.metadata?.comment_sync as
        | { status?: string }
        | undefined)?.status;
      if (
        status &&
        ["success", "empty", "failed", "queue_failed", "unsupported", "unavailable"].includes(
          status,
        )
      ) {
        setCollectingComments(false);
      }
    }, 1500);
    return () => clearInterval(timer);
  }, [collectingComments, comments.refetch, item.refetch]);
  const [dlVideo, setDlVideo] = useState(false);
  const [dlMetadata, setDlMetadata] = useState(false);
  const subtitleTracks = item.data?.media?.subtitles?.filter((track) => track?.file) ?? [];
  // null means "choose the first available track" on first render; an empty
  // string is an explicit user choice to turn that language off.
  const [subtitlePrimaryLang, setSubtitlePrimaryLang] = useState<string | null>(null);
  const [subtitleSecondaryLang, setSubtitleSecondaryLang] = useState<string | null>(null);
  const [subtitleShowTimeline, setSubtitleShowTimeline] = useState<boolean | null>(null);
  const [subtitleCurrentTime, setSubtitleCurrentTime] = useState<number | null>(null);
  const [showVideoSubtitles, setShowVideoSubtitles] = useState(true);
  const [subtitleFontSize, setSubtitleFontSize] = useState<"small" | "medium" | "large">("medium");
  const [subtitleBackground, setSubtitleBackground] = useState<"box" | "shadow" | "none">("box");
  const [subtitlePosition, setSubtitlePosition] = useState<"bottom" | "middle">("bottom");
  const subtitleLanguages = Array.from(
    new Set(subtitleTracks.map((track) => track.lang).filter(Boolean)),
  );
  const defaultSubtitlePair = defaultSubtitleLanguagePair(subtitleLanguages);
  const effectiveSubtitlePrimaryLang =
    subtitlePrimaryLang === null
      ? defaultSubtitlePair.primary
      : subtitlePrimaryLang && subtitleLanguages.includes(subtitlePrimaryLang)
      ? subtitlePrimaryLang
      : "";
  const effectiveSubtitleSecondaryLang =
      !effectiveSubtitlePrimaryLang
      ? ""
      : subtitleSecondaryLang === null
        ? defaultSubtitlePair.secondary !== effectiveSubtitlePrimaryLang
          ? defaultSubtitlePair.secondary
          : subtitleLanguages.find((language) => language !== effectiveSubtitlePrimaryLang) ?? ""
        : subtitleSecondaryLang &&
            subtitleLanguages.includes(subtitleSecondaryLang) &&
            subtitleSecondaryLang !== effectiveSubtitlePrimaryLang
          ? subtitleSecondaryLang
          : "";
  const persistedSubtitleShowTimeline = Boolean(item.data?.media?.subtitle_show_timestamps);
  const effectiveSubtitleShowTimeline =
    subtitleShowTimeline ?? persistedSubtitleShowTimeline;
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
  const collectHotComments = async () => {
    setCollectingComments(true);
    setCommentActionError(null);
    try {
      await apiRequest(`/contents/${id}/comments/collect`, {
        method: "POST",
        workspaceId: workspaceId!,
        csrf: true,
      });
      await item.refetch();
      await comments.refetch();
    } catch (error) {
      setCollectingComments(false);
      setCommentActionError(
        error instanceof Error ? error.message : "热门评论采集启动失败",
      );
    }
  };
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
  const artifactFor = (kind: string, file?: string) =>
    data.artifacts?.find(
      (artifact) =>
        artifact.artifact_kind === kind &&
        (!file || artifact.file_name === file),
    );
  const readyArtifact = (kind: string, file?: string) =>
    artifactFor(kind, file)?.status === "ready";
  const hasArtifactLedger = (data.artifacts?.length ?? 0) > 0;
  const subs =
    media?.subtitles?.filter(
      (s) => s?.file && (!hasArtifactLedger || readyArtifact("subtitle", s.file)),
    ) ?? [];
  const handleSubtitlePrimaryChange = (value: string) => {
    setSubtitlePrimaryLang(value);
    if (value && value === effectiveSubtitleSecondaryLang) setSubtitleSecondaryLang("");
  };
  const handleSubtitleSecondaryChange = (value: string) => {
    setSubtitleSecondaryLang(value);
    if (value && value === effectiveSubtitlePrimaryLang) setSubtitlePrimaryLang("");
  };
  const assetLinkClass =
    "inline-flex items-center gap-1 text-sm text-sky-400 hover:text-sky-300";
  const dlBtn = (kind: "video" | "subtitle" | "metadata") => {
    const downloaded =
      kind === "video"
        ? Boolean(media?.video && readyArtifact("video", media.video))
        : kind === "metadata"
          ? Boolean(media?.info_json && readyArtifact("info_json", media.info_json))
          : subs.length > 0;
    return (
      <button
        type="button"
        disabled={downloaded}
        onClick={() => {
          if (downloaded) return;
          if (kind === "video") setDlVideo(true);
          else if (kind === "metadata") setDlMetadata(true);
        }}
        className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:border-emerald-900/70 disabled:bg-emerald-950/20 disabled:text-emerald-300"
      >
        {downloaded ? "已下载" : "下载"}
      </button>
    );
  };
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
            present={Boolean(media?.video && readyArtifact("video", media.video))}
            notDownloadedHint="未下载 · 点击「下载」用 yt-dlp 从源站重新拉取"
            action={dlBtn("video")}
          >
            <SubtitleVideoPlayer
              contentId={id}
              videoFile={media?.video}
              subtitles={subs}
              primaryLang={effectiveSubtitlePrimaryLang}
              secondaryLang={effectiveSubtitleSecondaryLang}
              showTimeline={effectiveSubtitleShowTimeline}
              showSubtitles={showVideoSubtitles}
              fontSize={subtitleFontSize}
              background={subtitleBackground}
              position={subtitlePosition}
              onTimeChange={setSubtitleCurrentTime}
              onPrimaryLangChange={handleSubtitlePrimaryChange}
              onSecondaryLangChange={handleSubtitleSecondaryChange}
              onShowTimelineChange={(value) => setSubtitleShowTimeline(value)}
              onShowSubtitlesChange={setShowVideoSubtitles}
              onFontSizeChange={setSubtitleFontSize}
              onBackgroundChange={setSubtitleBackground}
              onPositionChange={setSubtitlePosition}
            />
          </MediaCard>
          <SubtitleFileCard
            content={data}
            workspaceId={workspaceId!}
            subtitles={subs}
            primaryLang={effectiveSubtitlePrimaryLang}
            secondaryLang={effectiveSubtitleSecondaryLang}
            showTimeline={effectiveSubtitleShowTimeline}
            currentTime={subtitleCurrentTime}
            onPrimaryChange={handleSubtitlePrimaryChange}
            onSecondaryChange={handleSubtitleSecondaryChange}
            onTimelineChange={setSubtitleShowTimeline}
            onCompleted={() => void item.refetch()}
          />
          <MediaCard
            title="原始信息 (info.json)"
            icon={<FileJson size={15} />}
            present={Boolean(media?.info_json && readyArtifact("info_json", media.info_json))}
            notDownloadedHint="未下载 · 点击「下载」用 yt-dlp 从源站重新拉取"
            action={dlBtn("metadata")}
          >
            {media?.info_json && readyArtifact("info_json", media.info_json) && (
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
      <MetadataDownloadModal
        key={dlMetadata ? "open" : "closed"}
        open={dlMetadata}
        onClose={() => setDlMetadata(false)}
        content={data}
        workspaceId={workspaceId!}
      />
      <Panel className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <MessageCircle size={17} className="text-amber-400" />
            <div>
              <h2 className="font-medium text-white">热门评论 Top 20</h2>
              <p className="mt-1 text-xs text-slate-500">
                按点赞数 + 3 × 回复数排序；只显示真实返回的公开或已授权评论
              </p>
            </div>
          </div>
          <button
            type="button"
            className={secondaryButtonClass}
            onClick={() => void collectHotComments()}
            disabled={collectingComments}
          >
            <RefreshCw size={14} className={collectingComments ? "animate-spin" : ""} />
            {collectingComments ? "采集中…" : commentSync?.status ? "刷新热门评论" : "采集热门评论"}
          </button>
        </div>
        {commentActionError && (
          <p className="mt-3 rounded-md border border-rose-900/60 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
            {commentActionError}
          </p>
        )}
        {comments.isError && (
          <p className="mt-3 text-xs text-rose-300">热门评论加载失败，请重试。</p>
        )}
        {!comments.isLoading && comments.data && comments.data.length > 0 && (
          <div className="mt-4 divide-y divide-slate-800/70 rounded-xl border border-slate-800">
            {comments.data.map((comment, index) => (
              <article key={comment.id} className="grid grid-cols-[2rem_1fr] gap-3 p-3">
                <div className="grid size-7 place-items-center rounded-full bg-amber-500/15 text-xs font-semibold text-amber-300">
                  {index + 1}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                    <span className="font-medium text-slate-200">{comment.author_name}</span>
                    <span className="text-rose-300">♥ {formatNumber(comment.like_count)}</span>
                    <span className="text-cyan-300">↩ {formatNumber(comment.reply_count)}</span>
                    <span className="text-slate-500">
                      {comment.published_at ? formatDate(comment.published_at) : "时间未提供"}
                    </span>
                  </div>
                  <p className="mt-1 text-sm leading-6 text-slate-300">{comment.text}</p>
                  <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-slate-600">
                    <span>{comment.source_provider}</span>
                    <span>{comment.is_reply ? "回复" : "顶层评论"}</span>
                    <span>采集于 {formatDate(comment.fetched_at)}</span>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
        {!comments.isLoading && !comments.data?.length && (
          <div className="mt-4 rounded-xl border border-dashed border-slate-700 px-4 py-6 text-center text-xs text-slate-500">
            {commentSync?.notice ||
              (commentSync?.status === "failed"
                ? "本次评论采集失败，请检查平台登录凭证或稍后重试。"
                : "尚未采集热门评论；点击右上角即可按当前作品抓取 Top 20。")}
          </div>
        )}
        {commentSync?.fetched_at && (
          <p className="mt-3 text-[11px] text-slate-600">
            最近采集：{formatDate(commentSync.fetched_at)} · 来源：{commentSync.source_provider || "yt_dlp"}
          </p>
        )}
      </Panel>
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
