"use client";

import { subtitleLanguageBase } from "@/lib/language-options";

export const LOCAL_SUBTITLE_LANGUAGE_OPTIONS = [
  ["zh", "中文"],
  ["en", "英语"],
  ["ja", "日语"],
  ["ko", "韩语"],
  ["es", "西班牙语"],
  ["fr", "法语"],
  ["de", "德语"],
  ["pt", "葡萄牙语"],
] as const;

export function existingSubtitleGenerationLanguages(existingLanguages: string[]): string[] {
  return LOCAL_SUBTITLE_LANGUAGE_OPTIONS.filter(([value]) =>
    existingLanguages.some((language) => subtitleLanguageBase(language) === value),
  ).map(([value]) => value);
}

export function missingSubtitleGenerationLanguages(existingLanguages: string[]): string[] {
  const existing = new Set(existingSubtitleGenerationLanguages(existingLanguages));
  return LOCAL_SUBTITLE_LANGUAGE_OPTIONS.map(([value]) => value).filter(
    (value) => !existing.has(value),
  );
}

export function SubtitleGenerationOptions({
  enabled,
  languages,
  existingLanguages = [],
  disabled,
  onEnabledChange,
  onLanguagesChange,
}: {
  enabled: boolean;
  languages: string[];
  existingLanguages?: string[];
  disabled?: boolean;
  onEnabledChange: (value: boolean) => void;
  onLanguagesChange: (value: string[]) => void;
}) {
  const existing = new Set(existingSubtitleGenerationLanguages(existingLanguages));
  const missing = LOCAL_SUBTITLE_LANGUAGE_OPTIONS.map(([value]) => value).filter(
    (value) => !existing.has(value),
  );
  const toggleLanguage = (language: string) => {
    if (existing.has(language)) return;
    onLanguagesChange(
      languages.includes(language)
        ? languages.filter((item) => item !== language)
        : [...languages, language],
    );
  };

  return (
    <div className="rounded-lg border border-cyan-900/60 bg-cyan-950/10 p-3">
      <label className="flex items-center gap-2 text-sm text-slate-200">
        <input
          type="checkbox"
          className="rounded border-slate-600 bg-slate-800"
          checked={enabled}
          disabled={disabled}
          onChange={(event) => onEnabledChange(event.target.checked)}
        />
        生成多语言字幕（本地语音识别 + 翻译）
      </label>
      {enabled && (
        <div className="mt-3 border-t border-cyan-900/40 pt-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-slate-400">选择要生成的语种（默认全部）：</p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="text-[11px] text-cyan-300 hover:text-cyan-200 disabled:opacity-50"
                disabled={disabled}
                onClick={() => onLanguagesChange(missing)}
              >
                全选
              </button>
              <button
                type="button"
                className="text-[11px] text-slate-400 hover:text-slate-200 disabled:opacity-50"
                disabled={disabled}
                onClick={() => onLanguagesChange([])}
              >
                清空
              </button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
            {LOCAL_SUBTITLE_LANGUAGE_OPTIONS.map(([value, label]) => (
              <label key={value} className="flex items-center gap-1.5 text-xs text-slate-300">
                <input
                  type="checkbox"
                  className="rounded border-slate-600 bg-slate-800"
                  checked={existing.has(value) || languages.includes(value)}
                  disabled={disabled || existing.has(value)}
                  onChange={() => toggleLanguage(value)}
                />
                {label}
                {existing.has(value) && <span className="text-[10px] text-emerald-300">已生成</span>}
              </label>
            ))}
          </div>
          <p className="mt-2 text-[11px] leading-5 text-slate-500">
            有原字幕时沿用原字幕时间轴；没有原字幕时才使用 faster-whisper 从本地视频生成时间轴。生成结果会作为独立字幕轨道加入字幕列表和视频控件。
          </p>
        </div>
      )}
    </div>
  );
}
