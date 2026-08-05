"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Captions, Languages } from "lucide-react";
import { useWorkspace } from "@/components/app-shell";

interface SubtitleTrack {
  lang: string;
  file: string;
}

interface Cue {
  start: number;
  end: number;
  text: string;
}

function toSeconds(ts: string): number {
  const clean = ts.trim().replace(",", ".");
  const parts = clean.split(":");
  let secs = 0;
  for (const p of parts) secs = secs * 60 + parseFloat(p);
  return Number.isFinite(secs) ? secs : 0;
}

function parseSubtitles(raw: string): Cue[] {
  const text = raw.replace(/^﻿/, "").replace(/^WEBVTT.*?(\r?\n\r?\n)/s, "");
  const blocks = text.trim().split(/\r?\n\r?\n/);
  const cues: Cue[] = [];
  for (const block of blocks) {
    const lines = block.split(/\r?\n/).filter((l) => l.trim().length > 0);
    if (lines.length === 0) continue;
    const timingIdx = lines.findIndex((l) => l.includes("-->"));
    if (timingIdx === -1) continue;
    const timingLine = lines[timingIdx];
    if (!timingLine) continue;
    const m = timingLine.match(/([\d:.,]+)\s*-->\s*([\d:.,]+)/);
    if (!m) continue;
    const start = toSeconds(m[1] ?? "0");
    const end = toSeconds(m[2] ?? "0");
    const cueText = lines
      .slice(timingIdx + 1)
      .join("\n")
      .trim();
    if (cueText) cues.push({ start, end, text: cueText });
  }
  return cues.sort((a, b) => a.start - b.start);
}

function formatStamp(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const mm = Math.floor(s / 60);
  const ss = s % 60;
  return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

function cueAt(cues: Cue[] | null, t: number): Cue | null {
  if (!cues || cues.length === 0) return null;
  // linear scan is fine for typical subtitle counts
  for (const c of cues) {
    if (t >= c.start && t < c.end) return c;
  }
  return null;
}

/**
 * Video player with a custom bilingual subtitle overlay.
 * - Two language dropdowns (first / second); the same language cannot be
 *   selected in both (mutually exclusive).
 * - Subtitles are fetched from the /media route and parsed (SRT + VTT).
 * - "显示时间轴" toggle (default OFF) prefixes each line with its [mm:ss]
 *   start, i.e. alignment is driven by the SRT/VTT timeline.
 */
export function SubtitleVideoPlayer({
  contentId,
  videoFile,
  subtitles,
}: {
  contentId: string;
  videoFile: string | null | undefined;
  subtitles: SubtitleTrack[];
}) {
  const { workspaceId } = useWorkspace();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [primaryLang, setPrimaryLang] = useState<string>(() => subtitles[0]?.lang ?? "");
  const [secondaryLang, setSecondaryLang] = useState<string>(
    () => subtitles[1]?.lang ?? "",
  );
  const [showTimeline, setShowTimeline] = useState(false);
  const [cues, setCues] = useState<Record<string, Cue[]>>({});
  const [loadingLang, setLoadingLang] = useState<string | null>(null);

  const langs = useMemo(
    () => subtitles.map((s) => s.lang).filter(Boolean),
    [subtitles],
  );

  const fileForLang = useCallback(
    (lang: string) => subtitles.find((s) => s.lang === lang)?.file ?? "",
    [subtitles],
  );

  const loadLang = useCallback(
    async (lang: string) => {
      if (!lang || cues[lang] || !fileForLang(lang) || !workspaceId) return;
      setLoadingLang(lang);
      try {
        const res = await fetch(
          `/api/v1/media/${contentId}/${encodeURIComponent(fileForLang(lang))}`,
          { headers: { "X-Workspace-Id": workspaceId }, credentials: "include" },
        );
        if (!res.ok) return;
        const raw = await res.text();
        setCues((prev) => ({ ...prev, [lang]: parseSubtitles(raw) }));
      } finally {
        setLoadingLang(null);
      }
    },
    [cues, fileForLang, contentId, workspaceId],
  );

  useEffect(() => {
    if (!primaryLang) return;
    queueMicrotask(() => void loadLang(primaryLang));
  }, [primaryLang, loadLang]);
  useEffect(() => {
    if (!secondaryLang) return;
    queueMicrotask(() => void loadLang(secondaryLang));
  }, [secondaryLang, loadLang]);

  const onTimeUpdate = () => {
    if (videoRef.current) setCurrentTime(videoRef.current.currentTime);
  };

  const primaryCue = cueAt(primaryLang ? cues[primaryLang] ?? null : null, currentTime);
  const secondaryCue = cueAt(
    secondaryLang ? cues[secondaryLang] ?? null : null,
    currentTime,
  );

  function pickPrimary(lang: string) {
    setPrimaryLang(lang);
    if (lang && lang === secondaryLang) setSecondaryLang("");
  }
  function pickSecondary(lang: string) {
    setSecondaryLang(lang);
    if (lang && lang === primaryLang) setPrimaryLang("");
  }

  const hasSubtitles = subtitles.length > 0;

  return (
    <div className="space-y-3">
      <div className="relative overflow-hidden rounded-xl border border-slate-800 bg-black">
        {videoFile ? (
          <video
            ref={videoRef}
            src={`/api/v1/media/${contentId}/${encodeURIComponent(videoFile)}`}
            controls
            preload="metadata"
            className="w-full"
            onTimeUpdate={onTimeUpdate}
          />
        ) : (
          <div className="flex h-40 items-center justify-center text-sm text-slate-500">
            未下载视频
          </div>
        )}
        {(primaryCue || secondaryCue) && (
          <div className="pointer-events-none absolute inset-x-0 bottom-12 flex flex-col items-center gap-1 px-3 text-center">
            {primaryCue && (
              <span className="max-w-[90%] whitespace-pre-wrap break-words rounded bg-black/70 px-2 py-0.5 text-base leading-snug text-white shadow">
                {showTimeline && `[${formatStamp(primaryCue.start)}] `}
                {primaryCue.text}
              </span>
            )}
            {secondaryCue && (
              <span className="max-w-[90%] whitespace-pre-wrap break-words rounded bg-black/70 px-2 py-0.5 text-sm leading-snug text-cyan-200 shadow">
                {showTimeline && `[${formatStamp(secondaryCue.start)}] `}
                {secondaryCue.text}
              </span>
            )}
          </div>
        )}
      </div>

      {hasSubtitles && (
        <div className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
          <div className="flex items-center gap-1 text-sm text-slate-400">
            <Languages size={15} /> 字幕
          </div>
          <label className="flex flex-col gap-1 text-xs text-slate-500">
            第一语种
            <select
              className="rounded-lg border border-slate-800 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
              value={primaryLang}
              onChange={(e) => pickPrimary(e.target.value)}
            >
              <option value="">关闭</option>
              {langs.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-500">
            第二语种
            <select
              className="rounded-lg border border-slate-800 bg-slate-950 px-2 py-1.5 text-sm text-slate-200"
              value={secondaryLang}
              onChange={(e) => pickSecondary(e.target.value)}
            >
              <option value="">关闭</option>
              {langs.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-400">
            <input
              type="checkbox"
              checked={showTimeline}
              onChange={(e) => setShowTimeline(e.target.checked)}
            />
            显示时间轴
          </label>
          {loadingLang && (
            <span className="flex items-center gap-1 text-xs text-slate-500">
              <Captions size={13} /> 加载 {loadingLang}…
            </span>
          )}
        </div>
      )}
    </div>
  );
}
