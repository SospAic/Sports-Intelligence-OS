"use client";

import { useState } from "react";

import { ExternalImage } from "@/components/external-image";

/**
 * Account avatar that falls back to initials when the platform-provided image
 * (e.g. a short-lived signed TikTok / Douyin CDN link) fails to load. Shared by
 * the accounts list and the account detail page so both degrade gracefully
 * instead of rendering a broken / blank image when the avatar fetch errors.
 */
export function AccountAvatar({
  url,
  remoteUrl,
  name,
  className = "size-9 shrink-0 rounded-full object-cover ring-1 ring-slate-700",
  fallbackClassName,
}: {
  /** Primary image source — usually the locally-archived avatar route. */
  url?: string | null;
  /** Fallback remote URL (the platform's CDN link) tried after `url` fails. */
  remoteUrl?: string | null;
  name?: string | null;
  className?: string;
  fallbackClassName?: string;
}) {
  // 0 = primary (url), 1 = remote fallback, 2 = initials
  const [stage, setStage] = useState(0);
  const current = stage === 0 ? url : stage === 1 ? remoteUrl : null;
  if (!current) {
    return (
      <span
        className={
          fallbackClassName ??
          "grid size-9 shrink-0 place-items-center rounded-full bg-slate-800 text-xs font-medium text-slate-400 ring-1 ring-slate-700"
        }
      >
        {(name || "?").slice(0, 2)}
      </span>
    );
  }
  return (
    <ExternalImage
      src={current}
      alt=""
      className={className}
      onError={() => setStage((s) => Math.min(s + 1, 2))}
    />
  );
}
