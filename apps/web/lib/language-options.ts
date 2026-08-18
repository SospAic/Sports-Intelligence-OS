export const UI_LANGUAGE_OPTIONS = [
  { value: "zh-CN", label: "简体中文", nativeLabel: "简体中文" },
  { value: "en-US", label: "英语", nativeLabel: "English" },
  { value: "ja-JP", label: "日语", nativeLabel: "日本語" },
  { value: "ko-KR", label: "韩语", nativeLabel: "한국어" },
  { value: "es-ES", label: "西班牙语", nativeLabel: "Español" },
  { value: "fr-FR", label: "法语", nativeLabel: "Français" },
  { value: "de-DE", label: "德语", nativeLabel: "Deutsch" },
  { value: "pt-BR", label: "葡萄牙语", nativeLabel: "Português" },
] as const;

export type UiLanguageCode = (typeof UI_LANGUAGE_OPTIONS)[number]["value"];

const SUBTITLE_LANGUAGE_LABELS: Record<string, string> = {
  ar: "阿拉伯语",
  de: "德语",
  en: "英语",
  es: "西班牙语",
  fr: "法语",
  hi: "印地语",
  id: "印度尼西亚语",
  it: "意大利语",
  ja: "日语",
  ko: "韩语",
  ms: "马来语",
  nl: "荷兰语",
  no: "挪威语",
  pl: "波兰语",
  pt: "葡萄牙语",
  ru: "俄语",
  sv: "瑞典语",
  th: "泰语",
  tr: "土耳其语",
  uk: "乌克兰语",
  vi: "越南语",
  zh: "中文",
  und: "源字幕",
  "und-auto": "源字幕",
};

/** Return a Chinese label while preserving the original code as the option value. */
export function subtitleLanguageLabel(language: string | null | undefined): string {
  const raw = String(language ?? "").trim();
  if (!raw) return "未知语种";
  const normalized = raw.toLowerCase().replaceAll("_", "-");
  const exact = {
    "en-orig": "英语（原始）",
    "zh-hans": "中文（简体）",
    "zh-hant": "中文（繁体）",
    und: "源字幕",
    "und-auto": "源字幕",
  }[normalized];
  if (exact) return exact;
  const base = normalized.split("-")[0] ?? "";
  const label = SUBTITLE_LANGUAGE_LABELS[base];
  if (!label) return `其他语言（${raw}）`;
  if (normalized === base) return label;
  return `${label}（${raw}）`;
}

export function normalizeSubtitleLanguageCode(language: string | null | undefined): string {
  return String(language ?? "")
    .trim()
    .toLowerCase()
    .replaceAll("_", "-");
}

export function subtitleLanguageBase(language: string | null | undefined): string {
  return normalizeSubtitleLanguageCode(language).split("-")[0] ?? "";
}

/** Pick stable YouTube-like defaults: English first, Chinese second. */
export function defaultSubtitleLanguagePair(languages: string[]): {
  primary: string;
  secondary: string;
} {
  const available = Array.from(new Set(languages.filter(Boolean)));
  const findPreferred = (preferred: string[], base: string, excluded = "") =>
    preferred
      .map((code) =>
        available.find(
          (language) =>
            language !== excluded && normalizeSubtitleLanguageCode(language) === code,
        ),
      )
      .find(Boolean) ??
    available.find(
      (language) =>
        language !== excluded && subtitleLanguageBase(language) === base,
    ) ??
    "";
  const primary =
    findPreferred(["en", "en-orig"], "en") || available[0] || "";
  const secondary =
    findPreferred(["zh", "zh-hans", "zh-cn", "zh-hant"], "zh", primary) ||
    available.find((language) => language !== primary) ||
    "";
  return { primary, secondary };
}

export function subtitleTrackLabel(
  language: string | null | undefined,
  kind?: "manual" | "automatic",
): string {
  const label = subtitleLanguageLabel(language);
  if (!kind) return label;
  return `${label}（${kind === "automatic" ? "自动" : "人工"}）`;
}

export function isUiLanguageCode(value: string): value is UiLanguageCode {
  return UI_LANGUAGE_OPTIONS.some((item) => item.value === value);
}
