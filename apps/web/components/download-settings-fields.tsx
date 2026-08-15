"use client";

import type { YtDlpDownloadSettings } from "@sio/shared-types";
import { inputClass } from "@/components/ui";

export const DEFAULT_DOWNLOAD_SETTINGS: YtDlpDownloadSettings = {
  write_thumbnail: true,
  write_subtitles: false,
  write_auto_subtitles: false,
  subtitle_langs: "zh,en",
  download_video: false,
  video_format: "best",
  write_info_json: false,
  fetch_comments: false,
};

type Props = {
  value: YtDlpDownloadSettings;
  onChange: (next: YtDlpDownloadSettings) => void;
  disabled?: boolean;
};

const BOOLEAN_FIELDS: {
  key: keyof YtDlpDownloadSettings;
  label: string;
  hint: string;
}[] = [
  { key: "write_thumbnail", label: "下载封面缩略图", hint: "归档作品的封面图" },
  { key: "write_subtitles", label: "下载字幕", hint: "抓取作者上传的字幕文件" },
  {
    key: "write_auto_subtitles",
    label: "下载自动字幕",
    hint: "抓取平台自动生成的字幕",
  },
  {
    key: "download_video",
    label: "下载视频文件",
    hint: "抓取视频本体（占用空间较大）",
  },
  {
    key: "write_info_json",
    label: "下载元数据 JSON",
    hint: "归档作品的结构化元数据",
  },
  {
    key: "fetch_comments",
    label: "抓取热门评论（每条作品 Top 20）",
    hint: "可选：按点赞与回复数排序保存；默认关闭，不拖慢普通账号同步",
  },
];

export function DownloadSettingsFields({ value, onChange, disabled }: Props) {
  function setField<K extends keyof YtDlpDownloadSettings>(
    key: K,
    v: YtDlpDownloadSettings[K],
  ) {
    onChange({ ...value, [key]: v });
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {BOOLEAN_FIELDS.map((field) => (
          <label
            key={field.key}
            className="flex items-start gap-2 rounded-lg border border-slate-800 bg-slate-900/40 p-3 text-sm"
          >
            <input
              type="checkbox"
              className="mt-0.5"
              checked={Boolean(value[field.key])}
              disabled={disabled}
              onChange={(event) => setField(field.key, event.target.checked)}
            />
            <span className="min-w-0">
              <span className="block font-medium text-slate-200">
                {field.label}
              </span>
              <span className="block text-xs text-slate-500">{field.hint}</span>
            </span>
          </label>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="grid gap-2 text-sm">
          字幕语言
          <input
            className={inputClass}
            value={value.subtitle_langs}
            disabled={disabled}
            placeholder="zh,en"
            onChange={(event) => setField("subtitle_langs", event.target.value)}
          />
        </label>
        <label className="grid gap-2 text-sm">
          视频格式
          <input
            className={inputClass}
            value={value.video_format}
            disabled={disabled}
            placeholder="best"
            onChange={(event) => setField("video_format", event.target.value)}
          />
        </label>
      </div>
    </div>
  );
}
