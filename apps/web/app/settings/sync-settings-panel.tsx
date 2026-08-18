"use client";

import type {
  SyncSettingsRecord,
  YtDlpRuntimeRecord,
  YtDlpSettings,
} from "@sio/shared-types";
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, RefreshCw, Save, Wrench } from "lucide-react";
import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import {
  Badge,
  Panel,
  SettingsGroup,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";

function ymdToDateInput(ymd?: string): string {
  if (!ymd || !/^\d{8}$/.test(ymd)) return "";
  return `${ymd.slice(0, 4)}-${ymd.slice(4, 6)}-${ymd.slice(6, 8)}`;
}

function dateInputToYmd(value?: string): string {
  if (!value) return "";
  const clean = value.replace(/-/g, "");
  return /^\d{8}$/.test(clean) ? clean : "";
}

type YtFieldValue = string | boolean | null;
type FieldType = "text" | "int" | "bool" | "select";

interface FieldDef {
  key: keyof YtDlpSettings;
  label: string;
  type: FieldType;
  placeholder?: string;
  help?: string;
  options?: { value: string; label: string }[];
}

interface FieldGroup {
  title: string;
  description?: string;
  fields: FieldDef[];
}

// Comprehensive, categorised set of yt-dlp parameters surfaced as form
// controls. Operators can enable only what they need; the adapter translates
// the non-empty ones into CLI flags. Anything not modelled here can still be
// passed via the free-form "extra_args" JSON below.
const YTDLP_FIELD_GROUPS: FieldGroup[] = [
  {
    title: "时间与日期范围",
    description: "限定抓取作品的时间窗口；留空表示不限制。",
    fields: [
      {
        key: "daterange",
        label: "日期区间 (daterange)",
        type: "text",
        placeholder: "YYYYMMDD-YYYYMMDD",
        help: "只抓取区间内的作品，如 20240101-20241231",
      },
    ],
  },
  {
    title: "播放列表与数量",
    description: "控制账号作品列表的截取与展开方式。",
    fields: [
      {
        key: "playlist_items",
        label: "指定条目 (playlist_items)",
        type: "text",
        placeholder: "1,3,5-7",
        help: "只抓取指定编号的条目",
      },
      {
        key: "playlist_reverse",
        label: "倒序抓取 (playlist_reverse)",
        type: "bool",
      },
      {
        key: "playlist_random",
        label: "随机顺序 (playlist_random)",
        type: "bool",
      },
      {
        key: "no_playlist",
        label: "仅单视频非列表 (no_playlist)",
        type: "bool",
        help: "遇到列表 URL 时只抓单个视频",
      },
      {
        key: "flat_playlist",
        label: "扁平播放列表 (flat_playlist)",
        type: "bool",
        help: "不递归展开嵌套播放列表",
      },
    ],
  },
  {
    title: "筛选与排序",
    description: "按条件过滤作品或对列表排序。",
    fields: [
      {
        key: "sort",
        label: "排序方式 (sort)",
        type: "text",
        placeholder: "view_count",
        help: "如 view_count、upload_date、-playlist_index",
      },
      {
        key: "match_filter",
        label: "匹配过滤器 (match_filter)",
        type: "text",
        placeholder: "like_count > 1000",
        help: "yt-dlp 匹配表达式语法",
      },
      {
        key: "match_title",
        label: "标题匹配 (match_title)",
        type: "text",
        placeholder: "正则",
        help: "标题包含该正则才抓取",
      },
      {
        key: "reject_title",
        label: "标题排除 (reject_title)",
        type: "text",
        placeholder: "正则",
        help: "标题包含该正则则跳过",
      },
      {
        key: "age_limit",
        label: "年龄限制 (age_limit, 岁)",
        type: "int",
        help: "仅抓取不低于该年龄分级的内容",
      },
      { key: "min_duration", label: "最短时长秒 (min_duration)", type: "int" },
      { key: "max_duration", label: "最长时长秒 (max_duration)", type: "int" },
      {
        key: "min_filesize",
        label: "最小文件大小 (min_filesize)",
        type: "text",
        placeholder: "10M",
      },
      {
        key: "max_filesize",
        label: "最大文件大小 (max_filesize)",
        type: "text",
        placeholder: "1G",
      },
    ],
  },
  {
    title: "网络与限流",
    description: "控制请求代理、超时、重试与限速，降低被限流风险。",
    fields: [
      {
        key: "proxy",
        label: "代理 (proxy)",
        type: "text",
        placeholder: "http://host:port",
      },
      {
        key: "socket_timeout",
        label: "套接字超时秒 (socket_timeout)",
        type: "int",
      },
      { key: "retries", label: "重试次数 (retries)", type: "int" },
      {
        key: "fragment_retries",
        label: "分片重试 (fragment_retries)",
        type: "int",
      },
      {
        key: "sleep_interval",
        label: "请求间隔秒 (sleep_interval)",
        type: "int",
      },
      {
        key: "max_sleep_interval",
        label: "最大间隔秒 (max_sleep_interval)",
        type: "int",
      },
      {
        key: "sleep_requests",
        label: "每 N 请求休眠 (sleep_requests)",
        type: "int",
      },
      {
        key: "limit_rate",
        label: "下载限速 (limit_rate)",
        type: "text",
        placeholder: "1M",
      },
      { key: "geo_bypass", label: "绕过地理限制 (geo_bypass)", type: "bool" },
      {
        key: "geo_bypass_country",
        label: "绕过国家 (geo_bypass_country)",
        type: "text",
        placeholder: "US",
      },
      {
        key: "geo_verification_proxy",
        label: "地理验证代理 (geo_verification_proxy)",
        type: "text",
        placeholder: "http://host:port",
      },
    ],
  },
  {
    title: "登录与鉴权",
    description:
      "YouTube 等平台触发 429 或要求确认身份时，可从运行环境可见的浏览器配置读取已登录会话。",
    fields: [
      {
        key: "cookies_from_browser",
        label: "浏览器 Cookie 来源 (cookies_from_browser)",
        type: "select",
        options: [
          { value: "", label: "不读取浏览器 Cookie（匿名）" },
          { value: "chrome", label: "Google Chrome" },
          { value: "edge", label: "Microsoft Edge" },
          { value: "firefox", label: "Mozilla Firefox" },
          { value: "brave", label: "Brave" },
          { value: "chromium", label: "Chromium" },
          { value: "opera", label: "Opera" },
          { value: "vivaldi", label: "Vivaldi" },
          { value: "safari", label: "Safari（macOS）" },
          { value: "whale", label: "Whale" },
        ],
        help: "只保存浏览器类型，不保存 Cookie；Docker 需要挂载对应浏览器配置目录。",
      },
    ],
  },
  {
    title: "提取与输出",
    description: "抓取过程的容错与日志行为。",
    fields: [
      {
        key: "ignore_errors",
        label: "忽略错误继续 (ignore_errors)",
        type: "bool",
        help: "默认开启，单个作品失败不影响其余",
      },
      { key: "no_warnings", label: "禁用警告 (no_warnings)", type: "bool" },
    ],
  },
];

const DEFAULT_YT: Record<string, YtFieldValue> = {
  daterange: "",
  playlist_items: "",
  playlist_reverse: false,
  playlist_random: false,
  no_playlist: false,
  flat_playlist: false,
  sort: "",
  match_filter: "",
  match_title: "",
  reject_title: "",
  age_limit: null,
  min_duration: null,
  max_duration: null,
  min_filesize: "",
  max_filesize: "",
  proxy: "",
  socket_timeout: null,
  retries: null,
  fragment_retries: null,
  sleep_interval: null,
  max_sleep_interval: null,
  sleep_requests: null,
  limit_rate: "",
  geo_bypass: false,
  geo_bypass_country: "",
  geo_verification_proxy: "",
  cookies_from_browser: "",
  ignore_errors: true,
  no_warnings: true,
};

// yt-dlp *download* toggles — what media to archive locally during a sync.
// Defaults: cover thumbnail + subtitles on, auto subs / video / info-json off.
type DownloadFieldDef = {
  key: string;
  label: string;
  type: FieldType;
  help?: string;
  placeholder?: string;
  options?: { value: string; label: string }[];
};

const DOWNLOAD_FIELDS: DownloadFieldDef[] = [
  {
    key: "write_thumbnail",
    label: "下载封面缩略图 (write_thumbnail)",
    type: "bool",
  },
  { key: "write_subtitles", label: "下载字幕 (write_subtitles)", type: "bool" },
  {
    key: "write_auto_subtitles",
    label: "自动生成字幕 (write_auto_subtitles)",
    type: "bool",
    help: "平台自动语音识别字幕，质量低于人工字幕",
  },
  {
    key: "subtitle_langs",
    label: "字幕语言 (subtitle_langs)",
    type: "text",
    placeholder: "zh.*,en.*",
    help: "逗号分隔的语言代码，如 zh.*,en.*,ja",
  },
  {
    key: "download_video",
    label: "下载视频文件 (download_video)",
    type: "bool",
    help: "⚠️ 体积大，会显著消耗磁盘与带宽；按需开启",
  },
  {
    key: "video_quality",
    label: "视频清晰度 (video_quality)",
    type: "select",
    options: [
      { value: "best", label: "最佳（原始）" },
      { value: "2160p", label: "4K (2160p)" },
      { value: "1440p", label: "2K (1440p)" },
      { value: "1080p", label: "1080p" },
      { value: "720p", label: "720p" },
      { value: "480p", label: "480p" },
      { value: "audio", label: "仅音频 (audio)" },
    ],
    help: "下载分辨率；选「仅音频」会提取音轨、忽略视频画面",
  },
  {
    key: "video_format",
    label: "视频格式 (video_format)",
    type: "select",
    options: [
      { value: "best", label: "最佳（自动）" },
      { value: "mp4", label: "MP4" },
      { value: "webm", label: "WebM" },
      { value: "mkv", label: "MKV" },
    ],
    help: "视频容器格式；「最佳（自动）」交给 yt-dlp 自动选择",
  },
  {
    key: "audio_format",
    label: "音频格式 (audio_format)",
    type: "select",
    options: [
      { value: "best", label: "最佳（自动）" },
      { value: "mp3", label: "MP3" },
      { value: "m4a", label: "M4A" },
      { value: "aac", label: "AAC" },
      { value: "opus", label: "Opus" },
      { value: "wav", label: "WAV" },
      { value: "flac", label: "FLAC" },
    ],
    help: "仅当清晰度为「仅音频」时生效",
  },
  {
    key: "bitrate",
    label: "音频码率 (bitrate)",
    type: "select",
    options: [
      { value: "", label: "默认（不限制）" },
      { value: "320K", label: "320K" },
      { value: "256K", label: "256K" },
      { value: "192K", label: "192K" },
      { value: "128K", label: "128K" },
    ],
    help: "仅音频提取时生效；空表示不限制码率",
  },
  {
    key: "naming_rule",
    label: "文件命名规则 (naming_rule)",
    type: "select",
    options: [
      { value: "id", label: "视频 ID" },
      { value: "title", label: "标题" },
      { value: "uploader", label: "上传者 + ID" },
      { value: "date_title", label: "日期 + 标题" },
    ],
    help: "归档到本地的文件名规则",
  },
  {
    key: "write_info_json",
    label: "下载原始信息 (write_info_json)",
    type: "bool",
  },
  {
    key: "fetch_comments",
    label: "抓取热门评论（每条作品 Top 20）",
    type: "bool",
    help: "可选：按点赞与回复数排序保存，默认关闭；需要平台公开评论或已授权 Cookie",
  },
];

const DEFAULT_DOWNLOAD: Record<string, YtFieldValue> = {
  write_thumbnail: true,
  write_subtitles: true,
  write_auto_subtitles: true,
  subtitle_langs: "zh.*,en.*",
  download_video: false,
  video_quality: "best",
  video_format: "best",
  audio_format: "best",
  bitrate: "",
  naming_rule: "id",
  write_info_json: false,
  fetch_comments: true,
};

export function SyncSettingsPanel() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const canEdit = ["owner", "admin"].includes(role ?? "");

  const data = useQuery({
    queryKey: ["sync-settings", workspaceId],
    queryFn: () =>
      apiRequest<SyncSettingsRecord>("/settings/sync", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const runtime = useQuery({
    queryKey: ["ytdlp-runtime", workspaceId],
    queryFn: () =>
      apiRequest<YtDlpRuntimeRecord>("/downloads/runtime", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });

  const [maxContents, setMaxContents] = useState<string>("");
  const [skipExisting, setSkipExisting] = useState(true);
  const [syncTaskMaxRetries, setSyncTaskMaxRetries] = useState<string>("");
  const [dateAfter, setDateAfter] = useState("");
  const [dateBefore, setDateBefore] = useState("");
  const [playlistStart, setPlaylistStart] = useState("1");
  const [yt, setYt] = useState<Record<string, YtFieldValue>>(DEFAULT_YT);
  const [download, setDownload] =
    useState<Record<string, YtFieldValue>>(DEFAULT_DOWNLOAD);
  const [extraArgs, setExtraArgs] = useState("{}");
  const [pending, setPending] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const [runtimeUpdating, setRuntimeUpdating] = useState(false);
  const [runtimeCheckedAt, setRuntimeCheckedAt] = useState<string | null>(null);

  async function checkRuntime() {
    const result = await runtime.refetch();
    setRuntimeCheckedAt(new Date().toISOString());
    if (result.error) {
      notify(
        result.error instanceof Error
          ? `运行时检查失败：${result.error.message}`
          : "运行时检查失败",
        "error",
      );
      return;
    }
    const checked = result.data;
    notify(
      checked?.status === "ready"
        ? "视频解析运行时检查通过"
        : `运行时检查完成：${checked?.detail ?? "当前运行时需要关注"}`,
      checked?.status === "ready" ? "success" : "error",
    );
  }

  async function updateRuntime() {
    if (!workspaceId || !runtime.data?.update_enabled) return;
    setRuntimeUpdating(true);
    try {
      await apiRequest<YtDlpRuntimeRecord>("/downloads/runtime/update", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({}),
      });
      notify("yt-dlp 已更新；生产容器建议随后重建镜像", "success");
      await runtime.refetch();
    } catch (error) {
      notify(
        error instanceof Error ? error.message : "yt-dlp 更新失败",
        "error",
      );
    } finally {
      setRuntimeUpdating(false);
    }
  }

  useEffect(() => {
    if (hydrated || !data.data) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      const cfg = data.data!.config;
      setMaxContents(cfg.max_contents != null ? String(cfg.max_contents) : "");
      setSkipExisting(cfg.skip_existing);
      setSyncTaskMaxRetries(
        data.data!.sync_task_max_retries != null
          ? String(data.data!.sync_task_max_retries)
          : "",
      );
      setDateAfter(ymdToDateInput(cfg.yt_dlp.dateafter));
      setDateBefore(ymdToDateInput(cfg.yt_dlp.datebefore));
      setPlaylistStart(String(cfg.yt_dlp.playlist_start ?? 1));
      const source = cfg.yt_dlp as unknown as Record<string, unknown>;
      const nextYt: Record<string, YtFieldValue> = { ...DEFAULT_YT };
      for (const group of YTDLP_FIELD_GROUPS) {
        for (const f of group.fields) {
          const raw = source[f.key as string];
          if (f.type === "bool") {
            nextYt[f.key as string] = Boolean(raw);
          } else if (f.type === "int") {
            nextYt[f.key as string] =
              raw == null || raw === "" ? null : String(raw);
          } else {
            nextYt[f.key as string] = raw == null ? "" : String(raw);
          }
        }
      }
      setYt(nextYt);
      const dlSource = (cfg.download ?? {}) as unknown as Record<
        string,
        unknown
      >;
      const nextDl: Record<string, YtFieldValue> = { ...DEFAULT_DOWNLOAD };
      for (const f of DOWNLOAD_FIELDS) {
        const raw = dlSource[f.key];
        if (f.type === "bool") {
          nextDl[f.key] = Boolean(raw);
        } else {
          nextDl[f.key] = raw == null ? "" : String(raw);
        }
      }
      setDownload(nextDl);
      setExtraArgs(JSON.stringify(cfg.yt_dlp.extra_args ?? {}, null, 2));
      setHydrated(true);
    });
    return () => {
      cancelled = true;
    };
  }, [data.data, hydrated]);

  async function saveSettings() {
    if (!workspaceId) return;
    setPending(true);
    try {
      let parsedExtra: Record<string, unknown> = {};
      const rawExtra = extraArgs.trim();
      if (rawExtra) {
        try {
          const parsed = JSON.parse(rawExtra);
          parsedExtra =
            parsed && typeof parsed === "object"
              ? (parsed as Record<string, unknown>)
              : {};
        } catch {
          notify("附加参数（extra_args）不是合法 JSON", "error");
          return;
        }
      }
      const ytBody: Record<string, unknown> = {};
      for (const group of YTDLP_FIELD_GROUPS) {
        for (const f of group.fields) {
          const value = yt[f.key as string];
          if (f.type === "int") {
            ytBody[f.key as string] =
              value == null || value === "" ? null : Number(value);
          } else if (f.type === "bool") {
            ytBody[f.key as string] = Boolean(value);
          } else {
            ytBody[f.key as string] = value == null ? "" : String(value);
          }
        }
      }
      ytBody.dateafter = dateInputToYmd(dateAfter);
      ytBody.datebefore = dateInputToYmd(dateBefore);
      ytBody.playlist_start = Number(playlistStart) || 1;
      ytBody.extra_args = parsedExtra;

      const downloadBody: Record<string, unknown> = {};
      for (const f of DOWNLOAD_FIELDS) {
        const value = download[f.key];
        downloadBody[f.key] =
          f.type === "bool"
            ? Boolean(value)
            : value == null
              ? ""
              : String(value);
      }

      const body = {
        config: {
          max_contents: maxContents.trim() ? Number(maxContents) : null,
          skip_existing: skipExisting,
          yt_dlp: ytBody,
          download: downloadBody,
        },
        sync_task_max_retries:
          syncTaskMaxRetries.trim() === ""
            ? null
            : Math.min(10, Math.max(0, Number(syncTaskMaxRetries))),
      };
      await apiRequest("/settings/sync", {
        method: "PUT",
        workspaceId,
        csrf: true,
        body: JSON.stringify(body),
      });
      notify("同步设置已保存");
      setHydrated(false);
      await queryClient.invalidateQueries({ queryKey: ["sync-settings"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "保存失败", "error");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-5">
      <Panel className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <Wrench size={16} className="text-cyan-300" />
              <h2 className="font-medium text-white">视频解析运行时</h2>
              {runtime.data && (
                <Badge
                  tone={runtime.data.status === "ready" ? "success" : "warning"}
                >
                  {runtime.data.status === "ready" ? "已就绪" : "需配置"}
                </Badge>
              )}
            </div>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              YouTube 完整解析需要 Node.js 22+ 与 yt-dlp[default] 的 EJS
              组件。解析失败时先检查这里的版本与路径。
            </p>
          </div>
          <div className="flex gap-2">
            <button
              className={secondaryButtonClass}
              disabled={runtime.isFetching}
              onClick={() => void checkRuntime()}
              type="button"
            >
              <RefreshCw size={14} className={runtime.isFetching ? "animate-spin" : ""} />
              {runtime.isFetching ? "检查中…" : "检查运行时"}
            </button>
            <button
              className={buttonClass}
              disabled={!runtime.data?.update_enabled || runtimeUpdating}
              onClick={() => void updateRuntime()}
              title={
                runtime.data?.update_enabled
                  ? "在当前 API 容器中更新 yt-dlp"
                  : "默认关闭，请通过镜像重建更新"
              }
              type="button"
            >
              <CheckCircle2 size={14} />
              {runtimeUpdating ? "更新中" : "更新 yt-dlp"}
            </button>
          </div>
        </div>
        {runtime.data ? (
          <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <RuntimeValue
              label="Node.js"
              value={runtime.data.node_version ?? "未发现"}
            />
            <RuntimeValue
              label="Node 路径"
              value={runtime.data.node_resolved_path ?? "未发现"}
            />
            <RuntimeValue
              label="yt-dlp"
              value={runtime.data.yt_dlp_version ?? "未发现"}
            />
            <RuntimeValue
              label="EJS 远程组件"
              value={
                runtime.data.remote_components.join(", ") || "使用内置组件"
              }
            />
          </div>
        ) : runtime.isLoading ? (
          <p className="mt-4 text-sm text-slate-500">正在检查运行时…</p>
        ) : runtime.error ? (
          <p className="mt-4 text-sm text-rose-300">{runtime.error.message}</p>
        ) : null}
        {runtime.data && (
          <p className="mt-3 text-xs leading-5 text-slate-500">
            {runtime.data.detail} {runtime.data.update_note} 更新命令：
            <code className="ml-1 text-slate-300">
              {runtime.data.update_command}
            </code>
          </p>
        )}
        {runtimeCheckedAt && (
          <p className="mt-2 text-xs text-slate-600">
            本次检查：{new Date(runtimeCheckedAt).toLocaleString("zh-CN")}
          </p>
        )}
      </Panel>
      <Panel className="p-5">
        <h2 className="font-medium text-white">同步与抓取策略</h2>
        <p className="mt-1 text-xs text-slate-500">
          统一控制本工作区所有账号的抓取行为。同步默认拉取账号的
          <strong>全部历史作品</strong>
          （全量抓取）；下方参数用于限定范围、量级与重复处理方式。
        </p>
      </Panel>
      {data.isLoading && (
        <Panel className="p-5 text-sm text-slate-500">正在加载同步设置…</Panel>
      )}
      {data.error && (
        <Panel className="p-5 text-sm text-rose-400">
          同步设置加载失败：{data.error.message}
        </Panel>
      )}
      {data.data && (
        <Panel className="p-5">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void saveSettings();
            }}
            className="grid gap-5"
          >
            <SettingsGroup
              title="同步范围与时间窗口"
              description="先定义单次任务规模，再设置日期、分页起点与已存在作品的处理方式。"
              tone="slate"
            >
            <label className="grid gap-2 text-sm">
              单次同步最多抓取作品数
              <input
                name="max_contents"
                className={inputClass}
                type="number"
                min="1"
                max="5000"
                value={maxContents}
                onChange={(e) => setMaxContents(e.target.value)}
                placeholder="留空 = 全量抓取（受分页上限约束）"
                disabled={!canEdit}
              />
            </label>

            <label className="grid gap-2 text-sm">
              同步任务最大重试次数（sync_task_max_retries）
              <input
                name="sync_task_max_retries"
                className={inputClass}
                type="number"
                min="0"
                max="10"
                value={syncTaskMaxRetries}
                onChange={(e) => setSyncTaskMaxRetries(e.target.value)}
                placeholder="0–10，留空 = 沿用环境变量默认"
                disabled={!canEdit}
              />
              <span className="text-xs text-slate-500">
                Celery
                同步任务失败后的重试上限；保存后立即生效，无需重启服务。可在「运行时设置」页查看当前生效值。
              </span>
            </label>

            <div className="grid grid-cols-2 gap-4">
              <label className="grid gap-2 text-sm">
                仅抓取此日期之后（dateafter）
                <input
                  name="dateafter"
                  className={inputClass}
                  type="date"
                  value={dateAfter}
                  onChange={(e) => setDateAfter(e.target.value)}
                  disabled={!canEdit}
                />
              </label>
              <label className="grid gap-2 text-sm">
                仅抓取此日期之前（datebefore）
                <input
                  name="datebefore"
                  className={inputClass}
                  type="date"
                  value={dateBefore}
                  onChange={(e) => setDateBefore(e.target.value)}
                  disabled={!canEdit}
                />
              </label>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <label className="grid gap-2 text-sm">
                播放列表起始位置（playlist_start）
                <input
                  name="playlist_start"
                  className={inputClass}
                  type="number"
                  min="1"
                  value={playlistStart}
                  onChange={(e) => setPlaylistStart(e.target.value)}
                  disabled={!canEdit}
                />
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  name="skip_existing"
                  type="checkbox"
                  checked={skipExisting}
                  onChange={(e) => setSkipExisting(e.target.checked)}
                  disabled={!canEdit}
                />
                已存在的作品跳过更新（仅刷新指标，不覆盖标题 / 封面）
              </label>
            </div>

            </SettingsGroup>

            {YTDLP_FIELD_GROUPS.map((group) => (
              <SettingsGroup
                key={group.title}
                title={group.title}
                description={group.description}
                tone={
                  group.fields.some((field) => field.key === "cookies_from_browser")
                    ? "violet"
                    : "cyan"
                }
              >
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {group.fields.map((f) => {
                    const value = yt[f.key as string];
                    if (f.type === "bool") {
                      return (
                        <label
                          key={f.key as string}
                          className="flex min-h-10 items-start gap-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-sm transition-colors hover:border-cyan-900/80"
                        >
                          <input
                            type="checkbox"
                            className="mt-1"
                            checked={Boolean(value)}
                            onChange={(e) =>
                              setYt((prev) => ({
                                ...prev,
                                [f.key as string]: e.target.checked,
                              }))
                            }
                            disabled={!canEdit}
                          />
                          <span>
                            <span className="block">{f.label}</span>
                            {f.help && (
                              <span className="block text-xs text-slate-500">
                                {f.help}
                              </span>
                            )}
                          </span>
                        </label>
                      );
                    }
                    if (f.type === "select") {
                      return (
                        <label key={f.key as string} className="grid min-w-0 gap-2 text-sm">
                          <span>{f.label}</span>
                          <select
                            className={inputClass}
                            value={value == null ? "" : String(value)}
                            onChange={(e) =>
                              setYt((prev) => ({
                                ...prev,
                                [f.key as string]: e.target.value,
                              }))
                            }
                            disabled={!canEdit}
                          >
                            {(f.options ?? []).map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                          {f.help && (
                            <span className="text-xs leading-5 text-slate-500">
                              {f.help}
                            </span>
                          )}
                        </label>
                      );
                    }
                    return (
                      <label
                        key={f.key as string}
                        className="grid min-w-0 gap-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-sm"
                      >
                        <span>
                          {f.label}
                          {f.help && (
                            <span className="ml-1 text-xs text-slate-500">
                              — {f.help}
                            </span>
                          )}
                        </span>
                        <input
                          type={f.type === "int" ? "number" : "text"}
                          min={f.type === "int" ? "0" : undefined}
                          className={inputClass}
                          value={value == null ? "" : String(value)}
                          placeholder={f.placeholder}
                          onChange={(e) =>
                            setYt((prev) => ({
                              ...prev,
                              [f.key as string]: e.target.value,
                            }))
                          }
                          disabled={!canEdit}
                        />
                      </label>
                    );
                  })}
                </div>
              </SettingsGroup>
            ))}

            <fieldset className="grid gap-3 rounded-xl border border-amber-900/70 bg-amber-950/10 p-4">
              <legend className="px-1 text-xs font-medium uppercase tracking-wide text-amber-300">
                媒体下载
              </legend>
              <p className="text-xs text-slate-500">
                同步时把对应媒体文件归档到本地，供详情页「媒体资源」展示。默认已开启封面与字幕；
                <strong className="text-amber-300">
                  下载视频会显著消耗磁盘与带宽，请按需开启
                </strong>
                。
              </p>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {DOWNLOAD_FIELDS.map((f) => {
                  const value = download[f.key];
                  if (f.type === "bool") {
                    return (
                      <label
                        key={f.key}
                        className="flex min-h-10 items-start gap-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-sm transition-colors hover:border-amber-900/80"
                      >
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={Boolean(value)}
                          onChange={(e) =>
                            setDownload((prev) => ({
                              ...prev,
                              [f.key]: e.target.checked,
                            }))
                          }
                          disabled={!canEdit}
                        />
                        <span>
                          <span className="block">{f.label}</span>
                          {f.help && (
                            <span className="block text-xs text-slate-500">
                              {f.help}
                            </span>
                          )}
                        </span>
                      </label>
                    );
                  }
                  if (f.type === "select") {
                    return (
                      <label key={f.key} className="grid min-w-0 gap-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-sm">
                        <span>
                          {f.label}
                          {f.help && (
                            <span className="ml-1 text-xs text-slate-500">
                              — {f.help}
                            </span>
                          )}
                        </span>
                        <select
                          className={inputClass}
                          value={value == null ? "" : String(value)}
                          onChange={(e) =>
                            setDownload((prev) => ({
                              ...prev,
                              [f.key]: e.target.value,
                            }))
                          }
                          disabled={!canEdit}
                        >
                          {(f.options ?? []).map((opt) => (
                            <option key={opt.value} value={opt.value}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                      </label>
                    );
                  }
                  return (
                      <label key={f.key} className="grid min-w-0 gap-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-sm">
                      <span>
                        {f.label}
                        {f.help && (
                          <span className="ml-1 text-xs text-slate-500">
                            — {f.help}
                          </span>
                        )}
                      </span>
                      <input
                        type="text"
                        className={inputClass}
                        value={value == null ? "" : String(value)}
                        placeholder={f.placeholder}
                        onChange={(e) =>
                          setDownload((prev) => ({
                            ...prev,
                            [f.key]: e.target.value,
                          }))
                        }
                        disabled={!canEdit}
                      />
                    </label>
                  );
                })}
              </div>
            </fieldset>

            <label className="grid gap-2 text-sm">
              额外 yt-dlp 参数（extra_args，JSON）
              <textarea
                name="extra_args"
                className={`${inputClass} min-h-24 font-mono text-xs`}
                value={extraArgs}
                onChange={(e) => setExtraArgs(e.target.value)}
                placeholder={
                  '{\n  "match_filter": "...",\n  "geo_bypass": true\n}'
                }
                disabled={!canEdit}
              />
            </label>
            <p className="text-xs text-slate-500">
              行业实践：用日期区间缩小范围、控制单次量级、设置请求间隔与限速可显著降低被限流与超时风险；
              同步间隔请在账号的「同步周期」中设置。上方结构化字段已覆盖常用
              yt-dlp 参数； 若仍需其他参数，可在 extra_args 中按{" "}
              <code>{'{ "参数名": 值 }'}</code> 形式自由追加。
            </p>
            {canEdit && (
              <button
                type="submit"
                className={`${buttonClass} w-full justify-center`}
                disabled={pending}
              >
                <Save size={14} />
                {pending ? "保存中…" : "保存同步设置"}
              </button>
            )}
          </form>
        </Panel>
      )}
      <Panel className="p-5">
        <h3 className="flex items-center gap-2 font-medium text-slate-200">
          <RefreshCw size={14} className="text-cyan-400" />
          抓取逻辑说明
        </h3>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-xs leading-5 text-slate-400">
          <li>
            默认对每个账号执行<strong>全量抓取</strong>
            ，不再区分增量与全量；历史作品会被一并拉取回填。
          </li>
          <li>
            「单次同步最多抓取作品数」为空时，抓取受平台分页上限约束；设置数值可硬性限制单次量级。
          </li>
          <li>
            遇到已存在的作品时，由「已存在的作品跳过更新」决定是跳过还是覆盖可编辑字段（指标始终刷新）。
          </li>
          <li>
            日期区间（dateafter / datebefore / daterange）以 YYYYMMDD 形式传给
            yt-dlp，用于限定作品时间范围。
          </li>
          <li>
            其余 yt-dlp
            参数（排序、筛选、代理、限速、地理绕过等）仅在填写时生效，留空表示不施加该限制。
          </li>
        </ul>
      </Panel>
    </div>
  );
}

function RuntimeValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-950/60 p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 truncate text-slate-200" title={value}>
        {value}
      </div>
    </div>
  );
}
