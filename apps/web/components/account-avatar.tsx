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
  name,
  className = "size-9 shrink-0 rounded-full object-cover ring-1 ring-slate-700",
  fallbackClassName,
}: {
  url?: string | null;
  name?: string | null;
  className?: string;
  fallbackClassName?: string;
}) {
  const [errored, setErrored] = useState(false);
  if (!url || errored) {
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
      src={url}
      alt=""
      className={className}
      onError={() => setErrored(true)}
    />
  );
}
