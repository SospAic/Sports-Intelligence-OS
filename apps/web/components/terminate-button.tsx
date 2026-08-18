"use client";

import { Ban, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface TerminateButtonProps {
  /** Called when the user confirms termination (second click). */
  onTerminate: () => Promise<void> | void;
  label?: string;
  confirmingLabel?: string;
  busy?: boolean;
  disabled?: boolean;
  size?: "sm" | "md";
  title?: string;
  className?: string;
}

const ARM_RESET_MS = 3000;

/**
 * Destructive "terminate running task" button.
 *
 * Industry pattern (Vercel / GitHub Actions / AWS): a running job exposes a
 * red Stop/Cancel control, and accidental termination is prevented with a
 * lightweight two-step confirm — the first click arms the button (darker red,
 * pulsing, "确认终止？"), the second confirms. The armed state auto-resets after
 * a few seconds. While the request is in flight the button shows a spinner and
 * "终止中…" and ignores further clicks.
 */
export function TerminateButton({
  onTerminate,
  label = "终止任务",
  confirmingLabel = "确认终止？",
  busy = false,
  disabled = false,
  size = "md",
  title,
  className = "",
}: TerminateButtonProps) {
  const [armed, setArmed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  function arm() {
    setArmed(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setArmed(false), ARM_RESET_MS);
  }

  async function confirm() {
    if (timer.current) clearTimeout(timer.current);
    setArmed(false);
    await onTerminate();
  }

  const sizeClass = size === "sm" ? "h-8 px-3 text-xs" : "h-10 px-4 text-sm";
  const iconSize = size === "sm" ? 13 : 15;

  if (armed) {
    return (
      <button
        type="button"
        onClick={confirm}
        title={title ?? "再次点击以确认终止"}
        className={`inline-flex ${sizeClass} items-center justify-center gap-2 rounded-lg bg-red-700 font-medium text-white shadow-sm shadow-red-900/40 ring-2 ring-red-400/70 transition hover:bg-red-600 animate-pulse ${className}`}
      >
        <Ban size={iconSize} />
        {confirmingLabel}
      </button>
    );
  }

  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg bg-red-600 font-medium text-white transition hover:bg-red-500 active:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50";
  return (
    <button
      type="button"
      disabled={disabled || busy}
      onClick={busy ? undefined : arm}
      title={title ?? "终止正在进行的任务"}
      className={`${base} ${sizeClass} ${busy ? "opacity-70" : ""} ${className}`}
    >
      {busy ? (
        <Loader2 size={iconSize} className="animate-spin" />
      ) : (
        <Ban size={iconSize} />
      )}
      {busy ? "终止中…" : label}
    </button>
  );
}
