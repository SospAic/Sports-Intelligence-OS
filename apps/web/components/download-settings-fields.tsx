"use client";

import type { YtDlpDownloadSettings } from "@sio/shared-types";
import { inputClass } from "@/components/ui";

export const DEFAULT_DOWNLOAD_SETTINGS: YtDlpDownloadSettings = {
  write_thumbnail: true,
  write_subtitles: true,
  write_auto_subtitles: true,
  subtitle_langs: "zh.*,en.*",
  download_video: false,
  video_format: "best",
  write_info_json: false,
  fetch_comments: true,
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
    label: "自动生成字幕",
    hint: "抓取平台提供的自动生成字幕轨道",
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
    hint: "按点赞与回复数排序保存；可能增加同步耗时",
  },
];

const SUBTITLE_LANGUAGE_OPTIONS = [
  { value: "zh.*", label: "中文" },
  { value: "en.*", label: "英语" },
  { value: "ja.*", label: "日语" },
  { value: "ko.*", label: "韩语" },
  { value: "es.*", label: "西班牙语" },
  { value: "fr.*", label: "法语" },
  { value: "de.*", label: "德语" },
  { value: "pt.*", label: "葡萄牙语" },
] as const;

function isLanguageSelected(filter: string, value: string): boolean {
  const base = value.replace(/\.\*$/, "");
  return filter.split(",").some((item) => {
    const normalized = item.trim().toLowerCase();
    return normalized === value || normalized === base || normalized.startsWith(`${base}-`);
  });
}

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
      <fieldset className="space-y-2 rounded-lg border border-violet-900/60 bg-violet-950/10 p-3">
        <legend className="px-1 text-sm font-medium text-violet-200">
          自动生成语言
        </legend>
        <p className="text-xs leading-5 text-slate-500">
          选择向平台请求的自动字幕语言；平台未提供时不会用估算文本代替。
        </p>
        <div className="flex flex-wrap gap-2">
          {SUBTITLE_LANGUAGE_OPTIONS.map((language) => {
            const checked = isLanguageSelected(value.subtitle_langs, language.value);
            return (
              <label
                className={`inline-flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-xs transition ${checked ? "border-violet-700 bg-violet-500/15 text-violet-200" : "border-slate-800 text-slate-400 hover:border-slate-700"} ${!value.write_auto_subtitles ? "cursor-not-allowed opacity-50" : ""}`}
                key={language.value}
              >
                <input
                  aria-label={language.label}
                  checked={checked}
                  className="accent-violet-400"
                  disabled={disabled || !value.write_auto_subtitles}
                  onChange={(event) => {
                    const selected = value.subtitle_langs
                      .split(",")
                      .map((item) => item.trim())
                      .filter(Boolean)
                      .filter((item) => !isLanguageSelected(item, language.value));
                    if (event.target.checked) selected.push(language.value);
                    setField("subtitle_langs", selected.join(","));
                  }}
                  type="checkbox"
                />
                {language.label}
              </label>
            );
          })}
        </div>
      </fieldset>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="grid gap-2 text-sm">
          视频格式
          <select
            className={inputClass}
            value={value.video_format}
            disabled={disabled}
            onChange={(event) => setField("video_format", event.target.value)}
          >
            <option value="best">最佳（自动）</option>
            <option value="mp4">MP4</option>
            <option value="webm">WebM</option>
            <option value="mkv">MKV</option>
          </select>
        </label>
      </div>
    </div>
  );
}
