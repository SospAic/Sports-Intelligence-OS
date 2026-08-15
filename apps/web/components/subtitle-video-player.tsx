"use client";

import {
  Captions,
  Maximize,
  Minimize,
  MoreVertical,
  Pause,
  Play,
  Settings2,
  Volume2,
  VolumeX,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { useWorkspace } from "@/components/app-shell";
import { subtitleLanguageLabel } from "@/lib/language-options";
import {
  parseSubtitles,
  subtitleDisplayText,
  type SubtitleCue,
  type SubtitleWord,
} from "@/lib/subtitles";

interface SubtitleTrack {
  lang: string;
  file: string;
}

type Cue = SubtitleCue;
type PlayerFontSize = "small" | "medium" | "large";
type PlayerBackground = "box" | "shadow" | "none";
type PlayerPosition = "bottom" | "middle";

function formatStamp(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "--:--";
  const s = Math.max(0, Math.floor(seconds));
  const hh = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return hh
    ? `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`
    : `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

function safeMediaSeconds(value: number): number {
  return Number.isFinite(value) && value >= 0 ? value : 0;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function cueAt(cues: Cue[] | null, time: number): Cue | null {
  if (!cues?.length) return null;
  for (const cue of cues) {
    if (time >= cue.start && time < cue.end) return cue;
  }
  return null;
}

function renderCueText(cue: Cue, currentTime: number): ReactNode {
  if (!cue.words?.length) return subtitleDisplayText(cue.text);
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

export function SubtitleVideoPlayer({
  contentId,
  videoFile,
  subtitles,
  primaryLang,
  secondaryLang,
  showTimeline,
  onTimeChange,
  showSubtitles = true,
  fontSize = "medium",
  background = "box",
  position = "bottom",
  onPrimaryLangChange,
  onSecondaryLangChange,
  onShowTimelineChange,
  onShowSubtitlesChange,
  onFontSizeChange,
  onBackgroundChange,
  onPositionChange,
}: {
  contentId: string;
  videoFile: string | null | undefined;
  subtitles: SubtitleTrack[];
  primaryLang: string;
  secondaryLang: string;
  showTimeline: boolean;
  onTimeChange?: (seconds: number) => void;
  showSubtitles?: boolean;
  fontSize?: PlayerFontSize;
  background?: PlayerBackground;
  position?: PlayerPosition;
  onPrimaryLangChange?: (value: string) => void;
  onSecondaryLangChange?: (value: string) => void;
  onShowTimelineChange?: (value: boolean) => void;
  onShowSubtitlesChange?: (value: boolean) => void;
  onFontSizeChange?: (value: PlayerFontSize) => void;
  onBackgroundChange?: (value: PlayerBackground) => void;
  onPositionChange?: (value: PlayerPosition) => void;
}) {
  const { workspaceId } = useWorkspace();
  const frameRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [buffered, setBuffered] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [controlsVisible, setControlsVisible] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [cues, setCues] = useState<Record<string, Cue[]>>({});
  const [loadingLang, setLoadingLang] = useState<string | null>(null);
  const [localPrimaryLang, setLocalPrimaryLang] = useState(primaryLang);
  const [localSecondaryLang, setLocalSecondaryLang] = useState(secondaryLang);
  const [localShowSubtitles, setLocalShowSubtitles] = useState(showSubtitles);
  const [localFontSize, setLocalFontSize] = useState<PlayerFontSize>(fontSize);
  const [localBackground, setLocalBackground] = useState<PlayerBackground>(background);
  const [localPosition, setLocalPosition] = useState<PlayerPosition>(position);

  const activePrimaryLang = onPrimaryLangChange ? primaryLang : localPrimaryLang;
  const activeSecondaryLang = onSecondaryLangChange ? secondaryLang : localSecondaryLang;
  const activeShowSubtitles = onShowSubtitlesChange ? showSubtitles : localShowSubtitles;
  const activeFontSize = onFontSizeChange ? fontSize : localFontSize;
  const activeBackground = onBackgroundChange ? background : localBackground;
  const activePosition = onPositionChange ? position : localPosition;

  const fileForLang = useCallback(
    (lang: string) => subtitles.find((track) => track.lang === lang)?.file ?? "",
    [subtitles],
  );
  const loadLang = useCallback(
    async (lang: string) => {
      if (!lang || cues[lang] || !fileForLang(lang) || !workspaceId) return;
      setLoadingLang(lang);
      try {
        const response = await fetch(
          `/api/v1/media/${contentId}/${encodeURIComponent(fileForLang(lang))}`,
          { headers: { "X-Workspace-Id": workspaceId }, credentials: "include" },
        );
        if (!response.ok) return;
        const raw = await response.text();
        setCues((previous) => ({ ...previous, [lang]: parseSubtitles(raw) }));
      } finally {
        setLoadingLang(null);
      }
    },
    [contentId, cues, fileForLang, workspaceId],
  );

  useEffect(() => {
    if (!activePrimaryLang) return;
    const timer = window.setTimeout(() => void loadLang(activePrimaryLang), 0);
    return () => window.clearTimeout(timer);
  }, [activePrimaryLang, loadLang]);
  useEffect(() => {
    if (!activeSecondaryLang) return;
    const timer = window.setTimeout(() => void loadLang(activeSecondaryLang), 0);
    return () => window.clearTimeout(timer);
  }, [activeSecondaryLang, loadLang]);
  const visibleCues = useMemo(() => {
    const languages = new Set(subtitles.map((track) => track.lang));
    return Object.fromEntries(
      Object.entries(cues).filter(([lang]) => languages.has(lang)),
    );
  }, [cues, subtitles]);

  const revealControls = useCallback(() => {
    setControlsVisible(true);
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    if (isPlaying) {
      hideTimerRef.current = setTimeout(() => {
        if (!settingsOpen) setControlsVisible(false);
      }, 2600);
    }
  }, [isPlaying, settingsOpen]);

  useEffect(() => {
    const timer = window.setTimeout(revealControls, 0);
    return () => {
      window.clearTimeout(timer);
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    };
  }, [isPlaying, revealControls]);

  useEffect(() => {
    const handleFullscreen = () => setFullscreen(document.fullscreenElement === frameRef.current);
    document.addEventListener("fullscreenchange", handleFullscreen);
    return () => document.removeEventListener("fullscreenchange", handleFullscreen);
  }, []);

  const togglePlay = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) await video.play();
    else video.pause();
  }, []);

  const seekBy = (delta: number) => {
    const video = videoRef.current;
    if (!video) return;
    const total = duration || safeMediaSeconds(video.duration);
    if (!total) return;
    video.currentTime = clamp(safeMediaSeconds(video.currentTime) + delta, 0, total);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
    if (event.key === " ") {
      event.preventDefault();
      void togglePlay();
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      seekBy(-5);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      seekBy(5);
    } else if (event.key.toLowerCase() === "f") {
      event.preventDefault();
      void toggleFullscreen();
    }
  };

  async function toggleFullscreen() {
    if (!frameRef.current) return;
    if (document.fullscreenElement) await document.exitFullscreen();
    else await frameRef.current.requestFullscreen();
  }

  const setVideoVolume = (value: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.volume = value;
    video.muted = value === 0;
    setVolume(value);
    setMuted(value === 0);
  };

  const updatePrimary = (value: string) => {
    setLocalPrimaryLang(value);
    onPrimaryLangChange?.(value);
    if (value && value === activeSecondaryLang) {
      setLocalSecondaryLang("");
      onSecondaryLangChange?.("");
    }
  };
  const updateSecondary = (value: string) => {
    setLocalSecondaryLang(value);
    onSecondaryLangChange?.(value);
    if (value && value === activePrimaryLang) {
      setLocalPrimaryLang("");
      onPrimaryLangChange?.("");
    }
  };
  const updateShowSubtitles = (value: boolean) => {
    setLocalShowSubtitles(value);
    onShowSubtitlesChange?.(value);
  };
  const updateFontSize = (value: PlayerFontSize) => {
    setLocalFontSize(value);
    onFontSizeChange?.(value);
  };
  const updateBackground = (value: PlayerBackground) => {
    setLocalBackground(value);
    onBackgroundChange?.(value);
  };
  const updatePosition = (value: PlayerPosition) => {
    setLocalPosition(value);
    onPositionChange?.(value);
  };

  const primaryCue = cueAt(activePrimaryLang ? visibleCues[activePrimaryLang] ?? null : null, currentTime);
  const secondaryCue = cueAt(
    activeSecondaryLang ? visibleCues[activeSecondaryLang] ?? null : null,
    currentTime,
  );
  const languages = Array.from(new Set(subtitles.map((track) => track.lang).filter(Boolean)));
  const subtitleTextClass =
    activeFontSize === "small" ? "text-sm" : activeFontSize === "large" ? "text-xl" : "text-base";
  const subtitleSecondaryClass =
    activeFontSize === "small" ? "text-xs" : activeFontSize === "large" ? "text-base" : "text-sm";
  const subtitleSurfaceClass =
    activeBackground === "box"
      ? "rounded bg-black/70 shadow"
      : activeBackground === "shadow"
        ? "[text-shadow:0_2px_5px_rgba(0,0,0,0.95)]"
        : "";
  const subtitlePositionClass = activePosition === "middle" ? "top-1/2 -translate-y-1/2" : "bottom-16";
  const progressMax = duration > 0 ? duration : 1;
  const progressValue = clamp(currentTime, 0, duration > 0 ? duration : 1);
  const progressPercent = duration > 0 ? (progressValue / duration) * 100 : 0;
  const bufferedPercent = duration > 0 ? clamp((buffered / duration) * 100, 0, 100) : 0;
  const controlButtonClass =
    "rounded-lg p-1.5 text-slate-200 transition-all duration-200 hover:bg-white/15 hover:text-cyan-200 active:scale-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300";
  const compactButtonClass =
    "rounded-md px-2 py-1 text-xs text-slate-200 transition-all duration-200 hover:bg-white/15 hover:text-cyan-200 active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300";

  return (
    <div className="space-y-3">
      <div
        ref={frameRef}
        tabIndex={0}
        role="application"
        aria-label="视频播放器"
        onKeyDown={handleKeyDown}
        onMouseMove={revealControls}
        onDoubleClick={() => void toggleFullscreen()}
        className="group relative mx-auto max-w-4xl overflow-hidden rounded-2xl border border-white/10 bg-[#050811] shadow-[0_24px_80px_-30px_rgba(34,211,238,0.45)] outline-none ring-1 ring-cyan-300/5 focus-visible:ring-2 focus-visible:ring-cyan-300"
      >
        {videoFile ? (
          <video
            ref={videoRef}
            src={`/api/v1/media/${contentId}/${encodeURIComponent(videoFile)}`}
            preload="metadata"
            className="mx-auto block max-h-[520px] min-h-[220px] w-full cursor-pointer bg-black object-contain"
            onClick={() => void togglePlay()}
            onLoadedMetadata={(event) => {
              setDuration(safeMediaSeconds(event.currentTarget.duration));
              setCurrentTime(safeMediaSeconds(event.currentTarget.currentTime));
            }}
            onDurationChange={(event) => setDuration(safeMediaSeconds(event.currentTarget.duration))}
            onProgress={(event) => {
              const media = event.currentTarget;
              const end = media.buffered.length ? media.buffered.end(media.buffered.length - 1) : 0;
              setBuffered(safeMediaSeconds(end));
            }}
            onTimeUpdate={(event) => {
              const media = event.currentTarget;
              const value = safeMediaSeconds(media.currentTime);
              setCurrentTime(value);
              onTimeChange?.(value);
            }}
            onPlay={() => setIsPlaying(true)}
            onPause={() => setIsPlaying(false)}
            onEnded={() => setIsPlaying(false)}
            onVolumeChange={(event) => {
              setVolume(event.currentTarget.volume);
              setMuted(event.currentTarget.muted || event.currentTarget.volume === 0);
            }}
            onRateChange={(event) => setPlaybackRate(event.currentTarget.playbackRate)}
          />
        ) : (
          <div className="flex h-48 items-center justify-center text-sm text-slate-500">未下载视频</div>
        )}

        {videoFile && !isPlaying && (
          <button
            type="button"
            aria-label="播放"
            onClick={() => void togglePlay()}
            className="absolute inset-0 m-auto grid size-16 place-items-center rounded-full border border-white/60 bg-cyan-300/90 text-slate-950 shadow-[0_0_0_8px_rgba(34,211,238,0.08),0_0_35px_rgba(34,211,238,0.5)] transition-all duration-200 hover:scale-110 hover:bg-cyan-200 active:scale-95"
          >
            <Play size={27} fill="currentColor" />
          </button>
        )}

        {activeShowSubtitles && (primaryCue || secondaryCue) && (
          <div className={`pointer-events-none absolute inset-x-0 ${subtitlePositionClass} flex flex-col items-center gap-1 px-3 text-center`}>
            {primaryCue && (
              <span className={`max-w-[90%] whitespace-normal break-words px-2 py-0.5 font-semibold leading-snug text-white ${subtitleTextClass} ${subtitleSurfaceClass}`}>
                {showTimeline && `[${formatStamp(primaryCue.start)}] `}
                {renderCueText(primaryCue, currentTime)}
              </span>
            )}
            {secondaryCue && (
              <span className={`max-w-[90%] whitespace-normal break-words bg-cyan-950/50 px-2 py-0.5 font-semibold leading-snug text-cyan-100 ${subtitleSecondaryClass} ${subtitleSurfaceClass}`}>
                {showTimeline && `[${formatStamp(secondaryCue.start)}] `}
                {renderCueText(secondaryCue, currentTime)}
              </span>
            )}
          </div>
        )}

        {videoFile && (
          <div
            className={`absolute inset-x-0 bottom-0 z-10 bg-gradient-to-t from-black via-black/75 to-transparent px-3 pb-3 pt-12 transition-opacity duration-300 ${controlsVisible ? "opacity-100" : "pointer-events-none opacity-0"}`}
            onMouseMove={revealControls}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="relative mb-2 h-1.5 rounded-full bg-white/20">
              <div className="pointer-events-none absolute inset-y-0 left-0 rounded-full bg-white/35" style={{ width: `${bufferedPercent}%` }} />
              <div className="pointer-events-none absolute inset-y-0 left-0 rounded-full bg-cyan-300" style={{ width: `${progressPercent}%` }} />
              <input
                type="range"
                aria-label="播放进度"
                aria-valuetext={`${formatStamp(currentTime)} / ${formatStamp(duration)}`}
                min={0}
                max={progressMax}
                step={0.01}
                value={progressValue}
                onChange={(event) => {
                  const value = clamp(Number(event.target.value), 0, duration || 1);
                  if (videoRef.current && duration > 0) videoRef.current.currentTime = value;
                  setCurrentTime(value);
                  onTimeChange?.(value);
                }}
                className="absolute inset-0 h-1.5 w-full cursor-pointer opacity-0"
              />
            </div>
            <div className="flex items-center gap-1.5 text-white sm:gap-2">
              <button type="button" aria-label={isPlaying ? "暂停" : "播放"} title={isPlaying ? "暂停" : "播放"} onClick={() => void togglePlay()} className={controlButtonClass}>
                {isPlaying ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}
              </button>
              <button type="button" aria-label="后退 5 秒" title="后退 5 秒" onClick={() => seekBy(-5)} className={compactButtonClass}>−5</button>
              <button type="button" aria-label="前进 5 秒" title="前进 5 秒" onClick={() => seekBy(5)} className={compactButtonClass}>+5</button>
              <span className="min-w-20 text-[11px] tabular-nums tracking-wide text-slate-200 sm:min-w-24 sm:text-xs">{formatStamp(currentTime)} / {formatStamp(duration)}</span>
              <button
                type="button"
                aria-label={muted ? "取消静音" : "静音"}
                title={muted ? "取消静音" : "静音"}
                onClick={() => {
                  if (!videoRef.current) return;
                  videoRef.current.muted = !videoRef.current.muted;
                  setMuted(videoRef.current.muted);
                }}
                className={controlButtonClass}
              >
                {muted || volume === 0 ? <VolumeX size={18} /> : <Volume2 size={18} />}
              </button>
              <input
                type="range"
                aria-label="音量"
                min={0}
                max={1}
                step={0.01}
                value={muted ? 0 : volume}
                onChange={(event) => setVideoVolume(Number(event.target.value))}
                className="hidden w-20 cursor-pointer accent-cyan-300 sm:block"
              />
              <span className="flex-1" />
              <button type="button" aria-label="字幕" title={activeShowSubtitles ? "关闭字幕" : "打开字幕"} onClick={() => updateShowSubtitles(!activeShowSubtitles)} className={`${controlButtonClass} ${activeShowSubtitles ? "text-cyan-300" : "text-slate-400"}`}>
                <Captions size={18} />
              </button>
              <button type="button" aria-label="播放器设置" title="播放器设置" onClick={() => setSettingsOpen((value) => !value)} className={`${controlButtonClass} ${settingsOpen ? "bg-white/15 text-cyan-300" : ""}`}>
                <MoreVertical size={19} />
              </button>
              <button type="button" aria-label={fullscreen ? "退出全屏" : "全屏"} title={fullscreen ? "退出全屏" : "全屏"} onClick={() => void toggleFullscreen()} className={controlButtonClass}>
                {fullscreen ? <Minimize size={18} /> : <Maximize size={18} />}
              </button>
            </div>
          </div>
        )}

        {settingsOpen && videoFile && (
          <div className="absolute bottom-14 right-3 z-20 w-72 max-w-[calc(100%-1.5rem)] origin-bottom-right rounded-xl border border-white/10 bg-slate-950/95 p-3 text-xs text-slate-200 shadow-[0_16px_50px_rgba(0,0,0,0.5)] backdrop-blur-xl transition-all duration-200">
            <div className="mb-3 flex items-center justify-between border-b border-slate-800 pb-2">
              <span className="font-semibold text-white">播放器设置</span>
              <Settings2 size={15} className="text-cyan-300" />
            </div>
            <label className="mb-3 flex items-center justify-between gap-3">
              <span>显示字幕</span>
              <input type="checkbox" checked={activeShowSubtitles} onChange={(event) => updateShowSubtitles(event.target.checked)} />
            </label>
            <label className="mb-3 flex items-center justify-between gap-3">
              <span>显示时间戳</span>
              <input type="checkbox" checked={showTimeline} onChange={(event) => onShowTimelineChange?.(event.target.checked)} />
            </label>
            <label className="mb-2 grid gap-1">
              <span>第一语言</span>
              <select aria-label="第一语言" value={activePrimaryLang} onChange={(event) => updatePrimary(event.target.value)} className="rounded border border-slate-700 bg-slate-900 px-2 py-1.5">
                <option value="">关闭</option>
                {languages.map((lang) => <option key={lang} value={lang}>{subtitleLanguageLabel(lang)}</option>)}
              </select>
            </label>
            <label className="mb-2 grid gap-1">
              <span>第二语言</span>
              <select aria-label="第二语言" value={activeSecondaryLang} onChange={(event) => updateSecondary(event.target.value)} className="rounded border border-slate-700 bg-slate-900 px-2 py-1.5">
                <option value="">无</option>
                {languages.filter((lang) => lang !== activePrimaryLang).map((lang) => <option key={lang} value={lang}>{subtitleLanguageLabel(lang)}</option>)}
              </select>
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="grid gap-1"><span>字号</span><select value={activeFontSize} onChange={(event) => updateFontSize(event.target.value as PlayerFontSize)} className="rounded border border-slate-700 bg-slate-900 px-2 py-1.5"><option value="small">小</option><option value="medium">中</option><option value="large">大</option></select></label>
              <label className="grid gap-1"><span>背景</span><select value={activeBackground} onChange={(event) => updateBackground(event.target.value as PlayerBackground)} className="rounded border border-slate-700 bg-slate-900 px-2 py-1.5"><option value="box">黑底</option><option value="shadow">阴影</option><option value="none">无</option></select></label>
              <label className="grid gap-1"><span>位置</span><select value={activePosition} onChange={(event) => updatePosition(event.target.value as PlayerPosition)} className="rounded border border-slate-700 bg-slate-900 px-2 py-1.5"><option value="bottom">底部</option><option value="middle">中间</option></select></label>
              <label className="grid gap-1"><span>播放速度</span><select value={playbackRate} onChange={(event) => { const value = Number(event.target.value); setPlaybackRate(value); if (videoRef.current) videoRef.current.playbackRate = value; }} className="rounded border border-slate-700 bg-slate-900 px-2 py-1.5"><option value={0.5}>0.5x</option><option value={0.75}>0.75x</option><option value={1}>正常</option><option value={1.25}>1.25x</option><option value={1.5}>1.5x</option><option value={2}>2x</option></select></label>
            </div>
          </div>
        )}
      </div>
      {loadingLang && <div className="flex items-center gap-1 text-xs text-slate-500"><Captions size={13} /> 加载字幕中…</div>}
    </div>
  );
}
