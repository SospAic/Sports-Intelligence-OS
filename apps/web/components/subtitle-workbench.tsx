"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Captions, Download, Eye, Loader2 } from "lucide-react";
import { apiRequest, downloadApiPostFile } from "@/lib/browser-api";
import { subtitleDisplayText } from "@/lib/subtitles";
import {
  defaultSubtitleLanguagePair,
  subtitleLanguageLabel,
} from "@/lib/language-options";

export interface SubtitleSourceTrack {
  lang: string;
  file: string;
}

interface SubtitlePreview {
  primary_lang: string;
  secondary_lang: string;
  format: "vtt" | "srt" | "txt" | "json" | "ass";
  show_timestamps: boolean;
  cue_count: number;
  cues: { start_ms: number; end_ms: number; text: string }[];
  rendered_text: string;
  source_files: string[];
  generated_file: string | null;
}

const formatLabels: Record<SubtitlePreview["format"], string> = {
  srt: "SRT（通用）",
  vtt: "WebVTT（网页）",
  txt: "TXT（纯文本）",
  json: "JSON（结构化）",
  ass: "ASS（样式字幕）",
};

function stamp(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  return `${String(minutes).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function displayText(value: string): string {
  return subtitleDisplayText(value);
}

/**
 * A small, shared subtitle workbench for archived content and download rows.
 * It never transcribes missing audio; it previews and composes only real
 * tracks recorded by the backend, then asks the backend to render the file.
 */
export function SubtitleWorkbench({
  endpoint,
  workspaceId,
  tracks,
  compact = false,
  currentTimeSeconds,
}: {
  endpoint: string;
  workspaceId: string;
  tracks: SubtitleSourceTrack[];
  compact?: boolean;
  currentTimeSeconds?: number | null;
}) {
  const languages = useMemo(
    () => Array.from(new Set(tracks.map((track) => track.lang).filter(Boolean))),
    [tracks],
  );
  // null is the initial auto-selection; an empty string is an explicit
  // "no second language" choice and must not be auto-filled again.
  const [primary, setPrimary] = useState<string | null>(null);
  const [secondary, setSecondary] = useState<string | null>(null);
  const [format, setFormat] = useState<SubtitlePreview["format"]>("srt");
  const [showTimestamps, setShowTimestamps] = useState(false);
  const [preview, setPreview] = useState<SubtitlePreview | null>(null);
  const [busy, setBusy] = useState<"preview" | "export" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cueRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const previewScrollRef = useRef<HTMLDivElement | null>(null);
  const defaultLanguagePair = useMemo(
    () => defaultSubtitleLanguagePair(languages),
    [languages],
  );

  const selectedPrimary =
    primary === null
      ? defaultLanguagePair.primary
      : primary && languages.includes(primary)
        ? primary
        : "";
  const selectedSecondary =
    !selectedPrimary
      ? ""
      : secondary === null
        ? defaultLanguagePair.secondary !== selectedPrimary
          ? defaultLanguagePair.secondary
          : languages.find((language) => language !== selectedPrimary) ?? ""
        : secondary && languages.includes(secondary) && secondary !== selectedPrimary
          ? secondary
          : "";

  const payload = useMemo(
    () => ({
      primary_lang: selectedPrimary,
      secondary_lang: selectedSecondary,
      format,
      show_timestamps: showTimestamps,
    }),
    [format, selectedPrimary, selectedSecondary, showTimestamps],
  );

  const loadPreview = useCallback(async () => {
    if (!selectedPrimary) return;
    setBusy("preview");
    setError(null);
    try {
      const result = await apiRequest<SubtitlePreview>(`${endpoint}/subtitle-preview`, {
        method: "POST",
        workspaceId,
        body: JSON.stringify(payload),
      });
      setPreview(result);
    } catch (reason) {
      setPreview(null);
      setError(reason instanceof Error ? reason.message : "字幕预览失败");
    } finally {
      setBusy(null);
    }
  }, [endpoint, payload, selectedPrimary, workspaceId]);

  useEffect(() => {
    if (!selectedPrimary) return;
    const timer = window.setTimeout(() => void loadPreview(), 180);
    return () => window.clearTimeout(timer);
  }, [loadPreview, selectedPrimary]);

  const exportFile = async () => {
    if (!selectedPrimary) return;
    setBusy("export");
    setError(null);
    try {
      const base = `${selectedPrimary}${selectedSecondary ? `-and-${selectedSecondary}-bilingual` : ""}.${format}`;
      await downloadApiPostFile(`${endpoint}/subtitle-export`, payload, workspaceId, base);
      await loadPreview();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "字幕导出失败");
    } finally {
      setBusy(null);
    }
  };

  const visiblePreview = selectedPrimary ? preview : null;
  const activeCueIndex =
    visiblePreview && currentTimeSeconds != null
      ? visiblePreview.cues.findIndex(
          (cue) =>
            currentTimeSeconds >= cue.start_ms / 1000 &&
            currentTimeSeconds < cue.end_ms / 1000,
        )
      : -1;

  useEffect(() => {
    if (activeCueIndex < 0) return;
    const container = previewScrollRef.current;
    const cue = cueRefs.current[activeCueIndex];
    if (!container || !cue) return;
    const containerRect = container.getBoundingClientRect();
    const cueRect = cue.getBoundingClientRect();
    if (cueRect.top < containerRect.top) {
      container.scrollTo({
        top: Math.max(0, container.scrollTop - (containerRect.top - cueRect.top) - 12),
        behavior: "smooth",
      });
    } else if (cueRect.bottom > containerRect.bottom) {
      container.scrollTo({
        top: container.scrollTop + (cueRect.bottom - containerRect.bottom) + 12,
        behavior: "smooth",
      });
    }
  }, [activeCueIndex]);

  if (languages.length === 0) {
    return (
      <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-3 text-xs leading-5 text-amber-200">
        目前没有可读取的原始字幕轨道。系统不会用估算文本冒充字幕；如需从视频声音生成字幕，需要另外配置语音识别引擎。
      </div>
    );
  }

  return (
    <div className={`space-y-3 rounded-lg border border-violet-900/50 bg-violet-950/10 ${compact ? "p-3" : "p-4"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <div className="mr-auto flex items-center gap-2 text-sm font-medium text-violet-100">
          <Captions size={15} /> 字幕工作台
        </div>
        <select
          aria-label="字幕输出格式"
          className="h-8 rounded-md border border-slate-700 bg-slate-900 px-2 text-xs text-slate-200"
          value={format}
          onChange={(event) => setFormat(event.target.value as SubtitlePreview["format"])}
        >
          {Object.entries(formatLabels).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <button
          type="button"
          className="inline-flex h-8 items-center gap-1 rounded-md border border-slate-700 px-2 text-xs text-slate-200 hover:border-violet-500"
          onClick={() => void loadPreview()}
          disabled={busy !== null}
        >
          {busy === "preview" ? <Loader2 size={13} className="animate-spin" /> : <Eye size={13} />}
          预览
        </button>
        <button
          type="button"
          className="inline-flex h-8 items-center gap-1 rounded-md bg-violet-500 px-2 text-xs font-medium text-white hover:bg-violet-400 disabled:opacity-50"
          onClick={() => void exportFile()}
          disabled={busy !== null || !selectedPrimary}
        >
          {busy === "export" ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
          生成并下载
        </button>
      </div>
      <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
        <label className="grid gap-1 text-[11px] text-slate-400">
          第一语言
          <select className="h-8 rounded-md border border-slate-700 bg-slate-900 px-2 text-xs text-slate-200" value={selectedPrimary} onChange={(event) => setPrimary(event.target.value)}>
            {languages.map((language) => <option key={`primary-${language}`} value={language}>{subtitleLanguageLabel(language)}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-[11px] text-slate-400">
          第二语言
          <select className="h-8 rounded-md border border-slate-700 bg-slate-900 px-2 text-xs text-slate-200" value={selectedSecondary} onChange={(event) => setSecondary(event.target.value)}>
            <option value="">无（单行）</option>
            {languages.map((language) => <option key={`secondary-${language}`} value={language} disabled={language === selectedPrimary}>{subtitleLanguageLabel(language)}</option>)}
          </select>
        </label>
        <label className="flex items-end gap-2 pb-2 text-xs text-slate-400">
          <input type="checkbox" className="rounded border-slate-600 bg-slate-800" checked={showTimestamps} onChange={(event) => setShowTimestamps(event.target.checked)} />
          显示时间戳
        </label>
      </div>
      <p className="text-[11px] leading-5 text-slate-500">
        已检测到 {tracks.length} 条真实轨道；第二语言会按时间区间自动对齐。SRT/VTT/ASS 文件保留结构化时间轴，时间戳开关控制字幕文本中是否额外显示起始时间。
      </p>
      {error && <p className="rounded-md border border-rose-900/60 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">{error}</p>}
      {visiblePreview && (
        <div className="rounded-md border border-slate-800 bg-slate-950/60 p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500">
            <span>{visiblePreview.primary_lang}{visiblePreview.secondary_lang ? ` + ${visiblePreview.secondary_lang}` : " · 单语"} · {visiblePreview.cue_count} 条</span>
            <span>预览前 {Math.min(visiblePreview.cue_count, visiblePreview.cues.length)} 条</span>
          </div>
          <div
            ref={previewScrollRef}
            tabIndex={0}
            aria-label="字幕滚动预览"
            className="max-h-72 min-h-0 space-y-2 overflow-y-auto overscroll-contain pr-1 outline-none"
          >
            {visiblePreview.cues.map((cue, index) => (
              <div
                key={`${cue.start_ms}-${index}`}
                ref={(node) => { cueRefs.current[index] = node; }}
                className={`rounded-md border-b border-slate-800/80 pb-2 last:border-0 last:pb-0 ${
                  activeCueIndex === index
                    ? "bg-cyan-950/60 px-2 py-1.5 text-white ring-1 ring-cyan-500/60"
                    : "px-2 py-1.5"
                }`}
              >
                {showTimestamps && (
                  <div className="mb-1 text-[10px] text-cyan-300/80">{stamp(cue.start_ms)} → {stamp(cue.end_ms)}</div>
                )}
                <div className="whitespace-normal break-words text-xs leading-5 text-slate-200">{displayText(cue.text)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
